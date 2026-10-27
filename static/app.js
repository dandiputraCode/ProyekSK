const dateFilter = document.getElementById('date-filter');
const searchInput = document.getElementById('search-input');
const body = document.getElementById('attendance-body');
const refreshButton = document.getElementById('refresh-button');
const exportButton = document.getElementById('export-button');
const studentsBody = document.getElementById('students-body');
let cachedStudents = [];
let cachedRecords = [];
let isLoading = false;

function todayISO() {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

function initials(name) {
  return String(name || '?').trim().split(/\s+/).slice(0, 2).map(x => x[0] || '').join('').toUpperCase();
}

function renderRecords() {
  const query = searchInput.value.trim().toLowerCase();
  const records = cachedRecords.filter(row =>
    String(row.nama).toLowerCase().includes(query) ||
    String(row.npm).toLowerCase().includes(query)
  );

  if (!records.length) {
    body.innerHTML = `<tr><td colspan="6" class="empty-cell">${query ? 'Tidak ada data yang sesuai dengan pencarian.' : 'Belum ada absensi pada tanggal ini.'}</td></tr>`;
  } else {
    body.innerHTML = records.map(row => `
      <tr>
        <td><div class="student-cell"><div class="student-avatar">${escapeHtml(initials(row.nama))}</div><div><div class="student-name">${escapeHtml(row.nama)}</div><div class="student-caption">Student profile</div></div></div></td>
        <td><span class="mono">${escapeHtml(row.npm)}</span></td>
        <td>${escapeHtml(row.tanggal)}</td>
        <td><span class="mono">${escapeHtml(row.waktu)}</span></td>
        <td><span class="source-tag">◉ ${escapeHtml(row.sumber)}</span></td>
        <td><span class="pill pill-green">${escapeHtml(row.status)}</span></td>
      </tr>`).join('');
  }
  document.getElementById('record-count').textContent = `${records.length} rekaman ditampilkan`;
}

function renderStudents() {
  if (!studentsBody) return;
  const query = searchInput.value.trim().toLowerCase();
  const list = cachedStudents.filter(row =>
    String(row.nama).toLowerCase().includes(query) ||
    String(row.npm).toLowerCase().includes(query)
  );

  if (!list.length) {
    studentsBody.innerHTML = `<tr><td colspan="5" class="empty-cell">${query ? 'Tidak ada siswa yang sesuai pencarian.' : 'Belum ada siswa terdaftar.'}</td></tr>`;
  } else {
    studentsBody.innerHTML = list.map(row => {
      const fingerBadge = row.finger_id != null
        ? `<span class="pill pill-green">ID #${escapeHtml(row.finger_id)}</span>`
        : `<span class="pill pill-neutral">Belum direkam</span>`;
      const created = String(row.created_at || '-').replace('T', ' ');
      return `
      <tr>
        <td><div class="student-cell"><div class="student-avatar">${escapeHtml(initials(row.nama))}</div><div><div class="student-name">${escapeHtml(row.nama)}</div><div class="student-caption">Terdaftar</div></div></div></td>
        <td><span class="mono">${escapeHtml(row.npm)}</span></td>
        <td><span class="source-tag">▣ ${escapeHtml(row.photo_count)} foto</span></td>
        <td>${fingerBadge}</td>
        <td><span class="mono">${escapeHtml(created)}</span></td>
      </tr>`;
    }).join('');
  }
  const countEl = document.getElementById('student-count');
  if (countEl) countEl.textContent = `${list.length} siswa terdaftar`;
}

async function loadDashboard() {
  if (isLoading) return;
  isLoading = true;
  refreshButton.disabled = true;
  document.getElementById('refresh-symbol').textContent = '…';
  try {
    const selectedDate = dateFilter.value || todayISO();
    const response = await fetch(`/api/dashboard?date=${encodeURIComponent(selectedDate)}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();

    document.getElementById('stat-registered').textContent = data.registered_students;
    document.getElementById('stat-present').textContent = data.present_count;
    document.getElementById('stat-percentage').textContent = data.attendance_percentage;
    document.getElementById('attendance-progress').style.width = `${data.attendance_percentage}%`;
    document.getElementById('stat-total').textContent = data.total_records;
    document.getElementById('last-updated').textContent = data.server_time;
    cachedRecords = data.records || [];
    cachedStudents = data.students || [];
    renderRecords();
    renderStudents();
    exportButton.href = `/api/export?date=${encodeURIComponent(selectedDate)}`;
    document.getElementById('current-date').textContent = new Date(`${selectedDate}T00:00:00`).toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric' });
  } catch (error) {
    body.innerHTML = '<tr><td colspan="6" class="empty-cell">Gagal memuat data. Pastikan server Flask masih berjalan.</td></tr>';
    document.getElementById('record-count').textContent = 'Koneksi dashboard bermasalah';
    console.error(error);
  } finally {
    isLoading = false;
    refreshButton.disabled = false;
    document.getElementById('refresh-symbol').textContent = '↻';
  }
}

dateFilter.value = todayISO();
searchInput.addEventListener('input', () => { renderRecords(); renderStudents(); });
dateFilter.addEventListener('change', loadDashboard);
refreshButton.addEventListener('click', loadDashboard);
loadDashboard();
setInterval(loadDashboard, 1000);

// ponytail: syncs sidebar .active from URL hash + scroll; move to router if SPA added
const navLinks = [...document.querySelectorAll('.sidebar .nav-item')];
const navSections = navLinks
  .map(link => ({ link, hash: new URL(link.href, location.href).hash }))
  .filter(item => item.hash)
  .map(item => ({ ...item, el: document.querySelector(item.hash) }))
  .filter(item => item.el);
let navLockUntil = 0;

function setActiveNav(activeLink) {
  navLinks.forEach(link => link.classList.toggle('active', link === activeLink));
}

function syncNavFromHash() {
  const match = navSections.find(item => item.hash === location.hash);
  if (!match) return false;
  navLockUntil = performance.now() + 700;
  setActiveNav(match.link);
  return true;
}

function syncNavFromScroll() {
  if (performance.now() < navLockUntil) return;
  if (scrollY <= 20) return setActiveNav(navLinks[0]);
  const hashed = navSections.find(item => item.hash === location.hash);
  if (navSections.length && innerHeight + scrollY >= document.documentElement.scrollHeight - 10) {
    return setActiveNav((hashed || navSections[navSections.length - 1]).link);
  }
  const line = innerHeight * 0.35;
  setActiveNav(navSections.filter(item => item.el.getBoundingClientRect().top <= line).pop()?.link || navLinks[0]);
}

navLinks.forEach(link => {
  link.addEventListener('click', event => {
    const url = new URL(link.href, location.href);
    navLockUntil = performance.now() + 700;
    setActiveNav(link);
    if (url.pathname === location.pathname && !url.hash) {
      event.preventDefault();
      history.pushState(null, '', url.pathname);
      scrollTo({ top: 0, behavior: 'smooth' });
    }
  });
});
addEventListener('scroll', syncNavFromScroll, { passive: true });
addEventListener('hashchange', syncNavFromHash);
addEventListener('resize', syncNavFromScroll);
if (!syncNavFromHash()) syncNavFromScroll();

