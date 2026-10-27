
import requests

# Ganti jika alamat IP ESP32 berubah
ESP32_IP = "10.251.114.225"

BASE_URL = f"http://{ESP32_IP}"


def main():
    print("Menghubungkan Python ke ESP32...")

    try:
        # Mengirim simulasi hasil pengenalan wajah
        payload = {
            "event": "FACE_OK",
            "npm": "27126014"
        }

        response = requests.get(
            f"{BASE_URL}/test",
            params=payload,
            timeout=5
        )

        response.raise_for_status()

        print("\nData berhasil dikirim!")
        print("Respons ESP32:")
        print(response.text)

        # Memeriksa status terbaru ESP32
        status_response = requests.get(
            f"{BASE_URL}/status",
            timeout=5
        )

        status_response.raise_for_status()

        print("\nStatus perangkat:")
        print(status_response.json())

    except requests.exceptions.RequestException as error:
        print("\nGagal berkomunikasi dengan ESP32.")
        print("Detail:", error)
        print("Periksa alamat IP dan koneksi Wi-Fi.")


if __name__ == "__main__":
    main()
