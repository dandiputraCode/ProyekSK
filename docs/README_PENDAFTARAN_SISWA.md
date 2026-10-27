# Fitur Pendaftaran Siswa melalui Kamera — AIoT Smart Attendance

Paket ini adalah patch untuk proyek lokal yang telah memiliki `app_web.py`, `templates/index.html`, `static/style.css`, folder `models/yolo26n-face.pt`, dan folder `database_wajah`.

## Fitur
- Menu **Pendaftaran Siswa** di dashboard.
- Form NPM dan nama lengkap.
- Mengambil tepat 3 foto dari kamera browser.
- Validasi pada backend menggunakan model `models/yolo26n-face.pt`; setiap foto harus memiliki tepat satu wajah yang terdeteksi.
- Foto disimpan otomatis sebagai `database_wajah/NPM_Nama_Siswa/foto1.jpg` sampai `foto3.jpg`.
- Dashboard memuat daftar siswa terdaftar dari folder database wajah.
- Dashboard polling diperpendek menjadi setiap 1 detik.

## Memasang patch dengan aman
1. Hentikan Flask lokal dengan `Ctrl+C`.
2. Buat cadangan folder proyek. Terutama jangan sampai kehilangan `attendance.db`, `database_wajah`, `models`, `.venv`, atau kode pengenalan wajah.
3. Ekstrak isi ZIP ke folder utama `AIoT_Smart_Attendance` dan izinkan file web dengan nama yang sama ditimpa:
   - `app_web.py`
   - `templates/index.html`
   - `static/style.css`
   - `static/app.js`
   File baru: `templates/enroll.html`, `static/registration.css`, `static/enroll.js`.
4. Pastikan model ada di `models/yolo26n-face.pt` dan library tersedia di virtual environment:
   ```powershell
   python -m pip install flask opencv-python numpy ultralytics
   ```
5. Jalankan `python app_web.py` lalu buka `http://127.0.0.1:5000`.
6. Klik **Pendaftaran Siswa** atau buka `http://127.0.0.1:5000/students/register`.

## Alur pendaftaran
1. Isi NPM dan nama siswa.
2. Centang pernyataan bahwa izin/persetujuan yang diperlukan telah diperoleh.
3. Sebelum memakai kamera browser, tutup jendela `test_face_recognition.py` dengan menekan `Q`. Browser dan OpenCV terkadang tidak dapat memakai kamera yang sama secara bersamaan.
4. Klik **Aktifkan Kamera**, kemudian ambil tepat tiga foto. Usahakan satu foto menghadap ke depan dan dua foto dengan sedikit variasi sudut.
5. Klik **Simpan Siswa**. Backend akan memvalidasi setiap foto menggunakan YOLO. Apabila tidak ada wajah atau ada lebih dari satu wajah, foto ditolak dan pesan akan ditampilkan.
6. Setelah sukses, program pengenalan wajah memuat database saat proses mulai. Jalankan lagi `python test_face_recognition.py` agar siswa baru dapat dikenali.

## Catatan penting
- Jangan hapus `attendance.db` ketika memasang patch; file itu berisi riwayat absensi lokal.
- Jangan memasukkan NPM yang sudah terdaftar. Versi ini menolak duplikasi NPM, tidak mengganti foto lama.
- Fitur ini dibuat untuk prototipe lokal dan validasi YOLO dasar. Deteksi satu wajah bukan bukti identitas atau bukti anti-spoofing.
- Jangan publikasikan endpoint pendaftaran ke internet sebelum menambahkan autentikasi admin, otorisasi, HTTPS, pembatasan akses dan penyimpanan biometrik yang aman. Server Flask pada patch ini tetap bind ke `127.0.0.1` untuk akses lokal.
- Foto wajah adalah data sensitif. Daftarkan hanya orang yang telah memberikan persetujuan yang diperlukan, batasi akses folder `database_wajah`, dan jangan mengunggah folder ini ke repositori publik.
