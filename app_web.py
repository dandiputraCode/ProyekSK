from datetime import date, datetime
from pathlib import Path
import base64
import binascii
import csv
import io
import re
import shutil
import sqlite3
import socket
import sys

import cv2
import numpy as np
from flask import Flask, jsonify, render_template, request, Response
from esp32_serial import bridge

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "attendance.db"
FACE_DB_PATH = BASE_DIR / "database_wajah"
YOLO_MODEL_PATH = BASE_DIR / "models" / "yolo26n-face.pt"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024

# YOLO face detector is loaded lazily when an admin registers a student.
_FACE_DETECTOR = None


# Membuka koneksi SQLite ke file attendance.db dengan hasil baris berbentuk dictionary (sqlite3.Row).
def get_db():
    connection = sqlite3.connect(DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    return connection


# Membuat tabel attendance di SQLite jika belum ada (unik per kombinasi npm dan tanggal).
def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_db() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                npm TEXT NOT NULL,
                nama TEXT NOT NULL,
                tanggal TEXT NOT NULL,
                waktu TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Hadir',
                sumber TEXT NOT NULL DEFAULT 'Face Recognition',
                UNIQUE(npm, tanggal)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS students (
                npm TEXT PRIMARY KEY,
                nama TEXT NOT NULL,
                finger_id INTEGER UNIQUE,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.commit()



init_db()

# Mengambil daftar seluruh siswa terdaftar (gabungan folder database_wajah/ dan tabel students di SQLite).
def list_registered_students():
    image_extensions = {".jpg", ".jpeg", ".png", ".webp"}
    with get_db() as connection:
        db_rows = {
            row["npm"]: dict(row)
            for row in connection.execute(
                "SELECT npm, nama, finger_id, created_at FROM students"
            ).fetchall()
        }

    items = {}
    if FACE_DB_PATH.exists():
        for folder in FACE_DB_PATH.iterdir():
            if not folder.is_dir() or "_" not in folder.name:
                continue
            photos = [
                p for p in folder.iterdir()
                if p.is_file() and p.suffix.lower() in image_extensions
            ]
            if not photos:
                continue
            npm, raw_name = folder.name.split("_", 1)
            db_info = db_rows.get(npm, {})
            mtime = datetime.fromtimestamp(folder.stat().st_mtime).isoformat(timespec="seconds")
            items[npm] = {
                "npm": npm,
                "nama": db_info.get("nama") or raw_name.replace("_", " "),
                "photo_count": len(photos),
                "finger_id": db_info.get("finger_id"),
                "created_at": db_info.get("created_at") or mtime,
            }

    for npm, db_info in db_rows.items():
        if npm not in items:
            items[npm] = {
                "npm": npm,
                "nama": db_info["nama"],
                "photo_count": 0,
                "finger_id": db_info["finger_id"],
                "created_at": db_info["created_at"],
            }

    return sorted(items.values(), key=lambda item: item["created_at"] or "", reverse=True)


# Menghitung jumlah siswa terdaftar.
def count_registered_students():
    return len(list_registered_students())


# Memeriksa apakah folder dengan awalan "{npm}_" sudah ada di database_wajah/ untuk mencegah duplikasi.
def npm_already_registered(npm):
    if not FACE_DB_PATH.exists():
        return False
    prefix = f"{npm}_"
    return any(
        folder.is_dir() and folder.name.startswith(prefix)
        for folder in FACE_DB_PATH.iterdir()
    )


# Menentukan ID sidik jari berikutnya yang masih kosong (rentang sensor R503: 1-200).
def next_finger_id():
    with get_db() as connection:
        rows = connection.execute("SELECT finger_id FROM students WHERE finger_id IS NOT NULL").fetchall()
    terpakai = {row["finger_id"] for row in rows}
    for kandidat in range(1, 201):
        if kandidat not in terpakai:
            return kandidat
    return None


# Mengambil data siswa (termasuk finger_id) berdasarkan NPM.
def get_student(npm):
    with get_db() as connection:
        return connection.execute(
            "SELECT npm, nama, finger_id FROM students WHERE npm = ?",
            (npm,),
        ).fetchone()


# Menyimpan/memperbarui data siswa. finger_id=None berarti data sidik jari tidak diubah.
def simpan_siswa(npm, nama, finger_id=None, ubah_finger=False):
    with get_db() as connection:
        connection.execute(
            """
            INSERT INTO students (npm, nama, finger_id, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(npm) DO UPDATE SET
                nama = excluded.nama,
                finger_id = CASE WHEN ? THEN excluded.finger_id ELSE students.finger_id END
            """,
            (npm, nama, finger_id, datetime.now().isoformat(timespec="seconds"), 1 if ubah_finger else 0),
        )
        connection.commit()


# Memuat model YOLO (models/yolo26n-face.pt) secara lazy-load (hanya sekali saat dibutuhkan pertama kali).
def get_face_detector():
    global _FACE_DETECTOR
    if _FACE_DETECTOR is not None:
        return _FACE_DETECTOR

    if not YOLO_MODEL_PATH.is_file():
        raise FileNotFoundError(
            f"Model YOLO wajah tidak ditemukan: {YOLO_MODEL_PATH}"
        )

    from ultralytics import YOLO
    _FACE_DETECTOR = YOLO(str(YOLO_MODEL_PATH))
    return _FACE_DETECTOR


# Mengubah string gambar Base64 dari webcam browser menjadi array OpenCV, lalu memvalidasi tepat 1 wajah via YOLO.
def decode_and_validate_photo(data_url, index, detector):
    if not isinstance(data_url, str) or "," not in data_url:
        raise ValueError(f"Foto {index}: format gambar tidak valid.")

    header, encoded_data = data_url.split(",", 1)
    if not header.startswith("data:image/") or ";base64" not in header:
        raise ValueError(f"Foto {index}: gunakan gambar JPEG/PNG dari kamera.")

    try:
        raw = base64.b64decode(encoded_data, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError(f"Foto {index}: data gambar tidak dapat dibaca.")

    if not raw or len(raw) > 2 * 1024 * 1024:
        raise ValueError(f"Foto {index}: ukuran gambar kosong atau terlalu besar.")

    image_array = np.frombuffer(raw, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Foto {index}: gambar tidak dapat dibuka.")

    height, width = image.shape[:2]
    if width < 240 or height < 180:
        raise ValueError(
            f"Foto {index}: resolusi terlalu kecil. Ambil ulang dengan kamera yang jelas."
        )

    result = detector.predict(
        source=image,
        conf=0.35,
        imgsz=320,
        device="cpu",
        verbose=False,
    )[0]

    face_count = len(result.boxes) if result.boxes is not None else 0
    if face_count != 1:
        if face_count == 0:
            reason = "wajah tidak terdeteksi"
        else:
            reason = f"terdeteksi {face_count} wajah; foto harus berisi satu wajah saja"
        raise ValueError(f"Foto {index}: {reason}. Silakan ambil ulang.")

    return image


# Menampilkan halaman utama dashboard monitoring absensi (templates/index.html).
@app.route("/")
def dashboard():
    return render_template("index.html")


# Menampilkan halaman formulir pendaftaran wajah siswa (templates/enroll.html).
@app.get("/students/register")
def student_registration_page():
    return render_template("enroll.html")


# Status koneksi ESP32/R503 supaya halaman pendaftaran bisa menampilkan sensor siap atau tidak.
@app.get("/api/fingerprint/status")
def fingerprint_status():
    return jsonify({
        "status": "ok",
        "sensor": bridge.status(),
        "next_finger_id": next_finger_id(),
    })


# Daftar siswa terdaftar beserta jumlah foto wajah dan ID sidik jari R503 (terbaru di urutan pertama).
@app.get("/api/students")
def students_list():
    students = list_registered_students()
    return jsonify({
        "status": "ok",
        "total": len(students),
        "students": students,
    })


# Merekam sidik jari untuk siswa yang sudah punya foto wajah (dipanggil dari halaman pendaftaran).
@app.post("/api/fingerprint/enroll")
def enroll_fingerprint():
    payload = request.get_json(silent=True) or {}
    npm = str(payload.get("npm", "")).strip()
    nama = str(payload.get("nama", "")).strip()

    if not re.fullmatch(r"[A-Za-z0-9.-]{1,40}", npm):
        return jsonify({"status": "error", "message": "NPM wajib diisi sebelum merekam sidik jari."}), 400

    siswa = get_student(npm)
    if not nama and siswa:
        nama = siswa["nama"]
    if len(nama) < 2 or len(nama) > 150:
        return jsonify({"status": "error", "message": "Nama siswa wajib diketahui sebelum merekam sidik jari."}), 400
    if not bridge.status()["connected"]:
        return jsonify({"status": "error", "message": "ESP32/R503 belum terhubung ke port USB."}), 503

    # Sidik jari lama boleh ditimpa bila admin meminta rekam ulang (payload replace=true).
    if siswa and siswa["finger_id"] is not None:
        if payload.get("replace") is not True:
            return jsonify({
                "status": "error",
                "message": f"Sidik jari NPM {npm} sudah terdaftar (ID #{siswa['finger_id']}). Kirim replace=true untuk merekam ulang.",
                "replaceable": True,
            }), 409
        finger_id = siswa["finger_id"]
    else:
        finger_id = next_finger_id()
        if finger_id is None:
            return jsonify({"status": "error", "message": "Kapasitas 200 sidik jari di sensor sudah penuh."}), 409

    ok, pesan = bridge.enroll(finger_id)
    if not ok:
        return jsonify({"status": "error", "message": pesan}), 400

    simpan_siswa(npm, nama, finger_id, ubah_finger=True)
    return jsonify({
        "status": "fingerprint_registered",
        "message": pesan,
        "student": {"npm": npm, "nama": nama, "finger_id": finger_id},
    }), 201


@app.post("/api/students/register")
def register_student():
    """Endpoint pendaftaran siswa: validasi input, cek 3 foto dengan YOLO, lalu simpan ke database_wajah/."""
    payload = request.get_json(silent=True) or {}

    npm = str(payload.get("npm", "")).strip()
    nama = str(payload.get("nama", "")).strip()
    photos = payload.get("photos")
    consent = payload.get("consent") is True
    enroll_finger = payload.get("enroll_finger") is True

    if not re.fullmatch(r"[A-Za-z0-9.-]{1,40}", npm):
        return jsonify({"status": "error", "message": "NPM wajib diisi dan hanya boleh berisi huruf, angka, titik, atau tanda hubung."}), 400

    if len(nama) < 2 or len(nama) > 150:
        return jsonify({"status": "error", "message": "Nama siswa wajib diisi (2–150 karakter)."}), 400

    if not consent:
        return jsonify({"status": "error", "message": "Persetujuan penggunaan data wajah wajib dicentang."}), 400

    if not isinstance(photos, list) or len(photos) != 3:
        return jsonify({"status": "error", "message": "Ambil tepat 3 foto wajah sebelum menyimpan siswa."}), 400

    FACE_DB_PATH.mkdir(parents=True, exist_ok=True)
    if npm_already_registered(npm):
        return jsonify({"status": "error", "message": f"NPM {npm} sudah terdaftar. Gunakan menu pembaruan data jika ingin mengganti foto."}), 409

    # Build a folder-safe name while preserving readable Unicode letters.
    name_slug = re.sub(r"[^\w.-]+", "_", nama, flags=re.UNICODE).strip("_.")
    if not name_slug:
        return jsonify({"status": "error", "message": "Nama tidak dapat digunakan sebagai nama folder."}), 400

    try:
        detector = get_face_detector()
        validated_images = [
            decode_and_validate_photo(photo, idx + 1, detector)
            for idx, photo in enumerate(photos)
        ]
    except ValueError as error:
        return jsonify({"status": "error", "message": str(error)}), 400
    except Exception as error:
        app.logger.exception("Gagal memvalidasi foto pendaftaran")
        return jsonify({"status": "error", "message": f"Gagal memvalidasi foto dengan YOLO: {error}"}), 500

    student_folder = FACE_DB_PATH / f"{npm}_{name_slug}"
    try:
        student_folder.mkdir(parents=False, exist_ok=False)
        for idx, image in enumerate(validated_images, start=1):
            output_path = student_folder / f"foto{idx}.jpg"
            ok, encoded = cv2.imencode(
                ".jpg", image,
                [int(cv2.IMWRITE_JPEG_QUALITY), 92]
            )
            if not ok:
                raise RuntimeError(f"Gagal menyimpan foto {idx}.")
            encoded.tofile(str(output_path))
    except Exception as error:
        if student_folder.exists():
            shutil.rmtree(student_folder, ignore_errors=True)
        app.logger.exception("Gagal menyimpan pendaftaran siswa")
        return jsonify({"status": "error", "message": f"Gagal menyimpan data siswa: {error}"}), 500

    if enroll_finger:
        if not bridge.status()["connected"]:
            shutil.rmtree(student_folder, ignore_errors=True)
            return jsonify({"status": "error", "message": "Sidik jari diminta, tetapi ESP32/R503 belum terhubung ke port USB."}), 503

        finger_id = next_finger_id()
        if finger_id is None:
            shutil.rmtree(student_folder, ignore_errors=True)
            return jsonify({"status": "error", "message": "Kapasitas 200 sidik jari di sensor sudah penuh."}), 409

        ok, pesan = bridge.enroll(finger_id)
        if not ok:
            shutil.rmtree(student_folder, ignore_errors=True)
            return jsonify({"status": "error", "message": f"Pendaftaran dibatalkan: {pesan}"}), 400
    else:
        finger_id = None

    try:
        simpan_siswa(npm, nama, finger_id, ubah_finger=enroll_finger)
        tersimpan = get_student(npm)
        finger_id = tersimpan["finger_id"] if tersimpan else finger_id
    except Exception as error:
        shutil.rmtree(student_folder, ignore_errors=True)
        app.logger.exception("Gagal menyimpan data siswa")
        return jsonify({"status": "error", "message": f"Gagal menyimpan data siswa: {error}"}), 500

    catatan_sidik = (
        f" Sidik jari tersimpan dengan ID {finger_id}."
        if finger_id is not None
        else " Sidik jari belum direkam; daftarkan lewat tombol di halaman pendaftaran sebelum absensi 2 faktor."
    )
    return jsonify({
        "status": "registered",
        "message": "Siswa berhasil didaftarkan." + catatan_sidik + " Jalankan ulang program Face Recognition agar foto baru dimuat.",
        "student": {
            "npm": npm,
            "nama": nama,
            "photo_count": len(validated_images),
            "finger_id": finger_id,
        },
    }), 201


# Mengambil statistik ringkasan dan daftar hingga 200 log kehadiran pada tanggal terpilih dalam format JSON.
@app.get("/api/dashboard")
def dashboard_data():
    selected_date = request.args.get("date", date.today().isoformat())
    try:
        datetime.strptime(selected_date, "%Y-%m-%d")
    except ValueError:
        selected_date = date.today().isoformat()

    with get_db() as connection:
        today_rows = connection.execute(
            "SELECT id, npm, nama, tanggal, waktu, status, sumber FROM attendance WHERE tanggal = ? ORDER BY waktu DESC, id DESC",
            (selected_date,),
        ).fetchall()
        total_records = connection.execute(
            "SELECT COUNT(*) AS total FROM attendance"
        ).fetchone()["total"]

    students = list_registered_students()
    registered = len(students)
    present_count = len({row["npm"] for row in today_rows})
    percentage = round((present_count / registered) * 100) if registered else 0

    return jsonify({
        "selected_date": selected_date,
        "registered_students": registered,
        "present_count": present_count,
        "total_records": total_records,
        "attendance_percentage": min(percentage, 100),
        "records": [dict(row) for row in today_rows[:200]],
        "students": students,
        "server_time": datetime.now().strftime("%d %b %Y, %H:%M:%S"),
    })


# Mencatat kehadiran siswa dari script Face Recognition ke SQLite (maksimal 1 kali per NPM per hari).
@app.post("/api/attendance")
def add_attendance():
    payload = request.get_json(silent=True) or {}
    npm = str(payload.get("npm", "")).strip()
    nama = str(payload.get("nama", "")).strip()
    sumber = str(payload.get("source", "Face Recognition")).strip() or "Face Recognition"

    if not npm or not nama:
        return jsonify({"status": "error", "message": "npm dan nama wajib diisi"}), 400
    if len(npm) > 40 or len(nama) > 150 or len(sumber) > 80:
        return jsonify({"status": "error", "message": "Panjang data melebihi batas"}), 400

    tanggal = date.today().isoformat()

    with get_db() as connection:
        row = connection.execute(
            "SELECT id, npm, nama, tanggal, waktu, status, sumber FROM attendance WHERE npm = ? AND tanggal = ?",
            (npm, tanggal),
        ).fetchone()

    if row is not None:
        return jsonify({
            "status": "already_recorded",
            "message": "Siswa sudah tercatat hadir hari ini",
            "record": dict(row),
        }), 200

    # Faktor kedua: sidik jari siswa harus cocok di sensor R503 sebelum absensi disimpan.
    siswa = get_student(npm)
    finger_id = siswa["finger_id"] if siswa else None
    if finger_id is None:
        return jsonify({
            "status": "error",
            "message": "Sidik jari siswa belum terdaftar. Daftarkan lewat menu Pendaftaran Siswa.",
        }), 409
    if not bridge.status()["connected"]:
        return jsonify({
            "status": "error",
            "message": "ESP32/R503 belum terhubung ke port USB. Absensi 2 faktor tidak bisa diverifikasi.",
        }), 503

    confidence, alasan = bridge.tunggu_match(finger_id, timeout=30)
    if confidence is None:
        return jsonify({
            "status": "error",
            "message": f"Absensi 2 faktor tidak dicatat. {alasan}",
        }), 401

    bridge.kedip_hijau()
    waktu = datetime.now().strftime("%H:%M:%S")
    sumber = f"{sumber} + Sidik Jari"

    with get_db() as connection:
        cursor = connection.execute(
            "INSERT OR IGNORE INTO attendance (npm, nama, tanggal, waktu, status, sumber) VALUES (?, ?, ?, ?, ?, ?)",
            (npm, nama, tanggal, waktu, "Hadir", sumber),
        )
        connection.commit()
        was_inserted = cursor.rowcount == 1

        row = connection.execute(
            "SELECT id, npm, nama, tanggal, waktu, status, sumber FROM attendance WHERE npm = ? AND tanggal = ?",
            (npm, tanggal),
        ).fetchone()

    if was_inserted:
        return jsonify({
            "status": "recorded",
            "message": "Absensi berhasil disimpan",
            "record": dict(row),
        }), 201

    return jsonify({
        "status": "already_recorded",
        "message": "Siswa sudah tercatat hadir hari ini",
        "record": dict(row),
    }), 200


# Mengekspor data kehadiran pada tanggal tertentu menjadi file unduhan CSV (UTF-8 dengan BOM untuk Excel).
@app.get("/api/export")
def export_csv():
    selected_date = request.args.get("date", date.today().isoformat())
    try:
        datetime.strptime(selected_date, "%Y-%m-%d")
    except ValueError:
        selected_date = date.today().isoformat()

    with get_db() as connection:
        rows = connection.execute(
            "SELECT npm, nama, tanggal, waktu, status, sumber FROM attendance WHERE tanggal = ? ORDER BY waktu ASC",
            (selected_date,),
        ).fetchall()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["NPM", "Nama", "Tanggal", "Waktu", "Status", "Sumber"])
    for row in rows:
        writer.writerow(list(row))

    filename = f"absensi_{selected_date}.csv"
    return Response(
        "\ufeff" + buffer.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# Endpoint pengecekan status server Flask (health check).
@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "AIoT Smart Attendance Dashboard"})


# Menangani error HTTP 413 jika ukuran payload foto yang diunggah melebihi batas MAX_CONTENT_LENGTH (15 MB).
@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({"status": "error", "message": "Total ukuran foto terlalu besar. Ambil ulang foto dengan kamera standar."}), 413


def port_5000_dipakai():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", 5000)) == 0


if __name__ == "__main__":
    if port_5000_dipakai():
        print("Server Flask sudah berjalan di http://127.0.0.1:5000.")
        print("Hentikan instance itu dulu (Ctrl+C di terminalnya) sebelum menjalankan yang baru,")
        print("karena hanya SATU program yang boleh memegang port COM5 sensor R503.")
        sys.exit(1)

    init_db()
    print("\nAIoT Smart Attendance Dashboard")
    print("Dashboard: http://127.0.0.1:5000")
    print("Pendaftaran siswa: http://127.0.0.1:5000/students/register\n")
    # Local development only; do not expose this development server to the Internet.
    app.run(host="127.0.0.1", port=5000, debug=False)
