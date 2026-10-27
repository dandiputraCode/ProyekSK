"""Jembatan USB Serial dari laptop ke ESP32 + sensor sidik jari R503.

Hanya SATU proses yang boleh membuka port COM. Karena itu modul ini dipakai
oleh app_web.py (server yang selalu hidup); test_face_recognition.py tetap
berkomunikasi lewat HTTP ke Flask.
"""

import os
import queue
import re
import threading
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover - pyserial wajib ada saat dipakai
    serial = None
    list_ports = None

BAUDRATE = 115200
USB_VIDS = {0x10C4, 0x1A86, 0x303A, 0x0403, 0x2341, 0x2E8A}
USB_KEYWORDS = ("esp32", "cp210", "ch34", "usb-serial", "usb serial", "silicon labs")

MATCH_POLA = (re.compile(r"^MATCH (\d+) (\d+)$"), re.compile(r"ID #(\d+).*?confidence (\d+)"))


def pilih_port():
    """Port dari env ESP32_PORT, kalau tidak ada pilih otomatis port USB ESP32."""
    port_env = os.environ.get("ESP32_PORT", "").strip()
    if port_env:
        return port_env
    if list_ports is None:
        return None

    kandidat = list(list_ports.comports())
    for info in kandidat:
        if info.vid in USB_VIDS:
            return info.device
    for info in kandidat:
        deskripsi = f"{info.description} {info.manufacturer}".lower()
        if any(kata in deskripsi for kata in USB_KEYWORDS):
            return info.device
    return None


class R503Bridge:
    """Membuka port serial di thread latar, membaca baris event, dan mengirim perintah."""

    def __init__(self):
        self._port = None
        self._serial = None
        self._tulis_lock = threading.Lock()
        self._garis_lock = threading.Lock()
        self._garis = []          # riwayat baris dari ESP32
        self._match = queue.Queue()
        self._berhenti = threading.Event()
        self.error = "Belum terhubung"
        self.templates = None
        self.terakhir = "-"
        self._thread = threading.Thread(target=self._loop_baca, daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------ baca
    def _catat(self, baris):
        with self._garis_lock:
            self._garis.append(baris)
            del self._garis[:-200]
        self.terakhir = baris


        if baris == "NOMATCH":
            self._match.put(None)
            return
        for pola in MATCH_POLA:
            cocok = pola.search(baris)
            if cocok:
                self._match.put((int(cocok.group(1)), int(cocok.group(2))))
                return

        if baris.startswith(("READY", "PONG")):
            bagian = baris.split()
            if len(bagian) >= 2 and bagian[1].isdigit():
                self.templates = int(bagian[1])

    def _buka(self):
        port = pilih_port()
        if not port:
            self.error = "ESP32 tidak ditemukan (colok kabel USB)"
            return False
        try:
            self._serial = serial.Serial(port, BAUDRATE, timeout=0.5)
            self._port = port
            self.error = None
            time.sleep(1.2)          # ESP32 reset saat port dibuka
            self._serial.reset_input_buffer()
            self.kirim("PING")
            return True
        except PermissionError:
            self.error = (
                f"Port {port} sedang dipakai program lain (Serial Monitor Arduino IDE "
                "atau instance app_web.py kedua). Tutup program itu; koneksi dicoba ulang otomatis."
            )
            self._serial = None
            return False
        except Exception as error:
            self.error = f"Gagal membuka {port}: {error}"
            self._serial = None
            return False

    def _loop_baca(self):
        while not self._berhenti.is_set():
            if self._serial is None and not self._buka():
                self._berhenti.wait(2.0)
                continue
            try:
                baris = self._serial.readline().decode("utf-8", "replace").strip()
                if baris:
                    self._catat(baris)
            except Exception as error:
                self.error = f"Koneksi serial terputus: {error}"
                try:
                    self._serial.close()
                except Exception:
                    pass
                self._serial = None
                self._port = None
                self._berhenti.wait(1.5)

    # ----------------------------------------------------------------- tulis
    def kirim(self, perintah):
        if self._serial is None:
            return False
        try:
            with self._tulis_lock:
                self._serial.write((perintah + "\n").encode("utf-8"))
                self._serial.flush()
            return True
        except Exception as error:
            self.error = f"Gagal mengirim perintah: {error}"
            return False

    def status(self):
        return {
            "connected": self._serial is not None,
            "port": self._port,
            "templates": self.templates,
            "last_event": self.terakhir,
            "error": self.error,
        }

    def _baris_baru(self, mulai):
        with self._garis_lock:
            return self._garis[mulai:], len(self._garis)

    # ----------------------------------------------------------------- tunggu
    def enroll(self, finger_id, timeout=45):
        """Minta ESP32 merekam sidik jari baru. Kembalikan (ok, pesan)."""
        if self._serial is None:
            return False, "ESP32 belum terhubung lewat USB Serial."

        with self._garis_lock:
            mulai = len(self._garis)

        if not self.kirim(f"ENROLL {finger_id}"):
            return False, "Gagal mengirim perintah ENROLL ke ESP32."

        batas = time.monotonic() + timeout
        while time.monotonic() < batas:
            baru, mulai = self._baris_baru(mulai)
            for baris in baru:
                if baris.startswith(f"ENROLL_OK {finger_id}") or "Enroll BERHASIL" in baris:
                    return True, "Sidik jari berhasil direkam."
                if "Masukkan ID" in baris:
                    self.kirim(str(finger_id))
                if baris.startswith(f"ENROLL_FAIL {finger_id}") or "tidak cocok" in baris or "Gagal" in baris:
                    return False, f"Sensor menolak perekaman ({baris.split()[-1]}). Tempelkan jari dengan bersih."
            time.sleep(0.05)
        return False, "Waktu habis: jari tidak terdeteksi di sensor R503."

    def tunggu_match(self, finger_id, timeout):
        """Tunggu MATCH untuk finger_id. Kembalikan (confidence, pesan)."""
        # Buang event lama: jari yang ditempel sebelum permintaan ini tidak boleh
        # dipakai untuk memverifikasi absensi (cegah 2FA lolos tanpa tempelan baru).
        while True:
            try:
                self._match.get_nowait()
            except queue.Empty:
                break

        batas = time.monotonic() + timeout
        while True:
            sisa = batas - time.monotonic()
            if sisa <= 0:
                return None, "Waktu habis: jari tidak ditempel di sensor R503."
            try:
                event = self._match.get(timeout=min(sisa, 0.5))
            except queue.Empty:
                if self._serial is None:
                    return None, "Koneksi ESP32/R503 terputus saat verifikasi."
                continue
            if event is None:
                return None, "Sidik jari tidak dikenali sensor R503. Tempelkan ulang jari yang terdaftar."
            id_terbaca, confidence = event
            if id_terbaca == finger_id:
                return confidence, "Sidik jari cocok."
            return None, (
                f"Jari cocok dengan template ID #{id_terbaca}, bukan ID #{finger_id} milik siswa ini. "
                "Rekam ulang sidik jari siswa lewat menu Pendaftaran Siswa."
            )

    def kedip_hijau(self):
        self.kirim("LED_OK")


bridge = R503Bridge()
