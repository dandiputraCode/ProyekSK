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

#include <Adafruit_Fingerprint.h>

#define FW_VERSION "1.0"

#define RX_PIN      16   // ESP32 RX2 <- TX sensor (kuning)
#define TX_PIN      17   // ESP32 TX2 -> RX sensor (hijau)
#define WAKEUP_PIN   4   // opsional (kabel biru)

HardwareSerial fpSerial(2);
Adafruit_Fingerprint finger(&fpSerial);

// ---------- LED helper (ring RGB R503) ----------
void ledBiru()   { finger.LEDcontrol(FINGERPRINT_LED_BREATHING, 100, FINGERPRINT_LED_BLUE); }
void ledHijau()  { finger.LEDcontrol(FINGERPRINT_LED_ON, 0, FINGERPRINT_LED_PURPLE); }
void ledMerah()  { finger.LEDcontrol(FINGERPRINT_LED_FLASHING, 25, FINGERPRINT_LED_RED, 3); }
void ledMati()   { finger.LEDcontrol(FINGERPRINT_LED_OFF, 0, FINGERPRINT_LED_BLUE); }

// ---------- Utilitas ----------
void kirim(const String &baris) {
  Serial.println(baris);
  Serial.flush();
}

void kirimKode(const char *perintah, uint8_t id, uint8_t kode) {
  char buffer[48];
  snprintf(buffer, sizeof(buffer), "%s %u %u", perintah, id, kode);
  kirim(buffer);
}

// Tunggu jari ditempel (dengan batas waktu agar tidak menggantung selamanya)
uint8_t tungguJari(uint32_t timeout_ms = 15000) {
  uint32_t mulai = millis();
  while (millis() - mulai < timeout_ms) {
    uint8_t p = finger.getImage();
    if (p == FINGERPRINT_OK) return FINGERPRINT_OK;
    if (p == FINGERPRINT_NOFINGER) { delay(50); continue; }
    return p; // error komunikasi / gambar kotor
  }
  return FINGERPRINT_TIMEOUT;
}

// Tunggu jari diangkat agar satu tempelan tidak memicu MATCH berkali-kali
void tungguJariAngkat(uint32_t timeout_ms = 4000) {
  uint32_t mulai = millis();
  while (millis() - mulai < timeout_ms) {
    if (finger.getImage() == FINGERPRINT_NOFINGER) return;
    delay(50);
  }
}

// ---------- Enroll ----------
void enrollFinger(uint8_t id) {
  kirim(String("PLACE ") + id);
  ledBiru();

  uint8_t p = tungguJari();
  if (p != FINGERPRINT_OK) { kirimKode("ENROLL_FAIL", id, p); ledMerah(); return; }

  p = finger.image2Tz(1);
  if (p != FINGERPRINT_OK) { kirimKode("ENROLL_FAIL", id, p); ledMerah(); return; }

  kirim("REMOVE");
  tungguJariAngkat();

  kirim(String("PLACE ") + id);
  p = tungguJari();
  if (p != FINGERPRINT_OK) { kirimKode("ENROLL_FAIL", id, p); ledMerah(); return; }

  p = finger.image2Tz(2);
  if (p != FINGERPRINT_OK) { kirimKode("ENROLL_FAIL", id, p); ledMerah(); return; }

  p = finger.createModel();
  if (p != FINGERPRINT_OK) { kirimKode("ENROLL_FAIL", id, p); ledMerah(); return; }

  p = finger.storeModel(id);
  if (p != FINGERPRINT_OK) { kirimKode("ENROLL_FAIL", id, p); ledMerah(); return; }

  kirimKode("ENROLL_OK", id, 0);
  ledHijau();
  delay(600);
  ledMati();
}

// ---------- Verifikasi (2 faktor, dipanggil dari Flask) ----------
void verifikasi() {
  uint8_t p = finger.getImage();
  if (p != FINGERPRINT_OK) return;

  p = finger.image2Tz();
  if (p != FINGERPRINT_OK) return;

  p = finger.fingerSearch();
  if (p == FINGERPRINT_OK) {
    char buffer[48];
    snprintf(buffer, sizeof(buffer), "MATCH %u %u", finger.fingerID, finger.confidence);
    kirim(buffer);
    ledHijau();
    delay(400);
    ledMati();
  } else {
    kirim("NOMATCH");
    ledMerah();
    delay(300);
    ledMati();
  }

  tungguJariAngkat();
  delay(300); // debounce tambahan
}

// ---------- Perintah Serial ----------
void prosesPerintah(String baris) {
  baris.trim();
  if (baris.length() == 0) return;

  if (baris == "PING" || baris == "m") {
    finger.getTemplateCount();
    kirim(String("PONG ") + finger.templateCount);
    return;
  }

  if (baris == "LED_OK") {
    ledHijau();
    delay(700);
    ledMati();
    kirim("LED_DONE");
    return;
  }

  if (baris == "CLEAR" || baris == "c") {
    uint8_t p = finger.emptyDatabase();
    kirim(p == FINGERPRINT_OK ? String("CLEAR_OK 0") : String("CLEAR_FAIL ") + p);
    return;
  }

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

  int spasi = baris.indexOf(' ');
  String perintah = (spasi < 0) ? baris : baris.substring(0, spasi);
  int id = (spasi < 0) ? -1 : baris.substring(spasi + 1).toInt();

  if (perintah == "ENROLL") {
    if (id < 1 || id > 200) { kirim("ENROLL_FAIL 0 255"); return; }
    kirim(String("ENROLLING ") + id);
    enrollFinger((uint8_t)id);
    return;
  }

  if (perintah == "DELETE" || perintah == "d") {
    if (id < 1 || id > 200) { kirim("DELETE_FAIL 0 255"); return; }
    uint8_t p = finger.deleteModel((uint8_t)id);
    if (p == FINGERPRINT_OK) kirimKode("DELETE_OK", id, 0);
    else kirimKode("DELETE_FAIL", id, p);
    return;
  }

  kirim(String("ERR_UNKNOWN ") + perintah);
}

void setup() {
  Serial.begin(115200);
  pinMode(WAKEUP_PIN, INPUT);
  fpSerial.begin(57600, SERIAL_8N1, RX_PIN, TX_PIN);

  delay(300);
  kirim(String("BOOT ") + FW_VERSION);

  finger.begin(57600);
  delay(100);

  if (!finger.verifyPassword()) {
    kirim("SENSOR_FAIL 0");
    return; // jangan hang: laptop tetap bisa membaca status
  }

  finger.getTemplateCount();
  kirim(String("READY ") + finger.templateCount);
  ledBiru();
}

void loop() {
  if (Serial.available()) {
    String baris = Serial.readStringUntil('\n');
    prosesPerintah(baris);
    return; // hormati hasil perintah sebelum polling sensor
  }

  // Poll langsung ke R503 (tetap jalan walaupun kabel biru WAKEUP_PIN tidak dipasang)
  verifikasi();

  delay(50);
}
