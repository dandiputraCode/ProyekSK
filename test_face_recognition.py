
import cv2
import time
import numpy as np
import requests

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from ultralytics import YOLO
from insightface.app import FaceAnalysis


# ==================================================
# 1. KONFIGURASI
# ==================================================

BASE_DIR = Path(__file__).resolve().parent

MODEL_PATH = BASE_DIR / "models" / "yolo26n-face.pt"
DATABASE_PATH = BASE_DIR / "database_wajah"

# Alamat Flask lokal yang memegang port USB ESP32/R503.
DASHBOARD_API_URL = "http://127.0.0.1:5000/api/attendance"


YOLO_CONFIDENCE = 0.35
YOLO_IMAGE_SIZE = 320

# Nilai awal pengujian, perlu dievaluasi
FACE_THRESHOLD = 0.45

# Pengenalan diulang secara berkala
RECOGNITION_INTERVAL = 1.0

# Jeda sebelum mencoba absensi lagi setelah sidik jari ditolak (naik 2x, maksimal 60 detik).
GAGAL_JEDA_AWAL = 15
GAGAL_JEDA_MAKS = 60
 
# Parameter tracking kotak wajah
TRACK_TIMEOUT = 1.5
IOU_THRESHOLD = 0.20

CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480


# ==================================================
# 2. NORMALISASI EMBEDDING (L2 NORMALIZATION)
# ==================================================
# Fungsi: Mengubah panjang vektor embedding menjadi tepat 1.0.
# Alasan: Cosine similarity antara dua vektor ternormalisasi (A dan B)
# disederhanakan menjadi perkalian titik sederhana (dot product: np.dot(A, B)),
# tanpa perlu pembagian dengan ||A|| * ||B|| yang membebani komputasi CPU.
def normalisasi(vector):
    panjang = np.linalg.norm(vector)

    if panjang == 0:
        return vector

    return vector / panjang


# ==================================================
# 3. MEMBACA DATABASE FOTO WAJAH SISWA
# ==================================================
# Fungsi: Memindai folder 'database_wajah/', membaca foto setiap siswa (NPM_Nama),
# mengekstrak fitur 512-d via InsightFace ArcFace, lalu merata-ratakan vektornya.
def muat_database(face_app):
    database = {}

    if not DATABASE_PATH.exists():
        raise FileNotFoundError(
            f"Folder tidak ditemukan: {DATABASE_PATH}"
        )

    ekstensi_valid = {
        ".jpg", ".jpeg", ".png", ".webp"
    }

    for folder in sorted(DATABASE_PATH.iterdir()):

        if not folder.is_dir() or "_" not in folder.name:
            continue

        npm, nama = folder.name.split("_", 1)
        nama = nama.replace("_", " ")

        # Menyimpan vektor embedding dari seluruh foto valid dalam satu folder siswa
        embeddings = []

        for foto_path in sorted(folder.iterdir()):

            if foto_path.suffix.lower() not in ekstensi_valid:
                continue

            # Membaca file citra menggunakan OpenCV (format BGR)
            gambar = cv2.imread(str(foto_path))

            if gambar is None:
                print("Foto gagal dibaca:", foto_path.name)
                continue

            # Ekstraksi fitur wajah via InsightFace
            wajah = face_app.get(gambar)

            # Validasi ketat: foto referensi hanya boleh memuat tepat 1 wajah
            if len(wajah) != 1:
                print(
                    "Foto dilewati, harus ada tepat satu wajah:",
                    foto_path.name
                )
                continue

            # normed_embedding adalah vektor 512 dimensi yang sudah dinormalisasi L2
            embeddings.append(
                wajah[0].normed_embedding
            )

        # Jika terdapat minimal 1 foto yang valid, buat vektor representatif rata-rata
        if embeddings:

            # Rata-rata vektor dari beberapa foto (depan, sudut kiri, sudut kanan)
            # menghasilkan representasi wajah yang lebih toleran terhadap perubahan pose.
            rata_rata = np.mean(
                np.asarray(embeddings),
                axis=0
            )

            database[npm] = {
                "nama": nama,
                "embedding": normalisasi(rata_rata)
            }

            print(
                f"Terdaftar: {nama} | NPM: {npm} | "
                f"Foto valid: {len(embeddings)}"
            )

    if not database:
        raise RuntimeError(
            "Database kosong. Periksa folder foto siswa."
        )

    return database


# ==================================================
# 4. PENGENALAN IDENTITAS WAJAH (COSINE SIMILARITY)
# ==================================================
# Fungsi: Membandingkan 512-d vektor wajah kamera dengan seluruh database siswa.
# Skor berupa rentang -1.0 hingga 1.0 (nilai 1.0 = identik sempurna).
# Mengembalikan (NPM, Nama, Skor) jika skor >= FACE_THRESHOLD (0.45).
def kenali_siswa(embedding, database):

    npm_terbaik = None
    skor_terbaik = -1.0

    for npm, data in database.items():

        # Dot product pada dua vektor berpanjang 1.0 setara dengan Cosine Similarity
        skor = float(
            np.dot(
                embedding,
                data["embedding"]
            )
        )

        # Pencarian skor kemiripan tertinggi (argmax)
        if skor > skor_terbaik:
            skor_terbaik = skor
            npm_terbaik = npm

    if (
        npm_terbaik is not None
        and skor_terbaik >= FACE_THRESHOLD
    ):
        return (
            npm_terbaik,
            database[npm_terbaik]["nama"],
            skor_terbaik
        )

    return None, "Tidak dikenal", skor_terbaik


# ==================================================
# 5. IOU (INTERSECTION OVER UNION) UNTUK TRACKING
# ==================================================
# Fungsi: Mengukur rasio tumpang tindih antara kotak deteksi frame saat ini
# dengan kotak frame sebelumnya. Digunakan untuk melacak pergerakan wajah (tracking)
# antar-frame tanpa perlu menjalankan pengenalan wajah berulang-ulang setiap frame.
def hitung_iou(a, b):

    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b

    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)

    irisan = (
        max(0, ix2 - ix1)
        * max(0, iy2 - iy1)
    )

    luas_a = (
        max(0, ax2 - ax1)
        * max(0, ay2 - ay1)
    )

    luas_b = (
        max(0, bx2 - bx1)
        * max(0, by2 - by1)
    )

    gabungan = luas_a + luas_b - irisan

    if gabungan <= 0:
        return 0.0

    return irisan / gabungan


# ==================================================
# 6. PENGIRIMAN DATA ABSENSI (WEBSITE + SIDIK JARI R503)
# ==================================================
# Alur 2 faktor: wajah dikenali -> Flask meminta sidik jari cocok di sensor R503
# (port USB dipegang app_web.py) -> baru absensi dicatat ke SQLite.
# Fungsi ini berjalan di thread HTTP sehingga video kamera tidak membeku.
def jeda_ulang(jumlah_gagal):
    """Backoff eksponensial: 15s, 30s, 60s, 60s, ..."""
    if jumlah_gagal <= 0:
        return 0
    return min(GAGAL_JEDA_MAKS, GAGAL_JEDA_AWAL * 2 ** (jumlah_gagal - 1))
def boleh_kirim(npm, sekarang, percobaan_terakhir, gagal_berturut):
    """True bila NPM ini boleh dicoba absensi lagi (jeda backoff sudah lewat)."""
    return (
        sekarang - percobaan_terakhir.get(npm, 0.0)
        >= jeda_ulang(gagal_berturut.get(npm, 0))
    )



def kirim_absensi(npm, nama, percobaan=1):

    print(f"\nWAJAH DIKENALI: {nama} ({npm}) - percobaan absensi ke-{percobaan}")
    print("Tempelkan jari pada sensor R503 (maksimal 30 detik)...")

    web_response = requests.post(
        DASHBOARD_API_URL,
        json={
            "npm": npm,
            "nama": nama,
            "source": "Face Recognition"
        },
        timeout=35
    )

    data_web = web_response.json() if web_response.content else {}

    if not web_response.ok:
        raise RuntimeError(
            data_web.get("message")
            or f"Absensi 2 faktor ditolak (HTTP {web_response.status_code})."
        )

    print("\n===== ABSENSI WEBSITE =====")
    print("Nama:", nama)
    print("NPM:", npm)
    print("Status:", data_web.get("message", "Berhasil"))
    if data_web.get("finger_confidence") is not None:
        print("Confidence sidik jari:", data_web["finger_confidence"])

    return {
        "npm": npm,
        "nama": nama,
        "response": data_web.get("message", "Berhasil"),
    }




# ==================================================
# 7. KELAS PEMROSES WAJAH (FACE PROCESSOR)
# ==================================================
# Kelas ini memadukan 3 tahapan penglihatan komputer:
# 1. Deteksi cepat lokasi wajah menggunakan Ultralytics YOLO (setiap frame yang diproses).
# 2. Asosiasi kotak wajah lama dan baru menggunakan algoritma IoU Tracking.
# 3. Crop area wajah + pengenalan biometrik via InsightFace ArcFace (secara berkala).
class FaceProcessor:

    def __init__(self, yolo, face_app, database):
        self.yolo = yolo
        self.face_app = face_app
        self.database = database
        self.previous_tracks = []

    def process(self, frame, recognize_now):

        tinggi_frame, lebar_frame = frame.shape[:2]

        # Tahap 1: Inferensi YOLO pada CPU dengan resolusi input diperkecil (320x320)
        # agar inferensi berlangsung ringan (< 30-50 ms).
        hasil = self.yolo.predict(
            source=frame,
            conf=YOLO_CONFIDENCE,
            imgsz=YOLO_IMAGE_SIZE,
            device="cpu",
            verbose=False
        )[0]

        detections = []

        if hasil.boxes is not None:

            boxes = (
                hasil.boxes.xyxy
                .cpu()
                .numpy()
                .astype(int)
            )

            for box in boxes:
                detections.append(
                    tuple(map(int, box))
                )

        tracks_baru = []
        tracks_terpakai = set()

        # Tahap 2: Cocokkan setiap kotak hasil deteksi YOLO dengan jejak wajah sebelumnya (IoU Tracking)
        for bbox in detections:

            best_track = None
            best_iou = 0.0

            for idx, old_track in enumerate(
                self.previous_tracks
            ):

                if idx in tracks_terpakai:
                    continue

                # Hitung nilai tumpang-tindih (IoU) dengan kotak di frame sebelumnya
                skor_iou = hitung_iou(
                    bbox,
                    old_track["bbox"]
                )

                if skor_iou > best_iou:
                    best_iou = skor_iou
                    best_track = idx

            # Jika tumpang tindih memadai (IoU >= 0.20), pertahankan identitas yang sudah dikenali
            if (
                best_track is not None
                and best_iou >= IOU_THRESHOLD
            ):

                old = self.previous_tracks[best_track]

                track = {
                    "bbox": bbox,
                    "label": old["label"],
                    "color": old["color"],
                    "npm": old["npm"],
                    "verified_now": False
                }

                tracks_terpakai.add(best_track)

            else:

                # Wajah baru yang belum pernah terdeteksi di frame sebelumnya
                track = {
                    "bbox": bbox,
                    "label": "Mengenali...",
                    "color": (0, 165, 255),
                    "npm": None,
                    "verified_now": False
                }

            # Tahap 3: Pengenalan identitas wajah hanya dijalankan pada interval waktu tertentu (1 detik)
            # untuk menghemat sumber daya CPU laptop.
            if recognize_now:

                x1, y1, x2, y2 = bbox

                lebar = x2 - x1
                tinggi = y2 - y1

                # Tambahkan bantalan margin (padding) 25% horizontal dan 35% vertikal
                # agar dahi, rahang, dan telinga ikut terbaca oleh InsightFace.
                pad_x = int(lebar * 0.25)
                pad_y = int(tinggi * 0.35)

                cx1 = max(0, x1 - pad_x)
                cy1 = max(0, y1 - pad_y)
                cx2 = min(lebar_frame, x2 + pad_x)
                cy2 = min(tinggi_frame, y2 + pad_y)

                crop = frame[cy1:cy2, cx1:cx2]

                if crop.size > 0:
                    # InsightFace mengekstrak landmark 5 titik dan vektor embedding 512-d

                    wajah_crop = self.face_app.get(crop)

                    if wajah_crop:
                        # Ambil wajah dengan ukuran kotak terluas di area crop

                        wajah = max(
                            wajah_crop,
                            key=lambda f: (
                                (f.bbox[2] - f.bbox[0])
                                * (f.bbox[3] - f.bbox[1])
                            )
                        )

                        # Cocokkan embedding wajah dengan database
                        npm, nama, skor = kenali_siswa(
                            wajah.normed_embedding,
                            self.database
                        )

                        if npm is not None:
                            # Siswa terdaftar: kotak hijau dan label nama

                            track["npm"] = npm
                            track["label"] = (
                                f"{nama} | skor {skor:.2f}"
                            )
                            track["color"] = (0, 200, 0)
                            track["verified_now"] = True

                        else:
                            # Siswa tidak terdaftar / skor < 0.45: kotak merah

                            track["npm"] = None
                            track["label"] = "Tidak dikenal"
                            track["color"] = (0, 0, 255)
                            track["verified_now"] = False

                    else:

                        track["npm"] = None
                        track["label"] = "Wajah belum terbaca"
                        track["color"] = (0, 165, 255)
                        track["verified_now"] = False

            tracks_baru.append(track)

        self.previous_tracks = tracks_baru

        return tracks_baru


# ==================================================
# 8. PROGRAM UTAMA (LOOP MULTI-THREADING)
# ==================================================
# Arsitektur loop utama:
# - Thread Utama: Membaca webcam dan merender visual 30 FPS secara mulus.
# - Thread AI (ai_executor): Menjalankan YOLO dan ArcFace secara asinkron tanpa menahan FPS kamera.
# - Thread HTTP (http_executor): Mengirim data ke Flask dan ESP32 di latar belakang tanpa freeze.
def main():

    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Model YOLO tidak ditemukan: {MODEL_PATH}"
        )

    print("Memuat model YOLO...")
    yolo = YOLO(str(MODEL_PATH))

    print("Memuat InsightFace...")
    face_app = FaceAnalysis(
        name="buffalo_l",
        providers=["CPUExecutionProvider"]
    )

    face_app.prepare(
        ctx_id=-1,
        det_size=(320, 320)
    )

    print("Memuat database wajah...")
    database = muat_database(face_app)

    processor = FaceProcessor(
        yolo,
        face_app,
        database
    )

    # Worker terpisah: 1 thread untuk inferensi AI agar tidak memblokir loop kamera
    ai_executor = ThreadPoolExecutor(max_workers=1)

    # Worker terpisah: 1 thread untuk permintaan jaringan HTTP (Flask & ESP32)
    http_executor = ThreadPoolExecutor(max_workers=1)

    kamera = cv2.VideoCapture(0)

    kamera.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    kamera.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
    kamera.set(cv2.CAP_PROP_FPS, 30)
    kamera.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    if not kamera.isOpened():
        ai_executor.shutdown(wait=False)
        http_executor.shutdown(wait=False)

        raise RuntimeError(
            "Kamera tidak dapat dibuka."
        )

    ai_future = None
    tracks_terakhir = []

    # Proteksi anti-spam: Mencegah pengiriman data berulang kali untuk siswa yang sama
    sudah_dikirim = set()         # Siswa yang sudah sukses dikirim selama sesi aplikasi berjalan
    sedang_dikirim = {}           # Job HTTP yang masih aktif mengudara di background
    percobaan_terakhir = {}       # Waktu percobaan terakhir per NPM
    gagal_berturut = {}           # Jumlah kegagalan sidik jari berturut-turut per NPM
    terakhir_terlihat = {}        # Waktu terakhir wajah siswa terverifikasi

    waktu_pengakuan_terakhir = 0.0

    display_fps = 0.0
    waktu_frame_terakhir = time.perf_counter()

    print("\nSistem absensi AIoT aktif.")
    print("Dashboard (2 faktor):", DASHBOARD_API_URL)
    print("Tekan Q untuk keluar.")

    try:

        while True:

            berhasil, frame = kamera.read()

            if not berhasil:
                print("Gagal membaca kamera.")
                break

            sekarang = time.monotonic()

            # --------------------------------------
            # A. AMBIL HASIL PEMROSESAN AI
            # --------------------------------------

            if ai_future is not None and ai_future.done():

                try:
                    tracks_terakhir = ai_future.result()

                except Exception as error:
                    print("Kesalahan pemrosesan AI:", error)

                ai_future = None

                # ----------------------------------
                # B. KIRIM IDENTITAS YANG BARU
                #    DIVERIFIKASI KE ESP32
                # ----------------------------------

                for track in tracks_terakhir:
                    if track.get("npm") and track.get("verified_now"):
                        terakhir_terlihat[track["npm"]] = sekarang

                # Siswa yang wajahnya hilang > 5 detik dianggap pergi: reset jeda backoff.
                for npm_lama in list(gagal_berturut):
                    if sekarang - terakhir_terlihat.get(npm_lama, 0.0) > 5:
                        gagal_berturut.pop(npm_lama, None)

                for track in tracks_terakhir:

                    npm = track.get("npm")

                    if not npm:
                        continue

                    if not track.get("verified_now"):
                        continue

                    if npm in sudah_dikirim:
                        continue

                    if npm in sedang_dikirim:
                        continue

                    if not boleh_kirim(npm, sekarang, percobaan_terakhir, gagal_berturut):
                        continue

                    nama = database[npm]["nama"]

                    job = http_executor.submit(
                        kirim_absensi,
                        npm,
                        nama,
                        gagal_berturut.get(npm, 0) + 1
                    )

                    sedang_dikirim[npm] = job
                    percobaan_terakhir[npm] = sekarang

            # --------------------------------------
            # C. PERIKSA HASIL KOMUNIKASI HTTP
            # --------------------------------------

            for npm, job in list(sedang_dikirim.items()):

                if not job.done():
                    continue

                try:
                    hasil_kirim = job.result()

                    sudah_dikirim.add(npm)
                    gagal_berturut.pop(npm, None)

                    print("\nABSENSI 2 FAKTOR BERHASIL:")
                    print("Nama:", hasil_kirim["nama"])
                    print("NPM:", hasil_kirim["npm"])
                    print("Respons:", hasil_kirim["response"])

                except Exception as error:

                    gagal_berturut[npm] = gagal_berturut.get(npm, 0) + 1
                    percobaan_terakhir[npm] = time.monotonic()

                    print(
                        f"Gagal mengirim NPM {npm} (percobaan ke-{gagal_berturut[npm]}):",
                        error
                    )
                    print(
                        f"Absensi NPM {npm} dijeda {jeda_ulang(gagal_berturut[npm])} detik. "
                        "Jauhkan wajah dari kamera untuk membatalkan percobaan."
                    )

                finally:
                    sedang_dikirim.pop(npm, None)

            # --------------------------------------
            # D. JADWALKAN FRAME UNTUK AI
            # --------------------------------------
            # Jika worker AI sedang menganggur, kirim salinan frame terbaru ke background

            if ai_future is None:

                recognize_now = (
                    sekarang - waktu_pengakuan_terakhir
                    >= RECOGNITION_INTERVAL
                )

                if recognize_now:
                    waktu_pengakuan_terakhir = sekarang

                ai_future = ai_executor.submit(
                    processor.process,
                    frame.copy(),
                    recognize_now
                )

            # --------------------------------------
            # E. TAMPILKAN VIDEO DAN HASIL TERAKHIR
            # --------------------------------------

            for track in tracks_terakhir:

                x1, y1, x2, y2 = track["bbox"]

                cv2.rectangle(
                    frame,
                    (x1, y1),
                    (x2, y2),
                    track["color"],
                    2
                )

                cv2.putText(
                    frame,
                    track["label"],
                    (x1, max(25, y1 - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    track["color"],
                    2
                )

            # Status absensi 2 faktor (wajah + sidik jari)
            if sedang_dikirim:
                status_absensi = "TEMPELKAN JARI DI R503: " + ", ".join(sedang_dikirim)
                warna_status = (0, 215, 255)
            elif gagal_berturut:
                npm_tunggu, sisa = min(
                    (
                        (
                            npm,
                            jeda_ulang(gagal)
                            - (sekarang - percobaan_terakhir.get(npm, 0.0))
                        )
                        for npm, gagal in gagal_berturut.items()
                    ),
                    key=lambda item: item[1],
                )
                status_absensi = (
                    f"Sidik jari ditolak ({npm_tunggu}) - coba lagi {max(0.0, sisa):.0f} detik"
                )
                warna_status = (0, 0, 255)
            else:
                status_absensi = f"Absensi terverifikasi: {len(sudah_dikirim)} siswa"
                warna_status = (255, 255, 0)

            cv2.putText(
                frame,
                status_absensi,
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                warna_status,
                2
            )

            # FPS tampilan kamera
            waktu_sekarang = time.perf_counter()

            delta = waktu_sekarang - waktu_frame_terakhir
            waktu_frame_terakhir = waktu_sekarang

            if delta > 0:

                fps_baru = 1.0 / delta

                if display_fps == 0:
                    display_fps = fps_baru
                else:
                    display_fps = (
                        0.9 * display_fps
                        + 0.1 * fps_baru
                    )

            cv2.putText(
                frame,
                f"Display FPS: {display_fps:.1f}",
                (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 0),
                2
            )

            cv2.imshow(
                "AIoT Smart Attendance",
                frame
            )

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    finally:

        kamera.release()
        cv2.destroyAllWindows()

        ai_executor.shutdown(
            wait=True,
            cancel_futures=True
        )

        http_executor.shutdown(
            wait=True,
            cancel_futures=True
        )

        print("Sistem absensi dihentikan.")


if __name__ == "__main__":
    main()
