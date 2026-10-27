AIoT SMART ATTENDANCE - DASHBOARD STARTER

Isi paket:
- app_web.py: Flask backend + API + SQLite
- templates/index.html: dashboard admin
- static/style.css: tampilan responsif
- static/app.js: refresh data dan pencarian

CARA MEMASANG KE PROYEK YANG SUDAH ADA
1. Salin app_web.py, folder templates, dan folder static ke folder utama AIoT_Smart_Attendance.
2. Pastikan folder database_wajah tetap berada di folder utama seperti sebelumnya.
3. Aktifkan .venv di terminal VS Code.
4. Instal Flask:
   python -m pip install flask
5. Jalankan dashboard:
   python app_web.py
6. Buka browser:
   http://127.0.0.1:5000

UJI API DARI TERMINAL LAIN (opsional):
   python -c "import requests; r=requests.post('http://127.0.0.1:5000/api/attendance',json={'npm':'27126014','nama':'Bartolomeus Yoel Heriyanto','source':'Face Recognition'}); print(r.status_code,r.text)"

CATATAN
- Database attendance.db dibuat otomatis saat app_web.py dijalankan.
- Endpoint absensi: POST http://127.0.0.1:5000/api/attendance
- Payload JSON: {"npm":"27126014","nama":"Bartolomeus Yoel Heriyanto","source":"Face Recognition"}
- Satu NPM hanya dicatat sekali per tanggal kalender pada versi awal ini.
- Dashboard hanya listen pada 127.0.0.1 (laptop yang sama). Jangan expose aplikasi ini ke jaringan publik tanpa autentikasi dan pengamanan.
- ESP32 web server yang ada tetap untuk komunikasi/indikator perangkat. Flask + SQLite menjadi tempat pencatatan dashboard sementara.
