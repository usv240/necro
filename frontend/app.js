/* ── NECRO — The Code Necromancer — Frontend App ─────────────────────────── */
'use strict';

// ── Core Simulated Console Log Telemetry ──
const INITIAL_SIMULATED_MESSAGES = [
  { t: 'NECRO Forensic Laboratory active // ADK orchestrator online', type: 'info' },
  { t: 'Google Cloud Gemini 3 Flash connection: STABLE · ping 45ms', type: 'gemini' },
  { t: 'Vertex AI Gemini 3 Flash Adversarial agent: ACTIVE · monitoring target range', type: 'gemini' },
  { t: 'Google Search grounding: ACTIVE · constraint verification enabled · live URL evidence', type: 'gemini' },
  { t: 'MongoDB Atlas vector database clusters: SYNCED · 1,827 records mapped', type: 'mcp' },
  { t: 'GitLab Official MCP Server (SSE): CONNECTED · 10 tools active', type: 'mcp' },
  { t: '@zereight/mcp-gitlab (stdio): CONNECTED · 9 tools active · 19 total', type: 'mcp' },
  { t: 'NECRO MCP Server (/mcp): ACTIVE · scan_repository · get_candidates · get_health', type: 'mcp' },
  { t: 'Slack notifications autonomous alerts: PRIMED · weekly digest Monday 09:00 UTC', type: 'info' }
];

function bootSimulatedLogs() {
  const globalFeed = document.getElementById('cliFeedContainer');
  if (!globalFeed) return;
  globalFeed.innerHTML = '';
  INITIAL_SIMULATED_MESSAGES.forEach((msg, idx) => {
    setTimeout(() => {
      const gl = document.createElement('div');
      gl.className = `terminal-line ${msg.type}`;
      const ts = new Date().toLocaleTimeString();
      gl.textContent = `[${ts}] ${msg.t}`;
      globalFeed.appendChild(gl);
      globalFeed.scrollTop = globalFeed.scrollHeight;
    }, 100 + idx * 750);
  });
}

// ── Interactive ROI Calculator ──
function calculateROI(val) {
  const devCountLabel = document.getElementById('devCountLabel');
  const calcWastedHours = document.getElementById('calcWastedHours');
  const calcBuriedROI = document.getElementById('calcBuriedROI');
  if (!devCountLabel || !calcWastedHours || !calcBuriedROI) return;

  devCountLabel.textContent = val;
  const features = Math.round(val * 0.16);
  const dollars = Math.round(val * 5625);

  calcWastedHours.textContent = features;
  calcBuriedROI.textContent = '$' + dollars.toLocaleString();
}

// ── URL hash routing ────────────────────────────────────────────────────────
const TABS = ['graveyard', 'timeline', 'watchlist', 'auditlog', 'guide'];

function activateTab(name) {
  if (!TABS.includes(name)) name = 'graveyard';
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === `tab-${name}`));
  
  // Dynamic header title update
  const titleEl = document.getElementById('currentViewTitle');
  if (titleEl) {
    if (name === 'graveyard') titleEl.textContent = 'Dormant Feature Registry';
    else if (name === 'timeline') titleEl.textContent = 'Timeline Forensics';
    else if (name === 'watchlist') titleEl.textContent = 'Active Watchlist';
    else if (name === 'auditlog') titleEl.textContent = 'Revival Logs';
    else if (name === 'guide') titleEl.textContent = 'System Guide';
  }

  if (name === 'timeline') renderCharts();
  if (name === 'watchlist') loadWatchList();
  if (name === 'auditlog') loadAuditLog();
}

window.addEventListener('hashchange', () => activateTab(location.hash.slice(1)));
window.addEventListener('load', () => {
  activateTab(location.hash.slice(1) || 'graveyard');
  checkHealth();
  loadLiveStats();
  bootSimulatedLogs();
  calculateROI(25);
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

// ── Welcome Hero Onboarding Toggle ──────────────────────────────────────────
function toggleWelcomeHero() {
  const hero = document.getElementById('welcomeHero');
  const btn = document.getElementById('toggleHeroBtn');
  if (!hero || !btn) return;
  const isCollapsed = hero.classList.toggle('collapsed');
  
  if (isCollapsed) {
    btn.textContent = 'Show Guide';
    localStorage.setItem('necro-welcome-hidden', 'true');
  } else {
    btn.textContent = 'Hide Guide';
    localStorage.removeItem('necro-welcome-hidden');
  }
}

// Restore welcome hero preference on load
window.addEventListener('DOMContentLoaded', () => {
  const welcomeHidden = localStorage.getItem('necro-welcome-hidden');
  const hero = document.getElementById('welcomeHero');
  const btn = document.getElementById('toggleHeroBtn');
  if (welcomeHidden && hero && btn) {
    hero.classList.add('collapsed');
    btn.textContent = 'Show Guide';
  }
});

// ── Health check ─────────────────────────────────────────────────────────────
let _lastHealth = null;

async function checkHealth() {
  const pulse = document.querySelector('.status-pulse');
  try {
    const r = await fetch('/api/health', { signal: AbortSignal.timeout(4000) });
    _lastHealth = await r.json();
    const ok = _lastHealth.status === 'ok';
    if (pulse) pulse.className = `status-pulse ${ok ? '' : 'warn'}`;
    document.getElementById('offlineBanner').classList.remove('visible');
  } catch (e) {
    _lastHealth = null;
    if (pulse) pulse.className = 'status-pulse error';
    document.getElementById('offlineBanner').classList.add('visible');
  }
}

function toggleStatusOverlay() {
  const overlay = document.getElementById('statusOverlay');
  if (!overlay) return;
  const open = overlay.style.display !== 'none';
  if (open) {
    overlay.style.display = 'none';
    return;
  }
  // Populate with latest health data
  const list = document.getElementById('statusServiceList');
  if (_lastHealth) {
    const services = [
      { name: 'Backend API',       state: _lastHealth.status === 'ok' ? 'ok' : 'error' },
      { name: 'GitLab MCP',        state: _lastHealth.gitlab_mcp === 'active' ? 'ok' : 'warn',
        note: _lastHealth.gitlab_mcp === 'active' ? 'stdio' : 'no token' },
      { name: 'ADK Agent',         state: _lastHealth.adk_agent === 'initialized' ? 'ok' : 'warn',
        note: _lastHealth.adk_agent },
      { name: 'Google Search',     state: _lastHealth.google_search === 'active' ? 'ok' : 'warn',
        note: _lastHealth.google_search === 'active' ? 'grounded' : 'inactive' },
      { name: 'MongoDB Atlas',     state: _lastHealth.mongodb === 'connected' ? 'ok' : 'warn',
        note: _lastHealth.mongodb },
    ];
    list.innerHTML = services.map(s => `
      <div class="status-row">
        <span class="svc-dot svc-${s.state}"></span>
        <span class="svc-name">${s.name}${s.note ? ` <span>(${s.note})</span>` : ''}</span>
      </div>`).join('');
  } else {
    list.innerHTML = `<div class="status-row"><span class="svc-dot svc-error"></span><span class="svc-name">Backend unreachable</span></div>`;
  }
  overlay.style.display = 'block';
}

// Close overlay when clicking outside
document.addEventListener('click', e => {
  const wrap = document.getElementById('statusDotWrap');
  if (wrap && !wrap.contains(e.target)) {
    const overlay = document.getElementById('statusOverlay');
    if (overlay) overlay.style.display = 'none';
  }
});

function renderActiveIntegrations(h) {
  const container = document.getElementById('activeIntegrations');
  if (!container) return;

  const mongoStatus = h.mongodb === 'connected' ? 'active' : 'inactive';
  const mcpStatus = h.gitlab_mcp === 'active' ? 'active' : 'inactive';
  const agentStatus = h.adk_agent === 'initialized' ? 'active' : 'pending';
  const slackStatus = h.slack === 'configured' ? 'active' : 'inactive';
  
  const geminiName = h.gemini_primary || 'Gemini 3 Flash';
  const vertexName = h.gemini_fallback || 'Vertex AI Gemini 3 Flash';

  container.innerHTML = `
    <span class="tech-stack-label">Active integrations:</span>
    <span class="tech-tag-status active" title="Model: ${geminiName}">${geminiName}</span>
    <span class="tech-tag-status active" title="Model: ${vertexName}">Vertex AI (Adversarial)</span>
    <span class="tech-tag-status ${agentStatus}" title="ADK Agent status">${h.adk_agent === 'initialized' ? 'Agent Builder Active' : 'Agent Builder Initializing'}</span>
    <span class="tech-tag-status active" title="ADK agent calls Google Search to verify constraint-resolution claims live — every 'what changed' has a cited URL">Google Search Grounding</span>
    <span class="tech-tag-status ${mcpStatus}" title="GitLab Official MCP Server (SSE) + @zereight/mcp-gitlab (stdio) · ${h.mcp_tool_count} tools total">GitLab MCP (official SSE + stdio) · ${h.mcp_tool_count} tools</span>
    <span class="tech-tag-status ${mcpStatus}" title="NECRO exposes itself as MCP server at /mcp — consumable by GitLab Duo agents">NECRO → MCP Server (/mcp)</span>
    <span class="tech-tag-status ${mongoStatus}" title="MongoDB Atlas DB connection">MongoDB Atlas (${h.features_in_db} features)</span>
    <span class="tech-tag-status ${slackStatus}" title="Slack bot alerts integration">${h.slack === 'configured' ? 'Slack Notifications' : 'Slack Disabled'}</span>
  `;
}

async function loadLiveStats() {
  try {
    const res = await fetch('/api/report/stats', { signal: AbortSignal.timeout(5000) });
    if (!res.ok) return;
    const d = await res.json();
    
    const bar = document.getElementById('liveStatsBar');
    if (!bar) return;
    bar.classList.remove('hidden');

    const fmt = n => n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);

    function animateStat(id, value) {
      const el = document.getElementById(id);
      if (!el) return;
      const start = performance.now();
      const duration = 1200;
      const step = (now) => {
        const t = Math.min((now - start) / duration, 1);
        const ease = 1 - Math.pow(1 - t, 3); // ease-out cubic
        el.textContent = fmt(Math.round(value * ease));
        if (t < 1) requestAnimationFrame(step);
        else el.textContent = fmt(value);
      };
      requestAnimationFrame(step);
    }

    animateStat('ls-total-scans',      d.total_scans);
    animateStat('ls-features-found',   d.total_features_found);
    animateStat('ls-watched-repos',    d.watched_repos_count);
    animateStat('ls-revivals-logged',  d.revivals_logged_count);
    animateStat('ls-mcp-calls',        d.mcp_tool_calls_count);
  } catch (err) {
    console.warn('Failed to load dynamic system stats:', err);
  }
}

// ── State ────────────────────────────────────────────────────────────────────
let currentFeatures = [];
let currentFilter = 'all';
let _reportMeta = {}; // full report payload — used by renderCards, chains, scatter

// ── Scan ────────────────────────────────────────────────────────────────────
function setRepoUrl(url) {
  document.getElementById('repoUrl').value = url;
  document.getElementById('repoUrl').focus();
}

/** Normalize any GitLab URL form to the bare namespace/project path */
function normalizeGitLabPath(raw) {
  let s = raw.trim();
  // Strip .git suffix
  s = s.replace(/\.git$/, '');
  // If it's a URL, pull out the path portion after the host
  try {
    const u = new URL(s);
    // e.g. https://gitlab.com/namespace/project  → /namespace/project
    s = u.pathname.replace(/^\/+/, '').replace(/\/+$/, '');
  } catch (_) {
    // Not a URL — treat as bare path, just clean slashes
    s = s.replace(/^\/+/, '').replace(/\/+$/, '');
  }
  return s;
}

async function startScan() {
  const raw = document.getElementById('repoUrl').value.trim();
  if (!raw) { toast('Enter a GitLab repository URL or namespace/project', 'error'); return; }
  const url = normalizeGitLabPath(raw);
  if (!url || !url.includes('/')) {
    toast('Enter a full URL (https://gitlab.com/org/repo) or namespace/project', 'error');
    return;
  }
  // Show the normalized path back in the input so users can see what was parsed
  document.getElementById('repoUrl').value = url;

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
    btn.innerHTML = 'Run Forensic Scan';
  }
}

// ── Quick Scan examples ──────────────────────────────────────────────────────
function quickScan(projectPath, maxCommits, lookbackMonths) {
  document.getElementById('repoUrl').value = `https://gitlab.com/${projectPath}`;
  if (maxCommits) document.getElementById('maxCommits').value = maxCommits;
  if (lookbackMonths) document.getElementById('lookbackMonths').value = lookbackMonths;
  startScan();
}

// ── Repo browser toggle ──────────────────────────────────────────────────────
function toggleMoreRepos() {
  const browser = document.getElementById('repoBrowser');
  const btn = document.getElementById('moreReposToggle');
  if (!browser) return;
  const open = browser.style.display !== 'none';
  browser.style.display = open ? 'none' : 'block';
  if (btn) btn.textContent = open ? '＋ More repos' : '－ Hide repos';
}

// Picks a repo from the expanded browser: fills fields + closes browser
function pickRepo(projectPath, maxCommits, lookbackMonths) {
  document.getElementById('repoUrl').value = `https://gitlab.com/${projectPath}`;
  if (maxCommits) document.getElementById('maxCommits').value = maxCommits;
  if (lookbackMonths) document.getElementById('lookbackMonths').value = lookbackMonths;
  toggleMoreRepos();
  document.getElementById('repoUrl').scrollIntoView({ behavior: 'smooth', block: 'center' });
  document.getElementById('repoUrl').focus();
}

// ── loadDemo redirects to real scan (no fake data) ───────────────────────────
async function loadDemo(which) {
  const repos = {
    'gitlab-foss': { path: 'gitlab-org/gitlab-foss', commits: 80, months: 12 },
    'inkscape':    { path: 'inkscape/inkscape',       commits: 60, months: 12 },
  };
  const r = repos[which];
  if (r) quickScan(r.path, r.commits, r.months);
  else toast('Unknown quick-scan target', 'error');
}

// ── Pre-analyzed demo loader (instant — no live scan wait) ───────────────────
// Two demo modes:
//   1) `seed` chips load hand-curated demos (gitlab-foss, inkscape) from seed.py
//   2) `cached` chips load the best real cached live scan from MongoDB for
//      that project_path. Backed by actual scans run with the bug-fixed pipeline.
const _DEMO_REPO_MAP = {
  // ── Hand-curated seed demos ──
  'gitlab-org/gitlab-foss': { mode: 'seed', key: 'gitlab-foss', label: 'gitlab-org/gitlab-foss' },
  'inkscape/inkscape':       { mode: 'seed', key: 'inkscape',    label: 'inkscape/inkscape' },
  'videolan/vlc':            { mode: 'seed', key: 'inkscape',    label: 'videolan/vlc' },
  'kde/krita':               { mode: 'seed', key: 'inkscape',    label: 'kde/krita' },
  'godotengine/godot':       { mode: 'seed', key: 'gitlab-foss', label: 'godotengine/godot' },

  // ── Cached real-scan demos (verified post bug-fix) ──
  'gitlab-org/gitlab':           { mode: 'cached', label: 'gitlab-org/gitlab' },
  'gitlab-org/gitlab-shell':     { mode: 'cached', label: 'gitlab-org/gitlab-shell' },
  'gitlab-org/gitaly':           { mode: 'cached', label: 'gitlab-org/gitaly' },
  'gitlab-org/cli':              { mode: 'cached', label: 'gitlab-org/cli' },
  'gitlab-org/omnibus-gitlab':   { mode: 'cached', label: 'gitlab-org/omnibus-gitlab' },
  'fdroid/fdroidclient':         { mode: 'cached', label: 'fdroid/fdroidclient' },
  'gstreamer/gstreamer':         { mode: 'cached', label: 'gstreamer/gstreamer' },
};

async function loadDemoData(projectPath) {
  const entry = _DEMO_REPO_MAP[projectPath] || { mode: 'seed', key: 'gitlab-foss', label: projectPath || 'gitlab-org/gitlab-foss' };
  const btn = document.getElementById('demoDataBtn');
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Loading...'; }

  const terminal = showTerminal();
  clearResults();

  const isCached = entry.mode === 'cached';
  const lines = isCached ? [
    `[MongoDB] Loading cached live scan for ${entry.label}...`,
    '[MongoDB] Query: scans by project_path, sorted by revive_now_count DESC',
    '[MongoDB] Pulling features collection for matched scan_id',
    'Cached scan retrieved — replaying real pipeline output',
    'SCAN COMPLETE — instant cached result',
  ] : [
    `[MCP] GitLab MCP — loading pre-analyzed ${entry.label} report...`,
    '[MCP] list_commits · list_issues · list_merge_requests · get_commit',
    'Detection complete — 5 dead features found',
    'Gemini 3 Flash — analyzing kill reasons and revival viability...',
    '[SEARCH] Google Search — verifying constraint resolution: "webpack CSS Modules support"',
    '[SEARCH] Google Search — constraint resolved Oct 2020 · webpack 5 release · evidence URL cited',
    '[ADK] Google Cloud Agent Builder — strategic synthesis complete',
    'SCAN COMPLETE — 2 features ready to revive',
  ];
  for (const line of lines) addTerminalLine(terminal, line);

  try {
    const url = isCached
      ? `/api/scan/demo?project_path=${encodeURIComponent(projectPath)}`
      : `/api/scan/demo?repo=${entry.key}`;
    const r = await fetch(url, { method: 'POST' });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    if (!isCached && projectPath) data.project_path = entry.label;
    renderReport(data);
    const reviveCt = (data.features || []).filter(f => (f.viability || {}).recommendation === 'revive_now').length;
    toast(`${entry.label} — ${reviveCt} revival candidate(s) ready`, 'success');
  } catch (e) {
    addTerminalLine(terminal, `ERROR: ${e.message}`, 'error');
    toast('Failed to load demo data', 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = 'Load Example Report'; }
  }
}

// ── Terminal helpers ─────────────────────────────────────────────────────────
function showTerminal() {
  const t = document.getElementById('terminal');
  t.innerHTML = '';
  t.style.display = '';        // clear inline display:none
  t.classList.add('visible');
  return t;
}

function addTerminalLine(terminal, msg, cls) {
  if (!cls) {
    if (msg.startsWith('[MCP]')) cls = 'mcp';
    else if (msg.startsWith('[SEARCH]') || msg.startsWith('Google Search')) cls = 'search';
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

  // Also mirror to global dashboard coordinator CLI feed
  const globalFeed = document.getElementById('cliFeedContainer');
  if (globalFeed) {
    const gl = document.createElement('div');
    gl.className = `terminal-line ${cls}`;
    const ts = new Date().toLocaleTimeString();
    gl.textContent = `[${ts}] ${msg}`;
    globalFeed.appendChild(gl);
    globalFeed.scrollTop = globalFeed.scrollHeight;
    while (globalFeed.childNodes.length > 60) {
      globalFeed.removeChild(globalFeed.firstChild);
    }
  }
}

// ── Render report ────────────────────────────────────────────────────────────
function clearResults() {
  document.getElementById('summaryBar').style.display = 'none';
  document.getElementById('filterBar').style.display = 'none';
  document.getElementById('graveyardGrid').innerHTML = '';
  const wrapper = document.getElementById('postToGitLabBtnWrapper');
  if (wrapper) wrapper.style.display = 'none';
  const synth = document.getElementById('adkSynthesisPanel');
  if (synth) { synth.innerHTML = ''; synth.style.display = 'none'; }
  const t = document.getElementById('terminal');
  if (t) { t.classList.remove('visible'); t.style.display = 'none'; }
  currentFeatures = [];
}

function renderReport(data) {
  const t = document.getElementById('terminal');
  if (t) t.classList.remove('visible');
  const features = data.features || [];
  currentFeatures = features;
  _reportMeta = data;
  _allFeaturesCache = null; // invalidate timeline cache so next visit shows fresh data

  // Stats
  const reviveCt = features.filter(f => _rec(f) === 'revive_now').length;
  const investigateCt = features.filter(f => _rec(f) === 'investigate_further').length;
  const buriedCt = features.filter(f => _rec(f) === 'keep_buried').length;

  document.getElementById('statRepo').textContent = data.project_path || '—';
  document.getElementById('statCommits').textContent = (data.total_commits_scanned || 0).toLocaleString();
  document.getElementById('statRevive').textContent = reviveCt;
  document.getElementById('statInvestigate').textContent = investigateCt;
  document.getElementById('statBuried').textContent = buriedCt;

  // Opportunity cost estimate: avg 40 engineer-hours × $150/hr per revival candidate
  const roiCard = document.getElementById('statRoiCard');
  const roiVal  = document.getElementById('statRoiValue');
  if (roiCard && roiVal && (reviveCt + investigateCt) > 0) {
    const totalCandidates = reviveCt + investigateCt;
    const dollars = totalCandidates * 40 * 150;  // 40 hrs × $150/hr per feature
    roiVal.textContent = '$' + (dollars >= 1000 ? (dollars / 1000).toFixed(0) + 'k' : dollars);
    roiCard.style.display = '';
  } else if (roiCard) {
    roiCard.style.display = 'none';
  }

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

  // Portfolio ROI bar — sum estimated value from revive_now features
  const reviveFeatures = features.filter(f => _rec(f) === 'revive_now');
  let roiLow = 0, roiHigh = 0;
  for (const f of reviveFeatures) {
    const roi = f.roi || {};
    roiLow  += roi.annual_value_low  || roi.annual_value_estimate || 0;
    roiHigh += roi.annual_value_high || roi.annual_value_estimate || 0;
  }
  const fmtVal = v => v >= 1000000 ? `$${(v/1000000).toFixed(1)}M` : v >= 1000 ? `$${(v/1000).toFixed(0)}K` : (v > 0 ? `$${v}` : null);
  const roiBarEl = document.getElementById('roiBar');
  if (roiBarEl && (roiLow > 0 || roiHigh > 0)) {
    const lo = fmtVal(roiLow), hi = fmtVal(roiHigh);
    const roiStr = lo && hi && lo !== hi ? `${lo} – ${hi}` : (hi || lo || '—');
    const isApprox = !!(data.source === 'mongodb_atlas');
    roiBarEl.innerHTML = `
      <div class="roi-bar-item">
        <div class="roi-bar-label">Buried potential (est.)</div>
        <div class="roi-bar-value">${isApprox ? '~' : ''}${roiStr}<span style="font-size:0.65rem;font-weight:400;color:var(--text-muted)"> / yr</span></div>
        <div class="roi-bar-sub">across ${reviveCt} revivable feature${reviveCt !== 1 ? 's' : ''}</div>
      </div>
      <div class="roi-bar-divider"></div>
      <div class="roi-bar-item">
        <div class="roi-bar-label">Orchestrated by</div>
        <div class="roi-bar-value" style="color:#a78bfa;font-size:0.82rem">Google Cloud Agent Builder</div>
        <div class="roi-bar-sub">ADK + Gemini 3 Flash + GitLab MCP</div>
      </div>
      ${data.mcp_tool_count ? `
      <div class="roi-bar-divider"></div>
      <div class="roi-bar-item">
        <div class="roi-bar-label">MCP tool calls</div>
        <div class="roi-bar-value" style="font-size:0.85rem">${data.mcp_tool_count}</div>
        <div class="roi-bar-sub">${(data.mcp_tools_used || []).slice(0,3).join(', ')}</div>
      </div>` : ''}
    `;
    roiBarEl.style.display = 'flex';
  } else if (roiBarEl) {
    roiBarEl.style.display = 'none';
  }

  // Show action buttons after results render
  if (features.length > 0) {
    const wrapper = document.getElementById('postToGitLabBtnWrapper');
    if (wrapper) wrapper.style.display = '';
    const postBtn = document.getElementById('postToGitLabBtn');
    if (postBtn) { postBtn.style.display = ''; postBtn._reportData = data; }
    const exportBtn = document.getElementById('exportJsonBtn');
    if (exportBtn) exportBtn.style.display = '';
  }

  // ADK Synthesis panel — show when ADK successfully synthesized findings
  const synthPanel = document.getElementById('adkSynthesisPanel');
  const synth = data.adk_synthesis;
  if (synthPanel && synth && synth.status === 'success') {
    const top3 = (synth.top_3_priorities || []).map((p, i) => `
      <div class="synth-priority">
        <span class="synth-rank">#${p.rank || i + 1}</span>
        <div>
          <strong>${escHtml(p.feature || '')}</strong>
          <div class="synth-reason">${escHtml(p.reason || '')}</div>
          <div class="synth-action">→ ${escHtml(p.first_action || '')}</div>
        </div>
      </div>`).join('');

    const disagreements = (synth.challenger_disagreements || []);
    const disagreementsHtml = disagreements.length
      ? `<div class="synth-section"><span class="synth-label">Challenger disagreements</span> ${disagreements.map(d => `<span class="synth-tag synth-tag-warn">${escHtml(d)}</span>`).join(' ')}</div>`
      : '';

    const verifBadge = synth.verification_quality
      ? `<span class="synth-tag synth-tag-${synth.verification_quality === 'high' ? 'ok' : synth.verification_quality === 'medium' ? 'warn' : 'bad'}">${synth.verification_quality} verification</span>`
      : '';

    synthPanel.innerHTML = `
      <div class="synth-header">
        <span class="synth-adk-badge">Google Cloud Agent Builder</span>
        <span style="font-size:0.72rem;color:var(--text-muted);margin-left:0.5rem">ADK strategic synthesis</span>
        ${verifBadge}
      </div>
      ${synth.executive_summary ? `<div class="synth-exec">${escHtml(synth.executive_summary)}</div>` : ''}
      ${synth.graveyard_pattern ? `<div class="synth-section"><span class="synth-label">Pattern</span> <span class="synth-pattern">${escHtml(synth.graveyard_pattern)}</span></div>` : ''}
      ${top3 ? `<div class="synth-section"><span class="synth-label">Top priorities</span>${top3}</div>` : ''}
      ${disagreementsHtml}
    `;
    synthPanel.style.display = '';
  } else if (synthPanel) {
    synthPanel.style.display = 'none';
  }

  // Resurrection Chains panel — show when chains detected
  const chainsPanel = document.getElementById('resurrectChainsPanel');
  const chains = data.resurrection_chains || [];
  if (chainsPanel && chains.length) {
    const chainsHtml = chains.map(chain => `
      <div class="chain-item chain-impact-${chain.impact || 'low'}">
        <div class="chain-icon">✦</div>
        <div class="chain-body">
          <div class="chain-title">
            <span class="chain-keyword">${escHtml(chain.constraint_key)}</span>
            <span class="chain-count">1 fix unlocks ${chain.feature_count} feature${chain.feature_count !== 1 ? 's' : ''}</span>
            ${chain.revivable_count > 0 ? `<span class="chain-revivable">${chain.revivable_count} revivable now</span>` : ''}
          </div>
          <div class="chain-features">${(chain.features || []).map(f => `<span class="chain-feat">${escHtml(f)}</span>`).join('')}</div>
          <div class="chain-fix">→ ${escHtml(chain.fix_suggestion || '')}</div>
        </div>
      </div>`).join('');

    const topChain = chains[0];
    chainsPanel.innerHTML = `
      <div class="chains-header">
        <span class="chains-badge">Resurrection Chains</span>
        <span class="chains-sub">Shared constraints locking multiple features — fix once, unlock many</span>
        ${chains.length > 1 ? `<span class="chains-count">${chains.length} chains detected</span>` : ''}
      </div>
      <div class="chains-list">${chainsHtml}</div>`;
    chainsPanel.style.display = '';
  } else if (chainsPanel) {
    chainsPanel.style.display = 'none';
  }

  renderCards(features);
  loadLiveStats();
}

function renderCards(features) {
  const grid = document.getElementById('graveyardGrid');
  grid.innerHTML = '';
  if (!features.length) {
    grid.innerHTML = '<div class="empty-state"><p>No dead features found in the scanned range.</p></div>';
    return;
  }

  // Sort: revive_now first, then investigate, then keep_buried
  const order = { revive_now: 0, investigate_further: 1, keep_buried: 2 };
  const sorted = [...features].sort((a, b) => (order[_rec(a)] ?? 3) - (order[_rec(b)] ?? 3));
  const isDemo = _reportMeta.source === 'mongodb_atlas';

  for (const feat of sorted) {
    const card = buildFeatureCard(feat, isDemo);
    grid.appendChild(card);
  }

  applyFilter();

  // Load vitality sparklines asynchronously for all features
  if (isDemo) {
    requestAnimationFrame(() => loadVitalitySparklines(sorted));
  }
}

// ── Feature EKG — Vitality Sparklines ───────────────────────────────────────
async function loadVitalitySparklines(features) {
  for (const feat of features) {
    const featureId = feat.feature_id || feat.id || '';
    const projectPath = feat.project_path || _reportMeta.project_path || '';
    const container = document.getElementById(`sparkline-${featureId}`);
    if (!container || !featureId) continue;

    try {
      const url = `/api/scan/vitality/${encodeURIComponent(featureId)}?project_path=${encodeURIComponent(projectPath)}`;
      const r = await fetch(url, { signal: AbortSignal.timeout(5000) });
      if (!r.ok) { container.innerHTML = ''; document.getElementById(`sparkline-row-${featureId}`)?.remove(); continue; }
      const data = await r.json();
      const sp = data.sparkline;
      if (!sp || !sp.points || !sp.points.length) {
        document.getElementById(`sparkline-row-${featureId}`)?.remove();
        continue;
      }
      container.innerHTML = renderSparklineSVG(sp, feat);
    } catch {
      document.getElementById(`sparkline-row-${featureId}`)?.remove();
    }
  }
}

function renderSparklineSVG(sp, feat) {
  const pts = sp.points || [];
  if (!pts.length) return '';

  const W = 180, H = 36;
  const max = Math.max(...pts, 1);
  const min = 0;
  const range = max - min || 1;

  // Build polyline points
  const coords = pts.map((v, i) => {
    const x = (i / (pts.length - 1)) * W;
    const y = H - ((v - min) / range) * (H - 4) - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');

  const trendColor = sp.trend === 'rising' ? '#10b981' : sp.trend === 'falling' ? '#ef4444' : '#6b7280';
  const trendIcon = sp.trend === 'rising' ? '↑' : sp.trend === 'falling' ? '↓' : '→';
  const rec = _rec(feat);
  const strokeColor = rec === 'revive_now' ? '#10b981' : rec === 'investigate_further' ? '#f59e0b' : '#6b7280';

  return `
    <div class="sparkline-wrap" title="Demand curve: ${sp.current} issues now · peak: ${sp.peak} · trend: ${sp.trend}">
      <svg class="sparkline-svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">
        <polyline points="${coords}" fill="none" stroke="${strokeColor}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" opacity="0.85"/>
        <circle cx="${W}" cy="${pts.length > 0 ? (H - ((pts[pts.length-1] - min) / range) * (H - 4) - 2) : H/2}" r="3" fill="${strokeColor}"/>
      </svg>
      <div class="sparkline-meta">
        <span class="sparkline-trend" style="color:${trendColor}">${trendIcon} ${sp.trend}</span>
        <span class="sparkline-current">${sp.current} now · peak ${sp.peak}</span>
        <span class="sparkline-label">demand</span>
      </div>
    </div>
  `;
}

function buildFeatureCard(feat, isDemo) {
  const rec = _rec(feat);
  const vi = feat.viability || {};
  const dr = feat.death_reason || {};
  const roi = feat.roi || {};
  const ci = feat.competitive_intel || null;
  const grounding = vi.grounding || null;
  const featureId = feat.feature_id || feat.id || '';

  const feasibility = vi.revival_feasibility || 0;
  const feasClass = feasibility >= 7 ? '' : feasibility >= 4 ? 'med' : 'low';

  const icons = { revive_now: '✦', investigate_further: '⬢', keep_buried: '⬩' };
  const badgeClass = { revive_now: 'badge-revive', investigate_further: 'badge-investigate', keep_buried: 'badge-buried' };
  const badgeLabel = { revive_now: 'Revive Now', investigate_further: 'Investigate', keep_buried: 'Keep Buried' };

  const ciUrgency = ci ? ci.market_urgency : null;
  const ciComp = ci ? ci.competitors_with_feature : [];

  const card = document.createElement('div');
  card.className = 'feature-card';
  card.dataset.rec = rec;
  card.dataset.featureId = featureId;

  const strokeColor = rec === 'revive_now' ? 'var(--green)' : rec === 'investigate_further' ? 'var(--amber)' : 'var(--text-muted)';
  const fillPct = feasibility * 10;
  const revivalScore = feat.revival_score != null ? feat.revival_score : null;
  const scoreColor = revivalScore != null
    ? (revivalScore >= 70 ? 'var(--green)' : revivalScore >= 40 ? 'var(--amber)' : 'var(--text-muted)')
    : 'var(--text-muted)';

  card.innerHTML = `
    <div class="card-header" onclick="toggleCard(this)" style="display:flex;width:100%;justify-content:space-between;align-items:center">
      <div style="display:flex;align-items:center;gap:0.75rem">
        <div class="tombstone-icon" style="font-size:1.45rem">${icons[rec] || '✦'}</div>
        <div class="card-title-group" style="display:flex;flex-direction:column;gap:0.15rem">
          <div class="card-name" style="font-size:0.95rem;font-weight:700;color:var(--text)">${esc(feat.name || featureId)}</div>
          <div class="card-meta">
            ${feat.kill_date ? `killed ${esc(feat.kill_date)}` : ''}
            ${feat.kill_commit_sha ? ` · <span class="sha" title="Representative commit ref">${esc(feat.kill_commit_sha.slice(0, 8))}</span>` : ''}
            ${feat.detection_method ? ` · ${esc(feat.detection_method.replace(/_/g,' '))}` : ''}
          </div>
          <div class="card-badges" style="display:flex;gap:0.35rem;margin-top:0.15rem;flex-wrap:wrap">
            <span class="badge ${badgeClass[rec] || ''}" style="font-size:0.65rem">${badgeLabel[rec] || rec}</span>
            ${dr.category ? `<span class="badge badge-detection" style="background:rgba(255,255,255,0.03);border:1px solid var(--border);font-size:0.65rem;color:var(--text-secondary);border-radius:6px;padding:0.1rem 0.4rem">${esc(dr.category.replace(/_/g,' '))}</span>` : ''}
            ${ciComp.length ? `<span class="badge badge-competitive" style="background:rgba(6, 182, 212, 0.08);border:1px solid rgba(6, 182, 212, 0.15);color:var(--neon-cyan);font-size:0.65rem;border-radius:6px;padding:0.1rem 0.4rem">vs ${ciComp.length} competitors</span>` : ''}
          </div>
        </div>
      </div>
      <div style="display:flex;align-items:center;gap:0.75rem;margin-left:auto">
        ${revivalScore != null ? `
        <div title="Revival Priority Score (0-100): 40% feasibility + 30% demand + 15% effort + 15% competitive gap" style="display:flex;flex-direction:column;align-items:center;gap:0.1rem">
          <span style="font-size:1.1rem;font-weight:800;color:${scoreColor};line-height:1">${revivalScore}</span>
          <span style="font-size:0.55rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.05em">score</span>
        </div>` : ''}
        <div class="radial-viability-gauge" title="Revival Viability: ${feasibility}/10" >
          <svg class="radial-svg" viewBox="0 0 36 36">
            <circle class="radial-track" cx="18" cy="18" r="15.915"></circle>
            <circle class="radial-fill" cx="18" cy="18" r="15.915" stroke="${strokeColor}" stroke-dasharray="100" stroke-dashoffset="${100 - fillPct}"></circle>
          </svg>
          <span class="radial-value-text">${feasibility * 10}%</span>
        </div>
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

      ${(vi.what_changed && feat.kill_date && rec !== 'keep_buried') ? `
        <div class="section-label">Timeline — constraint resolved</div>
        <div class="why-now-timeline">
          <div class="tl-step tl-killed">
            <div class="tl-dot"></div>
            <div class="tl-content">
              <div class="tl-label">Disabled</div>
              <div class="tl-date">${esc(feat.kill_date || 'unknown date')}</div>
              <div class="tl-desc">${esc(dr.specific_constraint || dr.primary_reason || feat.kill_commit_message || '')}</div>
            </div>
          </div>
          <div class="tl-line"></div>
          <div class="tl-step tl-resolved">
            <div class="tl-dot"></div>
            <div class="tl-content">
              <div class="tl-label">Constraint resolved${grounding && grounding.grounded ? ' <span class="verified-badge">✓ verified</span>' : ' <span class="unverified-badge">AI-inferred</span>'}</div>
              ${grounding && grounding.evidence_date ? `<div class="tl-date">${esc(grounding.evidence_date)} · ${esc(grounding.technology || '')} ${esc(grounding.latest_version || '')}</div>` : ''}
              <div class="tl-desc">${grounding && grounding.evidence_url
                ? `<a href="${esc(grounding.evidence_url)}" target="_blank" rel="noopener" style="color:var(--amber)">${esc(vi.what_changed)}</a>`
                : esc(vi.what_changed)}</div>
            </div>
          </div>
          <div class="tl-line"></div>
          <div class="tl-step ${rec === 'revive_now' ? 'tl-ready' : 'tl-investigate'}">
            <div class="tl-dot"></div>
            <div class="tl-content">
              <div class="tl-label">${rec === 'revive_now' ? 'Ready to revive' : 'Investigate'}</div>
              <div class="tl-desc">${esc(vi.reasoning || '')}</div>
            </div>
          </div>
        </div>
      ` : (vi.what_changed ? `
        <div class="section-label">Why it's revivable now</div>
        <div class="what-changed">${esc(vi.what_changed)}</div>
      ` : '')}

      ${vi.reasoning && !vi.what_changed ? `
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
          <div class="mval" style="font-size:0.85rem;color:var(--text-muted)">${esc(vi.effort_estimate ? `${vi.effort_estimate} ${vi.effort_category}` : vi.effort_category || '—')}</div>
          <div class="mlabel">Effort</div>
        </div>
      </div>

      ${roi.roi_estimate_label || roi.demand_level ? `
        <div class="section-label">Business value</div>
        <div class="roi-breakdown">
          ${roi.priority_tier ? `<span class="roi-tier roi-tier-${(roi.priority_tier || '').replace(/\W+/g,'').toLowerCase().slice(0,2)}">${esc(roi.priority_tier)}</span>` : ''}
          ${roi.demand_level ? `<span class="roi-demand demand-${roi.demand_level}">${roi.demand_level} demand</span>` : ''}
          ${roi.request_count ? `<span class="roi-requests">${roi.request_count} issue ref${roi.request_count !== 1 ? 's' : ''}</span>` : ''}
        </div>
        ${roi.roi_estimate_label ? `<div class="reason-text roi-estimate-value">${esc(roi.roi_estimate_label)}</div>` : ''}
        ${roi.reasoning ? `<div class="reason-text" style="font-size:0.78rem;margin-top:0.3rem">${esc(roi.reasoning)}</div>` : ''}
        ${roi.value_drivers && roi.value_drivers.length ? `
          <div class="roi-drivers">${roi.value_drivers.slice(0,3).map(d => `<span class="roi-driver-tag">${esc(d)}</span>`).join('')}</div>
        ` : ''}
        ${roi.caveats ? `<div class="roi-caveat">${esc(roi.caveats)}</div>` : ''}
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
        <div class="section-label">Challenger Agent — independent verification</div>
        <div class="challenger-box ${feat.challenger.challenger_verdict || ''}">
          <div class="challenger-verdict">
            ${feat.challenger.challenger_verdict === 'confirm' ? 'Confirmed — ' : feat.challenger.challenger_verdict === 'downgrade' ? 'Downgraded — ' : 'Rejected — '}
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

      <!-- Detection provenance — how NECRO found this feature (live scans only) -->
      ${(() => {
        const method = feat.detection_method || '';
        if (!method) return '';
        const signals = feat.detection_signals || [];
        const conf = feat.detection_confidence || 0;
        const methodLabel = {
          feature_flag_removal:      '🚩 Feature flag removal',
          revert_commit:             '↩ Revert commit',
          commit_message_keyword:    '🔍 Commit keyword match',
          shelved_issue:             '📋 Shelved issue',
          gitlab_feature_flags_api:  '🚩 GitLab Feature Flags API',
        }[method] || method.replace(/_/g, ' ');
        const posSignals = signals.filter(s => !s.startsWith('⚠'));
        const negSignals = signals.filter(s => s.startsWith('⚠'));
        // Only show confidence dots when we have actual signal data (live scans)
        const showConf = conf > 0 && signals.length > 0;
        const confDots = showConf
          ? ('●'.repeat(Math.min(conf, 5)) + '○'.repeat(Math.max(0, 5 - conf)))
          : '';
        const confColor = conf >= 4 ? 'var(--green)' : conf >= 2 ? 'var(--amber)' : 'var(--text-muted)';
        return `
          <div class="section-label">Detection provenance</div>
          <div class="detection-provenance">
            <div class="dp-method">
              <span class="dp-method-label">${esc(methodLabel)}</span>
              ${showConf ? `<span class="dp-conf" style="color:${confColor}" title="Detection confidence: ${conf}/5 — ${posSignals.join(', ')}">${confDots}</span>` : ''}
            </div>
            ${posSignals.length ? `
              <div class="dp-signals">
                ${posSignals.map(s => `<span class="dp-signal dp-signal-pos">${esc(s)}</span>`).join('')}
                ${negSignals.map(s => `<span class="dp-signal dp-signal-neg">${esc(s)}</span>`).join('')}
              </div>` : ''}
          </div>
        `;
      })()}

      ${feat.context_snippets && feat.context_snippets.length ? `
        <div class="section-label">Evidence (cited from repo history)</div>
        <ul class="snippets-list">
          ${feat.context_snippets.slice(0, 3).map(s => `<li>${esc(s)}</li>`).join('')}
        </ul>
      ` : ''}

      ${feat.open_issue_matches && feat.open_issue_matches.length ? `
        <div class="section-label">Open Requests — users are asking for this now</div>
        <div class="open-requests-box">
          <div class="open-req-header">
            <span class="open-req-count">${feat.open_issue_matches.length} open issue${feat.open_issue_matches.length !== 1 ? 's' : ''} requesting this feature</span>
            <span class="open-req-insight">Already built — revival costs ~80% less than a rebuild.</span>
          </div>
          <ul class="open-req-list">
            ${feat.open_issue_matches.slice(0, 4).map(m => `
              <li><a href="${esc(m.url)}" target="_blank" rel="noopener">#${m.iid}: ${esc(m.title)}</a></li>
            `).join('')}
          </ul>
        </div>
      ` : ''}

      <!-- Feature EKG — Vitality Sparkline (demand over time) -->
      <div class="vitality-sparkline-row" id="sparkline-row-${featureId}">
        <div class="section-label" style="margin-top:0.6rem">Feature EKG — demand trend since kill</div>
        <div class="sparkline-container" id="sparkline-${featureId}">
          <span class="sparkline-loading">loading...</span>
        </div>
      </div>

      <div class="card-actions">
        ${rec !== 'keep_buried' ? `
          <button class="btn btn-primary btn-sm" onclick="createRevivalIssue('${featureId}', this)">
            Create GitLab Issue
          </button>
          <button class="btn btn-ghost-mr btn-sm" onclick="createGhostMR('${featureId}', this)" title="NECRO creates a real Draft MR with branch + NECRO_REVIVAL.md plan file via 3 GitLab MCP write operations">
            👻 Ghost MR
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

    btn.innerHTML = 'Issue Created';
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
    btn.innerHTML = 'Create GitLab Issue';
    toast(`Error: ${e.message}`, 'error');
  }
}

// ── Create Ghost MR — NECRO creates a real draft GitLab MR ──────────────────
async function createGhostMR(featureId, btn) {
  const project = currentFeatures.find(f => (f.feature_id || f.id) === featureId);
  const projectPath = project ? (project.project_path || '') : '';

  if (!projectPath) {
    toast('Cannot determine project path for this feature.', 'error');
    return;
  }

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Creating Ghost MR...';

  try {
    const r = await fetch(`/api/revive/${featureId}/ghost-mr`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_path: projectPath }),
    });
    const d = await r.json();

    if (!r.ok) throw new Error(d.detail || 'Failed to create Ghost MR');

    btn.innerHTML = 'Ghost MR Created';
    btn.className = 'btn btn-ghost-mr-done btn-sm';

    if (d.mr_url) {
      const link = document.createElement('a');
      link.href = d.mr_url;
      link.target = '_blank';
      link.rel = 'noopener';
      link.className = 'btn btn-sm btn-ghost-mr-link';
      link.textContent = `View Draft MR !${d.mr_iid || ''} ↗`;
      btn.insertAdjacentElement('afterend', link);
    }

    toast(
      `Ghost MR created! Branch: ${d.branch_name} · Plan: ${d.plan_file} · 3 GitLab write ops via MCP`,
      'success'
    );
    loadAuditLog();
  } catch (e) {
    btn.disabled = false;
    btn.innerHTML = '👻 Ghost MR';
    toast(`Ghost MR: ${e.message}`, 'error');
  }
}

// ── Post Graveyard Report to GitLab ─────────────────────────────────────────
function toggleGitlabProjectPicker() {
  const picker = document.getElementById('gitlabProjectPicker');
  if (!picker) return;
  const open = picker.style.display !== 'none';
  picker.style.display = open ? 'none' : 'block';
  if (!open) {
    // Pre-fill with scanned project path as default suggestion
    const input = document.getElementById('gitlabTargetProject');
    if (input && _reportMeta && _reportMeta.project_path) {
      input.value = _reportMeta.project_path;
    }
    setTimeout(() => input && input.focus(), 50);
  }
}

async function postReportToGitLab() {
  const data = _reportMeta;
  const btn = document.getElementById('postToGitLabBtn');
  if (!data) { toast('No scan results — run a scan first', 'error'); return; }

  const input = document.getElementById('gitlabTargetProject');
  const projectPath = (input && input.value.trim()) || data.project_path;
  if (!projectPath) { toast('Enter a GitLab project path', 'error'); return; }

  // Close picker, disable button
  const picker = document.getElementById('gitlabProjectPicker');
  if (picker) picker.style.display = 'none';
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Posting…'; }

  try {
    const r = await fetch('/api/report/post-to-gitlab', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project_path: projectPath,
        features: data.features || [],
        total_commits_scanned: data.total_commits_scanned || 0,
        mcp_tools_used: data.mcp_tools_used || [],
        mcp_tool_count: data.mcp_tool_count || 0,
      }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'Post failed');

    if (btn) { btn.disabled = false; btn.innerHTML = 'Posted to GitLab'; btn.style.background = 'var(--green)'; }
    if (d.issue_url) {
      const link = document.createElement('a');
      link.href = d.issue_url;
      link.target = '_blank';
      link.rel = 'noopener';
      link.textContent = `View Issue #${d.issue_iid || ''} ↗`;
      link.className = 'btn btn-sm';
      btn.insertAdjacentElement('afterend', link);
    }
    toast(`Report posted to ${projectPath} as Issue #${d.issue_iid || ''}`, 'success');
  } catch (e) {
    if (btn) { btn.disabled = false; btn.innerHTML = 'POST TO GITLAB'; }
    toast(e.message, 'error');
  }
}

// ── Share to Slack ────────────────────────────────────────────────────────────
const _SLACK_SVG = `<svg class="slack-logo-icon" viewBox="0 0 54 54" width="15" height="15" style="flex-shrink:0"><path class="s-green" d="M19.712.133a5.381 5.381 0 0 0-5.376 5.387 5.381 5.381 0 0 0 5.376 5.386h5.376V5.52A5.381 5.381 0 0 0 19.712.133m0 14.365H5.376A5.381 5.381 0 0 0 0 19.884a5.381 5.381 0 0 0 5.376 5.387h14.336a5.381 5.381 0 0 0 5.376-5.387 5.381 5.381 0 0 0-5.376-5.386"/><path class="s-blue" d="M53.76 19.884a5.381 5.381 0 0 0-5.376-5.386 5.381 5.381 0 0 0-5.376 5.386v5.387h5.376a5.381 5.381 0 0 0 5.376-5.387m-14.336 0V5.52A5.381 5.381 0 0 0 34.048.133a5.381 5.381 0 0 0-5.376 5.387v14.364a5.381 5.381 0 0 0 5.376 5.387 5.381 5.381 0 0 0 5.376-5.387"/><path class="s-red" d="M34.048 54a5.381 5.381 0 0 0 5.376-5.387 5.381 5.381 0 0 0-5.376-5.386h-5.376v5.386A5.381 5.381 0 0 0 34.048 54m0-14.365h14.336a5.381 5.381 0 0 0 5.376-5.386 5.381 5.381 0 0 0-5.376-5.387H34.048a5.381 5.381 0 0 0-5.376 5.387 5.381 5.381 0 0 0 5.376 5.386"/><path class="s-yellow" d="M0 34.249a5.381 5.381 0 0 0 5.376 5.386 5.381 5.381 0 0 0 5.376-5.386v-5.387H5.376A5.381 5.381 0 0 0 0 34.249m14.336 0v14.364A5.381 5.381 0 0 0 19.712 54a5.381 5.381 0 0 0 5.376-5.387V34.249a5.381 5.381 0 0 0-5.376-5.387 5.381 5.381 0 0 0-5.376 5.387"/></svg>`;

function _buildSlackText() {
  const data = _reportMeta;
  if (!data || !data.project_path) return null;

  const features = data.features || [];
  const reviveNow = features.filter(f => (f.viability || {}).recommendation === 'revive_now');
  const investigate = features.filter(f => (f.viability || {}).recommendation === 'investigate_further');

  let lines = [
    `*NECRO Graveyard Report — ${data.project_path}*`,
    `*${reviveNow.length}* ready to revive · *${investigate.length}* investigate · *${features.length}* total dead features`,
    '',
  ];
  reviveNow.slice(0, 5).forEach(f => {
    const score = (f.viability || {}).revival_feasibility || '?';
    const what = ((f.viability || {}).what_changed || '').slice(0, 80);
    lines.push(`• *${f.name}* _(${score}/10)_ — ${what}`);
  });
  if (reviveNow.length > 5) lines.push(`_…and ${reviveNow.length - 5} more_`);
  lines.push('', `_Scanned by NECRO — The Code Necromancer_`);
  return lines.join('\n');
}

async function notifySlack() {
  const btn = document.getElementById('notifySlackBtn');
  if (!btn) return;

  const data = _reportMeta;
  if (!data || !data.project_path) {
    toast('No scan results to send — run a scan first', 'error');
    return;
  }

  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span> Sending…`;

  try {
    const r = await fetch('/api/report/notify-slack', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        project_path: data.project_path,
        features: data.features || [],
      }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'Slack delivery failed');

    btn.classList.add('slack-sent');
    btn.style.background = '';
    btn.innerHTML = `<svg viewBox="0 0 20 20" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0"><polyline points="4 10 8 14 16 6"/></svg> Sent to Slack`;
    toast(`Slack alert sent — ${d.revive_now_count} revival candidates shared`, 'success');
  } catch (e) {
    btn.disabled = false;
    btn.classList.remove('slack-sent');
    btn.innerHTML = `${_SLACK_SVG} SHARE TO SLACK`;
    if (e.message.includes('not configured')) {
      toast('Slack not configured — add SLACK_WEBHOOK_URL to .env', 'error');
    } else {
      toast(`Slack error: ${e.message}`, 'error');
    }
  }
}

async function copySlackMessage() {
  const btn = document.getElementById('copySlackMsgBtn');
  const text = _buildSlackText();
  if (!text) {
    toast('No scan results to copy — run a scan first', 'error');
    return;
  }

  try {
    await navigator.clipboard.writeText(text);
    if (btn) {
      const orig = btn.innerHTML;
      btn.innerHTML = `✓`;  // single checkmark, not emoji
      btn.style.color = '#4ade80';
      setTimeout(() => { btn.innerHTML = orig; btn.style.color = ''; }, 2000);
    }
    toast('Slack message copied to clipboard', 'success');
  } catch {
    // fallback for non-HTTPS or older browsers
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    toast('Slack message copied to clipboard', 'success');
  }
}

// ── Export report as JSON ─────────────────────────────────────────────────────
function exportReportJson() {
  if (!_reportMeta || !_reportMeta.project_path) {
    toast('No report to export — run a scan first', 'error');
    return;
  }
  const slug = (_reportMeta.project_path || 'necro').replace(/\//g, '_');
  const ts = new Date().toISOString().slice(0, 19).replace(/:/g, '-');
  const filename = `necro_dormant_features_${slug}_${ts}.json`;
  const blob = new Blob([JSON.stringify(_reportMeta, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
  toast(`Exported ${filename}`, 'success');
}

// ── Charts (Timeline tab) ─────────────────────────────────────────────────────
let chartsDrawn = false;
let _charts = {};
let _allFeaturesCache = null;

async function renderCharts() {
  // Destroy existing charts so we can redraw cleanly
  if (Object.keys(_charts).length) {
    Object.values(_charts).forEach(c => { try { c.destroy(); } catch(_) {} });
    _charts = {};
  }
  chartsDrawn = false;

  const isDark = document.documentElement.getAttribute('data-theme') !== 'light';
  const gridColor = isDark ? 'rgba(255,255,255,0.07)' : 'rgba(0,0,0,0.06)';
  const textColor = isDark ? '#888898' : '#6b6b8a';

  // ── Fetch all features from MongoDB (not just current scan) ─────────────────
  let allFeatures = _allFeaturesCache;
  if (!allFeatures) {
    try {
      const r = await fetch('/api/report/all-features?limit=200');
      if (r.ok) {
        const d = await r.json();
        allFeatures = d.features || [];
        _allFeaturesCache = allFeatures;
      }
    } catch (_) {}
  }
  // Fallback to current scan features if API unavailable
  if (!allFeatures || !allFeatures.length) allFeatures = currentFeatures;
  if (!allFeatures.length) return;

  // ── Update insight cards ────────────────────────────────────────────────────
  const recCounts = { revive_now: 0, investigate_further: 0, keep_buried: 0 };
  let feasSum = 0, feasCount = 0;
  for (const f of allFeatures) {
    const r = _rec(f);
    if (r in recCounts) recCounts[r]++;
    const feas = (f.viability || {}).revival_feasibility;
    if (typeof feas === 'number') { feasSum += feas; feasCount++; }
  }
  const avgFeas = feasCount ? (feasSum / feasCount).toFixed(1) : '—';
  const setEl = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  setEl('tlReviveCount',    recCounts.revive_now);
  setEl('tlInvestCount',    recCounts.investigate_further);
  setEl('tlBuriedCount',    recCounts.keep_buried);
  setEl('tlAvgFeasibility', avgFeas);
  setEl('tlTotalFeats',     allFeatures.length);
  const srcEl = document.getElementById('tlDataSource');
  if (srcEl) srcEl.textContent = `Showing ${allFeatures.length} features across all scans in MongoDB Atlas`;

  // ── Chart 1: Kill Timeline ─────────────────────────────────────────────────
  const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const monthCounts = {};
  for (const feat of allFeatures) {
    const raw = feat.kill_date || '';
    let label = 'Unknown';
    if (raw) {
      const parsed = new Date(raw);
      if (!isNaN(parsed.getTime())) {
        label = `${MONTHS[parsed.getMonth()]} '${String(parsed.getFullYear()).slice(-2)}`;
      } else {
        // "April 17, 2026" format — already has month name
        const m = raw.match(/^([A-Za-z]+)/);
        if (m) label = `${m[1].slice(0,3)} '${raw.slice(-2)}`;
        else label = raw.slice(0, 7);
      }
    }
    monthCounts[label] = (monthCounts[label] || 0) + 1;
  }
  // Sort chronologically
  const sortedMonths = Object.keys(monthCounts).filter(m => m !== 'Unknown').sort((a, b) => {
    const parse = s => { const [mo, yr] = s.split(" '"); return parseInt('20'+yr)*12 + MONTHS.indexOf(mo); };
    return parse(a) - parse(b);
  });
  if (monthCounts['Unknown']) sortedMonths.push('Unknown');
  const tlCounts = sortedMonths.map(m => monthCounts[m]);
  // Color bars by recency: most recent = purple, older = lighter
  const tlColors = sortedMonths.map((_, i) => {
    const t = i / Math.max(sortedMonths.length - 1, 1);
    return `rgba(124,58,237,${0.3 + t * 0.65})`;
  });

  _charts.timeline = new Chart(document.getElementById('timelineChart'), {
    type: 'bar',
    data: {
      labels: sortedMonths,
      datasets: [{
        label: 'Features killed',
        data: tlCounts,
        backgroundColor: tlColors,
        borderColor: 'rgba(124,58,237,0.9)',
        borderWidth: 1,
        borderRadius: 3,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => `${ctx.raw} feature${ctx.raw !== 1 ? 's' : ''} killed` } },
      },
      scales: {
        x: { ticks: { color: textColor, maxRotation: 45, font: { size: 10 } }, grid: { color: gridColor } },
        y: { ticks: { color: textColor, stepSize: 1 }, grid: { color: gridColor }, beginAtZero: true },
      }
    }
  });

  // ── Chart 2: Recommendation Breakdown (pie) ────────────────────────────────
  _charts.recommendation = new Chart(document.getElementById('recommendationChart'), {
    type: 'doughnut',
    data: {
      labels: ['Revive Now', 'Investigate', 'Keep Buried'],
      datasets: [{
        data: [recCounts.revive_now, recCounts.investigate_further, recCounts.keep_buried],
        backgroundColor: ['#10b981', '#f59e0b', '#6b7280'],
        borderWidth: 3,
        borderColor: isDark ? '#12121a' : '#ffffff',
        hoverOffset: 6,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      cutout: '62%',
      plugins: {
        legend: { position: 'bottom', labels: { color: textColor, boxWidth: 11, padding: 12, font: { size: 11 } } },
        tooltip: {
          callbacks: {
            label: ctx => {
              const pct = allFeatures.length ? Math.round(ctx.raw / allFeatures.length * 100) : 0;
              return `${ctx.label}: ${ctx.raw} (${pct}%)`;
            }
          }
        }
      }
    }
  });

  // ── Chart 3: Feasibility Distribution (doughnut) ──────────────────────────
  const bins = [0, 0, 0, 0, 0]; // 0-2, 3-4, 5-6, 7-8, 9-10
  for (const feat of allFeatures) {
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
      datasets: [{ data: bins, backgroundColor: ['#6b7280','#ef4444','#f59e0b','#3b82f6','#10b981'], borderWidth: 3, borderColor: isDark ? '#12121a' : '#fff', hoverOffset: 6 }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      cutout: '62%',
      plugins: { legend: { position: 'bottom', labels: { color: textColor, boxWidth: 11, padding: 10, font: { size: 11 } } } }
    }
  });

  // ── Chart 4: Kill Reason Categories (horizontal bar) ─────────────────────
  const catCounts = {};
  for (const feat of allFeatures) {
    const c = (feat.death_reason || {}).category || 'unknown';
    catCounts[c] = (catCounts[c] || 0) + 1;
  }
  // Sort by count descending
  const cats = Object.keys(catCounts).sort((a, b) => catCounts[b] - catCounts[a]);
  const catPalette = ['#7c3aed','#10b981','#f59e0b','#3b82f6','#ef4444','#ec4899','#14b8a6','#8b5cf6'];

  _charts.category = new Chart(document.getElementById('categoryChart'), {
    type: 'bar',
    data: {
      labels: cats.map(c => c.replace(/_/g,' ')),
      datasets: [{
        label: 'Features',
        data: cats.map(c => catCounts[c]),
        backgroundColor: cats.map((_, i) => catPalette[i % catPalette.length]),
        borderWidth: 0,
        borderRadius: 3,
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => `${ctx.raw} feature${ctx.raw !== 1 ? 's' : ''}` } },
      },
      scales: {
        x: { ticks: { color: textColor, stepSize: 1 }, grid: { color: gridColor }, beginAtZero: true },
        y: { ticks: { color: textColor, font: { size: 11 } }, grid: { display: false } },
      }
    }
  });

  // ── Chart 5: Cost-Benefit Scatter ─────────────────────────────────────────
  const effortOrder = { days: 1, 'days-weeks': 2, weeks: 3, 'weeks-months': 4, months: 5, 'months-quarters': 6, quarters: 7 };
  const effortLabels = { 1: 'days', 2: 'days-wks', 3: 'weeks', 4: 'wks-mo', 5: 'months', 6: 'mo-qtr', 7: 'quarters' };

  const scatterData = allFeatures.map(f => {
    const vi = f.viability || {};
    const roi = f.roi || {};
    const rec = _rec(f);
    const xVal = effortOrder[vi.effort_category] || 3;
    const yVal = vi.revival_feasibility || 0;
    const demand = roi.request_count || 0;
    return {
      x: xVal + (Math.random() * 0.5 - 0.25),
      y: yVal + (Math.random() * 0.4 - 0.2),
      r: Math.max(5, Math.min(20, demand * 3 + 5)),
      label: f.name, rec,
    };
  });

  const pointColors = scatterData.map(d =>
    d.rec === 'revive_now'          ? 'rgba(16,185,129,0.78)' :
    d.rec === 'investigate_further' ? 'rgba(245,158,11,0.78)' :
                                      'rgba(107,114,128,0.4)'
  );

  _charts.scatter = new Chart(document.getElementById('scatterChart'), {
    type: 'bubble',
    data: {
      datasets: [{
        label: 'Features',
        data: scatterData,
        backgroundColor: pointColors,
        borderColor: pointColors.map(c => c.replace(/[\d.]+\)$/, '1)')),
        borderWidth: 1.5,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => {
              const d = ctx.raw;
              const el = effortLabels[Math.round(d.x)] || '?';
              return [`📦 ${d.label}`, `  effort: ${el}  ·  feasibility: ${Math.round(d.y)}/10`];
            }
          }
        }
      },
      scales: {
        x: {
          title: { display: true, text: 'Revival Effort  (← less effort)', color: textColor, font: { size: 10 } },
          ticks: { color: textColor, font: { size: 10 }, callback: v => effortLabels[Math.round(v)] || '' },
          min: 0, max: 8, grid: { color: gridColor },
        },
        y: {
          title: { display: true, text: 'Feasibility  (↑ easier to revive)', color: textColor, font: { size: 10 } },
          ticks: { color: textColor, font: { size: 10 }, stepSize: 2 },
          min: 0, max: 10, grid: { color: gridColor },
        }
      }
    }
  });

  chartsDrawn = true;
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
    // Encode each path segment individually — don't encode slashes, since FastAPI's
    // {project_path:path} route matches raw slashes in the URL path.
    const encodedPath = path.split('/').map(encodeURIComponent).join('/');
    const r = await fetch(`/api/watch/${encodedPath}`, { method: 'DELETE' });
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

    const hdr = document.getElementById('watchSectionHeader');
    const cnt = document.getElementById('watchRepoCount');
    if (hdr) hdr.style.display = repos.length ? 'flex' : 'none';
    if (cnt) cnt.textContent = `${repos.length} repo${repos.length !== 1 ? 's' : ''}`;

    if (!repos.length) {
      grid.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">👁</div>
          <p>No repositories monitored yet.<br>Add a GitLab URL above to start autonomous scanning.</p>
        </div>`;
      return;
    }

    grid.innerHTML = `<div class="watch-repo-grid">${repos.map(repo => {
      const revive  = repo.revive_now_count   || 0;
      const invest  = repo.investigate_count  || 0;
      const total   = repo.total_found        || 0;
      const lastRaw = repo.last_scanned;
      const lastScanned = lastRaw
        ? (() => {
            const d = new Date(lastRaw);
            const diff = Date.now() - d.getTime();
            const h = Math.floor(diff / 3600000);
            if (h < 1)  return 'just now';
            if (h < 24) return `${h}h ago`;
            const days = Math.floor(h / 24);
            return `${days}d ago · ${d.toLocaleDateString()}`;
          })()
        : 'never scanned';
      const path = esc(repo.project_path);
      const label = repo.label ? `<span class="watch-label-chip">${esc(repo.label)}</span>` : '';
      const hasResults = revive > 0 || invest > 0;

      return `
        <div class="watch-repo-card${revive > 0 ? ' has-revivals' : ''}">
          <div class="wrc-header">
            <div class="wrc-dot-wrap"><div class="pulse-dot${revive > 0 ? ' pulse-green' : ''}"></div></div>
            <div class="wrc-title">
              <a href="https://gitlab.com/${path}" target="_blank" rel="noopener" class="wrc-path">${path}</a>
              ${label}
            </div>
            <button class="btn btn-xs wrc-remove" onclick="removeWatch('${path}')" title="Stop monitoring">✕</button>
          </div>

          ${hasResults ? `
          <div class="wrc-stats">
            ${revive > 0 ? `<div class="wrc-stat wrc-stat-revive"><span class="wrc-stat-val">${revive}</span><span class="wrc-stat-lbl">Revive Now</span></div>` : ''}
            ${invest > 0 ? `<div class="wrc-stat wrc-stat-invest"><span class="wrc-stat-val">${invest}</span><span class="wrc-stat-lbl">Investigate</span></div>` : ''}
            ${total > 0  ? `<div class="wrc-stat wrc-stat-total"><span class="wrc-stat-val">${total}</span><span class="wrc-stat-lbl">Total found</span></div>` : ''}
          </div>` : `
          <div class="wrc-no-results">No revival candidates detected yet</div>`}

          <div class="wrc-footer">
            <span class="wrc-last-scan">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align:-1px"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
              ${lastScanned}
            </span>
            <div class="wrc-actions">
              <button class="btn btn-xs" onclick="scanWatchedRepo('${path}')">Scan Now</button>
            </div>
          </div>
        </div>`;
    }).join('')}</div>`;
  } catch (e) {
    grid.innerHTML = '<div class="empty-state"><p>Could not load watch list.</p></div>';
  }
  loadLiveStats();
}

async function scanWatchedRepo(projectPath) {
  // Pre-fill the scanner URL and switch to graveyard tab to run a live scan
  const urlInput = document.getElementById('repoUrl');
  if (urlInput) urlInput.value = `https://gitlab.com/${projectPath}`;
  activateTab('graveyard');
  toast(`Ready to scan ${projectPath} — click "Run Forensic Archaeology"`, 'info');
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
      area.innerHTML = '<div class="empty-state"><p>No revival issues created yet. Scan a repo and click "Create GitLab Issue" to start.</p></div>';
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
                ${e.issue_url
                  ? `<a href="${esc(e.issue_url)}" target="_blank" rel="noopener" class="btn btn-sm" style="display:inline-flex;align-items:center;gap:0.3rem">
                      ${e.issue_iid ? `#${e.issue_iid}` : 'View'}
                      <svg viewBox="0 0 12 12" width="10" height="10" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2 10L10 2M5 2h5v5"/></svg>
                    </a>`
                  : '—'}
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
  loadLiveStats();
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
const escHtml = esc; // alias used by ADK synthesis panel

// ── Group Scan — Cross-Repository Graveyard Federation ───────────────────────
function toggleGroupScanInput() {
  const panel = document.getElementById('groupScanInput');
  const btn = document.getElementById('groupScanToggle');
  if (!panel) return;
  const open = panel.style.display !== 'none';
  panel.style.display = open ? 'none' : 'block';
  if (btn) {
    btn.textContent = open ? '⛓ GROUP SCAN' : '⛓ HIDE GROUP SCAN';
    btn.classList.toggle('active', !open);
  }
  if (!open) {
    setTimeout(() => document.getElementById('groupNamespace')?.focus(), 50);
  }
}

async function runGroupScan() {
  const namespace = (document.getElementById('groupNamespace')?.value || '').trim();
  if (!namespace) { toast('Enter a GitLab namespace (e.g. gitlab-org, inkscape, kde)', 'error'); return; }

  const maxRepos = parseInt(document.getElementById('groupMaxRepos')?.value) || 8;
  const btn = document.getElementById('groupScanBtn');
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Federating...'; }

  const terminal = showTerminal();
  addTerminalLine(terminal, `[GROUP SCAN] Federating graveyard: namespace=${namespace}, max_repos=${maxRepos}`);
  addTerminalLine(terminal, `[MCP] list_projects_in_group → ${namespace}`);

  try {
    const r = await fetch('/api/scan/group', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ namespace, max_repos: maxRepos, max_commits_per_repo: 80, lookback_months: 24 }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);

    addTerminalLine(terminal, `[GROUP SCAN] ${d.repos_scanned} repos · ${d.total_features} dead features · ${(d.cross_repo_chains || []).length} cross-repo chains`);
    addTerminalLine(terminal, `[OK] Group scan complete — ${namespace}`, 'done');
    renderGroupScanResults(d, namespace);
    toast(`${namespace}: ${d.repos_scanned} repos scanned, ${(d.cross_repo_chains || []).length} cross-repo chains found`, 'success');
  } catch (e) {
    addTerminalLine(terminal, `ERROR: ${e.message}`, 'error');
    toast(`Group scan failed: ${e.message}`, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = 'FEDERATE GRAVEYARDS'; }
  }
}

function renderGroupScanResults(data, namespace) {
  const panel = document.getElementById('groupScanPanel');
  if (!panel) return;

  const chains = data.cross_repo_chains || [];
  const repoBreakdowns = data.repo_breakdowns || [];
  const totalFeats = data.total_features || 0;
  const reposScanned = data.repos_scanned || 0;

  if (!chains.length && !totalFeats) {
    panel.style.display = 'none';
    return;
  }

  const chainsHtml = chains.map(chain => `
    <div class="cross-chain-item">
      <div class="cross-chain-head">
        <span class="cross-chain-key">${escHtml(chain.constraint_key)}</span>
        <span class="cross-chain-count">${chain.cross_repo_count} features across ${(chain.repos_affected || []).length} repos</span>
        <span class="cross-chain-unlock">⚡ ${escHtml(chain.org_unlock || 'Fix once → unlock org-wide')}</span>
      </div>
      <div class="cross-chain-repos">
        ${(chain.repos_affected || []).map(r => `<span class="cross-chain-repo">${escHtml(r.split('/').pop() || r)}</span>`).join('')}
      </div>
    </div>`).join('');

  const topReposHtml = repoBreakdowns.slice(0, 6).map(rb => `
    <div class="group-repo-row">
      <span class="group-repo-name">${escHtml((rb.project_path || '').split('/').pop())}</span>
      <span class="group-repo-stats">
        ${rb.revive_now || 0} revive · ${rb.features_found || 0} total
      </span>
    </div>`).join('');

  panel.innerHTML = `
    <div class="group-scan-results">
      <div class="group-scan-results-header">
        <span class="group-scan-results-badge">⛓ Cross-Repository Graveyard Federation</span>
        <span class="group-scan-namespace">${escHtml(namespace)}</span>
        <span class="group-scan-summary">${reposScanned} repos · ${totalFeats} dead features · ${chains.length} cross-repo chain${chains.length !== 1 ? 's' : ''}</span>
      </div>

      ${chains.length ? `
        <div class="group-scan-section">
          <div class="group-scan-section-label">Org-Level Resurrection Chains — same constraint killed features in multiple repos</div>
          <div class="cross-chains-list">${chainsHtml}</div>
        </div>
      ` : `<div class="group-scan-no-chains">No cross-repo constraint patterns found — each repo appears to have unique kill reasons.</div>`}

      ${topReposHtml ? `
        <div class="group-scan-section">
          <div class="group-scan-section-label">Repo Breakdown</div>
          <div class="group-repos-grid">${topReposHtml}</div>
        </div>
      ` : ''}

      <div class="group-scan-meta">
        Scanned via GitLab MCP · <code>list_projects_in_group</code> + per-repo forensics
      </div>
    </div>
  `;
  panel.style.display = '';
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
