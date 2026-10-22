const video = document.getElementById('camera-video');
const canvas = document.getElementById('capture-canvas');
const ctx = canvas.getContext('2d', { willReadFrequently: false });
const startButton = document.getElementById('start-camera');
const captureButton = document.getElementById('capture-photo');
const retakeButton = document.getElementById('retake-photos');
const saveButton = document.getElementById('save-student');
const form = document.getElementById('registration-form');
const photoGrid = document.getElementById('photo-grid');
const photoCounter = document.getElementById('photo-counter');
const cameraPlaceholder = document.getElementById('camera-placeholder');
const cameraStatus = document.getElementById('camera-status');
const cameraLiveDot = document.querySelector('.camera-live-dot');
const messageBox = document.getElementById('registration-message');

const REQUIRED_PHOTOS = 3;
let stream = null;
let photos = [];
let saving = false;

function showMessage(message, type = 'info') {
  messageBox.textContent = message;
  messageBox.className = `registration-message ${type}`;
  messageBox.hidden = false;
}

function clearMessage() {
  messageBox.hidden = true;
  messageBox.textContent = '';
  messageBox.className = 'registration-message';
}

function updateControls() {
  photoCounter.textContent = `${photos.length} / ${REQUIRED_PHOTOS}`;
  captureButton.disabled = !stream || photos.length >= REQUIRED_PHOTOS || saving;
  retakeButton.disabled = photos.length === 0 || saving;
  saveButton.disabled = photos.length !== REQUIRED_PHOTOS || saving;
}

function renderPhotos() {
  photoGrid.replaceChildren();
  for (let i = 0; i < REQUIRED_PHOTOS; i++) {
    const slot = document.createElement('div');
    slot.className = 'photo-slot';

    if (photos[i]) {
      slot.classList.add('filled');
      const img = document.createElement('img');
      img.src = photos[i];
      img.alt = `Foto referensi ${i + 1}`;
      const check = document.createElement('span');
      check.className = 'photo-check';
      check.textContent = '✓';
      slot.append(img, check);
    } else {
      const number = document.createElement('span');
      number.textContent = String(i + 1).padStart(2, '0');
      const label = document.createElement('small');
      label.textContent = ['Foto pertama', 'Foto kedua', 'Foto ketiga'][i];
      slot.append(number, label);
    }
    photoGrid.append(slot);
  }
  updateControls();
}

async function startCamera() {
  clearMessage();

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    showMessage('Browser tidak mendukung akses kamera. Gunakan Chrome/Edge terbaru dan buka melalui localhost atau HTTPS.', 'error');
    return;
  }

  try {
    if (stream) stopCamera();
    stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        facingMode: 'user',
        width: { ideal: 640 },
        height: { ideal: 480 }
      }
    });

    video.srcObject = stream;
    await video.play();
    video.classList.add('active');
    cameraPlaceholder.classList.add('hidden');
    cameraStatus.textContent = 'KAMERA AKTIF';
    cameraLiveDot.classList.add('active');
    startButton.textContent = '↻ Mulai Ulang Kamera';
    updateControls();
    showMessage('Kamera aktif. Ambil tiga foto dengan sedikit variasi sudut wajah.', 'info');
  } catch (error) {
    let explanation = 'Kamera gagal dibuka.';
    if (error.name === 'NotAllowedError') explanation = 'Izin kamera ditolak. Izinkan akses kamera pada browser.';
    if (error.name === 'NotFoundError') explanation = 'Kamera tidak ditemukan.';
    if (error.name === 'NotReadableError') explanation = 'Kamera sedang dipakai aplikasi lain. Tutup test_face_recognition.py atau aplikasi kamera terlebih dahulu.';
    showMessage(`${explanation} (${error.message || error.name})`, 'error');
  }
}

function stopCamera() {
  if (stream) {
    stream.getTracks().forEach(track => track.stop());
    stream = null;
  }
  video.pause();
  video.srcObject = null;
  video.classList.remove('active');
  cameraPlaceholder.classList.remove('hidden');
  cameraStatus.textContent = 'KAMERA NONAKTIF';
  cameraLiveDot.classList.remove('active');
  captureButton.disabled = true;
}

function capturePhoto() {
  clearMessage();
  if (!stream || !video.videoWidth || !video.videoHeight) {
    showMessage('Aktifkan kamera dan tunggu gambar tampil sebelum mengambil foto.', 'error');
    return;
  }
  if (photos.length >= REQUIRED_PHOTOS) {
    showMessage('Sudah ada tiga foto. Hapus semua foto jika ingin mengambil ulang.', 'info');
    return;
  }

  // Capture unmirrored image from the video stream. CSS mirroring is display-only.
  canvas.width = 640;
  canvas.height = 480;
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  photos.push(canvas.toDataURL('image/jpeg', 0.82));
  renderPhotos();

  if (photos.length === REQUIRED_PHOTOS) {
    showMessage('Tiga foto siap. Klik Simpan Siswa untuk validasi YOLO dan pendaftaran.', 'success');
  } else {
    showMessage(`Foto ${photos.length} dari ${REQUIRED_PHOTOS} berhasil diambil. Ubah sedikit sudut wajah lalu ambil berikutnya.`, 'info');
  }
}

function clearPhotos() {
  photos = [];
  renderPhotos();
  clearMessage();
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  clearMessage();

  const npm = document.getElementById('student-npm').value.trim();
  const nama = document.getElementById('student-name').value.trim();
  const consent = document.getElementById('student-consent').checked;

  if (!npm || !nama) {
    showMessage('NPM dan nama lengkap wajib diisi.', 'error');
    return;
  }
  if (!consent) {
    showMessage('Centang pernyataan persetujuan terlebih dahulu.', 'error');
    return;
  }
  if (photos.length !== REQUIRED_PHOTOS) {
    showMessage('Ambil tepat tiga foto sebelum menyimpan.', 'error');
    return;
  }

  saving = true;
  saveButton.textContent = 'Memvalidasi dan menyimpan...';
  startButton.disabled = true;
  updateControls();
  showMessage('Sedang memvalidasi tiga foto dengan YOLO. Proses pertama mungkin lebih lama karena model dimuat.', 'info');

  try {
    const response = await fetch('/api/students/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ npm, nama, photos, consent })
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.message || `Pendaftaran gagal (HTTP ${response.status}).`);
    }

    showMessage(`${data.message} Siswa: ${data.student.nama} (${data.student.npm}), ${data.student.photo_count} foto tersimpan.`, 'success');
    form.reset();
    clearPhotos();
    showMessage(`${data.message} Siswa ${data.student.nama} (${data.student.npm}) berhasil disimpan dengan ${data.student.photo_count} foto.`, 'success');
    stopCamera();
  } catch (error) {
    showMessage(error.message || 'Terjadi kesalahan saat mendaftarkan siswa.', 'error');
  } finally {
    saving = false;
    saveButton.textContent = 'Simpan Siswa';
    startButton.disabled = false;
    updateControls();
  }
});

startButton.addEventListener('click', startCamera);
captureButton.addEventListener('click', capturePhoto);
retakeButton.addEventListener('click', clearPhotos);
window.addEventListener('beforeunload', stopCamera);

renderPhotos();
