
#include <WiFi.h>
#include <WebServer.h>

// =====================================
// 1. KONFIGURASI WIFI
// =====================================

const char* ssid = "aing maunk";
const char* password = "negaraKORUPSI";

WebServer server(80);

// Data simulasi sementara
String lastEvent = "BELUM ADA AKTIVITAS";
String lastNpm = "-";
String lastNama = "-";
unsigned long eventCount = 0;


// =====================================
// 2. HALAMAN UTAMA
// =====================================

void handleRoot() {
  String html = R"rawliteral(
  <!DOCTYPE html>
  <html lang="id">
  <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>AIoT Smart Attendance</title>
    <style>
      body {
        font-family: Arial, sans-serif;
        background: #f1f5f9;
        margin: 0;
        padding: 24px;
        color: #172554;
      }
      .card {
        max-width: 600px;
        margin: auto;
        background: white;
        padding: 24px;
        border-radius: 14px;
      }
      a {
        display: block;
        padding: 14px;
        margin: 12px 0;
        background: #dbeafe;
        border-radius: 8px;
        color: #1d4ed8;
        text-decoration: none;
      }
    </style>
  </head>
  <body>
    <div class="card">
      <h1>AIoT Smart Attendance</h1>
      <p>ESP32 berhasil menjalankan web server lokal.</p>
      <h3>Simulasi peristiwa</h3>

      <a href="/test?event=FACE_OK&npm=27126014">
        Simulasi wajah dikenali
      </a>

      <a href="/test?event=UNKNOWN&npm=-">
        Simulasi wajah tidak dikenal
      </a>

      <a href="/test?event=STUDENT_PRESENT&npm=27126014">
        Simulasi siswa terdeteksi hadir
      </a>

      <a href="/status">Lihat status perangkat</a>
    </div>
  </body>
  </html>
  )rawliteral";

  server.send(200, "text/html", html);
}


// =====================================
// 3. MENERIMA SIMULASI ABSENSI
// =====================================


void handleTest() {
  if (!server.hasArg("event") ||
      !server.hasArg("npm") ||
      !server.hasArg("nama")) {

    server.send(
      400,
      "text/plain",
      "Parameter event, npm, dan nama wajib diisi"
    );

    return;
  }

  lastEvent = server.arg("event");
  lastNpm = server.arg("npm");
  lastNama = server.arg("nama");

  eventCount++;

  Serial.println();
  Serial.println("===== ABSENSI SISWA =====");

  Serial.print("Event : ");
  Serial.println(lastEvent);

  Serial.print("Nama  : ");
  Serial.println(lastNama);

  Serial.print("NPM   : ");
  Serial.println(lastNpm);

  Serial.print("Jumlah event: ");
  Serial.println(eventCount);

  Serial.println("=========================");

  String respons =
    "Absensi diterima. Nama: " + lastNama +
    ", NPM: " + lastNpm;

  server.send(200, "text/plain", respons);
}



// =====================================
// 4. STATUS ESP32
// =====================================

void handleStatus() {
  String json = "{";
  json += "\"device\":\"ESP32\",";
  json += "\"wifi\":\"connected\",";
  json += "\"ip\":\"";
  json += WiFi.localIP().toString();
  json += "\",";
  json += "\"last_event\":\"";
  json += lastEvent;
  json += "\",";
  json += "\"last_npm\":\"";
  json += lastNpm;
  json += "\",";
  json += "\"event_count\":";
  json += String(eventCount);
  json += "}";

  server.send(200, "application/json", json);
}


// =====================================
// 5. SETUP
// =====================================

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println();
  Serial.println("AIoT Smart Attendance");
  Serial.println("Menghubungkan ke WiFi...");

  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  int percobaan = 0;

  while (WiFi.status() != WL_CONNECTED &&
         percobaan < 40) {
    delay(500);
    Serial.print(".");
    percobaan++;
  }

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println();
    Serial.println("WiFi gagal terhubung.");
    Serial.println("Periksa SSID, password, dan jaringan.");
    return;
  }

  Serial.println();
  Serial.println("WiFi berhasil terhubung.");

  Serial.print("Alamat IP: ");
  Serial.println(WiFi.localIP());

  server.on("/", HTTP_GET, handleRoot);
  server.on("/test", HTTP_GET, handleTest);
  server.on("/status", HTTP_GET, handleStatus);

  server.onNotFound([]() {
    server.send(
      404,
      "text/plain",
      "Endpoint tidak ditemukan"
    );
  });

  server.begin();

  Serial.println("Web server aktif.");
}


// =====================================
// 6. LOOP
// =====================================

void loop() {
  if (WiFi.status() == WL_CONNECTED) {
    server.handleClient();
  }

  delay(2);
}
