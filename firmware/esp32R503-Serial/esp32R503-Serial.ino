// ==================================================
// ESP32 + R503 Fingerprint - Jembatan USB Serial
// ==================================================
// Protokol baris (Line-based, 115200 baud) lewat kabel USB.
// Serial Monitor Arduino IDE tetap bisa dipakai manual (perintah: e, d, c, m).
//
// Perintah dari laptop (Flask / Python):
//   PING             -> "PONG <jumlah_template>"
//   ENROLL <id>      -> "ENROLLING <id>" ... "ENROLL_OK <id>" / "ENROLL_FAIL <id> <kode>"
//   DELETE <id>      -> "DELETE_OK <id>" / "DELETE_FAIL <id> <kode>"
//   CLEAR            -> "CLEAR_OK 0" / "CLEAR_FAIL <kode>"
//   LED_OK           -> "LED_DONE" (kedip hijau, dipakai saat absensi terverifikasi)
//
// Event dari ESP32 ke laptop:
//   BOOT <versi>              -> saat ESP32 menyala
//   READY <jumlah_template>   -> sensor siap dipakai
//   SENSOR_FAIL 0             -> sensor tidak terdeteksi (cek wiring 3.3V / TX-RX)
//   MATCH <id> <confidence>   -> sidik jari cocok
//   NOMATCH                   -> sidik jari tidak dikenali
//   PLACE <id> / REMOVE       -> instruksi saat proses enroll
// ==================================================

#include <Adafruit_Fingerprint.h>  // Library protokol paket biner UART sensor sidik jari (R503 / AS608)

#define FW_VERSION "1.0"           // Versi firmware yang dikirim saat ESP32 pertama kali menyala (BOOT)

// Konfigurasi pin UART2 pada ESP32 untuk berbicara dengan sensor R503
#define RX_PIN      16             // Pin GPIO16 (RX2 ESP32) menerima data dari kabel Kuning (TX R503)
#define TX_PIN      17             // Pin GPIO17 (TX2 ESP32) mengirim data ke kabel Hijau (RX R503)
#define WAKEUP_PIN   4             // Pin GPIO4 untuk sinyal sentuh/wakeup dari kabel Biru R503 (opsional)

// Membuka jalur komunikasi serial perangkat keras ke-2 (UART2) milik ESP32
HardwareSerial fpSerial(2);

// Membuat objek pengontrol sensor R503 yang terhubung di atas jalur UART2 (fpSerial)
Adafruit_Fingerprint finger(&fpSerial);

// ---------- LED helper (ring RGB R503) ----------
// Mengatur cincin lampu LED pada sensor R503:
// Parameter LEDcontrol(mode, kecepatan, warna, jumlah_kedip)
void ledBiru()   { finger.LEDcontrol(FINGERPRINT_LED_BREATHING, 100, FINGERPRINT_LED_BLUE); }   // Biru bernapas: siaga / menunggu jari
void ledHijau()  { finger.LEDcontrol(FINGERPRINT_LED_ON, 0, FINGERPRINT_LED_PURPLE); }          // Nyala penuh: berhasil / cocok
void ledMerah()  { finger.LEDcontrol(FINGERPRINT_LED_FLASHING, 25, FINGERPRINT_LED_RED, 3); }   // Kedip merah 3x: gagal / ditolak
void ledMati()   { finger.LEDcontrol(FINGERPRINT_LED_OFF, 0, FINGERPRINT_LED_BLUE); }           // Mematikan cincin LED

// ---------- Utilitas Komunikasi USB Serial ke Laptop ----------
// Mengirim satu baris teks ke laptop (Python esp32_serial.py) dan memastikan buffer USB terkirim tuntas
void kirim(const String &baris) {
  Serial.println(baris);  // Kirim teks diakhiri newline ('\n') ke port USB (COM5)
  Serial.flush();         // Tunggu hingga seluruh byte benar-benar keluar dari buffer UART0
}

// Memformat pesan berformat "<PERINTAH> <id> <kode>" lalu mengirimkannya ke laptop
void kirimKode(const char *perintah, uint8_t id, uint8_t kode) {
  char buffer[48];
  snprintf(buffer, sizeof(buffer), "%s %u %u", perintah, id, kode);
  kirim(buffer);
}

// ---------- Pembacaan Fisik Jari ----------
// Menunggu sampai permukaan kapasitif R503 menangkap gambar sidik jari (batas waktu default 15 detik)
uint8_t tungguJari(uint32_t timeout_ms = 15000) {
  uint32_t mulai = millis();                          // Catat waktu mulai (ms sejak ESP32 hidup)
  while (millis() - mulai < timeout_ms) {
    uint8_t p = finger.getImage();                    // Minta R503 memindai permukaan sensor kapasitif
    if (p == FINGERPRINT_OK) return FINGERPRINT_OK;   // Jari terdeteksi dan citra berhasil diambil
    if (p == FINGERPRINT_NOFINGER) { delay(50); continue; } // Belum ada jari: jeda 50 ms lalu cek lagi
    return p;                                         // Kembalikan kode error jika paket rusak / gambar buram
  }
  return FINGERPRINT_TIMEOUT;                         // Waktu habis (15 detik lewat tanpa jari ditempel)
}

// Menunggu sampai jari diangkat dari sensor agar 1 tempelan tidak terbaca berulang kali
void tungguJariAngkat(uint32_t timeout_ms = 4000) {
  uint32_t mulai = millis();
  while (millis() - mulai < timeout_ms) {
    if (finger.getImage() == FINGERPRINT_NOFINGER) return; // Berhenti menunggu begitu permukaan sensor kosong
    delay(50);
  }
}

// ---------- Enroll (Pendaftaran Sidik Jari Baru ke Memori Flash R503) ----------
// Alur standar R503 membutuhkan 2 kali tempel jari:
//   Tempel 1 -> diekstrak ke CharBuffer 1
//   Tempel 2 -> diekstrak ke CharBuffer 2
//   createModel() menggabungkan CharBuffer 1 & 2 menjadi 1 template utuh
//   storeModel(id) menyimpan template ke memori Flash internal R503 pada slot #id (1..200)
void enrollFinger(uint8_t id) {
  kirim(String("PLACE ") + id);                       // Beri tahu laptop: minta siswa tempelkan jari ke-1
  ledBiru();                                          // Nyalakan ring biru sebagai tanda siap rekam

  // Tahap 1: Ambil citra jari pertama dan ubah menjadi fitur minutiae di CharBuffer 1
  uint8_t p = tungguJari();
  if (p != FINGERPRINT_OK) { kirimKode("ENROLL_FAIL", id, p); ledMerah(); return; }

  p = finger.image2Tz(1);                             // Konversi gambar mentah ke titik fitur di slot RAM 1 (CharBuffer1)
  if (p != FINGERPRINT_OK) { kirimKode("ENROLL_FAIL", id, p); ledMerah(); return; }

  // Minta jari diangkat dulu supaya pengambilan kedua benar-benar posisi sampel baru
  kirim("REMOVE");
  tungguJariAngkat();

  // Tahap 2: Ambil citra jari kedua dan ubah menjadi fitur minutiae di CharBuffer 2
  kirim(String("PLACE ") + id);                       // Minta siswa menempelkan jari yang sama untuk ke-2 kalinya
  p = tungguJari();
  if (p != FINGERPRINT_OK) { kirimKode("ENROLL_FAIL", id, p); ledMerah(); return; }

  p = finger.image2Tz(2);                             // Konversi gambar kedua ke titik fitur di slot RAM 2 (CharBuffer2)
  if (p != FINGERPRINT_OK) { kirimKode("ENROLL_FAIL", id, p); ledMerah(); return; }

  // Tahap 3: Bandingkan CharBuffer1 & CharBuffer2; jika berasal dari jari yang sama, gabungkan jadi template
  p = finger.createModel();
  if (p != FINGERPRINT_OK) { kirimKode("ENROLL_FAIL", id, p); ledMerah(); return; }

  // Tahap 4: Simpan template permanen ke memori Flash internal R503 pada nomor slot 'id' (1-200)
  p = finger.storeModel(id);
  if (p != FINGERPRINT_OK) { kirimKode("ENROLL_FAIL", id, p); ledMerah(); return; }

  // Berhasil: kirim sinyal sukses ke Flask dan nyalakan lampu indikator
  kirimKode("ENROLL_OK", id, 0);
  ledHijau();
  delay(600);
  ledMati();
}

// ---------- Verifikasi 1:N (Pencocokan Jari Saat Absensi 2 Faktor) ----------
// Dipanggil terus-menerus di loop(). Saat ada jari menempel, sensor mencari kecocokan di seluruh slot Flash.
void verifikasi() {
  uint8_t p = finger.getImage();                      // Cek apakah ada jari di atas sensor
  if (p != FINGERPRINT_OK) return;                    // Kalau tidak ada jari, langsung keluar (non-blocking)

  p = finger.image2Tz();                              // Ekstrak titik minutiae jari ke CharBuffer1
  if (p != FINGERPRINT_OK) return;                    // Gambar kurang jelas: abaikan dan tunggu pembacaan berikutnya

  // Bandingkan CharBuffer1 terhadap seluruh template yang tersimpan di Flash R503 (pencarian 1:N di chip DSP sensor)
  p = finger.fingerSearch();
  if (p == FINGERPRINT_OK) {
    // Jari cocok dengan salah satu slot: kirim "MATCH <fingerID> <confidence>" ke Flask (esp32_serial.py)
    char buffer[48];
    snprintf(buffer, sizeof(buffer), "MATCH %u %u", finger.fingerID, finger.confidence);
    kirim(buffer);
    ledHijau();
    delay(400);
    ledMati();
  } else {
    // Jari tidak ada di database sensor: kirim "NOMATCH" agar Flask langsung menolak tanpa menunggu 30 detik
    kirim("NOMATCH");
    ledMerah();
    delay(300);
    ledMati();
  }

  tungguJariAngkat();                                 // Wajib angkat jari dulu sebelum bisa memindai lagi
  delay(300);                                         // Debounce tambahan agar tidak memicu bacaan ganda
}

// ---------- Parser Perintah Serial dari Laptop (Flask / Serial Monitor) ----------
void prosesPerintah(String baris) {
  baris.trim();                                       // Buang spasi/newline (\r\n) di awal & akhir baris
  if (baris.length() == 0) return;

  // 1. PING / 'm': Cek koneksi dan hitung berapa template sidik jari yang tersimpan di R503
  if (baris == "PING" || baris == "m") {
    finger.getTemplateCount();
    kirim(String("PONG ") + finger.templateCount);
    return;
  }

  // 2. LED_OK: Perintah dari Flask setelah absensi 2 faktor tercatat di SQLite
  if (baris == "LED_OK") {
    ledHijau();
    delay(700);
    ledMati();
    kirim("LED_DONE");
    return;
  }

  // 3. CLEAR / 'c': Hapus seluruh template sidik jari di memori Flash R503
  if (baris == "CLEAR" || baris == "c") {
    uint8_t p = finger.emptyDatabase();
    kirim(p == FINGERPRINT_OK ? String("CLEAR_OK 0") : String("CLEAR_FAIL ") + p);
    return;
  }

  // 4. 'e': Mode interaktif khusus saat menguji manual dari Serial Monitor Arduino IDE
  if (baris == "e") {
    Serial.println("Masukkan ID (1-200):");
    while (!Serial.available()) delay(10);
    int id = Serial.parseInt();
    while (Serial.available()) Serial.read();
    if (id >= 1 && id <= 200) {
      kirim(String("ENROLLING ") + id);
      enrollFinger((uint8_t)id);
    }
    return;
  }

  // Pisahkan kata perintah dan argumen angka ID (contoh: "ENROLL 3" -> perintah="ENROLL", id=3)
  int spasi = baris.indexOf(' ');
  String perintah = (spasi < 0) ? baris : baris.substring(0, spasi);
  int id = (spasi < 0) ? -1 : baris.substring(spasi + 1).toInt();

  // 5. ENROLL <id>: Dipanggil otomatis oleh Flask saat pendaftaran siswa / rekam sidik jari
  if (perintah == "ENROLL") {
    if (id < 1 || id > 200) { kirim("ENROLL_FAIL 0 255"); return; }
    kirim(String("ENROLLING ") + id);
    enrollFinger((uint8_t)id);
    return;
  }

  // 6. DELETE <id> / 'd <id>': Hapus 1 slot template sidik jari tertentu
  if (perintah == "DELETE" || perintah == "d") {
    if (id < 1 || id > 200) { kirim("DELETE_FAIL 0 255"); return; }
    uint8_t p = finger.deleteModel((uint8_t)id);
    if (p == FINGERPRINT_OK) kirimKode("DELETE_OK", id, 0);
    else kirimKode("DELETE_FAIL", id, p);
    return;
  }

  // Perintah tidak dikenali
  kirim(String("ERR_UNKNOWN ") + perintah);
}

// ---------- Inisialisasi Awal (Dijalankan 1x Saat ESP32 Menyala / Reset) ----------
void setup() {
  Serial.begin(115200);                               // Buka komunikasi USB ke laptop dengan kecepatan 115200 bps
  pinMode(WAKEUP_PIN, INPUT);                         // Set pin wakeup sebagai input
  fpSerial.begin(57600, SERIAL_8N1, RX_PIN, TX_PIN);  // Buka UART2 ke sensor R503 (baudrate bawaan R503 = 57600 bps)

  delay(300);                                         // Tunggu tegangan sensor stabil setelah power-on
  kirim(String("BOOT ") + FW_VERSION);                // Kabari laptop bahwa ESP32 baru saja booting

  finger.begin(57600);                                // Inisialisasi library Adafruit_Fingerprint
  delay(100);

  // Pastikan sensor R503 merespons handshake password UART
  if (!finger.verifyPassword()) {
    kirim("SENSOR_FAIL 0");                           // Jika kabel lepas / salah pin TX-RX, laporkan ke laptop
    return;                                           // Jangan mengunci ESP32 di while(1) agar tetap bisa didiagnosis
  }

  // Sensor siap: baca jumlah template tersimpan dan nyalakan ring biru
  finger.getTemplateCount();
  kirim(String("READY ") + finger.templateCount);
  ledBiru();
}

// ---------- Loop Utama (Berputar Terus-menerus Selama ESP32 Hidup) ----------
void loop() {
  // Prioritas 1: Jika ada perintah masuk dari laptop (PING, ENROLL, DELETE, CLEAR, LED_OK), jalankan dulu
  if (Serial.available()) {
    String baris = Serial.readStringUntil('\n');
    prosesPerintah(baris);
    return; // Kembali ke awal loop setelah menyelesaikan perintah
  }

  // Prioritas 2: Jika tidak ada perintah, periksa apakah ada jari menempel untuk verifikasi absensi
  verifikasi();

  delay(50); // Jeda 50 ms (~20 pengecekan per detik) agar trafik UART tidak jenuh
}
