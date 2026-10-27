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
const enrollFingerCheckbox = document.getElementById('enroll-finger');
const enrollFingerOnlyButton = document.getElementById('enroll-finger-only');
const sensorStatusText = document.getElementById('fingerprint-sensor-status');
const enrolledStudentsBody = document.getElementById('enrolled-students-body');

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

async function loadRegisteredStudents() {
  if (!enrolledStudentsBody) return;
  try {
    const res = await fetch('/api/students', { cache: 'no-store' });
    const data = await res.json();
    const list = data.students || [];
    if (!list.length) {
      enrolledStudentsBody.innerHTML = '<tr><td colspan="5" class="empty-cell">Belum ada siswa terdaftar.</td></tr>';
      return;
    }
    enrolledStudentsBody.innerHTML = list.map(row => {
      const fingerBadge = row.finger_id != null
        ? `<span class="pill pill-green">ID #${escapeHtml(row.finger_id)}</span>`
        : `<span class="pill pill-neutral">Belum direkam</span>`;
      const created = String(row.created_at || '-').replace('T', ' ');
      return `
      <tr data-npm="${escapeHtml(row.npm)}" data-nama="${escapeHtml(row.nama)}" style="cursor:pointer" title="Klik untuk isi NPM & Nama">
        <td><strong>${escapeHtml(row.nama)}</strong></td>
        <td><span class="mono">${escapeHtml(row.npm)}</span></td>
        <td><span class="source-tag">▣ ${escapeHtml(row.photo_count)} foto</span></td>
        <td>${fingerBadge}</td>
        <td><span class="mono">${escapeHtml(created)}</span></td>
      </tr>`;
    }).join('');
    enrolledStudentsBody.querySelectorAll('tr[data-npm]').forEach(tr => {
      tr.addEventListener('click', () => {
        document.getElementById('student-npm').value = tr.dataset.npm || '';
        document.getElementById('student-name').value = tr.dataset.nama || '';
      });
    });
  } catch (_err) {
    enrolledStudentsBody.innerHTML = '<tr><td colspan="5" class="empty-cell">Gagal memuat daftar siswa.</td></tr>';
  }
}

async function refreshSensorStatus() {
  if (!sensorStatusText) return;
  try {
    const res = await fetch('/api/fingerprint/status');
    const data = await res.json();
    const s = data.sensor || {};
    if (s.connected) {
      sensorStatusText.textContent = `Terhubung di ${s.port} · Siap merekam (ID berikutnya: #${data.next_finger_id ?? '-'})`;
      sensorStatusText.style.color = '#137a5a';
    } else {
      sensorStatusText.textContent = `ESP32/R503 belum terdeteksi di USB (${s.error || 'belum dicolok'}). Anda tetap bisa menyimpan foto wajah dulu.`;
      sensorStatusText.style.color = '#818da5';
      if (enrollFingerCheckbox) enrollFingerCheckbox.checked = false;
    }
  } catch (_err) {
    sensorStatusText.textContent = 'Tidak dapat memeriksa status sensor R503.';
  }
}

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
  const enrollFinger = enrollFingerCheckbox ? enrollFingerCheckbox.checked : false;
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
  showMessage(
    enrollFinger
      ? 'Memvalidasi 3 foto dengan YOLO, lalu tempelkan jari 2 kali di sensor R503 saat lampu biru menyala...'
      : 'Sedang memvalidasi tiga foto dengan YOLO. Proses pertama mungkin lebih lama karena model dimuat.',
    'info'
  );

  try {
    const response = await fetch('/api/students/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ npm, nama, photos, consent, enroll_finger: enrollFinger })
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
    loadRegisteredStudents();
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
if (enrollFingerOnlyButton) {
  enrollFingerOnlyButton.addEventListener('click', async () => {
    clearMessage();
    const npm = document.getElementById('student-npm').value.trim();
    const nama = document.getElementById('student-name').value.trim();
    if (!npm || !nama) {
      showMessage('Isi NPM dan Nama Lengkap terlebih dahulu untuk merekam sidik jari.', 'error');
      return;
    }
    enrollFingerOnlyButton.disabled = true;
    showMessage('Tempelkan jari pada sensor R503 (2 kali tempel saat lampu biru menyala)...', 'info');
    const rekam = (replace) => fetch('/api/fingerprint/enroll', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ npm, nama, replace })
    });
    try {
      let res = await rekam(false);
      let data = await res.json().catch(() => ({}));
      if (res.status === 409 && data.replaceable &&
          confirm(`${data.message}\n\nRekam ulang sidik jari sekarang? Template lama akan ditimpa.`)) {
        showMessage('Tempelkan jari pada sensor R503 (2 kali tempel)...', 'info');
        res = await rekam(true);
        data = await res.json().catch(() => ({}));
      }
      if (!res.ok) throw new Error(data.message || `Gagal merekam sidik jari (HTTP ${res.status}).`);
      showMessage(`${data.message} (${data.student.nama} - ID Sidik Jari #${data.student.finger_id}).`, 'success');
      refreshSensorStatus();
      loadRegisteredStudents();
    } catch (err) {
      showMessage(err.message || 'Gagal merekam sidik jari R503.', 'error');
    } finally {
      enrollFingerOnlyButton.disabled = false;
    }
  });
}

refreshSensorStatus();
setInterval(refreshSensorStatus, 4000);
loadRegisteredStudents();

renderPhotos();
