/**
 * WFM Schedule Generator — Frontend Application
 */

const API_BASE = '';

// ─── DOM References ───
const fileInput         = document.getElementById('fileInput');
const uploadZone        = document.getElementById('uploadZone');
const uploadProgress    = document.getElementById('uploadProgress');
const uploadSection     = document.getElementById('uploadSection');
const dataSummary       = document.getElementById('dataSummary');
const statsGrid         = document.getElementById('statsGrid');
const regulationsList   = document.getElementById('regulationsList');
const forecastSection   = document.getElementById('forecastSection');
const forecastUploadZone= document.getElementById('forecastUploadZone');
const forecastFileInput = document.getElementById('forecastFileInput');
const forecastProgress  = document.getElementById('forecastProgress');
const forecastSummary   = document.getElementById('forecastSummary');
const forecastStatsGrid = document.getElementById('forecastStatsGrid');
const generateSection   = document.getElementById('generateSection');
const generateBtn       = document.getElementById('generateBtn');
const solverProgress    = document.getElementById('solverProgress');
const resultsSection    = document.getElementById('resultsSection');
const solverStats       = document.getElementById('solverStats');
const coverageChart     = document.getElementById('coverageChart');
const scheduleTable     = document.getElementById('scheduleTable');
const exportBtn         = document.getElementById('exportBtn');
const resetBtn          = document.getElementById('resetBtn');
const timeLimitSelect   = document.getElementById('timeLimit');

// ─── App state ───
let currentShiftCodes = {};   // code → { period, label, time }
let solveTimerInterval = null;

// ─── File Upload ───
uploadZone.addEventListener('click', () => fileInput.click());
uploadZone.addEventListener('dragover', (e) => { e.preventDefault(); uploadZone.classList.add('drag-over'); });
uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('drag-over'));
uploadZone.addEventListener('drop', (e) => {
  e.preventDefault(); uploadZone.classList.remove('drag-over');
  if (e.dataTransfer.files[0]) handleUpload(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', () => { if (fileInput.files[0]) handleUpload(fileInput.files[0]); });

async function handleUpload(file) {
  if (!file.name.match(/\.xlsx?$/i)) { showToast('Please upload an Excel file (.xlsx)', 'error'); return; }

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

    const res = await fetch(`${API_BASE}/api/upload`, { method: 'POST', body: formData });
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
      resetBtn.style.display = 'inline-flex';
    }, 500);

  } catch (err) {
    progressFill.style.width = '0%';
    uploadProgress.style.display = 'none';
    showToast(err.message, 'error');
  }
}

// ─── Data Summary ───
function renderDataSummary(data) {
  const uploadIcon    = uploadZone.querySelector('.upload-icon');
  const uploadText    = uploadZone.querySelector('.upload-text');
  const uploadSubtext = uploadZone.querySelector('.upload-subtext');
  if (uploadIcon) uploadIcon.innerHTML = `
    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>
    </svg>`;
  if (uploadText)    uploadText.textContent = 'File uploaded successfully';
  if (uploadSubtext) uploadSubtext.textContent = 'Click or drop to upload a different file';
  uploadZone.style.borderColor = 'rgba(100, 255, 218, 0.3)';

  statsGrid.innerHTML = [
    { value: data.num_agents,         label: 'Agents' },
    { value: data.num_dates,          label: 'Days' },
    { value: data.num_shift_codes,    label: 'Shift Codes' },
    { value: data.num_leave_requests, label: 'Leave Requests' },
    { value: data.num_regulations,    label: 'Regulations' },
  ].map(s => `
    <div class="stat-card">
      <div class="stat-value">${s.value}</div>
      <div class="stat-label">${s.label}</div>
    </div>`).join('');

  if (data.regulations && data.regulations.length > 0) {
    const parsedRules = data.parsed_rules || [];
    regulationsList.innerHTML = data.regulations.map((r, i) => {
      const parsed = parsedRules[i];
      if (parsed) {
        const badge  = parsed.enforceable
          ? '<span class="rule-badge rule-enforced">🟢 Enforced</span>'
          : '<span class="rule-badge rule-display">🟡 Display Only</span>';
        const detail = parsed.enforceable
          ? `<span class="rule-detail">${parsed.type}${Object.keys(parsed.params).length ? ' · ' + JSON.stringify(parsed.params) : ''}</span>`
          : `<span class="rule-detail">${parsed.reason || 'Cannot map to solver constraint'}</span>`;
        return `<div class="regulation-item">
          <span class="reg-num">${i + 1}</span>
          <span class="reg-text">${escapeHtml(r)}</span>
          ${badge}${detail}
        </div>`;
      }
      return `<div class="regulation-item"><span class="reg-num">${i + 1}</span><span>${escapeHtml(r)}</span></div>`;
    }).join('');
  }

  dataSummary.style.display = 'block';
  forecastSection.style.display = 'block';
  dataSummary.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ─── Forecast Upload ───
forecastUploadZone.addEventListener('click', () => forecastFileInput.click());
forecastUploadZone.addEventListener('dragover', (e) => { e.preventDefault(); forecastUploadZone.classList.add('drag-over'); });
forecastUploadZone.addEventListener('dragleave', () => forecastUploadZone.classList.remove('drag-over'));
forecastUploadZone.addEventListener('drop', (e) => {
  e.preventDefault(); forecastUploadZone.classList.remove('drag-over');
  if (e.dataTransfer.files[0]) handleForecastUpload(e.dataTransfer.files[0]);
});
forecastFileInput.addEventListener('change', () => { if (forecastFileInput.files[0]) handleForecastUpload(forecastFileInput.files[0]); });

async function handleForecastUpload(file) {
  if (!file.name.match(/\.xlsx?$/i)) { showToast('Please upload an Excel file (.xlsx)', 'error'); return; }

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

    const res = await fetch(`${API_BASE}/api/upload-forecast`, { method: 'POST', body: formData });
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
  const icon    = forecastUploadZone.querySelector('.upload-icon');
  const text    = forecastUploadZone.querySelector('.upload-text');
  const subtext = forecastUploadZone.querySelector('.upload-subtext');
  if (icon)    icon.innerHTML = `
    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>
    </svg>`;
  if (text)    text.textContent = 'Forecast data loaded successfully';
  if (subtext) subtext.textContent = 'Click or drop to use a different forecast file';
  forecastUploadZone.style.borderColor = 'rgba(100, 255, 218, 0.3)';

  forecastStatsGrid.innerHTML = [
    { value: data.num_dates,    label: 'Schedule Days' },
    { value: data.date_range,   label: 'Date Range' },
    { value: data.avg_daily_demand, label: 'Avg Hourly Demand' },
    { value: `${data.leave_requests_in_range} / ${data.leave_requests_total}`, label: 'Leave in Range' },
  ].map(s => `
    <div class="stat-card">
      <div class="stat-value ${typeof s.value === 'string' && s.value.includes('to') ? 'stat-value-sm' : ''}">${s.value}</div>
      <div class="stat-label">${s.label}</div>
    </div>`).join('');

  forecastSummary.style.display = 'block';
  generateSection.style.display = 'block';
  forecastSummary.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ─── Generate Schedule ───
async function generateSchedule() {
  const timeLimit = parseInt(timeLimitSelect.value);

  generateBtn.disabled = true;
  solverProgress.style.display = 'flex';

  // Live elapsed-time counter
  let elapsed = 0;
  const progressText = solverProgress.querySelector('p');
  if (progressText) progressText.textContent = 'CP-SAT solver is finding the optimal schedule';
  solveTimerInterval = setInterval(() => {
    elapsed++;
    if (progressText) progressText.textContent = `Running… ${elapsed}s / ${timeLimit}s`;
  }, 1000);

  try {
    const res = await fetch(`${API_BASE}/api/generate?time_limit=${timeLimit}`, { method: 'POST' });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Generation failed' }));
      throw new Error(err.detail || 'Generation failed');
    }

    const results = await res.json();
    clearInterval(solveTimerInterval);
    solverProgress.style.display = 'none';
    generateBtn.disabled = false;

    // Store shift codes for display
    currentShiftCodes = results.shift_codes || {};

    renderResults(results);
    showToast('Schedule generated successfully!', 'success');

  } catch (err) {
    clearInterval(solveTimerInterval);
    solverProgress.style.display = 'none';
    generateBtn.disabled = false;
    showToast(err.message, 'error');
  }
}
window.generateSchedule = generateSchedule;

// ─── Results Rendering ───
function renderResults(results) {
  resultsSection.style.display = 'block';
  exportBtn.disabled = false;

  renderSolverStats(results);
  renderCoverageChart(results);
  renderScheduleGrid(results);
  renderLegend(results);

  resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderSolverStats(results) {
  const statusClass = results.solve_status === 'OPTIMAL' ? 'optimal' : 'feasible';
  solverStats.innerHTML = `
    <div class="solver-stat"><span class="label">Status</span><span class="value ${statusClass}">${results.solve_status}</span></div>
    <div class="solver-stat"><span class="label">Solve Time</span><span class="value">${results.solve_time}s</span></div>
    <div class="solver-stat"><span class="label">Agents</span><span class="value">${results.agents.length}</span></div>
    <div class="solver-stat"><span class="label">Days</span><span class="value">${results.dates.length}</span></div>
    <div class="solver-stat"><span class="label">Shifts</span><span class="value">${Object.keys(currentShiftCodes).filter(k => !['OFF','Leave','Resign'].includes(k)).length}</span></div>
  `;
}

function renderLegend(results) {
  const legend = document.getElementById('scheduleLegend');
  if (!legend) return;

  const periods = {};
  for (const [code, info] of Object.entries(currentShiftCodes)) {
    if (['OFF', 'Leave', 'Resign'].includes(code)) continue;
    const p = info.period || 'morning';
    if (!periods[p]) periods[p] = [];
    periods[p].push(info.label || code);
  }

  const periodDot = { morning: 'dot-morning', afternoon: 'dot-afternoon', night: 'dot-evening' };
  const periodLabel = { morning: 'Morning', afternoon: 'Afternoon', night: 'Night' };

  let html = '';
  for (const [p, labels] of Object.entries(periods)) {
    const sample = labels.slice(0, 2).join(', ');
    html += `<span class="legend-item"><span class="dot ${periodDot[p] || 'dot-morning'}"></span>${periodLabel[p] || p} (${sample}${labels.length > 2 ? '…' : ''})</span>`;
  }
  html += `<span class="legend-item"><span class="dot dot-off"></span>OFF</span>`;
  html += `<span class="legend-item"><span class="dot dot-leave"></span>Leave/Resign</span>`;

  legend.innerHTML = html;
}

function renderCoverageChart(results) {
  const coverage = results.coverage;
  if (!coverage) return;

  const dates = results.dates;
  const maxWorking = Math.max(...dates.map(d => coverage[d] ? coverage[d].total_working : 0), 1);

  // Determine which periods appear
  const periods = new Set();
  for (const d of dates) {
    const stats = coverage[d] || {};
    for (const k of Object.keys(stats)) {
      if (k.endsWith('_count') && !['off_count','leave_count'].includes(k)) {
        periods.add(k.replace('_count', ''));
      }
    }
  }

  const periodColors = {
    morning:   'linear-gradient(135deg, #1565c0, #42a5f5)',
    afternoon: 'linear-gradient(135deg, #2e7d32, #66bb6a)',
    night:     'linear-gradient(135deg, #e65100, #ff9800)',
  };

  let html = `<div class="chart-legend">`;
  for (const p of periods) {
    const col = periodColors[p] || periodColors.morning;
    const lbl = { morning: 'Morning', afternoon: 'Afternoon', night: 'Night' }[p] || p;
    html += `<span class="chart-legend-item"><span class="chart-legend-dot" style="background:${col}"></span>${lbl}</span>`;
  }
  html += `</div><div class="coverage-chart">`;

  const barScale = 300;
  for (const date of dates) {
    const stats   = coverage[date] || { total_working: 0, forecast_demand: 0 };
    const totalW  = stats.total_working || 0;
    const demand  = stats.forecast_demand || 0;
    const d       = new Date(date);
    const dayNames= ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
    const shortDate = `${dayNames[d.getDay()]} ${d.getDate()}`;

    html += `<div class="chart-row">
      <span class="chart-label">${shortDate}</span>
      <div class="chart-bars">`;

    for (const p of periods) {
      const cnt = stats[`${p}_count`] || 0;
      const w   = Math.max(Math.round((cnt / maxWorking) * barScale), 2);
      const col = periodColors[p] || periodColors.morning;
      html += `<div class="chart-bar" style="width:${w}px;background:${col}" title="${p}: ${cnt}">
        <span class="chart-bar-value">${cnt}</span></div>`;
    }

    html += `</div><span class="chart-total">${totalW} / ${demand}</span></div>`;
  }

  html += '</div>';
  coverageChart.innerHTML = html;
}

function renderScheduleGrid(results) {
  const { agents, dates } = results;

  let thead = '<thead><tr><th class="sticky-col">Agent</th>';
  for (const date of dates) {
    const d = new Date(date);
    const dayNames = ['Su','Mo','Tu','We','Th','Fr','Sa'];
    thead += `<th>${dayNames[d.getDay()]}<br>${d.getDate()}</th>`;
  }
  thead += '</tr></thead>';

  let tbody = '<tbody>';
  for (const agent of agents) {
    tbody += `<tr><td class="sticky-col">${escapeHtml(agent.name)}</td>`;
    for (const date of dates) {
      const shift = agent.schedule[date] || 'OFF';
      tbody += `<td class="${getShiftCellClass(shift)}">${getShiftDisplay(shift)}</td>`;
    }
    tbody += '</tr>';
  }
  tbody += '</tbody>';

  scheduleTable.innerHTML = thead + tbody;
}

// ─── Shift display helpers (now period-aware via currentShiftCodes) ───

function getShiftPeriod(displayValue) {
  // displayValue is the start time like "08:00" — look up in currentShiftCodes
  for (const [code, info] of Object.entries(currentShiftCodes)) {
    if (info.time === displayValue || info.label === displayValue) {
      return info.period || 'morning';
    }
  }
  // Fallback: infer from hour
  if (/^\d{2}:\d{2}$/.test(displayValue)) {
    const h = parseInt(displayValue.split(':')[0]);
    if (h >= 6  && h < 12) return 'morning';
    if (h >= 12 && h < 18) return 'afternoon';
    return 'night';
  }
  return 'morning';
}

function getShiftCellClass(shift) {
  if (shift === 'OFF')    return 'cell-off';
  if (shift === 'Leave' || shift === 'Resign') return 'cell-leave';

  const period = getShiftPeriod(shift);
  if (period === 'morning')   return 'cell-morning';
  if (period === 'afternoon') return 'cell-afternoon';
  return 'cell-evening';
}

function getShiftDisplay(shift) {
  if (shift === 'OFF')    return 'OFF';
  if (shift === 'Leave')  return 'LV';
  if (shift === 'Resign') return 'RS';

  // Show hour portion only (e.g. "08:00" → "08")
  if (/^\d{2}:\d{2}$/.test(shift)) return shift.slice(0, 2);
  return shift;
}

// ─── Export ───
async function exportSchedule() {
  try {
    const res = await fetch(`${API_BASE}/api/export`);
    if (!res.ok) throw new Error('Export failed');
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url; a.download = 'WFM_Generated_Schedule.xlsx';
    document.body.appendChild(a); a.click();
    document.body.removeChild(a); URL.revokeObjectURL(url);
    showToast('Schedule exported!', 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}
window.exportSchedule = exportSchedule;

// ─── Reset / Start Over ───
function resetApp() {
  // Hide result sections
  dataSummary.style.display     = 'none';
  forecastSection.style.display = 'none';
  forecastSummary.style.display = 'none';
  generateSection.style.display = 'none';
  resultsSection.style.display  = 'none';

  // Re-enable upload zones
  uploadZone.style.borderColor = '';
  forecastUploadZone.style.borderColor = '';

  // Reset upload zone appearance
  const uploadIcon    = uploadZone.querySelector('.upload-icon');
  const uploadText    = uploadZone.querySelector('.upload-text');
  const uploadSubtext = uploadZone.querySelector('.upload-subtext');
  if (uploadIcon) uploadIcon.innerHTML = `
    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
      <polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/>
      <polyline points="9 15 12 12 15 15"/>
    </svg>`;
  if (uploadText)    uploadText.textContent    = 'Drag & drop your Excel file here';
  if (uploadSubtext) uploadSubtext.textContent = 'or click to browse • .xlsx format';

  // Reset forecast upload zone
  const fIcon    = forecastUploadZone.querySelector('.upload-icon');
  const fText    = forecastUploadZone.querySelector('.upload-text');
  const fSubtext = forecastUploadZone.querySelector('.upload-subtext');
  if (fIcon) fIcon.innerHTML = `
    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M3 3v18h18"/><path d="M18 9l-5 5-2-2-4 4"/><circle cx="18" cy="9" r="1"/>
    </svg>`;
  if (fText)    fText.textContent    = 'Drop your Simulation Schedule file here';
  if (fSubtext) fSubtext.textContent = 'or click to browse • .xlsx format';

  // Reset buttons & state
  exportBtn.disabled       = true;
  generateBtn.disabled     = false;
  resetBtn.style.display   = 'none';
  currentShiftCodes        = {};
  fileInput.value          = '';
  forecastFileInput.value  = '';

  uploadSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  showToast('Ready for a new session', 'success');
}
window.resetApp = resetApp;

// ─── Utilities ───
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

function showToast(message, type = 'error') {
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
