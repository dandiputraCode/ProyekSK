
from pathlib import Path
import cv2
from ultralytics import YOLO

# ponytail: path relatif ke root proyek agar aman dijalankan dari mana saja
MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "yolo26n-face.pt"
model = YOLO(str(MODEL_PATH))

# Membuka kamera bawaan laptop
kamera = cv2.VideoCapture(0)

if not kamera.isOpened():
    raise RuntimeError(
        "Kamera tidak dapat dibuka. Periksa izin kamera."
    )

print("YOLO Face Detection aktif.")
print("Tekan Q untuk keluar.")

try:
    while True:
        berhasil, frame = kamera.read()

        if not berhasil:
            print("Gagal mengambil gambar dari kamera.")
            break

        # Mendeteksi wajah pada gambar kamera
        hasil = model.predict(
            source=frame,
            conf=0.35,
            verbose=False
        )[0]

        # Menggambar kotak pada wajah yang terdeteksi
        frame_hasil = hasil.plot()

        cv2.imshow(
            "AIoT Smart Attendance - Face Detection",
            frame_hasil
        )

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

finally:
    kamera.release()
    cv2.destroyAllWindows()
