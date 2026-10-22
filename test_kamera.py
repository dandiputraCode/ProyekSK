import cv2

# Membuka kamera bawaan laptop
kamera = cv2.VideoCapture(0)

if not kamera.isOpened():
    print("Kamera gagal dibuka.")
    print("Periksa izin kamera Windows.")
    raise SystemExit

print("Kamera berhasil dibuka.")
print("Tekan Q untuk menutup kamera.")

while True:
    berhasil, frame = kamera.read()

    if not berhasil:
        print("Gagal membaca gambar kamera.")
        break

    cv2.imshow("Tes Kamera Laptop", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

kamera.release()
cv2.destroyAllWindows()
