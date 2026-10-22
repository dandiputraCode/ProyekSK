from datetime import date, datetime
from pathlib import Path
import base64
import binascii
import csv
import io
import re
import shutil
import sqlite3

import cv2
import numpy as np
from flask import Flask, jsonify, render_template, request, Response

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "attendance.db"
FACE_DB_PATH = BASE_DIR / "database_wajah"
YOLO_MODEL_PATH = BASE_DIR / "models" / "yolo26n-face.pt"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024

# YOLO face detector is loaded lazily when an admin registers a student.
_FACE_DETECTOR = None


def get_db():
    connection = sqlite3.connect(DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    return connection


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
        connection.commit()


def count_registered_students():
    if not FACE_DB_PATH.exists():
        return 0
    image_extensions = {".jpg", ".jpeg", ".png", ".webp"}
    total = 0
    for folder in FACE_DB_PATH.iterdir():
        if not folder.is_dir() or "_" not in folder.name:
            continue
        if any(p.is_file() and p.suffix.lower() in image_extensions for p in folder.iterdir()):
            total += 1
    return total


def npm_already_registered(npm):
    if not FACE_DB_PATH.exists():
        return False
    prefix = f"{npm}_"
    return any(
        folder.is_dir() and folder.name.startswith(prefix)
        for folder in FACE_DB_PATH.iterdir()
    )


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


@app.route("/")
def dashboard():
    return render_template("index.html")


@app.get("/students/register")
def student_registration_page():
    return render_template("enroll.html")


@app.post("/api/students/register")
def register_student():
    """Local prototype endpoint for controlled webcam enrollment."""
    payload = request.get_json(silent=True) or {}

    npm = str(payload.get("npm", "")).strip()
    nama = str(payload.get("nama", "")).strip()
    photos = payload.get("photos")
    consent = payload.get("consent") is True

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

    return jsonify({
        "status": "registered",
        "message": "Siswa berhasil didaftarkan. Hentikan lalu jalankan ulang program Face Recognition agar foto baru dimuat.",
        "student": {
            "npm": npm,
            "nama": nama,
            "photo_count": len(validated_images),
        },
    }), 201


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

    registered = count_registered_students()
    present_count = len({row["npm"] for row in today_rows})
    percentage = round((present_count / registered) * 100) if registered else 0

    return jsonify({
        "selected_date": selected_date,
        "registered_students": registered,
        "present_count": present_count,
        "total_records": total_records,
        "attendance_percentage": min(percentage, 100),
        "records": [dict(row) for row in today_rows[:200]],
        "server_time": datetime.now().strftime("%d %b %Y, %H:%M:%S"),
    })


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
    waktu = datetime.now().strftime("%H:%M:%S")

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


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "AIoT Smart Attendance Dashboard"})


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({"status": "error", "message": "Total ukuran foto terlalu besar. Ambil ulang foto dengan kamera standar."}), 413


if __name__ == "__main__":
    init_db()
    print("\nAIoT Smart Attendance Dashboard")
    print("Dashboard: http://127.0.0.1:5000")
    print("Pendaftaran siswa: http://127.0.0.1:5000/students/register\n")
    # Local development only; do not expose this development server to the Internet.
    app.run(host="127.0.0.1", port=5000, debug=False)
