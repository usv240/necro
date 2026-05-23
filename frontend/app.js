/* ── NECRO — The Code Necromancer — Frontend App ─────────────────────────── */
'use strict';

// ── URL hash routing ────────────────────────────────────────────────────────
const TABS = ['graveyard', 'timeline', 'watchlist', 'auditlog'];

function activateTab(name) {
  if (!TABS.includes(name)) name = 'graveyard';
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === `tab-${name}`));
  if (name === 'timeline') renderCharts();
  if (name === 'watchlist') loadWatchList();
  if (name === 'auditlog') loadAuditLog();
}

window.addEventListener('hashchange', () => activateTab(location.hash.slice(1)));
window.addEventListener('load', () => {
  activateTab(location.hash.slice(1) || 'graveyard');
  checkHealth();
  // Auto-load demo on first visit
  if (!sessionStorage.getItem('necro-loaded')) {
    sessionStorage.setItem('necro-loaded', '1');
    setTimeout(() => loadDemo('gitlab-foss'), 600);
  }
});

document.querySelectorAll('.nav-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    location.hash = tab.dataset.tab;
  });
});

// ── Theme toggle ────────────────────────────────────────────────────────────
const themeBtn = document.getElementById('themeToggle');
themeBtn.addEventListener('click', () => {
  const current = document.documentElement.getAttribute('data-theme') || 'dark';
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('necro-theme', next);
  themeBtn.textContent = next === 'dark' ? '🌙' : '☀️';
});
// Restore icon
(function() {
  const t = localStorage.getItem('necro-theme') || 'dark';
  themeBtn.textContent = t === 'dark' ? '🌙' : '☀️';
})();

// ── Health check ────────────────────────────────────────────────────────────
async function checkHealth() {
  const dot = document.getElementById('healthDot');
  try {
    const r = await fetch('/api/health', { signal: AbortSignal.timeout(4000) });
    const h = await r.json();
    if (h.status === 'ok') {
      dot.className = 'health-dot ok';
      dot.title = `MongoDB: ${h.mongodb} · MCP: ${h.gitlab_mcp} · Agent: ${h.adk_agent}`;
    } else {
      dot.className = 'health-dot warn';
    }
    document.getElementById('offlineBanner').classList.remove('visible');
  } catch (e) {
    dot.className = 'health-dot error';
    dot.title = 'Backend unreachable';
    document.getElementById('offlineBanner').classList.add('visible');
  }
}

// ── State ────────────────────────────────────────────────────────────────────
let currentFeatures = [];
let currentFilter = 'all';

// ── Scan ────────────────────────────────────────────────────────────────────
function setRepoUrl(url) {
  document.getElementById('repoUrl').value = url;
  document.getElementById('repoUrl').focus();
}

async function startScan() {
  const url = document.getElementById('repoUrl').value.trim();
  if (!url) { toast('Enter a GitLab repository URL', 'error'); return; }

  const maxCommits = parseInt(document.getElementById('maxCommits').value) || 300;
  const lookbackMonths = parseInt(document.getElementById('lookbackMonths').value) || 24;

  const btn = document.getElementById('scanBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Scanning...';

  const terminal = showTerminal();
  clearResults();

  try {
    const resp = await fetch('/api/scan/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo_url: url, max_commits: maxCommits, lookback_months: lookbackMonths }),
    });

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() || '';
      for (const line of lines) {
        if (!line.startsWith('data:')) continue;
        try {
          const evt = JSON.parse(line.slice(5).trim());
          if (evt.type === 'progress') addTerminalLine(terminal, evt.message);
          if (evt.type === 'report') renderReport(evt.data);
        } catch (_) {}
      }
    }
  } catch (e) {
    addTerminalLine(terminal, `ERROR: ${e.message}`, 'error');
    toast('Scan failed — check console', 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '⚡ Scan Repo';
  }
}

// ── Demo load ────────────────────────────────────────────────────────────────
async function loadDemo(which) {
  const terminal = showTerminal();
  clearResults();

  if (which === 'gitlab-foss') {
    document.getElementById('repoUrl').value = 'https://gitlab.com/gitlab-org/gitlab-foss';
    await startScan();
    return;
  }

  if (which === 'inkscape') {
    document.getElementById('repoUrl').value = 'https://gitlab.com/inkscape/inkscape';
    await startScan();
    return;
  }

  toast('Unknown demo', 'error');
}

// ── Terminal helpers ─────────────────────────────────────────────────────────
function showTerminal() {
  const t = document.getElementById('terminal');
  t.innerHTML = '';
  t.classList.add('visible');
  return t;
}

function addTerminalLine(terminal, msg, cls) {
  if (!cls) {
    if (msg.startsWith('[MCP]')) cls = 'mcp';
    else if (msg.startsWith('Gemini') || msg.startsWith('[ADK]') || msg.startsWith('Google Cloud Agent Builder')) cls = 'gemini';
    else if (msg.startsWith('REVIVE') || msg.startsWith('REVIVE NOW')) cls = 'revive';
    else if (msg.startsWith('INVESTIGATE')) cls = 'investigate';
    else if (msg.startsWith('KEEP BURIED')) cls = 'buried';
    else if (msg.startsWith('ERROR')) cls = 'error';
    else if (msg.startsWith('SCAN COMPLETE') || msg.startsWith('[OK]')) cls = 'done';
    else if (msg.startsWith('Competitive') || msg.startsWith('competitive')) cls = 'mcp';
    else cls = '';
  }
  const line = document.createElement('div');
  line.className = `terminal-line ${cls}`;
  line.textContent = `> ${msg}`;
  terminal.appendChild(line);
  terminal.scrollTop = terminal.scrollHeight;
}

// ── Render report ────────────────────────────────────────────────────────────
function clearResults() {
  document.getElementById('summaryBar').style.display = 'none';
  document.getElementById('filterBar').style.display = 'none';
  document.getElementById('graveyardGrid').innerHTML = '';
  currentFeatures = [];
}

function renderReport(data) {
  const features = data.features || [];
  currentFeatures = features;

  // Stats
  const reviveCt = features.filter(f => _rec(f) === 'revive_now').length;
  const investigateCt = features.filter(f => _rec(f) === 'investigate_further').length;
  const buriedCt = features.filter(f => _rec(f) === 'keep_buried').length;

  document.getElementById('statRepo').textContent = data.project_path || '—';
  document.getElementById('statCommits').textContent = (data.total_commits_scanned || 0).toLocaleString();
  document.getElementById('statRevive').textContent = reviveCt;
  document.getElementById('statInvestigate').textContent = investigateCt;
  document.getElementById('statBuried').textContent = buriedCt;

  // Source badge + MCP audit badge
  if (data.source) {
    const srcCard = document.getElementById('statSourceCard');
    const srcEl = document.getElementById('statSource');
    srcCard.style.display = '';
    const sourceHtml = data.source === 'mongodb_atlas'
      ? '<span class="source-badge source-mongodb">MongoDB Atlas</span>'
      : '<span class="source-badge source-inline">inline fallback</span>';
    const mcpHtml = data.data_source === 'gitlab_mcp'
      ? ` <span class="source-badge source-mcp" title="GitLab MCP tools: ${(data.mcp_tools_used || []).join(', ')}">GitLab MCP · ${data.mcp_tool_count || (data.mcp_tools_used || []).length} calls</span>`
      : '';
    srcEl.innerHTML = sourceHtml + mcpHtml;
  }

  document.getElementById('summaryBar').style.display = '';
  document.getElementById('filterBar').style.display = '';
  document.getElementById('tabBadgeGraveyard').textContent = features.length;
  if (reviveCt > 0) document.getElementById('tabBadgeGraveyard').classList.add('alert');

  renderCards(features);
}

function renderCards(features) {
  const grid = document.getElementById('graveyardGrid');
  grid.innerHTML = '';
  if (!features.length) {
    grid.innerHTML = '<div class="empty-state"><div class="empty-icon">💀</div><p>No dead features found in the scanned range.</p></div>';
    return;
  }

  // Sort: revive_now first, then investigate, then keep_buried
  const order = { revive_now: 0, investigate_further: 1, keep_buried: 2 };
  const sorted = [...features].sort((a, b) => (order[_rec(a)] ?? 3) - (order[_rec(b)] ?? 3));
  const isDemo = data.source === 'mongodb_atlas';

  for (const feat of sorted) {
    const card = buildFeatureCard(feat, isDemo);
    grid.appendChild(card);
  }

  applyFilter();
}

function buildFeatureCard(feat, isDemo) {
  const rec = _rec(feat);
  const vi = feat.viability || {};
  const dr = feat.death_reason || {};
  const roi = feat.roi || {};
  const ci = feat.competitive_intel || null;
  const featureId = feat.feature_id || feat.id || '';

  const feasibility = vi.revival_feasibility || 0;
  const feasClass = feasibility >= 7 ? '' : feasibility >= 4 ? 'med' : 'low';

  const icons = { revive_now: '💎', investigate_further: '🔍', keep_buried: '⚰' };
  const badgeClass = { revive_now: 'badge-revive', investigate_further: 'badge-investigate', keep_buried: 'badge-buried' };
  const badgeLabel = { revive_now: '🔥 Revive Now', investigate_further: '🔍 Investigate', keep_buried: '⚰ Keep Buried' };

  const ciUrgency = ci ? ci.market_urgency : null;
  const ciComp = ci ? ci.competitors_with_feature : [];

  const card = document.createElement('div');
  card.className = 'feature-card';
  card.dataset.rec = rec;
  card.dataset.featureId = featureId;

  card.innerHTML = `
    <div class="card-header" onclick="toggleCard(this)">
      <div class="tombstone-icon">${icons[rec] || '💀'}</div>
      <div class="card-title-group">
        <div class="card-name">${esc(feat.name || featureId)}</div>
        <div class="card-meta">
          ${feat.kill_date ? `killed ${esc(feat.kill_date)}` : ''}
          ${feat.kill_commit_sha ? ` · <span class="sha" title="Representative commit ref (illustrative for demo data)">${esc(feat.kill_commit_sha.slice(0, 8))}</span>` : ''}
          ${feat.detection_method ? ` · ${esc(feat.detection_method.replace(/_/g,' '))}` : ''}
        </div>
        <div class="card-badges">
          <span class="badge ${badgeClass[rec] || ''}">${badgeLabel[rec] || rec}</span>
          ${dr.category ? `<span class="badge badge-detection">${esc(dr.category.replace(/_/g,' '))}</span>` : ''}
          ${ciComp.length ? `<span class="badge badge-competitive">⚔ ${ciComp.length} competitor${ciComp.length > 1 ? 's' : ''}</span>` : ''}
        </div>
      </div>
      <div class="feasibility-bar">
        <div class="feasibility-track">
          <div class="feasibility-fill ${feasClass}" style="width:${feasibility * 10}%"></div>
        </div>
        <div class="feasibility-label">${feasibility}/10</div>
      </div>
    </div>

    <div class="card-body" id="body-${featureId}">
      ${feat.kill_commit_message ? `
        <div class="section-label">Kill commit</div>
        <div class="kill-commit">
          <span class="sha">${esc((feat.kill_commit_sha || '').slice(0,8))}</span>
          ${feat.kill_commit_sha ? ' · ' : ''}${esc(feat.kill_commit_message)}
        </div>
      ` : ''}

      ${dr.primary_reason ? `
        <div class="section-label">Why it was disabled</div>
        <div class="reason-text">${esc(dr.primary_reason)}</div>
        ${dr.cited_evidence ? `<div class="snippets-list"><li>${esc(dr.cited_evidence)}</li></div>` : ''}
      ` : ''}

      ${vi.what_changed ? `
        <div class="section-label">Why it's revivable now</div>
        <div class="what-changed">${esc(vi.what_changed)}</div>
      ` : ''}

      ${vi.reasoning ? `
        <div class="section-label">Agent reasoning</div>
        <div class="reason-text">${esc(vi.reasoning)}</div>
      ` : ''}

      <div class="section-label">Revival metrics</div>
      <div class="metrics-grid">
        <div class="metric-item">
          <div class="mval" style="color:var(--skull)">${feasibility}/10</div>
          <div class="mlabel">Feasibility</div>
        </div>
        <div class="metric-item">
          <div class="mval" style="color:var(--amber)">${roi.request_count || 0}</div>
          <div class="mlabel">Issue refs${isDemo ? ' (est.)' : ''}</div>
        </div>
        <div class="metric-item">
          <div class="mval" style="font-size:0.85rem;color:var(--text-muted)">${esc(vi.effort_category || '—')}</div>
          <div class="mlabel">Effort</div>
        </div>
      </div>

      ${roi.roi_estimate_label ? `
        <div class="section-label">ROI estimate</div>
        <div class="reason-text">${esc(roi.roi_estimate_label)}</div>
        <div class="reason-text" style="font-size:0.75rem;color:var(--text-muted);margin-top:0.25rem">
          ${esc(roi.caveats || '')}
        </div>
      ` : ''}

      ${ci ? `
        <div class="section-label">Competitive intelligence</div>
        <div class="competitive-box">
          <div class="comp-urgency ${ciUrgency || ''}">
            Market urgency: ${ciUrgency ? ciUrgency.toUpperCase() : 'UNKNOWN'}
          </div>
          ${ciComp.length ? `<div class="comp-competitors">Competitors with this: ${ciComp.join(', ')}</div>` : ''}
          <div class="comp-summary">${esc(ci.summary || '')}</div>
          ${ci.caveat ? `<div style="font-size:0.72rem;color:var(--text-muted);margin-top:0.3rem">${esc(ci.caveat)}</div>` : ''}
        </div>
      ` : ''}

      ${vi.technical_risks && vi.technical_risks.length ? `
        <div class="section-label">Technical risks</div>
        <ul class="risks-list">
          ${vi.technical_risks.map(r => `<li>${esc(r)}</li>`).join('')}
        </ul>
      ` : ''}

      ${feat.challenger ? `
        <div class="section-label">🤖 Challenger Agent — independent verification</div>
        <div class="challenger-box ${feat.challenger.challenger_verdict || ''}">
          <div class="challenger-verdict">
            ${feat.challenger.challenger_verdict === 'confirm' ? '✅ Confirmed — ' : feat.challenger.challenger_verdict === 'downgrade' ? '⚠️ Downgraded — ' : '❌ Rejected — '}
            Challenger score: ${feat.challenger.challenger_score || '?'}/10
            <span class="challenger-source">${feat.challenger.source || ''}</span>
          </div>
          ${feat.challenger.strongest_objection ? `<div class="challenger-text">Key objection: ${esc(feat.challenger.strongest_objection)}</div>` : ''}
          ${feat.challenger.recommended_first_step ? `<div class="challenger-text">First step: ${esc(feat.challenger.recommended_first_step)}</div>` : ''}
          ${feat.challenger.hidden_risks && feat.challenger.hidden_risks.length ? `
            <div class="challenger-risks">Hidden risks: ${feat.challenger.hidden_risks.map(r => esc(r)).join(' · ')}</div>
          ` : ''}
        </div>
      ` : ''}

      ${feat.context_snippets && feat.context_snippets.length ? `
        <div class="section-label">Evidence (cited from repo history)</div>
        <ul class="snippets-list">
          ${feat.context_snippets.slice(0, 3).map(s => `<li>${esc(s)}</li>`).join('')}
        </ul>
      ` : ''}

      <div class="card-actions">
        ${rec !== 'keep_buried' ? `
          <button class="btn btn-primary btn-sm" onclick="createRevivalIssue('${featureId}', this)">
            🚀 Create GitLab Issue
          </button>
        ` : ''}
        ${feat.linked_mr_iid ? `
          <a href="https://gitlab.com/${feat.project_path || ''}/-/merge_requests/${feat.linked_mr_iid}"
             target="_blank" rel="noopener" class="btn btn-sm">
            MR #${feat.linked_mr_iid} ↗
          </a>
        ` : ''}
        ${feat.linked_issue_iids && feat.linked_issue_iids.length ? feat.linked_issue_iids.slice(0,2).map(id =>
          `<a href="https://gitlab.com/${feat.project_path || ''}/-/issues/${id}"
              target="_blank" rel="noopener" class="btn btn-sm">Issue #${id} ↗</a>`
        ).join('') : ''}
      </div>
    </div>
  `;
  return card;
}

function toggleCard(header) {
  const body = header.nextElementSibling;
  body.classList.toggle('expanded');
}

// ── Filter ───────────────────────────────────────────────────────────────────
function setFilter(filter, btn) {
  currentFilter = filter;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  applyFilter();
}

function applyFilter() {
  document.querySelectorAll('.feature-card').forEach(card => {
    const match = currentFilter === 'all' || card.dataset.rec === currentFilter;
    card.classList.toggle('hidden', !match);
  });
}

// ── Create revival issue ─────────────────────────────────────────────────────
async function createRevivalIssue(featureId, btn) {
  const project = currentFeatures.find(f => (f.feature_id || f.id) === featureId);
  const projectPath = project ? (project.project_path || '') : '';

  if (!projectPath) {
    toast('Cannot determine project path for this feature.', 'error');
    return;
  }

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Agent Builder — creating issue...';

  try {
    // Route through ADK Agent (Google Cloud Agent Builder + GitLab MCPToolset)
    const r = await fetch(`/api/agent/revive`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ feature_id: featureId, project_path: projectPath }),
    });
    const d = await r.json();

    if (!r.ok) {
      throw new Error(d.detail || 'Failed to create issue');
    }

    btn.innerHTML = '✅ Issue Created';
    btn.style.background = 'var(--green)';
    btn.style.borderColor = 'var(--green)';

    if (d.issue_url) {
      const link = document.createElement('a');
      link.href = d.issue_url;
      link.target = '_blank';
      link.rel = 'noopener';
      link.className = 'btn btn-sm';
      link.textContent = `View Issue #${d.issue_iid || ''} ↗`;
      btn.insertAdjacentElement('afterend', link);
    }

    const via = d.via === 'adk_mcptoolset_gitlab'
      ? 'GitLab issue created via Google Cloud Agent Builder + MCPToolset'
      : `GitLab issue created: ${d.issue_url || 'done'}`;
    toast(via, 'success');
    // Update badge
    loadAuditLog();

  } catch (e) {
    btn.disabled = false;
    btn.innerHTML = '🚀 Create GitLab Issue';
    toast(`Error: ${e.message}`, 'error');
  }
}

// ── Charts (Timeline tab) ─────────────────────────────────────────────────────
let chartsDrawn = false;
let _charts = {};

function renderCharts() {
  if (!currentFeatures.length) return;
  if (_charts.timeline) { Object.values(_charts).forEach(c => c.destroy()); _charts = {}; chartsDrawn = false; }

  const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
  const gridColor = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.06)';
  const textColor = isDark ? '#888898' : '#6b6b8a';

  // Timeline chart — kills by month
  const monthCounts = {};
  for (const feat of currentFeatures) {
    const m = feat.kill_date ? feat.kill_date.slice(0, 7) : 'unknown';
    monthCounts[m] = (monthCounts[m] || 0) + 1;
  }
  const months = Object.keys(monthCounts).sort();
  const counts = months.map(m => monthCounts[m]);

  _charts.timeline = new Chart(document.getElementById('timelineChart'), {
    type: 'bar',
    data: {
      labels: months,
      datasets: [{ label: 'Features killed', data: counts, backgroundColor: 'rgba(124,58,237,0.6)', borderColor: 'rgba(124,58,237,1)', borderWidth: 1 }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: textColor, maxRotation: 45 }, grid: { color: gridColor } },
        y: { ticks: { color: textColor, stepSize: 1 }, grid: { color: gridColor } },
      }
    }
  });

  // Feasibility distribution
  const bins = [0, 0, 0, 0, 0]; // 0-2, 3-4, 5-6, 7-8, 9-10
  for (const feat of currentFeatures) {
    const f = (feat.viability || {}).revival_feasibility || 0;
    if (f <= 2) bins[0]++;
    else if (f <= 4) bins[1]++;
    else if (f <= 6) bins[2]++;
    else if (f <= 8) bins[3]++;
    else bins[4]++;
  }

  _charts.feasibility = new Chart(document.getElementById('feasibilityChart'), {
    type: 'doughnut',
    data: {
      labels: ['0–2 (Low)', '3–4', '5–6', '7–8', '9–10 (High)'],
      datasets: [{ data: bins, backgroundColor: ['#6b7280','#ef4444','#f59e0b','#3b82f6','#10b981'], borderWidth: 2, borderColor: isDark ? '#12121a' : '#fff' }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: textColor, boxWidth: 12 } } }
    }
  });

  // Kill reason categories
  const catCounts = {};
  for (const feat of currentFeatures) {
    const c = (feat.death_reason || {}).category || 'unknown';
    catCounts[c] = (catCounts[c] || 0) + 1;
  }
  const cats = Object.keys(catCounts);
  const catColors = ['#7c3aed','#ef4444','#f59e0b','#10b981','#3b82f6','#ec4899','#14b8a6'];

  _charts.category = new Chart(document.getElementById('categoryChart'), {
    type: 'bar',
    data: {
      labels: cats.map(c => c.replace(/_/g,' ')),
      datasets: [{ label: 'Features', data: cats.map(c => catCounts[c]), backgroundColor: catColors, borderWidth: 0 }]
    },
    options: {
      indexAxis: 'y',
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: textColor, stepSize: 1 }, grid: { color: gridColor } },
        y: { ticks: { color: textColor } },
      }
    }
  });
}

// ── Watch list ────────────────────────────────────────────────────────────────
async function addWatch() {
  const url = document.getElementById('watchUrl').value.trim();
  const label = document.getElementById('watchLabel').value.trim();
  if (!url) { toast('Enter a GitLab repository URL', 'error'); return; }

  try {
    const r = await fetch('/api/watch/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo_url: url, label }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'Failed');
    toast(`Now watching ${d.project_path}`, 'success');
    document.getElementById('watchUrl').value = '';
    document.getElementById('watchLabel').value = '';
    loadWatchList();
  } catch (e) {
    toast(`Error: ${e.message}`, 'error');
  }
}

async function removeWatch(path) {
  try {
    const r = await fetch(`/api/watch/${encodeURIComponent(path)}`, { method: 'DELETE' });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'Failed');
    toast(`Removed ${path}`, 'info');
    loadWatchList();
  } catch (e) {
    toast(`Error: ${e.message}`, 'error');
  }
}

async function loadWatchList() {
  const grid = document.getElementById('watchGrid');
  try {
    const r = await fetch('/api/watch/list');
    const d = await r.json();
    const repos = d.repos || [];
    document.getElementById('tabBadgeWatch').textContent = repos.length;

    if (!repos.length) {
      grid.innerHTML = '<div class="empty-state"><div class="empty-icon">👁</div><p>No repositories in watch list. Add one above.</p></div>';
      return;
    }

    grid.innerHTML = repos.map(repo => `
      <div class="watch-card">
        <div class="pulse-dot"></div>
        <div>
          <div class="watch-path">${esc(repo.project_path)}</div>
          <div class="watch-meta">
            ${repo.label ? esc(repo.label) + ' · ' : ''}
            Last scanned: ${repo.last_scanned ? new Date(repo.last_scanned).toLocaleDateString() : 'never'}
            ${repo.revive_now_count > 0 ? ` · <span style="color:var(--revive)">${repo.revive_now_count} revival candidates</span>` : ''}
          </div>
        </div>
        <button class="btn btn-sm" onclick="removeWatch('${esc(repo.project_path)}')" style="margin-left:auto;color:var(--red)">Remove</button>
      </div>
    `).join('');
  } catch (e) {
    grid.innerHTML = '<div class="empty-state"><p>Could not load watch list.</p></div>';
  }
}

async function triggerMonitor() {
  toast('Triggering monitor cycle...', 'info');
  try {
    const r = await fetch('/api/monitor/run', { method: 'POST' });
    const d = await r.json();
    toast(`Monitor ran: ${d.checked_repos?.length || 0} repos checked, ${d.new_candidates || 0} new candidates`, 'success');
    loadWatchList();
    updateMonitorStatus();
  } catch (e) {
    toast(`Error: ${e.message}`, 'error');
  }
}

async function updateMonitorStatus() {
  try {
    const r = await fetch('/api/monitor/status');
    const d = await r.json();
    const text = document.getElementById('monitorStatusText');
    const running = d.running ? 'Active' : 'Stopped';
    const lastRun = d.last_run ? ` · Last run: ${new Date(d.last_run).toLocaleTimeString()}` : '';
    text.textContent = `${running} · Every ${d.interval_hours || 24}h${lastRun}`;
  } catch (_) {}
}

// ── Audit log ────────────────────────────────────────────────────────────────
async function loadAuditLog() {
  const area = document.getElementById('auditLogArea');
  try {
    const r = await fetch('/api/report/revival-log');
    const d = await r.json();
    const entries = d.entries || [];
    document.getElementById('tabBadgeLog').textContent = entries.length;

    if (!entries.length) {
      area.innerHTML = '<div class="empty-state"><div class="empty-icon">📋</div><p>No revival issues created yet. Scan a repo and click "Create GitLab Issue" to start.</p></div>';
      return;
    }

    area.innerHTML = `
      <table class="log-table">
        <thead>
          <tr>
            <th>Feature</th>
            <th>Repository</th>
            <th>Issue</th>
            <th>Via</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          ${entries.map(e => `
            <tr>
              <td>${esc(e.feature_name || e.feature_id)}</td>
              <td><code>${esc(e.project_path)}</code></td>
              <td>
                ${e.issue_url ? `<a href="${esc(e.issue_url)}" target="_blank" rel="noopener" class="btn btn-sm">
                  #${e.issue_iid || '?'} ↗</a>` : '—'}
              </td>
              <td><code>${esc(e.via || 'gitlab_mcp')}</code></td>
              <td>${e.created_at ? new Date(e.created_at).toLocaleString() : '—'}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  } catch (e) {
    area.innerHTML = '<div class="empty-state"><p>Could not load revival log.</p></div>';
  }
}

// ── Toast notifications ───────────────────────────────────────────────────────
function toast(msg, type = 'info') {
  const container = document.getElementById('toastContainer');
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.textContent = msg;
  container.appendChild(t);
  setTimeout(() => t.remove(), 4500);
}

// ── Utilities ─────────────────────────────────────────────────────────────────
function _rec(feat) {
  return (feat.viability || {}).recommendation || feat.recommendation || 'keep_buried';
}

function esc(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Keyboard shortcuts ─────────────────────────────────────────────────────────
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    document.querySelectorAll('.card-body.expanded').forEach(b => b.classList.remove('expanded'));
  }
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
    startScan();
  }
});

// ── Periodic health + monitor status refresh ──────────────────────────────────
setInterval(checkHealth, 30000);
setInterval(updateMonitorStatus, 60000);
updateMonitorStatus();
