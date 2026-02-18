/**
 * WFM Schedule Generator — Frontend Application
 * Handles file upload, API integration, and results rendering.
 */

const API_BASE = '';

// ─── DOM References ───
const fileInput = document.getElementById('fileInput');
const uploadZone = document.getElementById('uploadZone');
const uploadProgress = document.getElementById('uploadProgress');
const uploadSection = document.getElementById('uploadSection');
const dataSummary = document.getElementById('dataSummary');
const statsGrid = document.getElementById('statsGrid');
const regulationsList = document.getElementById('regulationsList');
const forecastSection = document.getElementById('forecastSection');
const forecastUploadZone = document.getElementById('forecastUploadZone');
const forecastFileInput = document.getElementById('forecastFileInput');
const forecastProgress = document.getElementById('forecastProgress');
const forecastSummary = document.getElementById('forecastSummary');
const forecastStatsGrid = document.getElementById('forecastStatsGrid');
const generateSection = document.getElementById('generateSection');
const generateBtn = document.getElementById('generateBtn');
const solverProgress = document.getElementById('solverProgress');
const resultsSection = document.getElementById('resultsSection');
const solverStats = document.getElementById('solverStats');
const coverageChart = document.getElementById('coverageChart');
const scheduleTable = document.getElementById('scheduleTable');
const exportBtn = document.getElementById('exportBtn');
const timeLimitSelect = document.getElementById('timeLimit');

// ─── File Upload ───
uploadZone.addEventListener('click', () => fileInput.click());

uploadZone.addEventListener('dragover', (e) => {
  e.preventDefault();
  uploadZone.classList.add('drag-over');
});

uploadZone.addEventListener('dragleave', () => {
  uploadZone.classList.remove('drag-over');
});

uploadZone.addEventListener('drop', (e) => {
  e.preventDefault();
  uploadZone.classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file) handleUpload(file);
});

fileInput.addEventListener('change', () => {
  const file = fileInput.files[0];
  if (file) handleUpload(file);
});

async function handleUpload(file) {
  if (!file.name.match(/\.xlsx?$/i)) {
    showToast('Please upload an Excel file (.xlsx)', 'error');
    return;
  }

  // Show progress
  uploadProgress.style.display = 'block';
  const progressFill = uploadProgress.querySelector('.progress-fill');
  const progressText = uploadProgress.querySelector('.progress-text');
  progressFill.style.width = '30%';
  progressText.textContent = 'Uploading file...';

  const formData = new FormData();
  formData.append('file', file);

  try {
    progressFill.style.width = '60%';
    progressText.textContent = 'Parsing WFM data...';

    const res = await fetch(`${API_BASE}/api/upload`, {
      method: 'POST',
      body: formData,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Upload failed' }));
      throw new Error(err.detail || 'Upload failed');
    }

    const data = await res.json();

    progressFill.style.width = '100%';
    progressText.textContent = 'Done!';

    setTimeout(() => {
      uploadProgress.style.display = 'none';
      renderDataSummary(data.data);
    }, 500);

  } catch (err) {
    progressFill.style.width = '0%';
    uploadProgress.style.display = 'none';
    showToast(err.message, 'error');
  }
}

// ─── Data Summary ───
function renderDataSummary(data) {
  // Update upload zone appearance
  const uploadIcon = uploadZone.querySelector('.upload-icon');
  const uploadText = uploadZone.querySelector('.upload-text');
  const uploadSubtext = uploadZone.querySelector('.upload-subtext');
  if (uploadIcon) uploadIcon.innerHTML = `
    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
      <polyline points="22 4 12 14.01 9 11.01"/>
    </svg>`;
  if (uploadText) uploadText.textContent = 'File uploaded successfully';
  if (uploadSubtext) uploadSubtext.textContent = 'Click or drop to upload a different file';
  uploadZone.style.borderColor = 'rgba(100, 255, 218, 0.3)';

  // Stats grid
  const stats = [
    { value: data.num_agents, label: 'Agents' },
    { value: data.num_dates, label: 'Days' },
    { value: data.num_shift_codes, label: 'Shift Codes' },
    { value: data.num_leave_requests, label: 'Leave Requests' },
    { value: data.num_regulations, label: 'Regulations' },
  ];

  statsGrid.innerHTML = stats.map(s => `
    <div class="stat-card">
      <div class="stat-value">${s.value}</div>
      <div class="stat-label">${s.label}</div>
    </div>
  `).join('');

  // Regulations with GPT-parsed status
  if (data.regulations && data.regulations.length > 0) {
    const parsedRules = data.parsed_rules || [];

    regulationsList.innerHTML = data.regulations.map((r, i) => {
      const parsed = parsedRules[i];
      if (parsed) {
        const badge = parsed.enforceable
          ? '<span class="rule-badge rule-enforced">🟢 Enforced</span>'
          : '<span class="rule-badge rule-display">🟡 Display Only</span>';
        const detail = parsed.enforceable
          ? `<span class="rule-detail">${parsed.type}${Object.keys(parsed.params).length ? ' · ' + JSON.stringify(parsed.params) : ''}</span>`
          : `<span class="rule-detail">${parsed.reason || 'Cannot map to solver constraint'}</span>`;
        return `
          <div class="regulation-item">
            <span class="reg-num">${i + 1}</span>
            <span class="reg-text">${escapeHtml(r)}</span>
            ${badge}
            ${detail}
          </div>`;
      }
      return `
        <div class="regulation-item">
          <span class="reg-num">${i + 1}</span>
          <span>${escapeHtml(r)}</span>
        </div>`;
    }).join('');
  }

  dataSummary.style.display = 'block';
  forecastSection.style.display = 'block';

  // Smooth scroll to summary
  dataSummary.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ─── Forecast Upload ───
forecastUploadZone.addEventListener('click', () => forecastFileInput.click());

forecastUploadZone.addEventListener('dragover', (e) => {
  e.preventDefault();
  forecastUploadZone.classList.add('drag-over');
});

forecastUploadZone.addEventListener('dragleave', () => {
  forecastUploadZone.classList.remove('drag-over');
});

forecastUploadZone.addEventListener('drop', (e) => {
  e.preventDefault();
  forecastUploadZone.classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file) handleForecastUpload(file);
});

forecastFileInput.addEventListener('change', () => {
  const file = forecastFileInput.files[0];
  if (file) handleForecastUpload(file);
});

async function handleForecastUpload(file) {
  if (!file.name.match(/\.xlsx?$/i)) {
    showToast('Please upload an Excel file (.xlsx)', 'error');
    return;
  }

  forecastProgress.style.display = 'block';
  const progressFill = forecastProgress.querySelector('.progress-fill');
  const progressText = forecastProgress.querySelector('.progress-text');
  progressFill.style.width = '30%';
  progressText.textContent = 'Uploading forecast file...';

  const formData = new FormData();
  formData.append('file', file);

  try {
    progressFill.style.width = '60%';
    progressText.textContent = 'Parsing forecast data...';

    const res = await fetch(`${API_BASE}/api/upload-forecast`, {
      method: 'POST',
      body: formData,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Forecast upload failed' }));
      throw new Error(err.detail || 'Forecast upload failed');
    }

    const data = await res.json();

    progressFill.style.width = '100%';
    progressText.textContent = 'Done!';

    setTimeout(() => {
      forecastProgress.style.display = 'none';
      renderForecastSummary(data.data);
    }, 500);

  } catch (err) {
    progressFill.style.width = '0%';
    forecastProgress.style.display = 'none';
    showToast(err.message, 'error');
  }
}

function renderForecastSummary(data) {
  // Update forecast upload zone
  const icon = forecastUploadZone.querySelector('.upload-icon');
  const text = forecastUploadZone.querySelector('.upload-text');
  const subtext = forecastUploadZone.querySelector('.upload-subtext');
  if (icon) icon.innerHTML = `
    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
      <polyline points="22 4 12 14.01 9 11.01"/>
    </svg>`;
  if (text) text.textContent = 'Forecast data loaded successfully';
  if (subtext) subtext.textContent = 'Click or drop to use a different forecast file';
  forecastUploadZone.style.borderColor = 'rgba(100, 255, 218, 0.3)';

  // Stats
  const stats = [
    { value: data.num_dates, label: 'Schedule Days' },
    { value: data.date_range, label: 'Date Range' },
    { value: data.avg_daily_demand, label: 'Avg Hourly Demand' },
    { value: `${data.leave_requests_in_range} / ${data.leave_requests_total}`, label: 'Leave in Range' },
  ];

  forecastStatsGrid.innerHTML = stats.map(s => `
    <div class="stat-card">
      <div class="stat-value ${typeof s.value === 'string' && s.value.includes('to') ? 'stat-value-sm' : ''}">${s.value}</div>
      <div class="stat-label">${s.label}</div>
    </div>
  `).join('');

  forecastSummary.style.display = 'block';
  generateSection.style.display = 'block';

  forecastSummary.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ─── Generate Schedule ───
async function generateSchedule() {
  const timeLimit = parseInt(timeLimitSelect.value);

  generateBtn.disabled = true;
  solverProgress.style.display = 'flex';

  try {
    const res = await fetch(`${API_BASE}/api/generate?time_limit=${timeLimit}`, {
      method: 'POST',
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Generation failed' }));
      throw new Error(err.detail || 'Generation failed');
    }

    const results = await res.json();
    solverProgress.style.display = 'none';
    renderResults(results);
    showToast('Schedule generated successfully!', 'success');

  } catch (err) {
    solverProgress.style.display = 'none';
    generateBtn.disabled = false;
    showToast(err.message, 'error');
  }
}

// Make generateSchedule available globally for the onclick handler
window.generateSchedule = generateSchedule;

// ─── Results Rendering ───
function renderResults(results) {
  resultsSection.style.display = 'block';
  exportBtn.disabled = false;

  renderSolverStats(results);
  renderCoverageChart(results);
  renderScheduleGrid(results);

  resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderSolverStats(results) {
  const statusClass = results.solve_status === 'OPTIMAL' ? 'optimal' : 'feasible';
  solverStats.innerHTML = `
    <div class="solver-stat">
      <span class="label">Status</span>
      <span class="value ${statusClass}">${results.solve_status}</span>
    </div>
    <div class="solver-stat">
      <span class="label">Solve Time</span>
      <span class="value">${results.solve_time}s</span>
    </div>
    <div class="solver-stat">
      <span class="label">Agents</span>
      <span class="value">${results.agents.length}</span>
    </div>
    <div class="solver-stat">
      <span class="label">Days</span>
      <span class="value">${results.dates.length}</span>
    </div>
    <div class="solver-stat">
      <span class="label">Shifts Used</span>
      <span class="value">${results.shifts.length}</span>
    </div>
  `;
}

function renderCoverageChart(results) {
  const coverage = results.coverage;
  if (!coverage) return;

  const dates = results.dates;
  const maxWorking = Math.max(
    ...dates.map(d => coverage[d] ? coverage[d].total_working : 0),
    1
  );

  let html = `
    <div class="chart-legend">
      <span class="chart-legend-item">
        <span class="chart-legend-dot" style="background: linear-gradient(135deg, #1565c0, #42a5f5)"></span>
        03:00 Shift
      </span>
      <span class="chart-legend-item">
        <span class="chart-legend-dot" style="background: linear-gradient(135deg, #e65100, #ff9800)"></span>
        20:00 Shift
      </span>
      <span class="chart-legend-item">
        <span class="chart-legend-dot" style="background: linear-gradient(135deg, #2e7d32, #66bb6a)"></span>
        OFF
      </span>
    </div>
    <div class="coverage-chart">
  `;

  for (const date of dates) {
    const stats = coverage[date] || { shift_03_count: 0, shift_20_count: 0, off_count: 0, total_working: 0, forecast_demand: 0 };
    const barScale = 300; // max bar width in px

    const morningW = Math.round((stats.shift_03_count / maxWorking) * barScale);
    const eveningW = Math.round((stats.shift_20_count / maxWorking) * barScale);

    // Format date nicely
    const d = new Date(date);
    const dayNames = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const shortDate = `${dayNames[d.getDay()]} ${d.getDate()}`;

    html += `
      <div class="chart-row">
        <span class="chart-label">${shortDate}</span>
        <div class="chart-bars">
          <div class="chart-bar morning" style="width: ${Math.max(morningW, 2)}px" title="03:00 shift: ${stats.shift_03_count}">
            <span class="chart-bar-value">${stats.shift_03_count}</span>
          </div>
          <div class="chart-bar evening" style="width: ${Math.max(eveningW, 2)}px" title="20:00 shift: ${stats.shift_20_count}">
            <span class="chart-bar-value">${stats.shift_20_count}</span>
          </div>
        </div>
        <span class="chart-total">${stats.total_working} / ${stats.forecast_demand}</span>
      </div>
    `;
  }

  html += '</div>';
  coverageChart.innerHTML = html;
}

function renderScheduleGrid(results) {
  const { agents, dates } = results;

  // Header
  let thead = '<thead><tr>';
  thead += '<th class="sticky-col">Agent</th>';
  for (const date of dates) {
    const d = new Date(date);
    const day = d.getDate();
    const dayNames = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];
    thead += `<th>${dayNames[d.getDay()]}<br>${day}</th>`;
  }
  thead += '</tr></thead>';

  // Body
  let tbody = '<tbody>';
  for (const agent of agents) {
    tbody += '<tr>';
    tbody += `<td class="sticky-col">${escapeHtml(agent.name)}</td>`;
    for (const date of dates) {
      const shift = agent.schedule[date] || 'OFF';
      const cls = getShiftCellClass(shift);
      const display = getShiftDisplay(shift);
      tbody += `<td class="${cls}">${display}</td>`;
    }
    tbody += '</tr>';
  }
  tbody += '</tbody>';

  scheduleTable.innerHTML = thead + tbody;
}

function getShiftCellClass(shift) {
  if (shift === '03:00') return 'cell-morning';
  if (shift === '20:00') return 'cell-evening';
  if (shift === 'OFF') return 'cell-off';
  if (shift === 'Leave' || shift === 'Resign') return 'cell-leave';
  // Check for time-like formats
  if (/^\d{2}:\d{2}$/.test(shift)) {
    const hour = parseInt(shift.split(':')[0]);
    if (hour >= 3 && hour < 12) return 'cell-morning';
    if (hour >= 18 || hour < 3) return 'cell-evening';
  }
  return '';
}

function getShiftDisplay(shift) {
  if (shift === '03:00') return '☀ 03';
  if (shift === '20:00') return '🌙 20';
  if (shift === 'OFF') return 'OFF';
  if (shift === 'Leave') return 'LV';
  if (shift === 'Resign') return 'RS';
  return shift;
}

// ─── Export ───
async function exportSchedule() {
  try {
    const res = await fetch(`${API_BASE}/api/export`);
    if (!res.ok) throw new Error('Export failed');

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'WFM_Generated_Schedule.xlsx';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    showToast('Schedule exported!', 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

window.exportSchedule = exportSchedule;

// ─── Utilities ───
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function showToast(message, type = 'error') {
  // Remove existing toasts
  document.querySelectorAll('.toast').forEach(t => t.remove());

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  document.body.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(20px)';
    toast.style.transition = '0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}
