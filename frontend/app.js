/**
 * WFM Schedule Generator — Frontend Application (Form-based, no file upload)
 */

const API_BASE = window.location.port === '3000' ? 'http://localhost:8000' : '';

// ─── Shift definitions ───
const DEFAULT_SHIFTS = [
  { code: 'P1',  time: '06:00-15:00', period: 'morning' },
  { code: 'P2',  time: '07:00-16:00', period: 'morning' },
  { code: 'P3',  time: '08:00-17:00', period: 'morning' },
  { code: 'P4',  time: '09:00-18:00', period: 'morning' },
  { code: 'P10', time: '10:00-19:00', period: 'morning' },
  { code: 'S1',  time: '11:00-20:00', period: 'afternoon' },
  { code: 'S2',  time: '12:00-21:00', period: 'afternoon' },
  { code: 'S3',  time: '12:30-21:30', period: 'afternoon' },
  { code: 'S4',  time: '13:00-22:00', period: 'afternoon' },
  { code: 'S5',  time: '16:00-01:00', period: 'afternoon' },
  { code: 'S6',  time: '14:00-23:00', period: 'afternoon' },
  { code: 'S7',  time: '15:00-00:00', period: 'afternoon' },
  { code: 'M3',  time: '21:00-06:00', period: 'night' },
  { code: 'M1',  time: '22:00-07:00', period: 'night' },
];

// ─── Dropdown options ───
const SKILL_OPTIONS    = ['Bahasa', 'English'];
const CHANNEL_OPTIONS  = ['Social Media', 'Call', 'Email', 'Chat'];
const SITE_OPTIONS     = ['Jakarta', 'Semarang', 'Surabaya', 'Bandung', 'Yogyakarta'];
const GENDER_OPTIONS   = [{ value: 'P', label: 'P (Perempuan)' }, { value: 'L', label: 'L (Laki-laki)' }];
const RELIGION_OPTIONS = ['Islam', 'Kristen', 'Hindu', 'Buddha', 'Katolik'];

// ─── App State ───
let state = {
  agents: [],
  dates: [],
  results: null,
  solveTimerInterval: null,
  currentShiftCodes: {},
};

// ─── DOM References ───
const agentSetupSection   = document.getElementById('agentSetupSection');
const demandSetupSection  = document.getElementById('demandSetupSection');
const solverProgressOverlay = document.getElementById('solverProgressOverlay');
const resultsSection      = document.getElementById('resultsSection');
const agentsTableBody     = document.getElementById('agentsTableBody');
const agentCountBadge     = document.getElementById('agentCountBadge');
const exportBtn           = document.getElementById('exportBtn');
const resetBtn            = document.getElementById('resetBtn');
const startDateInput      = document.getElementById('startDateInput');
const numDaysSelect       = document.getElementById('numDaysSelect');
const demandGrid          = document.getElementById('demandGrid');
const solverStats         = document.getElementById('solverStats');
const resultsTable        = document.getElementById('resultsTable');
const solverProgressText  = document.getElementById('solverProgressText');
const regulationsInput    = document.getElementById('regulationsInput');

// ─── Initialise ───
(function init() {
  // Default start date = today
  const today = new Date();
  startDateInput.value = formatDateISO(today);

  // Add 3 sample rows
  addAgentRow({ nip: 'EMP001', name: 'Siti Rahayu',   skill: 'Bahasa',  channel: 'Call',         site: 'Jakarta',   gender: 'P', religion: 'Islam' });
  addAgentRow({ nip: 'EMP002', name: 'Budi Santoso',  skill: 'English', channel: 'Chat',         site: 'Semarang',  gender: 'L', religion: 'Islam' });
  addAgentRow({ nip: 'EMP003', name: 'Dewi Lestari',  skill: 'Bahasa',  channel: 'Social Media', site: 'Surabaya',  gender: 'P', religion: 'Kristen' });

  buildDemandGrid();
  initImportDropzone();
})();

// ─── Bulk Import ───

function initImportDropzone() {
  const zone = document.getElementById('importDropzone');
  if (!zone) return;

  zone.addEventListener('dragenter', e => { e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragover',  e => { e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragleave', e => {
    if (!zone.contains(e.relatedTarget)) zone.classList.remove('drag-over');
  });
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) handleAgentFile(file);
  });

  // Clicking the zone also opens the file picker
  zone.addEventListener('click', e => {
    if (e.target.closest('.import-dropzone-loading')) return;
    document.getElementById('agentFileInput').click();
  });
}

function handleAgentFileSelect(event) {
  const file = event.target.files[0];
  if (file) handleAgentFile(file);
  // Reset so the same file can be re-selected
  event.target.value = '';
}
window.handleAgentFileSelect = handleAgentFileSelect;

async function handleAgentFile(file) {
  if (!file.name.match(/\.(xlsx|xls)$/i)) {
    showToast('Please select an Excel file (.xlsx or .xls)', 'error');
    return;
  }

  const zone    = document.getElementById('importDropzone');
  const loading = document.getElementById('importLoading');
  const loadTxt = document.getElementById('importLoadingText');

  zone.classList.add('loading');
  if (loading) loading.style.display = 'flex';
  if (loadTxt) loadTxt.textContent = `Parsing "${file.name}"…`;

  try {
    const formData = new FormData();
    formData.append('file', file);

    const res = await fetch(`${API_BASE}/api/parse-agents`, {
      method: 'POST',
      body: formData,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Parse failed' }));
      throw new Error(err.detail || 'Parse failed');
    }

    const { agents, count } = await res.json();
    importAgents(agents);
    showToast(`Imported ${count} agent${count !== 1 ? 's' : ''} from "${file.name}"`, 'success');

  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    zone.classList.remove('loading', 'drag-over');
    if (loading) loading.style.display = 'none';
  }
}

function importAgents(agents) {
  // Clear existing rows
  agentsTableBody.innerHTML = '';
  // Add a row for each imported agent
  for (const agent of agents) {
    addAgentRow(agent);
  }
}

async function downloadAgentTemplate() {
  try {
    const res = await fetch(`${API_BASE}/api/download-agent-template`);
    if (!res.ok) throw new Error('Download failed');
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = 'Agent_List_Template.xlsx';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('Template downloaded!', 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}
window.downloadAgentTemplate = downloadAgentTemplate;

// ─── Agent Table ───

function buildSelect(options, selectedValue, name) {
  const opts = options.map(o => {
    const val   = typeof o === 'object' ? o.value : o;
    const label = typeof o === 'object' ? o.label : o;
    const sel   = val === selectedValue ? ' selected' : '';
    return `<option value="${escapeHtml(val)}"${sel}>${escapeHtml(label)}</option>`;
  });
  return `<select name="${name}">${opts.join('')}</select>`;
}

function addAgentRow(defaults = {}) {
  const tbody = agentsTableBody;
  const rowNum = tbody.rows.length + 1;

  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td class="col-no">${rowNum}</td>
    <td><input type="text" name="nip"      value="${escapeHtml(defaults.nip      || '')}" placeholder="NIP"></td>
    <td><input type="text" name="name"     value="${escapeHtml(defaults.name     || '')}" placeholder="Full Name"></td>
    <td>${buildSelect(SKILL_OPTIONS,    defaults.skill    || SKILL_OPTIONS[0],    'skill')}</td>
    <td>${buildSelect(CHANNEL_OPTIONS,  defaults.channel  || CHANNEL_OPTIONS[0],  'channel')}</td>
    <td>${buildSelect(SITE_OPTIONS,     defaults.site     || SITE_OPTIONS[0],     'site')}</td>
    <td>${buildSelect(GENDER_OPTIONS,   defaults.gender   || GENDER_OPTIONS[0].value, 'gender')}</td>
    <td>${buildSelect(RELIGION_OPTIONS, defaults.religion || RELIGION_OPTIONS[0], 'religion')}</td>
    <td><button class="btn-delete-row" onclick="deleteAgentRow(this)" title="Remove agent">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
        <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
      </svg>
    </button></td>
  `;
  tbody.appendChild(tr);
  updateAgentCount();
}

function deleteAgentRow(btn) {
  btn.closest('tr').remove();
  // Re-number rows
  Array.from(agentsTableBody.rows).forEach((row, i) => {
    const noCell = row.querySelector('.col-no');
    if (noCell) noCell.textContent = i + 1;
  });
  updateAgentCount();
}

function updateAgentCount() {
  const n = agentsTableBody.rows.length;
  agentCountBadge.textContent = `${n} agent${n !== 1 ? 's' : ''}`;
}

function getAgentsData() {
  return Array.from(agentsTableBody.rows).map((row, i) => ({
    id:       row.querySelector('[name=nip]').value.trim()  || `EMP${String(i + 1).padStart(3, '0')}`,
    name:     row.querySelector('[name=name]').value.trim() || `Agent ${i + 1}`,
    skill:    row.querySelector('[name=skill]').value,
    channel:  row.querySelector('[name=channel]').value,
    site:     row.querySelector('[name=site]').value,
    gender:   row.querySelector('[name=gender]').value,
    religion: row.querySelector('[name=religion]').value,
  }));
}

// ─── Step Navigation ───

function proceedToStep2() {
  if (agentsTableBody.rows.length === 0) {
    showToast('Please add at least one agent before continuing.', 'error');
    return;
  }
  agentSetupSection.style.display = 'none';
  demandSetupSection.style.display = 'block';
  resetBtn.style.display = 'inline-flex';
  demandSetupSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function backToStep1() {
  demandSetupSection.style.display = 'none';
  agentSetupSection.style.display = 'block';
  agentSetupSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ─── Demand Grid ───

function getScheduleDates() {
  const start   = new Date(startDateInput.value + 'T00:00:00');
  const numDays = parseInt(numDaysSelect.value);
  const dates   = [];
  for (let i = 0; i < numDays; i++) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    dates.push(formatDateISO(d));
  }
  return dates;
}

function buildDemandGrid() {
  const dates   = getScheduleDates();
  const numDays = dates.length;
  const DAY_NAMES = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];

  // Preserve existing values before rebuild
  const oldValues = getDemandData();

  let html = '<thead><tr>';
  html += '<th class="shift-label-th">Shift</th>';
  html += '<th class="shift-time-th">Time</th>';
  for (let i = 0; i < numDays; i++) {
    const d   = new Date(dates[i] + 'T00:00:00');
    const dow = DAY_NAMES[d.getDay()];
    const dom = d.getDate();
    html += `<th class="demand-day-th">${dow}<br><span class="day-num">${dom}</span></th>`;
  }
  html += '</tr></thead><tbody>';

  for (const shift of DEFAULT_SHIFTS) {
    const rowClass = `demand-row-${shift.period}`;
    html += `<tr class="${rowClass}" data-shift="${escapeHtml(shift.code)}">`;
    html += `<td class="shift-label"><span class="shift-code-badge shift-${shift.period}">${escapeHtml(shift.code)}</span></td>`;
    html += `<td class="shift-time">${escapeHtml(shift.time)}</td>`;
    for (let i = 0; i < numDays; i++) {
      const oldVal = oldValues[shift.code] ? (oldValues[shift.code][i] || 0) : 0;
      html += `<td><input type="number" class="demand-input" min="0" max="999" value="${oldVal}" data-shift="${escapeHtml(shift.code)}" data-day="${i}"></td>`;
    }
    html += '</tr>';
  }

  // Total row
  html += '<tr class="demand-total-row"><td class="shift-label" colspan="2">Total / Day</td>';
  for (let i = 0; i < numDays; i++) {
    html += `<td class="demand-total-cell" id="demandTotal_${i}">0</td>`;
  }
  html += '</tr></tbody>';

  demandGrid.innerHTML = html;

  // Wire up live totals
  demandGrid.querySelectorAll('.demand-input').forEach(input => {
    input.addEventListener('input', recalcDemandTotals);
  });
  recalcDemandTotals();
}

function recalcDemandTotals() {
  const numDays = parseInt(numDaysSelect.value);
  for (let i = 0; i < numDays; i++) {
    let total = 0;
    demandGrid.querySelectorAll(`input[data-day="${i}"]`).forEach(inp => {
      total += parseInt(inp.value) || 0;
    });
    const cell = document.getElementById(`demandTotal_${i}`);
    if (cell) cell.textContent = total;
  }
}

function getDemandData() {
  const data = {};
  demandGrid.querySelectorAll('.demand-input').forEach(inp => {
    const code = inp.dataset.shift;
    const day  = parseInt(inp.dataset.day);
    if (!data[code]) data[code] = [];
    data[code][day] = parseInt(inp.value) || 0;
  });
  return data;
}

// ─── Generate Schedule ───

async function generateSchedule() {
  const agents    = getAgentsData();
  const dates     = getScheduleDates();
  const demands   = getDemandData();
  const regsRaw   = regulationsInput ? regulationsInput.value.trim() : '';
  const regs      = regsRaw ? regsRaw.split('\n').map(r => r.trim()).filter(Boolean) : [];

  const shiftCodes = DEFAULT_SHIFTS.map(s => ({ code: s.code, time: s.time }));

  const setupPayload = {
    agents,
    shift_codes:  shiftCodes,
    start_date:   startDateInput.value,
    num_days:     dates.length,
    demands,
    regulations:  regs,

  };

  // Show overlay
  solverProgressOverlay.style.display = 'block';
  solverProgressText.textContent = 'CP-SAT solver is finding the optimal schedule';

  let elapsed = 0;
  state.solveTimerInterval = setInterval(() => {
    elapsed++;
    solverProgressText.textContent = `Running… ${elapsed}s`;
  }, 1000);

  try {
    // Step 1: setup
    const setupRes = await fetch(`${API_BASE}/api/setup`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(setupPayload),
    });
    if (!setupRes.ok) {
      const err = await setupRes.json().catch(() => ({ detail: 'Setup failed' }));
      throw new Error(err.detail || 'Setup failed');
    }

    // Step 2: generate
    const genRes = await fetch(`${API_BASE}/api/generate?time_limit=60`, { method: 'POST' });
    if (!genRes.ok) {
      const err = await genRes.json().catch(() => ({ detail: 'Generation failed' }));
      throw new Error(err.detail || 'Generation failed');
    }

    const results = await genRes.json();

    clearInterval(state.solveTimerInterval);
    solverProgressOverlay.style.display = 'none';

    state.currentShiftCodes = shiftCodes;
    state.results = results;

    renderResults(results);
    showToast('Schedule generated successfully!', 'success');

  } catch (err) {
    clearInterval(state.solveTimerInterval);
    solverProgressOverlay.style.display = 'none';
    showToast(err.message, 'error');
  }
}
window.generateSchedule = generateSchedule;

// ─── Results Rendering ───

function renderResults(results) {
  demandSetupSection.style.display = 'none';
  resultsSection.style.display     = 'block';
  exportBtn.disabled = false;

  renderSolverStats(results);
  renderScheduleGrid(results);

  resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderSolverStats(results) {
  const statusClass = results.solve_status === 'OPTIMAL' ? 'optimal' : 'feasible';
  const shiftCount  = Object.keys(state.currentShiftCodes).filter(k => !['OFF', 'Leave', 'Resign'].includes(k)).length;
  solverStats.innerHTML = `
    <div class="solver-stat">
      <span class="label">Status</span>
      <span class="value ${statusClass}">${escapeHtml(results.solve_status || 'N/A')}</span>
    </div>
    <div class="solver-stat">
      <span class="label">Solve Time</span>
      <span class="value">${results.solve_time != null ? results.solve_time + 's' : '—'}</span>
    </div>
    <div class="solver-stat">
      <span class="label">Agents</span>
      <span class="value">${results.agents ? results.agents.length : '—'}</span>
    </div>
    <div class="solver-stat">
      <span class="label">Days</span>
      <span class="value">${results.dates ? results.dates.length : '—'}</span>
    </div>
    <div class="solver-stat">
      <span class="label">Shift Codes</span>
      <span class="value">${shiftCount}</span>
    </div>
  `;
}

function renderScheduleGrid(results) {
  const { agents, dates, coverage, shift_demand } = results;
  if (!agents || !dates) return;

  const DAY_NAMES = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];

  // ── Header row ──
  let thead = `<thead><tr>
    <th class="col-sticky col-no">No</th>
    <th class="col-sticky col-name">Name</th>
    <th class="col-sticky col-skill">Skill</th>
    <th class="col-sticky col-channel">Channel</th>
    <th class="col-sticky col-site">Site</th>
    <th class="col-sticky col-gender">Gender</th>`;

  for (const date of dates) {
    const d   = new Date(date + 'T00:00:00');
    const dow = DAY_NAMES[d.getDay()];
    const dom = d.getDate();
    thead += `<th class="col-day">${dow}<br><span class="day-num">${dom}</span></th>`;
  }
  thead += '</tr></thead>';

  // ── Agent rows ──
  let tbody = '<tbody>';
  for (let i = 0; i < agents.length; i++) {
    const agent = agents[i];
    tbody += `<tr>
      <td class="col-sticky col-no">${i + 1}</td>
      <td class="col-sticky col-name">${escapeHtml(agent.name || '')}</td>
      <td class="col-sticky col-skill">${escapeHtml(agent.skill || '')}</td>
      <td class="col-sticky col-channel">${escapeHtml(agent.channel || '')}</td>
      <td class="col-sticky col-site">${escapeHtml(agent.site || '')}</td>
      <td class="col-sticky col-gender">${escapeHtml(agent.gender || '')}</td>`;

    for (const date of dates) {
      const shift = (agent.schedule && agent.schedule[date]) ? agent.schedule[date] : 'OFF';
      tbody += `<td class="${getShiftCellClass(shift)}">${escapeHtml(getShiftDisplay(shift))}</td>`;
    }
    tbody += '</tr>';
  }

  // ── Summary rows ──
  const summaryRows = [
    { id: 'demand',    label: 'Demand',    cls: 'summary-demand' },
    { id: 'scheduled', label: 'Scheduled', cls: 'summary-scheduled' },
    { id: 'gap',       label: 'GAP',       cls: 'summary-gap' },
    { id: 'off',       label: 'Off',       cls: 'summary-off' },
  ];

  for (const row of summaryRows) {
    tbody += `<tr class="summary-row">
      <td class="col-sticky col-no summary-row-label" colspan="6">${escapeHtml(row.label)}</td>`;
    for (const date of dates) {
      const cov = (coverage && coverage[date]) ? coverage[date] : {};
      let val = '—';
      let extraCls = row.cls;

      if (row.id === 'demand') {
        // Sum all shift demands for this date index
        const dayIdx = dates.indexOf(date);
        let total = 0;
        if (shift_demand) {
          for (const arr of Object.values(shift_demand)) {
            if (Array.isArray(arr) && arr[dayIdx] != null) total += arr[dayIdx];
          }
        } else if (cov.demand_total != null) {
          total = cov.demand_total;
        }
        val = total;
      } else if (row.id === 'scheduled') {
        val = cov.total_working != null ? cov.total_working : '—';
      } else if (row.id === 'gap') {
        const g = cov.gap;
        val = g != null ? g : '—';
        if (typeof g === 'number' && g < 0) extraCls += ' cell-gap-neg';
      } else if (row.id === 'off') {
        val = cov.off_count != null ? cov.off_count : '—';
      }

      tbody += `<td class="${extraCls}">${val}</td>`;
    }
    tbody += '</tr>';
  }

  tbody += '</tbody>';

  resultsTable.innerHTML = thead + tbody;
}

// ─── Shift helpers ───

function getShiftCellClass(shift) {
  if (!shift || shift === 'OFF')                    return 'cell-off';
  if (shift === 'Leave' || shift === 'LV')          return 'cell-leave';
  if (shift === 'Resign' || shift === 'RS')         return 'cell-leave';

  const info = state.currentShiftCodes[shift];
  const period = info ? info.period : inferPeriodFromCode(shift);
  if (period === 'morning')   return 'cell-morning';
  if (period === 'afternoon') return 'cell-afternoon';
  if (period === 'night')     return 'cell-evening';
  return 'cell-morning';
}

function inferPeriodFromCode(code) {
  const found = DEFAULT_SHIFTS.find(s => s.code === code);
  return found ? found.period : 'morning';
}

function getShiftDisplay(shift) {
  if (!shift || shift === 'OFF')           return 'OFF';
  if (shift === 'Leave' || shift === 'LV') return 'LV';
  if (shift === 'Resign' || shift === 'RS')return 'RS';
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

// ─── Reset / Start Over ───
function resetApp() {
  // Clear results
  state.results           = null;
  state.currentShiftCodes = {};
  exportBtn.disabled      = true;
  resetBtn.style.display  = 'none';

  // Clear agent table
  agentsTableBody.innerHTML = '';
  updateAgentCount();

  // Hide all steps except Step 1
  demandSetupSection.style.display    = 'none';
  solverProgressOverlay.style.display = 'none';
  resultsSection.style.display        = 'none';
  agentSetupSection.style.display     = 'block';

  // Reset demand grid date
  startDateInput.value = formatDateISO(new Date());
  numDaysSelect.value  = '14';

  // Re-add sample agents
  addAgentRow({ nip: 'EMP001', name: 'Siti Rahayu',  skill: 'Bahasa',  channel: 'Call',         site: 'Jakarta',  gender: 'P', religion: 'Islam' });
  addAgentRow({ nip: 'EMP002', name: 'Budi Santoso', skill: 'English', channel: 'Chat',         site: 'Semarang', gender: 'L', religion: 'Islam' });
  addAgentRow({ nip: 'EMP003', name: 'Dewi Lestari', skill: 'Bahasa',  channel: 'Social Media', site: 'Surabaya', gender: 'P', religion: 'Kristen' });

  buildDemandGrid();

  agentSetupSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  showToast('Ready for a new session', 'success');
}
window.resetApp = resetApp;

// ─── Utilities ───

function formatDateISO(date) {
  const y  = date.getFullYear();
  const m  = String(date.getMonth() + 1).padStart(2, '0');
  const d  = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = String(text);
  return div.innerHTML;
}

function showToast(message, type = 'error') {
  document.querySelectorAll('.toast').forEach(t => t.remove());
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity   = '0';
    toast.style.transform = 'translateY(20px)';
    toast.style.transition = '0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}
