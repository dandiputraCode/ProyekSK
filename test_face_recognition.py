
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

# Ganti jika alamat IP ESP32 berubah
DASHBOARD_API_URL = "http://127.0.0.1:5000/api/attendance"

ESP32_IP = "10.251.114.225"
ESP32_URL = f"http://{ESP32_IP}"

YOLO_CONFIDENCE = 0.35
YOLO_IMAGE_SIZE = 320

# Nilai awal pengujian, perlu dievaluasi
FACE_THRESHOLD = 0.45

# Pengenalan diulang secara berkala
RECOGNITION_INTERVAL = 1.0
 
# Parameter tracking kotak wajah
TRACK_TIMEOUT = 1.5
IOU_THRESHOLD = 0.20

CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480


# ==================================================
# 2. NORMALISASI EMBEDDING
# ==================================================

def normalisasi(vector):
    panjang = np.linalg.norm(vector)

    if panjang == 0:
        return vector

    return vector / panjang


# ==================================================
# 3. MEMBACA DATABASE FOTO
# ==================================================

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

        embeddings = []

        for foto_path in sorted(folder.iterdir()):

            if foto_path.suffix.lower() not in ekstensi_valid:
                continue

            gambar = cv2.imread(str(foto_path))

            if gambar is None:
                print("Foto gagal dibaca:", foto_path.name)
                continue

            wajah = face_app.get(gambar)

            if len(wajah) != 1:
                print(
                    "Foto dilewati, harus ada tepat satu wajah:",
                    foto_path.name
                )
                continue

            embeddings.append(
                wajah[0].normed_embedding
            )

        if embeddings:

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
# 4. FACE RECOGNITION
# ==================================================

def kenali_siswa(embedding, database):

    npm_terbaik = None
    skor_terbaik = -1.0

    for npm, data in database.items():

        skor = float(
            np.dot(
                embedding,
                data["embedding"]
            )
        )

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
# 5. IOU UNTUK TRACKING WAJAH
# ==================================================

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
# 6. MENGIRIM EVENT ABSENSI KE ESP32
# ==================================================



def kirim_ke_esp32(npm, nama):
    # 1. Catat ke database website
    web_response = requests.post(
        DASHBOARD_API_URL,
        json={
            "npm": npm,
            "nama": nama,
            "source": "Face Recognition"
        },
        timeout=3
    )

    web_response.raise_for_status()
    data_web = web_response.json()

    print("\n===== ABSENSI WEBSITE =====")
    print("Nama:", nama)
    print("NPM:", npm)
    print("Status:", data_web.get("message", "Berhasil"))
    
    # 2. Kirim event ke ESP32
    # Absensi website tetap dianggap berhasil
    # meskipun ESP32 sedang tidak tersedia.
    try:
        esp_response = requests.get(
            f"{ESP32_URL}/test",
            params={
                "event": "FACE_OK",
                "npm": npm,
                "nama": nama
            },
            timeout=3
        )

        esp_response.raise_for_status()
        pesan_esp32 = esp_response.text

        print("ESP32:", pesan_esp32)

    except requests.exceptions.RequestException as error:
        pesan_esp32 = "ESP32 tidak dapat dihubungi"
        print(pesan_esp32, error)

    return {
        "npm": npm,
        "nama": nama,
        "response": (
            f"Website: {data_web.get('message', 'Berhasil')} | "
            f"ESP32: {pesan_esp32}"
        )
    }




# ==================================================
# 7. PEMROSES WAJAH
# ==================================================

class FaceProcessor:

    def __init__(self, yolo, face_app, database):
        self.yolo = yolo
        self.face_app = face_app
        self.database = database
        self.previous_tracks = []

    def process(self, frame, recognize_now):

        tinggi_frame, lebar_frame = frame.shape[:2]

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

        for bbox in detections:

            best_track = None
            best_iou = 0.0

            for idx, old_track in enumerate(
                self.previous_tracks
            ):

                if idx in tracks_terpakai:
                    continue

                skor_iou = hitung_iou(
                    bbox,
                    old_track["bbox"]
                )

                if skor_iou > best_iou:
                    best_iou = skor_iou
                    best_track = idx

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

                track = {
                    "bbox": bbox,
                    "label": "Mengenali...",
                    "color": (0, 165, 255),
                    "npm": None,
                    "verified_now": False
                }

            # Pengenalan hanya pada frame terpilih
            if recognize_now:

                x1, y1, x2, y2 = bbox

                lebar = x2 - x1
                tinggi = y2 - y1

                pad_x = int(lebar * 0.25)
                pad_y = int(tinggi * 0.35)

                cx1 = max(0, x1 - pad_x)
                cy1 = max(0, y1 - pad_y)
                cx2 = min(lebar_frame, x2 + pad_x)
                cy2 = min(tinggi_frame, y2 + pad_y)

                crop = frame[cy1:cy2, cx1:cx2]

                if crop.size > 0:

                    wajah_crop = self.face_app.get(crop)

                    if wajah_crop:

                        wajah = max(
                            wajah_crop,
                            key=lambda f: (
                                (f.bbox[2] - f.bbox[0])
                                * (f.bbox[3] - f.bbox[1])
                            )
                        )

                        npm, nama, skor = kenali_siswa(
                            wajah.normed_embedding,
                            self.database
                        )

                        if npm is not None:

                            track["npm"] = npm
                            track["label"] = (
                                f"{nama} | skor {skor:.2f}"
                            )
                            track["color"] = (0, 200, 0)
                            track["verified_now"] = True

                        else:

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
# 8. PROGRAM UTAMA
# ==================================================

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

    # Satu worker untuk pemrosesan AI
    ai_executor = ThreadPoolExecutor(max_workers=1)

    # Worker terpisah untuk komunikasi ESP32
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

    # Proteksi pengiriman berulang selama program berjalan
    sudah_dikirim = set()
    sedang_dikirim = {}
    percobaan_terakhir = {}

    waktu_pengakuan_terakhir = 0.0

    display_fps = 0.0
    waktu_frame_terakhir = time.perf_counter()

    print("\nSistem absensi AIoT aktif.")
    print("ESP32:", ESP32_URL)
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

                    npm = track.get("npm")

                    if not npm:
                        continue

                    if not track.get("verified_now"):
                        continue

                    if npm in sudah_dikirim:
                        continue

                    if npm in sedang_dikirim:
                        continue

                    percobaan_sebelumnya = (
                        percobaan_terakhir.get(npm, 0.0)
                    )

                    # Jika gagal, tunggu sebelum mencoba lagi
                    if sekarang - percobaan_sebelumnya < 5:
                        continue

                    nama = database[npm]["nama"]

                    job = http_executor.submit(
                        kirim_ke_esp32,
                        npm,
                        nama
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

                    print(
                        "\nABSENSI DIKIRIM KE ESP32:"
                    )
                    print("Nama:", hasil_kirim["nama"])
                    print("NPM:", hasil_kirim["npm"])
                    print("Respons:", hasil_kirim["response"])

                except Exception as error:

                    print(
                        f"Gagal mengirim NPM {npm}:",
                        error
                    )

                finally:
                    sedang_dikirim.pop(npm, None)

            # --------------------------------------
            # D. JADWALKAN FRAME UNTUK AI
            # --------------------------------------

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

            # Status komunikasi ESP32
            cv2.putText(
                frame,
                f"ESP32 terkirim: {len(sudah_dikirim)} siswa",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 255, 0),
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
