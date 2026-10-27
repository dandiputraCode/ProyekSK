# AIoT Smart Attendance

Sistem absensi berbasis AI (YOLO + InsightFace) dan IoT (ESP32) dengan dashboard lokal Flask + SQLite.

## Struktur Folder

```text
├── app_web.py                # Server web Flask + SQLite + API pendaftaran
├── test_face_recognition.py  # Engine pengenalan wajah real-time
├── attendance.db             # Database SQLite lokal (dibuat otomatis)
├── models/                   # Letakkan file yolo26n-face.pt di sini
├── database_wajah/           # Foto biometrik siswa (NPM_Nama/foto1-3.jpg)
├── templates/                # Template HTML dashboard & enroll
├── static/                   # CSS & JS frontend
├── firmware/                 # Source code Arduino / ESP32
├── tests/                    # Script uji coba modular (kamera, YOLO, ESP32)
└── docs/                     # Dokumentasi detail & panduan pendaftaran
```

## Cara Menjalankan

### 1. Terminal 1 — Dashboard Web
```cmd
python app_web.py
```
Akses di browser: `http://127.0.0.1:5000`

### 2. Terminal 2 — Face Recognition
```cmd
python test_face_recognition.py
```

## Pengujian Terpisah (`tests/`)
* `python tests/test_kamera.py` — Uji koneksi webcam OpenCV
* `python tests/test_yolo.py` — Uji deteksi kotak wajah YOLO
* `python tests/test_esp32_http.py` — Uji kirim event ke ESP32

## Dokumentasi Teknis (`docs/`)
* **[`docs/CARA_KERJA_YOLO_DAN_FACE_RECOGNITION.md`](docs/CARA_KERJA_YOLO_DAN_FACE_RECOGNITION.md)** — Alur matematis Bounding Box YOLO dan pencocokan wajah InsightFace.
* **[`docs/PENJELASAN_6_LIBRARY_AI_VISION.md`](docs/PENJELASAN_6_LIBRARY_AI_VISION.md)** — Penjelasan mendalam 6 library AI/Vision, konsep **ArcFace**, analogi, ilustrasi, dan potongan kode asli.
* **[`docs/CARA_KERJA_WEBSITE_SQLITE_DAN_ESP32.md`](docs/CARA_KERJA_WEBSITE_SQLITE_DAN_ESP32.md)** — Penjelasan mendalam Web Server Flask, Database SQLite, HTTP Requests, dan IoT ESP32.

## Library & Dependensi yang Digunakan

### A. Bagian AI & Face Recognition
| Library | Kegunaan dalam Proyek | Website Resmi / Dokumentasi |
| :--- | :--- | :--- |
| **Ultralytics YOLO** | Deteksi lokasi wajah (*bounding box* `xyxy`) pada frame kamera dan validasi 1 wajah saat pendaftaran. | [https://www.ultralytics.com](https://www.ultralytics.com) / [Docs](https://docs.ultralytics.com) |
| **InsightFace** | Ekstraksi fitur biometrik wajah 512-dimensi (*ArcFace* `buffalo_l`). | [https://insightface.ai](https://insightface.ai) / [GitHub](https://github.com/deepinsight/insightface) |
| **OpenCV (`cv2`)** | Akuisisi kamera, *cropping* wajah, dan penggambaran `cv2.rectangle()` / `cv2.putText()`. | [https://opencv.org](https://opencv.org) / [Docs](https://docs.opencv.org) |
| **NumPy** | Komputasi matriks gambar, normalisasi L2 (`np.linalg.norm`), dan *Cosine Similarity* (`np.dot`). | [https://numpy.org](https://numpy.org) |
| **ONNX Runtime** | Runtime eksekusi model `.onnx` milik InsightFace di CPU (`CPUExecutionProvider`). | [https://onnxruntime.ai](https://onnxruntime.ai) |
| **PyTorch (`torch`)** | Engine deep learning di balik model `.pt` milik Ultralytics YOLO. | [https://pytorch.org](https://pytorch.org) |

### B. Bagian Website, Database SQLite & IoT (ESP32)
| Library | Kegunaan dalam Proyek | Website Resmi / Dokumentasi |
| :--- | :--- | :--- |
| **Flask** | Backend web server lokal (`127.0.0.1:5000`), endpoint API absensi, dan pendaftaran siswa. | [https://flask.palletsprojects.com](https://flask.palletsprojects.com) |
| **Requests** | Pengiriman HTTP POST ke dashboard Flask dan HTTP GET ke ESP32. | [https://requests.readthedocs.io](https://requests.readthedocs.io) |
| **SQLite (`sqlite3`)** | Penyimpanan database relasional lokal (`attendance.db`). | [https://www.sqlite.org](https://www.sqlite.org) |
| **Arduino ESP32** | Pustaka `WiFi.h` dan `WebServer.h` pada mikrokontroler ESP32. | [https://espressif.github.io/arduino-esp32/](https://espressif.github.io/arduino-esp32/) |
