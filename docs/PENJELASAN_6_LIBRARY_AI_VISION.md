# Penjelasan Mendalam 6 Library AI & Vision (YOLO, InsightFace, OpenCV, NumPy, ONNX Runtime, PyTorch)

Dokumen ini khusus membedah **6 pustaka penglihatan komputer (Computer Vision) dan kecerdasan buatan (AI)** yang dipakai pada script `test_face_recognition.py` dan `app_web.py`.

---

## 1. Analogi Sederhana Alur Kerja Sistem

Agar mudah dibayangkan, bayangkan proses absensi ini seperti tim pos pemeriksaan di gerbang sekolah:

```text
[Feed Kamera Laptop]
       │
       ▼
1. OpenCV (Juru Kamera)        ──> "Saya ambil video, potong gambar, dan lukis kotak ke layar."
       │
       ▼
2. PyTorch + YOLO (Satpam)     ──> "Ada kepala manusia di koordinat piksel [x1, y1, x2, y2]!"
       │
       ▼
3. OpenCV (Tukang Potong)      ──> "Saya gunting pas area wajahnya ditambah sedikit margin."
       │
       ▼
4. ONNX Runtime (Mesin Motor)  ──> "Saya putar model deep learning di CPU tanpa butuh GPU."
       │
       ▼
5. InsightFace / ArcFace       ──> "Saya ukur biometrik mata, hidung, rahang menjadi 512 angka desimal."
   (Ahli Biometrik)
       │
       ▼
6. NumPy (Kalkulator Kilat)    ──> "Saya kalikan 512 angka tadi dengan database. Kemiripan 0.88 -> COCOK!"
```

---

## 2. Apa itu YOLO? (Konsep Inti Deteksi Kotak Wajah)

### A. Masalah Metode Deteksi Lama (*Sliding Window* / Haar Cascade)
Sebelum ada YOLO, komputer mencari wajah dengan cara menggeser kotak kaca pembesar (*sliding window*) ribuan kali dari pojok kiri-atas ke kanan-bawah layar dengan berbagai ukuran kotak.
* **Kelemahan**: Sangat lambat (membuat video patah-patah) dan sering salah mengira benda bulat (jam dinding/kipas angin) sebagai wajah.

### B. Konsep Inti YOLO (*You Only Look Once* — "Sekali Lihat Langsung Tahu")

```text
   Frame Kamera (Diperkecil ke 320x320 & Dibagi Grid S x S)
   +-----------+-----------+-----------+-----------+
   |           |           |           |           |
   |           |  (x1,y1)  |           |           |
   |           |     #===================#         |
   +-----------+-----#-----+-----------+ | --------+
   |           |     |     |   WAJAH   | |         |
   |           |     |     |    (●) <--+-+-- Titik Tengah Wajah
   |           |     |     |           | |   jatuh di petak ini!
   +-----------+-----+-----+-----------+-#---------+
   |           |     #===================#         |
   |           |           |          (x2,y2)      |
   +-----------+-----------+-----------+-----------+
```

1. **Kompresi Ukuran (`imgsz=320`)**:
   Frame asli dari kamera (`640x480`) dikecilkan sementara ke `320x320` piksel agar CPU laptop sanggup menghitungnya di bawah **40 milidetik**.
2. **Grid Papan Catur ($S \times S$)**:
   YOLO membagi gambar menjadi petak-petak grid sekaligus dalam **1 kali jalan (*single forward pass*)**. Setiap petak kecil di grid bertugas menjawab: *"Apakah titik pusat (`●`) sebuah wajah jatuh di dalam petakku?"*
3. **Menghasilkan 5 Nilai Utama per Kotak**:
   Jika sebuah petak mendeteksi titik tengah wajah, petak itu mengeluarkan:
   * **`conf` (*Confidence*)**: Skor keyakinan `0.00` s.d. `1.00`. Di proyek ini batasnya `0.35` (keyakinan di bawah 35% langsung dibuang).
   * **`[x1, y1, x2, y2]` (*Format xyxy*)**:
     * `(x1, y1)` = Koordinat piksel pojok **kiri-atas** wajah.
     * `(x2, y2)` = Koordinat piksel pojok **kanan-bawah** wajah.
4. **Pembersihan Kotak Ganda (*NMS / End-to-End YOLO26*)**:
   Sering kali 3 petak grid yang bersebelahan sama-sama menunjuk 1 wajah yang sama sehingga muncul banyak kotak bertumpuk. YOLO menyaring tumpukan tersebut dan hanya menyisakan **1 kotak paling akurat**.

---

## 3. Apa itu OpenCV? (Konsep Matriks BGR & Crop Padding)

### A. Bagaimana Komputer Melihat Gambar? (Matriks 3 Lapis B-G-R)
Manusia melihat gambar sebagai wajah utuh, tetapi di dalam OpenCV, satu frame kamera hanyalah **tabel angka 3 dimensi (`480 baris × 640 kolom × 3 warna`)**:
1. **Sumbu Y (Tinggi = `480` baris)**: Dihitung dari paling atas (`y = 0`) turun ke paling bawah (`y = 480`).
2. **Sumbu X (Lebar = `640` kolom)**: Dihitung dari paling kiri (`x = 0`) ke paling kanan (`x = 640`).
3. **3 Lapis Warna B-G-R (*Blue, Green, Red*)**: Setiap titik piksel memiliki 3 angka kecerahan dari `0` (gelap) sampai `255` (paling terang).
   * **Penting**: OpenCV menggunakan urutan **BGR (Biru-Hijau-Merah)**, bukan RGB! Itulah sebabnya di kode proyek:
     * `(0, 200, 0)` = Biru 0, **Hijau 200**, Merah 0 $\rightarrow$ **Kotak Hijau** (Siswa dikenali).
     * `(0, 0, 255)` = Biru 0, Hijau 0, **Merah 255** $\rightarrow$ **Kotak Merah** (Orang asing / Tidak dikenal).
     * `(0, 165, 255)` = Biru 0, **Hijau 165 + Merah 255** $\rightarrow$ **Kotak Oranye** (`"Mengenali..."`).

### B. Mengapa OpenCV Melebarkan Kotak YOLO (*Margin Padding*) Sebelum *Crop*?

```text
(0,0) X ───────────────────────────► Lebar Frame (640)
  │
  │      (cx1, cy1)  [Kotak Crop + Padding OpenCV]
  │         + - - - - - - - - - - - - - - - - +  ▲
  │         |           pad_y (+35%)          |  │
  │         |     (x1,y1) [Kotak Ketat YOLO]  |  │
  │         |        +-----------------+      |  │ Tinggi
  │         |  pad_x |   WAJAH SISWA   |pad_x |  │ Potongan
  │         | (+25%) | (Alis s.d Dagu) |(+25%)|  │ (cy1:cy2)
  │         |        +-----------------+      |  │
  │         |                 (x2,y2)         |  │
  │         + - - - - - - - - - - - - - - - - +  ▼
  ▼         ◄────── Lebar Potongan (cx1:cx2) ─► (cx2, cy2)
Tinggi Frame (480)
```

1. **Masalah Kotak Ketat YOLO**: Kotak `[x1, y1, x2, y2]` dari YOLO sangat mepet ke alis dan dagu. Padahal, **InsightFace (ArcFace)** membutuhkan area dahi, rambut, telinga, dan rahang agar pelurusan wajah (*face alignment*) akurat.
2. **Solusi Padding (`pad_x` 25% & `pad_y` 35%)**: OpenCV memperlebar kotak tangkapan ke kiri-kanan sebesar 25% dan ke atas-bawah sebesar 35%, lalu membatasinya dengan `max(0, ...)` dan `min(lebar_frame, ...)` supaya tidak keluar dari batas layar kamera.
3. **Aturan Irisan Array (`frame[Baris_Y, Kolom_X]`) vs Gambar Kotak (`(X, Y)`)**:
   * Saat memotong gambar dengan `crop = frame[cy1:cy2, cx1:cx2]`, urutan indeks matriks NumPy/OpenCV wajib **`[Tinggi Y dulu, baru Lebar X]`**.
   * Sebaliknya, saat menggambar kotak `cv2.rectangle(frame, (x1, y1), (x2, y2))`, urutannya adalah koordinat kartesius **`(Lebar X dulu, baru Tinggi Y)`**.

---

## 4. Apa itu ArcFace? (Konsep Inti InsightFace)

### A. Mengapa Tidak Membandingkan Piksel Gambar Langsung?
Jika kita membandingkan gambar foto wajah secara langsung per piksel:
* Siswa tersenyum vs tidak tersenyum $\rightarrow$ susunan piksel berubah total.
* Lampu ruangan agak redup vs terang $\rightarrow$ nilai warna BGR piksel berubah drastis.
* Siswa menoleh 5 derajat $\rightarrow$ posisi mata bergeser puluhan piksel.
Akibatnya: **Pencocokan piksel pasti gagal.**

### B. Solusi: Mengubah Wajah Menjadi "Face Embedding" (512 Angka)
AI modern mengubah potongan wajah menjadi **Face Embedding** (vektor berisi 512 angka desimal float). Angka-angka ini mewakili proporsi biometrik wajah (jarak antar mata, lekuk hidung, struktur rahang) yang kebal terhadap perubahan ekspresi atau cahaya.

Contoh 512 angka embedding:
`[-0.0432, 0.0811, -0.0129, 0.1450, ..., 0.0094]` (total 512 angka dengan panjang vektor dinormalisasi menjadi `1.0`).

### C. Apa itu ArcFace (*Additive Angular Margin Loss*)?
**ArcFace** memetakan setiap vektor wajah ke atas **permukaan bola dimensi tinggi (*hypersphere*)** berjari-jari `1.0`:

```text
                 Wajah A (Budi - Foto 1)
                        ●
                       / \
                      /   \  Sudut θ kecil (< 25°) -> ORANG SAMA!
                     /  θ  \
                    /       ● Wajah B (Budi - Tersenyum)
          Pusat O (0,0)──────
                    \
                     \  Sudut θ lebar (> 70°) -> ORANG BERBEDA!
                      \
                       ● Wajah C (Orang Asing)
```

1. **Konsep Sudut ($\theta$) & Cosine Similarity**:
   Kemiripan dua wajah dihitung dari kosinus sudut $\theta$ di antara kedua vektornya:
   $$\text{Cosine Similarity} = \cos(\theta) = \frac{A \cdot B}{\|A\| \|B\|} = A \cdot B \quad (\text{karena } \|A\|=\|B\|=1)$$
2. **Additive Angular Margin ($+m$)**:
   * Huruf **"Arc"** singkatan dari **Arc-Cosine / Sudut ($\theta$)**.
   * Saat model dilatih, fungsi kerugian (*loss function*) memberi penalti margin sudut tambahan $+m$:
     $$L = -\log \frac{e^{s(\cos(\theta_{y_i} + m))}}{e^{s(\cos(\theta_{y_i} + m))} + \sum_{j \neq y_i} e^{s \cos \theta_j}}$$
   * Akibat penalti $+m$, foto orang yang sama dipaksa mengumpul rapat di sudut sempit, sedangkan foto orang berbeda didorong menjauh.

---

## 5. Bedah 6 Library AI/Vision Beserta Line Code Asli Proyek

### 1. Ultralytics YOLO (`models/yolo26n-face.pt`)

* **Peran**: *Face Localization* (mencari koordinat kotak `[x1, y1, x2, y2]` letak wajah di dalam frame video penuh).
* **Potongan Kode Asli Proyek**:
  * **File `test_face_recognition.py` (Baris 306–329)**:
    ```python
    # Menjalankan inferensi deteksi wajah YOLO pada frame webcam
    hasil = self.yolo.predict(
        source=frame,
        conf=YOLO_CONFIDENCE,   # 0.35 (abaikan deteksi di bawah keyakinan 35%)
        imgsz=YOLO_IMAGE_SIZE,  # 320 (resize frame ke 320x320 agar cepat di CPU)
        device="cpu",
        verbose=False
    )[0]

    # Ekstraksi koordinat kotak ke array bilangan bulat
    if hasil.boxes is not None:
        boxes = hasil.boxes.xyxy.cpu().numpy().astype(int)
        for box in boxes:
            detections.append(tuple(map(int, box)))
    ```
  * **File `app_web.py` (Baris 124–131)**:
    ```python
    # Validasi saat pendaftaran: wajib tepat 1 wajah
    results = detector.predict(source=image, conf=0.35, verbose=False)
    boxes = results[0].boxes
    if len(boxes) != 1:
        raise ValueError(f"Foto {index}: terdeteksi {len(boxes)} wajah. Wajib tepat 1 wajah.")
    ```
* **Link Dokumentasi & Gambar**:
  * [https://docs.ultralytics.com/tasks/detect/](https://docs.ultralytics.com/tasks/detect/)
  * ![YOLO Detection](https://raw.githubusercontent.com/ultralytics/assets/main/im/banner-tasks.png)

---

### 2. InsightFace (`buffalo_l` / ArcFace)

* **Peran**: *Biometric Face Recognition* (penentu siapa nama orang di dalam kotak wajah).
* **Mengapa InsightFace?**: Paket model `buffalo_l` menyediakan pipeline lengkap:
  1. *Landmark Detection*: Menemukan 5 titik kunci wajah (mata kiri, mata kanan, hidung, ujung bibir kiri, ujung bibir kanan).
  2. *Face Alignment*: Memutar dan meluruskan potongan wajah secara geometris.
  3. *ArcFace Embedding*: Menghasilkan vektor 512 angka floating point yang dinormalisasi L2.
* **Potongan Kode Asli Proyek**:
  * **Inisialisasi Model (`test_face_recognition.py:439–447`)**:
    ```python
    face_app = FaceAnalysis(
        name="buffalo_l",                    # Arsitektur ResNet-50 ArcFace
        providers=["CPUExecutionProvider"]   # Dijalankan via ONNX Runtime di CPU
    )
    face_app.prepare(ctx_id=-1, det_size=(320, 320))
    ```
  * **Ekstraksi Fitur dari Crop Wajah Kamera (`test_face_recognition.py:409–426`)**:
    ```python
    # Ekstraksi fitur wajah
    wajah_crop = self.face_app.get(crop)
    if wajah_crop:
        wajah = max(wajah_crop, key=lambda f: ((f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])))
        # wajah.normed_embedding berisi 512 angka
        npm, nama, skor = kenali_siswa(wajah.normed_embedding, self.database)
    ```
  * **Ekstraksi Saat Membaca Foto Database (`test_face_recognition.py:102–115`)**:
    ```python
    wajah = face_app.get(gambar)
    if len(wajah) == 1:
        embeddings.append(wajah[0].normed_embedding)
    ```
* **Link Dokumentasi & Gambar**:
  * [https://insightface.ai](https://insightface.ai) · [https://github.com/deepinsight/insightface](https://github.com/deepinsight/insightface)
  * ![InsightFace Video Demo](https://raw.githubusercontent.com/nttstar/insightface-resources/refs/heads/master/images/facerecognitionfromvideo.PNG)

---

### 3. OpenCV (`cv2`)

* **Peran**: Membaca feed webcam (`cv2.VideoCapture`), memotong matriks piksel (*crop* + padding), melukis kotak (`cv2.rectangle`), dan menulis teks nama siswa (`cv2.putText`).
* **Potongan Kode Asli Proyek**:
  * **Membuka Feed Webcam Laptop (`test_face_recognition.py:464–470`)**:
    ```python
    kamera = cv2.VideoCapture(0)
    kamera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    kamera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    kamera.set(cv2.CAP_PROP_FPS, 30)
    kamera.set(cv2.CAP_PROP_BUFFERSIZE, 1) # Supaya tidak ada delay/lag frame video
    ```
  * **Pemotongan Wajah dengan Margin Padding (`test_face_recognition.py:388–405`)**:
    ```python
    x1, y1, x2, y2 = bbox
    pad_x = int((x2 - x1) * 0.25) # Margin samping 25%
    pad_y = int((y2 - y1) * 0.35) # Margin atas/bawah 35% (rambut & dagu)

    cx1 = max(0, x1 - pad_x)
    cy1 = max(0, y1 - pad_y)
    cx2 = min(lebar_frame, x2 + pad_x)
    cy2 = min(tinggi_frame, y2 + pad_y)

    # Pemotongan gambar array slicing NumPy
    crop = frame[cy1:cy2, cx1:cx2]
    ```
  * **Menggambar Kotak & Label Nama ke Layar (`test_face_recognition.py:621–637`)**:
    ```python
    # Gambar kotak persegi
    cv2.rectangle(frame, (x1, y1), (x2, y2), track["color"], 2)

    # Tulis teks nama siswa di atas kotak
    cv2.putText(
        frame,
        track["label"],
        (x1, max(25, y1 - 10)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        track["color"],
        2
    )
    ```
* **Link Dokumentasi & Gambar**:
  * [https://docs.opencv.org](https://docs.opencv.org)
  * ![OpenCV Logo](https://raw.githubusercontent.com/opencv/opencv/master/doc/opencv-logo.png)

---

### 4. NumPy (`numpy` / `np`)

* **Peran**: Operasi aljabar linear dan kalkulasi numerik berkecepatan tinggi pada matriks citra dan vektor 512 fitur wajah.
* **Mengapa NumPy?**: Loop Python murni (`for item in list`) sangat lambat. NumPy ditulis dalam bahasa C terkompilasi dengan instruksi SIMD (*Single Instruction, Multiple Data*), sehingga operasi perkalian 512 angka selesai dalam beberapa mikrodetik.
* **Potongan Kode Asli Proyek**:
  * **Normalisasi Vektor L2 (`test_face_recognition.py:52–58`)**:
    ```python
    def normalisasi(vector):
        panjang = np.linalg.norm(vector) # ||v|| = sqrt(v1^2 + v2^2 + ... + v512^2)
        if panjang == 0:
            return vector
        return vector / panjang
    ```
  * **Menghitung Vektor Representatif Siswa (`test_face_recognition.py:122–127`)**:
    ```python
    # Menghitung titik tengah rata-rata dari 3 foto siswa
    rata_rata = np.mean(np.asarray(embeddings), axis=0)
    database[npm] = {
        "nama": nama,
        "embedding": normalisasi(rata_rata)
    }
    ```
  * **Pencocokan Kemiripan (Cosine Similarity via Dot Product) (`test_face_recognition.py:159–165`)**:
    ```python
    # Perkalian titik dua vektor ternormalisasi: A . B
    skor = float(np.dot(embedding, data["embedding"]))
    if skor > skor_terbaik:
        skor_terbaik = skor
        npm_terbaik = npm
    ```
* **Link Dokumentasi & Gambar**:
  * [https://numpy.org](https://numpy.org)
  * ![NumPy Logo](https://raw.githubusercontent.com/numpy/numpy/main/branding/icons/numpy.svg)

---

### 5. ONNX Runtime (`onnxruntime`)

* **Peran**: Mesin inferensi berkecepatan tinggi khusus untuk mengeksekusi model neural network berformat terbuka `.onnx` milik InsightFace.
* **Mengapa ONNX Runtime?**: 
  * Model ArcFace InsightFace tidak disimpan dalam `.pt` PyTorch, melainkan `.onnx` (`w600k_r50.onnx`).
  * ONNX Runtime dirancang oleh Microsoft dengan optimasi multi-threading tingkat rendah untuk prosesor Intel/AMD x86_64 dan ARM.
  * Memungkinkan laptop menjalankan pengenalan wajah multi-layer tanpa memerlukan kartu grafis (GPU) diskret.
* **Potongan Kode Asli Proyek**:
  * **Pemanggilan Provider CPU (`test_face_recognition.py:439–442`)**:
    ```python
    face_app = FaceAnalysis(
        name="buffalo_l",
        providers=["CPUExecutionProvider"] # Menugaskan ONNX Runtime berjalan di CPU
    )
    ```
* **Link Dokumentasi & Gambar**:
  * [https://onnxruntime.ai](https://onnxruntime.ai)
  * ![ONNX Runtime Diagram](https://raw.githubusercontent.com/microsoft/onnxruntime/main/docs/images/ONNX_Runtime_logo_dark.png)

---

### 6. PyTorch (`torch`)

* **Peran**: Framework dasar komputasi tensor dan deep learning yang menjadi mesin eksekutor di balik model Ultralytics YOLO (`yolo26n-face.pt`).
* **Mengapa PyTorch?**:
  * File berakhiran `.pt` adalah format checkpoint bobot jaringan saraf asli milik PyTorch (*PyTorch Tensor Checkpoint*).
  * PyTorch menangani operasi konvolusi multi-layer (CNN), aktivasi SiLU/ReLU, dan kalkulasi batas bounding box.
* **Potongan Kode Asli Proyek**:
  * **Memuat Bobot PyTorch `.pt` (`test_face_recognition.py:19, 436`)**:
    ```python
    MODEL_PATH = BASE_DIR / "models" / "yolo26n-face.pt"
    yolo = YOLO(str(MODEL_PATH)) # PyTorch meload graph model dan tensor bobot
    ```
  * **Mentransfer Hasil Tensor dari Jaringan ke CPU NumPy (`test_face_recognition.py:295–298`)**:
    ```python
    # hasil.boxes.xyxy adalah PyTorch Tensor (torch.Tensor)
    # .cpu() memindahkannya ke memori RAM utama
    # .numpy() mengonversinya menjadi array NumPy standar
    boxes = (
        hasil.boxes.xyxy
        .cpu()
        .numpy()
        .astype(int)
    )
    ```
* **Link Dokumentasi & Gambar**:
  * [https://pytorch.org](https://pytorch.org)
  * ![PyTorch Logo](https://raw.githubusercontent.com/pytorch/pytorch/main/docs/source/_static/img/pytorch-logo-dark.svg)
