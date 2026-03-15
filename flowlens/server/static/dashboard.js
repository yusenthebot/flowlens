/* FlowLens Dashboard — Main application logic */
'use strict';

// ==================================================================// State
// ==================================================================
const API_BASE = window.location.origin;

// ==================================================================// Agent Profile System
// ==================================================================
const AGENT_PROFILES = {
  'vr-alpha': {
    name: 'Alpha', role: 'Core Developer', color: '#3b82f6', bgClass: 'from-blue-500/20 to-blue-600/10',
    badgeClass: 'bg-blue-500/15 text-blue-400 border-blue-500/25',
    icon: `<svg viewBox="0 0 32 32" fill="none"><rect x="4" y="6" width="24" height="20" rx="3" stroke="currentColor" stroke-width="2"/><path d="M16 12v8m-4-4h8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`
  },
  'vr-beta': {
    name: 'Beta', role: 'Worker Engineer', color: '#10b981', bgClass: 'from-emerald-500/20 to-emerald-600/10',
    badgeClass: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/25',
    icon: `<svg viewBox="0 0 32 32" fill="none"><circle cx="16" cy="16" r="10" stroke="currentColor" stroke-width="2"/><path d="M16 11v5l3 3" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`
  },
  'vr-gamma': {
    name: 'Gamma', role: 'Test & Monitor', color: '#8b5cf6', bgClass: 'from-purple-500/20 to-purple-600/10',
    badgeClass: 'bg-purple-500/15 text-purple-400 border-purple-500/25',
    icon: `<svg viewBox="0 0 32 32" fill="none"><path d="M16 4l3 8h8l-6.5 5 2.5 8L16 20l-7 5 2.5-8L5 12h8z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>`
  },
  'vr-lead': {
    name: 'Lead', role: 'Architect', color: '#f59e0b', bgClass: 'from-amber-500/20 to-amber-600/10',
    badgeClass: 'bg-amber-500/15 text-amber-400 border-amber-500/25',
    icon: `<svg viewBox="0 0 32 32" fill="none"><path d="M6 20l4-8 6 4 6-4 4 8H6z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><rect x="8" y="20" width="16" height="4" rx="1" stroke="currentColor" stroke-width="2"/></svg>`
  },
  'vr-scribe': {
    name: 'Scribe', role: 'Documentation', color: '#6b7280', bgClass: 'from-slate-500/20 to-slate-600/10',
    badgeClass: 'bg-slate-500/15 text-slate-400 border-slate-500/25',
    icon: `<svg viewBox="0 0 32 32" fill="none"><rect x="7" y="4" width="18" height="24" rx="2" stroke="currentColor" stroke-width="2"/><path d="M11 10h10M11 14h10M11 18h6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`
  },
  'main': {
    name: 'Main', role: 'Session', color: '#6366f1', bgClass: 'from-indigo-500/20 to-indigo-600/10',
    badgeClass: 'bg-indigo-500/15 text-indigo-400 border-indigo-500/25',
    icon: `<svg viewBox="0 0 32 32" fill="none"><rect x="4" y="6" width="24" height="20" rx="3" stroke="currentColor" stroke-width="2"/><path d="M10 16l3 3 6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`
  },
  'Explore': {
    name: 'Explore', role: 'Explorer', color: '#06b6d4', bgClass: 'from-cyan-500/20 to-cyan-600/10',
    badgeClass: 'bg-cyan-500/15 text-cyan-400 border-cyan-500/25',
    icon: `<svg viewBox="0 0 32 32" fill="none"><circle cx="14" cy="14" r="8" stroke="currentColor" stroke-width="2"/><path d="M20 20l6 6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`
  },
};
const DEFAULT_PROFILE = {
  name: '?', role: 'Agent', color: '#9ca3af', bgClass: 'from-slate-500/20 to-slate-600/10',
  badgeClass: 'bg-slate-500/15 text-slate-400 border-slate-500/25',
  icon: `<svg viewBox="0 0 32 32" fill="none"><circle cx="16" cy="12" r="5" stroke="currentColor" stroke-width="2"/><path d="M8 26c0-4.4 3.6-8 8-8s8 3.6 8 8" stroke="currentColor" stroke-width="2"/></svg>`
};

function getAgentProfile(name) {
  return AGENT_PROFILES[name] || { ...DEFAULT_PROFILE, name: name || '?' };
}

function renderAgentAvatar(name, size = 'md') {
  const p = getAgentProfile(name);
  const sizes = { sm: 'w-6 h-6', md: 'w-8 h-8', lg: 'w-10 h-10' };
  return `<div class="${sizes[size] || sizes.md} rounded-lg bg-gradient-to-br ${p.bgClass} flex items-center justify-center flex-shrink-0" style="color:${p.color}">${p.icon}</div>`;
}

let currentView = 'overview';
let traceOffset = 0;
const TRACE_LIMIT = 30;
let currentTraceId = null;
let currentTraceData = null;
let cyInstance = null;
let autoRefreshTimer = null;
let chartInstances = {};
let allPatterns = [];
let selectedTraceIndex = -1; // For keyboard navigation
let wsConnection = null;
let wsReconnectTimer = null;
let wsReconnectAttempts = 0;
let compareSelection = []; // For trace comparison (max 2)
let isDarkTheme = document.documentElement.classList.contains('dark');
let dagLoaded = false; // Lazy load flag for DAG
let knownAgents = new Set(); // For new-agent detection in notifications
let virtualScrollState = { traces: [], renderedStart: 0, renderedEnd: 0, rowHeight: 56, containerHeight: 600 };

// Stat card time window: 'hour', 'day', 'all'
let _statsWindow = 'all';
// Live activity feed buffer (max 15 entries)
let _liveFeedEvents = [];
const _LIVE_FEED_MAX = 15;

// ==================================================================// Notification System
// ==================================================================
let notifications = [];

function toggleNotificationPanel() {
  const panel = document.getElementById('notification-panel');
  panel.classList.toggle('hidden');
  if (!panel.classList.contains('hidden')) {
    renderNotifications();
  }
}

function addNotification(type, title, message, traceId = null) {
  notifications.unshift({
    id: Date.now(),
    type,  // 'error', 'warning', 'info', 'success'
    title,
    message,
    traceId,
    timestamp: Date.now() / 1000,
    read: false,
  });
  // Keep max 50
  if (notifications.length > 50) notifications = notifications.slice(0, 50);
  updateNotificationBadge();
}

function updateNotificationBadge() {
  const unread = notifications.filter(n => !n.read).length;
  const badge = document.getElementById('notification-badge');
  if (unread > 0) {
    badge.textContent = unread > 9 ? '9+' : unread;
    badge.classList.remove('hidden');
  } else {
    badge.classList.add('hidden');
  }
}

function clearNotifications() {
  notifications = [];
  updateNotificationBadge();
  renderNotifications();
}

function renderNotifications() {
  const list = document.getElementById('notification-list');
  if (!list) return;
  // Mark all as read when panel is opened
  notifications.forEach(n => { n.read = true; });
  updateNotificationBadge();
  if (notifications.length === 0) {
    list.innerHTML = '<div class="p-6 text-center text-xs text-slate-500">No notifications</div>';
    return;
  }
  const typeConfig = {
    error:   { dot: 'notif-dot-error',   icon: '!', label: 'Error' },
    warning: { dot: 'notif-dot-warning', icon: '!', label: 'Warning' },
    info:    { dot: 'notif-dot-info',    icon: 'i', label: 'Info' },
    success: { dot: 'notif-dot-success', icon: '✓', label: 'Success' },
  };
  list.innerHTML = notifications.map(n => {
    const cfg = typeConfig[n.type] || typeConfig.info;
    const timeAgo = formatTimeAgo(n.timestamp);
    const clickAttr = n.traceId ? `onclick="openTrace('${escHtml(n.traceId)}');toggleNotificationPanel();" style="cursor:pointer"` : '';
    return `
      <div class="flex gap-3 p-3 notif-row transition" ${clickAttr}>
        <div class="flex-shrink-0 w-2 h-2 rounded-full ${cfg.dot} mt-1.5"></div>
        <div class="min-w-0 flex-1">
          <div class="text-xs font-semibold notif-title">${escHtml(n.title)}</div>
          <div class="text-[11px] notif-msg mt-0.5 break-words">${escHtml(n.message)}</div>
          <div class="text-[10px] notif-time mt-1">${timeAgo}</div>
        </div>
      </div>`;
  }).join('');
}

// ==================================================================// Live Activity Feed
// ==================================================================
function addToLiveFeed(event) {
  // event: { agent, action, status, timestamp }
  _liveFeedEvents.unshift({
    agent: event.agent || 'unknown',
    action: event.action || 'Event',
    status: event.status || 'ok', // 'ok', 'error'
    timestamp: event.timestamp || Date.now() / 1000,
  });
  if (_liveFeedEvents.length > _LIVE_FEED_MAX) {
    _liveFeedEvents = _liveFeedEvents.slice(0, _LIVE_FEED_MAX);
  }
  renderLiveFeed();
}

function renderLiveFeed() {
  const container = document.getElementById('live-activity-feed');
  if (!container) return;
  if (_liveFeedEvents.length === 0) {
    container.innerHTML = '<div class="px-4 py-6 text-center text-xs live-feed-empty">Waiting for activity...</div>';
    return;
  }
  container.innerHTML = _liveFeedEvents.map(ev => {
    const p = getAgentProfile(ev.agent);
    const timeAgo = formatTimeAgo(ev.timestamp);
    const isError = ev.status === 'error';
    const dotStyle = isError ? 'background:var(--color-coral,#e07a5f)' : 'background:var(--color-sage,#81b29a)';
    const rowClass = isError ? 'live-feed-row-error' : '';
    return `<div class="live-feed-row flex items-center gap-3 px-4 py-2.5 ${rowClass}">
      <span class="flex-shrink-0 text-[10px] live-feed-time w-12 text-right">${timeAgo}</span>
      <div class="flex-shrink-0 w-5 h-5 rounded-md flex items-center justify-center text-[10px] font-bold" style="background:${p.color}22;color:${p.color}">${(p.name||'?')[0]}</div>
      <span class="flex-1 text-xs live-feed-action truncate">${escHtml(ev.action)}</span>
      <span class="flex-shrink-0 w-1.5 h-1.5 rounded-full" style="${dotStyle}"></span>
    </div>`;
  }).join('');

  // Auto-scroll to top (newest first)
  container.scrollTop = 0;
}

// ==================================================================// API Helpers
// ==================================================================
async function apiFetch(path, opts = {}) {
  try {
    const res = await fetch(`${API_BASE}${path}`, opts);
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`HTTP ${res.status}: ${text}`);
    }
    return await res.json();
  } catch (err) {
    console.error(`API error [${path}]:`, err);
    throw err;
  }
}

function updateRefreshTime() {
  const el = document.getElementById('last-refresh');
  el.textContent = `Updated ${new Date().toLocaleTimeString()}`;
}

// ==================================================================// Utilities
// ==================================================================
function escHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = String(str);
  return div.innerHTML;
}

function formatDuration(ms) {
  if (ms < 1) return '<1ms';
  if (ms < 1000) return ms.toFixed(0) + 'ms';
  return (ms / 1000).toFixed(2) + 's';
}

// ==================================================================// Toast Notifications
// ==================================================================
function showToast(message, type = 'info', duration = 4000) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');

  const icons = {
    info:    '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>',
    error:   '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"/>',
    success: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>',
    warning: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"/>',
  };

  toast.className = `toast-v14 toast-${type} pointer-events-auto`;
  toast.innerHTML = `
    <svg class="toast-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">${icons[type] || icons.info}</svg>
    <span class="flex-1 leading-snug">${escHtml(message)}</span>
    <div class="toast-progress"><div class="toast-progress-fill" id="tp-${Date.now()}"></div></div>
  `;
  container.appendChild(toast);

  // Animate progress bar countdown
  const fill = toast.querySelector('.toast-progress-fill');
  if (fill) {
    fill.style.transition = `transform ${duration}ms linear`;
    // Trigger reflow then start animation
    void fill.offsetWidth;
    fill.style.transform = 'scaleX(0)';
  }

  setTimeout(() => {
    toast.classList.add('toast-exit');
    setTimeout(() => toast.remove(), 300);
  }, duration);
}
// ==================================================================// View Switching (with smooth transitions)
// ==================================================================
function switchView(view) {
  currentView = view;
  selectedTraceIndex = -1;

  // Fade out current visible panel before switching
  const currentPanel = document.querySelector('.view-panel:not(.hidden)');
  if (currentPanel && currentPanel.id !== `view-${view}`) {
    currentPanel.classList.add('view-leaving');
    setTimeout(() => {
      currentPanel.classList.add('hidden');
      currentPanel.classList.remove('view-leaving');
    }, 150);
  } else if (!currentPanel) {
    document.querySelectorAll('.view-panel').forEach(p => p.classList.add('hidden'));
  }

  document.querySelectorAll('.tab-btn').forEach(b => { b.classList.remove('tab-active'); b.classList.add('tab-inactive'); });

  const panel = document.getElementById(`view-${view}`);
  if (panel) {
    // Delay showing new panel until leave animation completes
    const delay = currentPanel && currentPanel.id !== `view-${view}` ? 140 : 0;
    setTimeout(() => {
      document.querySelectorAll('.view-panel').forEach(p => { if (p !== panel) p.classList.add('hidden'); });
      panel.classList.remove('hidden');
      panel.classList.remove('view-enter', 'tab-fade-in');
      void panel.offsetWidth;
      panel.classList.add('view-enter', 'tab-fade-in');
    }, delay);
  }

  // Move the pill nav glider to the active tab
  _movePillGlider(view);

  const tabBtn = document.querySelector(`[data-tab="${view}"]`);
  if (tabBtn) { tabBtn.classList.remove('tab-inactive'); tabBtn.classList.add('tab-active'); }

  // Load data for the view
  if (view === 'overview') {
    loadStats();
    loadRecentTraces();
    setTimeout(() => { loadAgentActivity(); loadOverviewAgents(); }, 300);
    setTimeout(() => { loadActivityTimeline(); loadTrendChart(_trendHours || 24); loadOverviewCharts(); }, 600);
    setTimeout(() => { loadOverviewGraph(); }, 1200);
    setTimeout(() => { loadRecentFeedback(); }, 800);
  }
  else if (view === 'traces') { loadTraces(); }
  else if (view === 'sessions') { loadSessions(); }
  else if (view === 'cost') { loadCostData(); }
  else if (view === 'patterns') { loadAllPatterns(); }
  else if (view === 'compare') { renderCompareView(); }
  else if (view === 'agents') { loadAgentData(); }

  // Persist current view to sessionStorage
  try { sessionStorage.setItem('flowlens-view', view); } catch (_) {}
}

// ==================================================================// Agent Activity (Overview panel — real-time compact cards)
// ==================================================================
async function loadAgentActivity() {
  try {
    const data = await apiFetch('/v1/agents/activity');
    const bar = document.getElementById('agent-team-bar');
    const label = document.getElementById('team-status-label');
    if (!data.agents || data.agents.length === 0) {
      bar.innerHTML = '<p class="text-xs text-slate-500">No agents detected yet</p>';
      label.textContent = '';
      return;
    }
    const activeCount = data.agents.filter(a => a.status === 'active').length;
    label.textContent = `${activeCount} active / ${data.agents.length} total`;

    // Update summary metrics row
    const metricActiveEl = document.getElementById('metric-active-now');
    const metricOpsEl = document.getElementById('metric-ops-1h');
    if (metricActiveEl) metricActiveEl.textContent = activeCount;
    if (metricOpsEl) {
      const totalOps1h = data.agents.reduce((sum, a) => sum + (a.trace_count_1h || 0), 0);
      metricOpsEl.textContent = totalOps1h;
    }

    bar.innerHTML = data.agents.map((a, idx) => {
      const p = getAgentProfile(a.agent);
      const isActive = a.status === 'active';
      const borderClass = isActive ? 'border-emerald-500/40 shadow-emerald-500/10 shadow-lg' : 'border-white/5';
      const timeAgo = formatTimeAgo(a.last_seen);
      const delay = idx * 80;
      return `
        <div class="glass rounded-xl p-2 min-w-[130px] border ${borderClass} cursor-pointer hover:border-indigo-500/30 transition flex-shrink-0 card-3d-hover agent-team-card" style="animation-delay:${delay}ms" onclick="filterTracesByAgent('${escHtml(a.agent)}')">
          <div class="flex items-center gap-2 mb-1">
            ${renderAgentAvatar(a.agent, 'md')}
            <div class="min-w-0">
              <div class="text-[10px] font-semibold text-white truncate">${escHtml(p.name)}</div>
              <div class="text-[10px] text-slate-500">${escHtml(p.role)}</div>
            </div>
            ${isActive ? '<span class="w-2 h-2 rounded-full pulse-dot ml-auto flex-shrink-0" style="background:var(--color-sage,#81b29a)"></span>' : '<span class="w-2 h-2 rounded-full bg-slate-600 ml-auto flex-shrink-0"></span>'}
          </div>
          <div class="text-[10px] text-slate-500">${timeAgo} · ${a.trace_count_1h || 0} ops</div>
        </div>`;
    }).join('');
    renderLiveMonitor(data.agents);
  } catch (e) { /* silently fail */ }
}

// ==================================================================// Live Agent Monitor
// ==================================================================
let _monitorAgents = [];
let _termPanes = [];  // [{id, agent}]
let _termMinimized = false;
let _termPaneIdCounter = 0;
let _termLayout = 'single'; // current layout: 'single' | 'vsplit' | 'hsplit' | 'grid'

function renderLiveMonitor(agents) {
  const container = document.getElementById('live-monitor');
  const timeEl = document.getElementById('monitor-update-time');
  if (!container) return;

  _monitorAgents = agents || [];
  if (timeEl) timeEl.textContent = new Date().toLocaleTimeString();

  if (!agents || agents.length === 0) {
    container.innerHTML = '<p class="text-xs text-slate-500 col-span-full">Waiting for agents...</p>';
    return;
  }

  container.innerHTML = agents.map(a => {
    const p = getAgentProfile(a.agent);
    const isActive = a.status === 'active';

    return `
      <div class="monitor-agent-card rounded-lg p-2 transition-all duration-300 flex flex-col items-center gap-1 cursor-pointer hover:scale-105 hover:border-indigo-400/40" style="${isActive ? 'background:var(--color-sage-bg,rgba(129,178,154,0.08));border:1px solid var(--color-sage-border,rgba(129,178,154,0.22))' : 'background:rgba(30,41,59,0.3);border:1px solid rgba(255,255,255,0.05)'}" data-agent="${escHtml(a.agent)}" onclick="openAgentTerminal('${escHtml(a.agent)}')" oncontextmenu="event.preventDefault();_termShowContextMenu(event,'${escHtml(a.agent)}')">
        <div class="w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-bold text-white relative" style="background:${p.color}">
          ${(p.name||'?')[0]}
          <span class="absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full border border-slate-900 ${isActive ? 'pulse-dot' : ''}" style="background:${isActive ? 'var(--color-sage,#81b29a)' : '#475569'}"></span>
        </div>
        <span class="text-[10px] font-medium text-white truncate w-full text-center">${escHtml(p.name)}</span>
      </div>`;
  }).join('');
}

/** Open an agent in the floating tmux terminal — adds a pane */
async function openAgentTerminal(agentName) {
  // If already in a pane, flash it
  const existing = _termPanes.find(p => p.agent === agentName);
  if (existing) {
    const el = document.getElementById(`tmux-pane-${existing.id}`);
    if (el) { el.style.outline = '2px solid #22d3ee'; setTimeout(() => el.style.outline = '', 600); }
    if (_termMinimized) _termToggleMinimize();
    return;
  }

  _termPanes.push({ id: ++_termPaneIdCounter, agent: agentName });

  if (_termMinimized) _termMinimized = false;
  _termRender();
  await _termLoadPane(agentName);
}

/** Show right-click context menu for split options */
function _termShowContextMenu(event, agentName) {
  // Remove any existing menu
  _termHideContextMenu();

  const p = getAgentProfile(agentName);
  const menu = document.createElement('div');
  menu.id = 'tmux-ctx-menu';
  menu.className = 'tmux-ctx-menu';
  menu.style.left = event.clientX + 'px';
  menu.style.top = event.clientY + 'px';
  menu.innerHTML = `
    <div class="tmux-ctx-header">${escHtml(p.name)}</div>
    <div class="tmux-ctx-item" onclick="_termOpenWithLayout('${escHtml(agentName)}','vsplit')">
      <span style="opacity:0.6">▐</span> Vertical Split
    </div>
    <div class="tmux-ctx-item" onclick="_termOpenWithLayout('${escHtml(agentName)}','hsplit')">
      <span style="opacity:0.6">▄</span> Horizontal Split
    </div>
    <div class="tmux-ctx-item" onclick="_termOpenWithLayout('${escHtml(agentName)}','grid')">
      <span style="opacity:0.6">⊞</span> Grid
    </div>
    <div class="tmux-ctx-sep"></div>
    <div class="tmux-ctx-item" onclick="openAgentTerminal('${escHtml(agentName)}')">
      Open in Terminal
    </div>
  `;
  document.body.appendChild(menu);

  // Keep menu in viewport
  requestAnimationFrame(() => {
    const r = menu.getBoundingClientRect();
    if (r.right > window.innerWidth) menu.style.left = (window.innerWidth - r.width - 8) + 'px';
    if (r.bottom > window.innerHeight) menu.style.top = (window.innerHeight - r.height - 8) + 'px';
  });

  // Close on any click
  setTimeout(() => {
    document.addEventListener('click', _termHideContextMenu, { once: true });
    document.addEventListener('contextmenu', _termHideContextMenu, { once: true });
  }, 10);
}

function _termHideContextMenu() {
  const m = document.getElementById('tmux-ctx-menu');
  if (m) m.remove();
}

/** Right-click inside a terminal pane */
function _termPaneContextMenu(event, paneId) {
  _termHideContextMenu();
  const pane = _termPanes.find(p => p.id === paneId);
  if (!pane) return;

  // Build list of agents not yet open
  const openAgents = new Set(_termPanes.map(p => p.agent));
  const available = _monitorAgents.filter(a => !openAgents.has(a.agent));

  const menu = document.createElement('div');
  menu.id = 'tmux-ctx-menu';
  menu.className = 'tmux-ctx-menu';
  menu.style.left = event.clientX + 'px';
  menu.style.top = event.clientY + 'px';

  let items = `<div class="tmux-ctx-header">Split Pane</div>`;

  // Layout switches
  items += `<div class="tmux-ctx-item" onclick="_termSetLayout('vsplit')"><span style="opacity:0.6">▐</span> Vertical Split</div>`;
  items += `<div class="tmux-ctx-item" onclick="_termSetLayout('hsplit')"><span style="opacity:0.6">▄</span> Horizontal Split</div>`;
  items += `<div class="tmux-ctx-item" onclick="_termSetLayout('grid')"><span style="opacity:0.6">⊞</span> Grid</div>`;

  if (available.length > 0) {
    items += `<div class="tmux-ctx-sep"></div>`;
    items += `<div class="tmux-ctx-header">Add Agent</div>`;
    available.forEach(a => {
      const ap = getAgentProfile(a.agent);
      items += `<div class="tmux-ctx-item" onclick="_termHideContextMenu();openAgentTerminal('${escHtml(a.agent)}')"><span style="color:${ap.color};font-weight:700;">${(ap.name||'?')[0]}</span> ${escHtml(ap.name)}</div>`;
    });
  }

  items += `<div class="tmux-ctx-sep"></div>`;
  items += `<div class="tmux-ctx-item" onclick="_termHideContextMenu();_termClosePane(${paneId})"><span style="opacity:0.6">✕</span> Close This Pane</div>`;

  menu.innerHTML = items;
  document.body.appendChild(menu);

  requestAnimationFrame(() => {
    const r = menu.getBoundingClientRect();
    if (r.right > window.innerWidth) menu.style.left = (window.innerWidth - r.width - 8) + 'px';
    if (r.bottom > window.innerHeight) menu.style.top = (window.innerHeight - r.height - 8) + 'px';
  });

  setTimeout(() => {
    document.addEventListener('click', _termHideContextMenu, { once: true });
    document.addEventListener('contextmenu', _termHideContextMenu, { once: true });
  }, 10);
}

/** Set layout without reloading pane content */
function _termSetLayout(layout) {
  _termHideContextMenu();
  if (_termPanes.length < 2) return;
  _termLayout = layout;
  const w = document.getElementById('tmux-terminal');
  if (!w) return;
  const pc = w.querySelector('.tmux-panes');
  if (pc) pc.className = `tmux-panes tmux-${layout}`;
  _termRender();
}

/** Open agent with a specific layout */
async function _termOpenWithLayout(agentName, layout) {
  _termHideContextMenu();
  // Add the pane if not already present
  const existing = _termPanes.find(p => p.agent === agentName);
  if (!existing) {
    _termPanes.push({ id: ++_termPaneIdCounter, agent: agentName });
  }
  // Set requested layout
  _termLayout = _termPanes.length <= 1 ? 'single' : layout;
  if (_termMinimized) _termMinimized = false;
  _termRender();
  await _termLoadPane(agentName);
}

/** @deprecated — layout is now automatic grid */
function _termCycleLayout() { _termRender(); }

function _termRender() {
  let w = document.getElementById('tmux-terminal');
  const isNew = !w;
  if (isNew) {
    w = document.createElement('div');
    w.id = 'tmux-terminal';
    document.body.appendChild(w);
    _termMakeDraggable(w);
    _termMakeResizable(w);
  }

  if (_termMinimized) {
    w.className = 'tmux-widget tmux-minimized';
    w.innerHTML = `<div class="tmux-titlebar" id="tmux-drag-handle">
      <span style="font-size:10px;color:#94a3b8;padding:0 8px;">⬛ Terminal (${_termPanes.length} panes)</span>
      <div style="display:flex;gap:2px">
        <button onclick="_termToggleMinimize()" class="tmux-btn" title="Restore">▢</button>
        <button onclick="_termCloseAll()" class="tmux-btn tmux-btn-close">✕</button>
      </div>
    </div>`;
    return;
  }

  // Auto grid: cols = ceil(sqrt(n))
  const n = _termPanes.length;
  const cols = Math.ceil(Math.sqrt(n));

  w.className = 'tmux-widget';

  // Update titlebar
  let titlebar = w.querySelector('.tmux-titlebar');
  if (!titlebar) {
    titlebar = document.createElement('div');
    titlebar.className = 'tmux-titlebar';
    titlebar.id = 'tmux-drag-handle';
    w.prepend(titlebar);
  }
  titlebar.innerHTML = `
    <span style="font-size:10px;color:#94a3b8;padding:0 8px;font-family:monospace;">agent-terminal · ${n} pane${n>1?'s':''}</span>
    <div style="display:flex;gap:2px;align-items:center;">
      <button onclick="_termToggleMinimize()" class="tmux-btn" title="Minimize">─</button>
      <button onclick="_termCloseAll()" class="tmux-btn tmux-btn-close">✕</button>
    </div>`;

  // Get or create panes container
  let panesContainer = w.querySelector('.tmux-panes');
  if (!panesContainer) {
    panesContainer = document.createElement('div');
    panesContainer.className = 'tmux-panes';
    w.insertBefore(panesContainer, w.querySelector('.tmux-statusbar'));
  }
  panesContainer.className = 'tmux-panes';
  panesContainer.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;

  // Add only NEW panes — don't rebuild existing ones
  _termPanes.forEach(p => {
    if (document.getElementById(`tmux-pane-${p.id}`)) return; // already exists

    const prof = getAgentProfile(p.agent);
    const isActive = _monitorAgents.find(a => a.agent === p.agent)?.status === 'active';
    const dot = isActive ? '●' : '○';
    const dotColor = isActive ? '#34d399' : '#64748b';

    const paneEl = document.createElement('div');
    paneEl.className = 'tmux-pane';
    paneEl.id = `tmux-pane-${p.id}`;
    paneEl.addEventListener('contextmenu', e => { e.preventDefault(); _termPaneContextMenu(e, p.id); });
    paneEl.innerHTML = `
      <div class="tmux-pane-header">
        <span style="color:${prof.color};font-weight:700;">${(prof.name||'?')[0]}</span>
        <span style="color:#e2e8f0;font-weight:600;">${escHtml(prof.name)}</span>
        <span style="color:${dotColor};font-size:8px;">${dot}</span>
        <span style="color:#475569;font-size:10px;margin-left:auto;">${escHtml(prof.role)}</span>
        <button class="tmux-pane-close" onclick="_termClosePane(${p.id})" title="Close pane">×</button>
      </div>
      <div class="tmux-pane-body" id="tmux-pane-body-${p.id}">
        <div class="agent-term-line dim">Loading...</div>
      </div>`;
    panesContainer.appendChild(paneEl);
  });

  // Remove panes that no longer exist
  panesContainer.querySelectorAll('.tmux-pane').forEach(el => {
    const id = parseInt(el.id.replace('tmux-pane-', ''));
    if (!_termPanes.find(p => p.id === id)) el.remove();
  });

  // Update statusbar
  let statusbar = w.querySelector('.tmux-statusbar');
  if (!statusbar) {
    statusbar = document.createElement('div');
    statusbar.className = 'tmux-statusbar';
    w.appendChild(statusbar);
  }
  statusbar.innerHTML = `
    <span>${n} pane${n > 1 ? 's' : ''} · ${cols}×${Math.ceil(n/cols)}</span>
    <span style="color:#475569;">click agent to add pane</span>`;

  // Resize edge handles (all 8 edges/corners)
  if (!w.querySelector('.tmux-edge')) {
    ['r','b','l','t','br','bl','tl','tr'].forEach(edge => {
      const h = document.createElement('div');
      h.className = `tmux-edge tmux-edge-${edge}`;
      h.dataset.edge = edge;
      w.appendChild(h);
    });
  }
}

async function _termLoadPane(agentName) {
  const pane = _termPanes.find(p => p.agent === agentName);
  if (!pane) return;
  const body = document.getElementById(`tmux-pane-body-${pane.id}`);
  if (!body) return;

  try {
    const data = await apiFetch('/v1/activity/stream?limit=200');
    const events = (data.events || []).filter(ev => ev.agent === agentName);

    // Fetch span details for richer output
    const traceIds = [...new Set(events.map(e => e.trace_id).filter(Boolean))].slice(0, 5);
    const spanDetails = {};
    await Promise.all(traceIds.map(async tid => {
      try {
        const t = await apiFetch(`/v1/traces/${tid}`);
        (t.spans || []).forEach(s => {
          const attrs = s.attributes || {};
          if (attrs['agent.name'] === agentName || (s.name || '').startsWith(agentName + '/')) {
            spanDetails[s.span_id] = s;
          }
        });
      } catch (_) {}
    }));

    if (events.length === 0) {
      body.innerHTML = '<div class="agent-term-line dim">~ no recent activity ~</div>';
      return;
    }

    body.innerHTML = events.slice(0, 30).map(ev => _termFormatLine(ev, spanDetails)).join('');
    body.scrollTop = body.scrollHeight;
  } catch (e) {
    body.innerHTML = `<div class="agent-term-line error">Error: ${escHtml(String(e))}</div>`;
  }
}

function _termFormatLine(ev, spanDetails) {
  const time = new Date(ev.timestamp * 1000);
  const timeStr = time.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const isError = ev.status === 'error';
  const tool = ev.tool || '?';
  const durStr = ev.duration_ms > 0 ? `<span class="agent-term-dur">${Math.round(ev.duration_ms)}ms</span>` : '';
  const icons = { Read:'📄', Edit:'✏️', Write:'📝', Bash:'⚡', Grep:'🔍', Glob:'📂', Agent:'🤖' };
  const icon = icons[tool] || '●';

  let detail = '';
  const matchingSpan = Object.values(spanDetails || {}).find(s =>
    Math.abs((s.start_time||0) - ev.timestamp) < 2 && (s.name||'').includes(tool));

  if (matchingSpan) {
    const attrs = matchingSpan.attributes || {};
    const input = attrs['tool.input'] || '';
    if (['Read','Write','Edit'].includes(tool)) {
      const m = input.match(/file_path=([^\s;,]+)/);
      if (m) detail = m[1].split('/').slice(-3).join('/');
    } else if (tool === 'Bash') {
      const m = input.match(/command=(.+?)(?:;|$)/);
      if (m) detail = m[1].substring(0, 80);
    } else if (tool === 'Grep') {
      const m = input.match(/pattern=(.+?)(?:;|$)/);
      if (m) detail = `/${m[1].substring(0, 40)}/`;
    } else if (tool === 'Glob') {
      const m = input.match(/pattern=(.+?)(?:;|$)/);
      if (m) detail = m[1].substring(0, 50);
    }
    const model = attrs['gen_ai.request.model'];
    if (model && !detail) detail = model;
  }
  if (!detail && isError && ev.error) detail = ev.error.substring(0, 60);
  const detailHtml = detail ? `<span class="agent-term-detail">${escHtml(detail)}</span>` : '';

  return `<div class="agent-term-line ${isError ? 'error' : ''}">`+
    `<span class="agent-term-time">${timeStr}</span>`+
    `<span class="agent-term-icon">${icon}</span>`+
    `<span class="agent-term-tool">${escHtml(tool)}</span>`+
    durStr + detailHtml + `</div>`;
}

function _termClosePane(paneId) {
  _termPanes = _termPanes.filter(p => p.id !== paneId);
  const el = document.getElementById(`tmux-pane-${paneId}`);
  if (el) el.remove();
  if (_termPanes.length === 0) { _termCloseAll(); return; }
  // Recalculate grid columns
  const pc = document.querySelector('.tmux-panes');
  if (pc) pc.style.gridTemplateColumns = `repeat(${Math.ceil(Math.sqrt(_termPanes.length))}, 1fr)`;
  _termRender();
}

function _termCloseAll() {
  _termPanes = []; _termLayout = 'single';
  const w = document.getElementById('tmux-terminal');
  if (w) w.remove();
}

function _termToggleMinimize() {
  _termMinimized = !_termMinimized;
  if (_termMinimized) {
    // Minimizing — just hide the widget contents, keep pane data
    _termRender();
  } else {
    // Restoring — need to rebuild panes and reload
    const w = document.getElementById('tmux-terminal');
    if (w) w.innerHTML = ''; // clear minimized view
    _termRender();
    _termPanes.forEach(p => _termLoadPane(p.agent));
  }
}

function _termMakeDraggable(el) {
  let isDrag = false, startX, startY, origX, origY;
  el.addEventListener('mousedown', e => {
    if (e.target.closest('button, .tmux-pane-close, .tmux-resize-handle')) return;
    const handle = e.target.closest('.tmux-titlebar');
    if (!handle) return;
    isDrag = true; startX = e.clientX; startY = e.clientY;
    const rect = el.getBoundingClientRect();
    origX = rect.left; origY = rect.top; e.preventDefault();
  });
  document.addEventListener('mousemove', e => {
    if (!isDrag) return;
    el.style.left = (origX + e.clientX - startX) + 'px';
    el.style.top = (origY + e.clientY - startY) + 'px';
    el.style.right = 'auto'; el.style.bottom = 'auto';
  });
  document.addEventListener('mouseup', () => { isDrag = false; });
}

function _termMakeResizable(el) {
  let edge = null, startX, startY, origW, origH, origL, origT;

  el.addEventListener('mousedown', e => {
    const edgeEl = e.target.closest('.tmux-edge');
    if (!edgeEl) return;
    edge = edgeEl.dataset.edge;
    startX = e.clientX; startY = e.clientY;
    const rect = el.getBoundingClientRect();
    origW = rect.width; origH = rect.height;
    origL = rect.left; origT = rect.top;
    e.preventDefault(); e.stopPropagation();
    document.body.style.cursor = getComputedStyle(edgeEl).cursor;
    document.body.style.userSelect = 'none';
  });

  document.addEventListener('mousemove', e => {
    if (!edge) return;
    const dx = e.clientX - startX, dy = e.clientY - startY;
    let newW = origW, newH = origH, newL = origL, newT = origT;

    // Right edges
    if (edge.includes('r')) newW = Math.max(360, origW + dx);
    // Left edges
    if (edge.includes('l')) { newW = Math.max(360, origW - dx); newL = origL + origW - newW; }
    // Bottom edges
    if (edge.includes('b')) newH = Math.max(180, origH + dy);
    // Top edges
    if (edge.includes('t')) { newH = Math.max(180, origH - dy); newT = origT + origH - newH; }

    el.style.width = newW + 'px';
    el.style.height = newH + 'px';
    el.style.left = newL + 'px';
    el.style.top = newT + 'px';
    el.style.right = 'auto';
    el.style.bottom = 'auto';
  });

  document.addEventListener('mouseup', () => {
    edge = null;
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  });
}

// ==================================================================// Agent Overview
// ==================================================================
async function loadAgentData() {
  const grid = document.getElementById('agents-grid');
  if (!grid) return;
  grid.innerHTML = '<p class="text-xs text-slate-500 col-span-full">Loading...</p>';
  try {
    // Fetch both summary stats and live activity in parallel
    const [summaryResp, activityData] = await Promise.all([
      fetch('/v1/agents/summary'),
      apiFetch('/v1/agents/activity').catch(() => ({ agents: [] })),
    ]);
    if (!summaryResp.ok) throw new Error(`HTTP ${summaryResp.status}`);
    const data = await summaryResp.json();
    const agents = data.agents || [];
    if (agents.length === 0) {
      grid.innerHTML = '<p class="text-xs text-slate-500 col-span-full">No agent data found. Ingest traces with a <code>tags.agent</code> field to populate this view.</p>';
      return;
    }

    // Build activity lookup by agent name
    const activityByAgent = {};
    (activityData.agents || []).forEach(a => { activityByAgent[a.agent] = a; });

    // Populate stats summary bar
    const totalAgents = agents.length;
    const activeAgents = agents.filter(a => { const act = activityByAgent[a.agent]; return act && act.status === 'active'; }).length;
    const totalCost = agents.reduce((s, a) => s + (a.total_cost_usd || 0), 0);
    const totalTraces = agents.reduce((s, a) => s + (a.trace_count || 0), 0);
    const elTotal = document.getElementById('agent-stat-total');
    const elActive = document.getElementById('agent-stat-active');
    const elCost = document.getElementById('agent-stat-cost');
    const elTraces = document.getElementById('agent-stat-traces');
    if (elTotal) elTotal.textContent = totalAgents;
    if (elActive) elActive.textContent = activeAgents;
    if (elCost) elCost.textContent = totalCost < 1 ? '$' + totalCost.toFixed(4) : '$' + totalCost.toFixed(2);
    if (elTraces) elTraces.textContent = totalTraces.toLocaleString();

    grid.innerHTML = agents.map(a => {
      const errPct = (a.error_rate * 100).toFixed(1);
      const errColor = a.error_rate < 0.05 ? 'stat-trend-up' : a.error_rate < 0.20 ? 'text-amber-400' : 'stat-trend-down';
      const latency = a.avg_duration_ms >= 1000
        ? (a.avg_duration_ms / 1000).toFixed(2) + 's'
        : a.avg_duration_ms.toFixed(0) + 'ms';
      const cost = a.total_cost_usd < 0.01
        ? '$' + a.total_cost_usd.toFixed(6)
        : '$' + a.total_cost_usd.toFixed(4);

      const activity = activityByAgent[a.agent] || null;
      const isActive = activity && activity.status === 'active';
      const statusColor = isActive ? 'status-dot-active' : 'status-dot-idle';
      const statusLabel = isActive ? 'active' : 'idle';
      const statusBadgeBg = isActive ? 'status-badge status-badge-active' : 'status-badge status-badge-idle';
      const recentTools = activity ? (activity.recent_tools || []).slice(0, 5) : [];
      const toolsHtml = recentTools.length > 0
        ? recentTools.map(t => `<span class="px-1.5 py-0.5 text-[10px] rounded bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">${escHtml(t)}</span>`).join(' ')
        : '<span class="text-[10px] text-slate-600">no recent tools</span>';
      const opsLastHour = activity ? activity.trace_count_1h : 0;

      // Mini activity bar: 24 dots representing last 24h — taller + fully rounded
      const activityDots = [];
      for (let h = 0; h < 24; h++) {
        const hasActivity = activity && activity.hourly_counts ? (activity.hourly_counts[h] || 0) > 0 : (Math.random() < Math.min(0.7, (a.trace_count || 1) / 100));
        const dotColor = hasActivity ? (isActive ? '#81b29a' : '#6b5ce7') : (isDarkTheme ? '#1e293b' : '#e2e8f0');
        const dotOpacity = hasActivity ? '1' : '0.5';
        activityDots.push(`<span class="activity-dot-v14" style="background:${dotColor};opacity:${dotOpacity}" title="Hour ${h}"></span>`);
      }

      const p = getAgentProfile(a.agent);
      const avatarInitial = (p.name || a.agent).charAt(0).toUpperCase();
      const avatarBg = p.color || '#6b5ce7';

      // Large avatar (56px) with shadow + ring in agent color
      const largeAvatarHtml = `<div class="agent-avatar-lg" style="background:${avatarBg}1a;border:2px solid ${avatarBg}50;box-shadow:0 4px 16px ${avatarBg}30;position:relative;display:flex;align-items:center;justify-content:center;">
        <span style="font-size:22px;font-weight:700;color:${avatarBg}">${avatarInitial}</span>
        ${isActive ? `<span style="position:absolute;bottom:-2px;right:-2px;width:13px;height:13px;border-radius:50%;background:#81b29a;border:2px solid var(--bg-base, #0f172a);box-shadow:0 0 6px #81b29a60;"></span>` : ''}
      </div>`;

      // Status badge using new design
      const statusBadgeClass = isActive ? 'status-badge status-badge-active' : 'status-badge status-badge-idle';
      const statusDotHtml = isActive
        ? `<span style="width:6px;height:6px;border-radius:50%;background:#81b29a;display:inline-block;"></span>`
        : `<span style="width:6px;height:6px;border-radius:50%;background:#94a3b8;display:inline-block;"></span>`;

      // Tool badges using monospace style
      const toolsHtmlV14 = recentTools.length > 0
        ? recentTools.map(t => `<span class="tool-badge">${escHtml(t)}</span>`).join(' ')
        : '<span class="text-[10px] text-slate-600">no recent tools</span>';

      // Store agent data for modal access
      const agentDataEncoded = escHtml(JSON.stringify({ agent: a.agent, trace_count: a.trace_count, error_rate: a.error_rate, avg_duration_ms: a.avg_duration_ms, total_cost_usd: a.total_cost_usd, total_spans: a.total_spans }));
      return `<div class="glass rounded-xl p-5 cursor-pointer border transition agent-card-polished" style="border-color:${avatarBg}18" onmouseover="this.style.borderColor='${avatarBg}45';this.style.boxShadow='0 8px 32px ${avatarBg}20'" onmouseout="this.style.borderColor='${avatarBg}18';this.style.boxShadow=''" onclick="openAgentDetailModal('${escHtml(a.agent)}', ${JSON.stringify(agentDataEncoded)})">
        <div class="flex items-center gap-3 mb-4">
          ${largeAvatarHtml}
          <div class="min-w-0 flex-1">
            <div class="text-base font-semibold text-white agents-grid-card-title truncate" title="${escHtml(a.agent)}">${escHtml(p.name || a.agent)}</div>
            <div class="text-[11px] text-slate-500 agents-grid-card-meta">${escHtml(p.role || 'Agent')}</div>
          </div>
          <span class="${statusBadgeClass}">${statusDotHtml}${statusLabel}</span>
        </div>
        <div class="agent-stats-row mb-3 text-xs">
          <div class="agent-stat-cell">
            <div class="text-[10px] text-slate-500 uppercase tracking-wider mb-0.5">Traces</div>
            <div class="text-white font-semibold agents-grid-card-title">${a.trace_count}</div>
          </div>
          <div class="agent-stat-cell">
            <div class="text-[10px] text-slate-500 uppercase tracking-wider mb-0.5">Errors</div>
            <div class="${errColor} font-semibold">${errPct}%</div>
          </div>
          <div class="agent-stat-cell">
            <div class="text-[10px] text-slate-500 uppercase tracking-wider mb-0.5">Cost</div>
            <div class="text-white font-semibold agents-grid-card-title">${cost}</div>
          </div>
          <div class="agent-stat-cell">
            <div class="text-[10px] text-slate-500 uppercase tracking-wider mb-0.5">Avg Lat</div>
            <div class="text-white font-semibold agents-grid-card-title">${latency}</div>
          </div>
        </div>
        <div class="mb-3">
          <div class="text-[10px] text-slate-500 uppercase tracking-wider mb-1.5">Activity (24h)</div>
          <div style="display:flex;align-items:flex-end;height:20px;">${activityDots.join('')}</div>
        </div>
        <div class="flex flex-wrap gap-1 mb-2">${toolsHtmlV14}</div>
        <div class="flex items-center justify-between text-[11px] text-slate-600 agents-grid-card-meta mb-2">
          <span>${a.total_spans} spans</span>
          <span>${opsLastHour} ops/hr</span>
        </div>
        <div class="agent-live-feed agent-live-feed-v14" id="agent-feed-${escHtml(a.agent)}" style="max-height:120px;overflow-y:auto;">
          <div class="text-[10px] text-slate-600 italic">Loading activity...</div>
        </div>
      </div>`;
    }).join('');

    // Load agent relationship graph after rendering cards
    loadAgentGraph();

    // Populate per-agent live activity feeds
    _loadAgentFeeds(agents.map(a => a.agent));
  } catch (err) {
    grid.innerHTML = `<p class="text-xs text-red-400 col-span-full">Failed to load agent data: ${escHtml(String(err))}</p>`;
  }
}

/** Fetch recent activity and distribute into per-agent feed panels */
async function _loadAgentFeeds(agentNames) {
  try {
    const data = await apiFetch('/v1/activity/stream?limit=200');
    const events = data.events || [];

    // Group events by agent
    const byAgent = {};
    agentNames.forEach(name => { byAgent[name] = []; });
    events.forEach(ev => {
      const agent = ev.agent || 'unknown';
      if (byAgent[agent]) {
        byAgent[agent].push(ev);
      }
    });

    // Render each agent's feed (max 8 events)
    for (const [agent, agentEvents] of Object.entries(byAgent)) {
      const feed = document.getElementById(`agent-feed-${agent}`);
      if (!feed) continue;

      const recent = agentEvents.slice(0, 8);
      if (recent.length === 0) {
        feed.innerHTML = '<div class="text-[10px] text-slate-600 italic py-1">No recent activity</div>';
        continue;
      }

      feed.innerHTML = recent.map(ev => {
        const timeAgo = formatTimeAgo(ev.timestamp);
        const isError = ev.status === 'error';
        const toolName = ev.tool || '?';
        const statusDot = isError
          ? '<span style="width:5px;height:5px;border-radius:50%;background:#ef4444;flex-shrink:0;display:inline-block;"></span>'
          : '<span style="width:5px;height:5px;border-radius:50%;background:#34d399;flex-shrink:0;display:inline-block;"></span>';
        const durStr = ev.duration_ms > 0 ? `${Math.round(ev.duration_ms)}ms` : '';
        const errorHint = isError && ev.error ? ` — ${escHtml(ev.error).substring(0, 40)}` : '';

        return `<div class="flex items-center gap-1.5 py-0.5 text-[10px] leading-tight" style="color:${isError ? 'var(--color-coral,#e07a5f)' : 'inherit'};opacity:${isError ? 1 : 0.7}" title="${escHtml(toolName)} ${durStr}${errorHint}">
          ${statusDot}
          <span class="font-medium" style="min-width:48px;color:${isError ? 'var(--color-coral,#e07a5f)' : 'inherit'}">${escHtml(toolName)}</span>
          <span class="text-slate-600 flex-1 truncate">${durStr}${errorHint}</span>
          <span class="text-slate-600 flex-shrink-0">${timeAgo}</span>
        </div>`;
      }).join('');
    }
  } catch (e) {
    console.warn('Agent feeds:', e);
  }
}

function filterTracesByAgent(agentName) {
  _tracesAgentFilter = agentName || null;
  switchView('traces');
}
// ==================================================================// Agent Detail Modal
// ==================================================================
async function openAgentDetailModal(agentName, _encodedData) {
  const modal = document.getElementById('agent-detail-modal');
  const titleEl = document.getElementById('agent-modal-title');
  const bodyEl = document.getElementById('agent-modal-body');
  if (!modal || !bodyEl) return;

  const p = getAgentProfile(agentName);
  titleEl.textContent = p.name || agentName;

  // Show loading state
  bodyEl.innerHTML = '<p class="text-xs text-slate-500">Loading...</p>';
  modal.classList.remove('hidden');

  try {
    // Fetch all-time stats, live activity, recent traces and activity stream in parallel
    const [summaryData, activityData, tracesData, activityStream] = await Promise.all([
      apiFetch('/v1/agents/summary').catch(() => ({ agents: [] })),
      apiFetch('/v1/agents/activity').catch(() => ({ agents: [] })),
      apiFetch(`/v1/traces?limit=10&agent=${encodeURIComponent(agentName)}`).catch(() => ({ traces: [] })),
      apiFetch('/v1/activity/stream?limit=20').catch(() => ({ activities: [] })),
    ]);

    const agentStats = (summaryData.agents || []).find(a => a.agent === agentName) || null;
    const agentActivity = (activityData.agents || []).find(a => a.agent === agentName) || null;
    const recentTraces = tracesData.traces || [];

    // Filter activity stream for this agent
    const agentActivities = (activityStream.activities || []).filter(ev => ev.agent === agentName);

    // Large SVG avatar using profile icon and gradient background
    const avatarLg = `<div class="w-16 h-16 rounded-xl bg-gradient-to-br ${p.bgClass} flex items-center justify-center flex-shrink-0" style="color:${p.color}">${p.icon}</div>`;

    const errPct = agentStats ? (agentStats.error_rate * 100).toFixed(1) + '%' : '--';
    const errColor = agentStats && agentStats.error_rate < 0.05 ? 'stat-trend-up' : agentStats && agentStats.error_rate < 0.20 ? 'text-amber-400' : 'stat-trend-down';
    const latency = agentStats ? (agentStats.avg_duration_ms >= 1000 ? (agentStats.avg_duration_ms / 1000).toFixed(2) + 's' : agentStats.avg_duration_ms.toFixed(0) + 'ms') : '--';
    const cost = agentStats ? (agentStats.total_cost_usd < 0.01 ? '$' + agentStats.total_cost_usd.toFixed(6) : '$' + agentStats.total_cost_usd.toFixed(4)) : '--';
    const totalTraces = agentStats ? agentStats.trace_count : '--';
    const totalSpans = agentStats ? agentStats.total_spans : '--';

    // Activity mini-timeline from stream filtered by agent
    const activityTimelineHtml = agentActivities.length === 0
      ? '<p class="text-[10px] text-slate-500 py-2">No recent activity found.</p>'
      : agentActivities.slice(0, 20).map(ev => {
          const actionLabel = escHtml(ev.action || ev.tool || ev.type || 'Event');
          const timeLabel = ev.timestamp ? formatTimeAgo(ev.timestamp) : '';
          const dotStyle = ev.error ? 'background:var(--color-coral,#e07a5f)' : 'background:var(--color-sage,#81b29a)';
          return `<div class="flex items-center gap-2 py-1.5 text-xs">
            <span class="w-1 h-1 rounded-full flex-shrink-0" style="${dotStyle}"></span>
            <span class="text-slate-300 truncate flex-1">${actionLabel}</span>
            <span class="text-slate-500 ml-auto flex-shrink-0">${timeLabel}</span>
          </div>`;
        }).join('');

    // Error history from recent traces that have errors
    const errorTraces = recentTraces.filter(t => t.has_error || t.error);
    const errorHistoryHtml = errorTraces.length === 0 ? '' : `
      <div class="mb-4">
        <div class="text-xs font-semibold uppercase tracking-wider mb-2" style="color:var(--color-coral,#e07a5f)">Error History (${errorTraces.length})</div>
        <div class="rounded-lg p-3 max-h-[150px] overflow-y-auto" style="border:1px solid var(--color-coral-border,rgba(224,122,95,0.28));background:var(--color-coral-bg,rgba(224,122,95,0.08))">
          ${errorTraces.map(t => {
            const traceTime = t.start_time ? new Date(t.start_time * 1000).toLocaleTimeString() : '';
            return `<div class="flex items-center gap-2 py-1 text-xs cursor-pointer rounded px-1 agent-error-trace-row" onclick="closeAgentDetailModal();openTrace('${escHtml(t.trace_id)}')">
              <span class="w-1.5 h-1.5 rounded-full flex-shrink-0" style="background:var(--color-coral,#e07a5f)"></span>
              <span class="truncate flex-1" style="color:var(--color-coral,#e07a5f);opacity:0.9">${escHtml(t.service_name || t.trace_id.substring(0, 12))}</span>
              <span class="flex-shrink-0" style="color:var(--color-coral,#e07a5f);opacity:0.7">${traceTime}</span>
            </div>`;
          }).join('')}
        </div>
      </div>`;

    const recentTracesHtml = recentTraces.length === 0
      ? '<p class="text-[10px] text-slate-500 py-2">No recent traces found.</p>'
      : recentTraces.map(t => {
          const isError = t.has_error || t.error;
          const statusDotStyle = isError ? 'background:var(--color-coral,#e07a5f)' : 'background:var(--color-sage,#81b29a)';
          const traceTime = t.start_time ? new Date(t.start_time * 1000).toLocaleTimeString() : '';
          return `<div class="flex items-center gap-2 py-1.5 border-b border-white/5 text-xs cursor-pointer hover:bg-white/[0.02] rounded px-1" onclick="closeAgentDetailModal();openTrace('${escHtml(t.trace_id)}')">
            <span class="w-1.5 h-1.5 rounded-full flex-shrink-0" style="${statusDotStyle}"></span>
            <span class="text-white truncate flex-1">${escHtml(t.service_name || t.trace_id.substring(0, 12))}</span>
            <span class="text-slate-600 flex-shrink-0">${traceTime}</span>
          </div>`;
        }).join('');

    bodyEl.innerHTML = `
      <div class="flex items-center gap-4 mb-5">
        ${avatarLg}
        <div>
          <div class="text-lg font-semibold text-white">${escHtml(p.name || agentName)}</div>
          <div class="text-xs text-slate-500">${escHtml(p.role || 'Agent')}</div>
          <div class="text-[10px] text-slate-600 mt-0.5 font-mono">${escHtml(agentName)}</div>
        </div>
      </div>
      <div class="grid grid-cols-2 gap-3 mb-5">
        <div class="glass rounded-lg p-3">
          <div class="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Total Traces</div>
          <div class="text-white font-semibold text-lg">${totalTraces}</div>
        </div>
        <div class="glass rounded-lg p-3">
          <div class="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Error Rate</div>
          <div class="${errColor} font-semibold text-lg">${errPct}</div>
        </div>
        <div class="glass rounded-lg p-3">
          <div class="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Avg Duration</div>
          <div class="text-white font-semibold text-lg">${latency}</div>
        </div>
        <div class="glass rounded-lg p-3">
          <div class="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Total Cost</div>
          <div class="text-white font-semibold text-lg">${cost}</div>
        </div>
        <div class="glass rounded-lg p-3 col-span-2">
          <div class="text-[10px] text-slate-500 uppercase tracking-wider mb-1">Total Spans</div>
          <div class="text-white font-semibold">${totalSpans}</div>
        </div>
      </div>
      <div class="mb-4">
        <div class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Activity Timeline</div>
        <div class="max-h-[200px] overflow-y-auto">${activityTimelineHtml}</div>
      </div>
      ${errorHistoryHtml}
      <div class="mb-4">
        <div class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Recent Traces (last 10)</div>
        <div class="max-h-[180px] overflow-y-auto">${recentTracesHtml}</div>
      </div>
      <button onclick="closeAgentDetailModal();filterTracesByAgent('${escHtml(agentName)}')" class="w-full px-3 py-2 text-xs font-medium bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg transition">
        View all traces for this agent
      </button>
    `;
  } catch (err) {
    bodyEl.innerHTML = `<p class="text-xs text-red-400">Failed to load agent details: ${escHtml(String(err))}</p>`;
  }
}

function closeAgentDetailModal() {
  const modal = document.getElementById('agent-detail-modal');
  if (modal) modal.classList.add('hidden');
}

function showDetailTab(tab) {
  document.querySelectorAll('.detail-panel').forEach(p => p.classList.add('hidden'));
  document.querySelectorAll('.dtab-btn').forEach(b => { b.classList.remove('tab-active'); b.classList.add('tab-inactive'); });

  const panel = document.getElementById(`detail-${tab}`);
  if (panel) panel.classList.remove('hidden');

  const btn = document.querySelector(`[data-dtab="${tab}"]`);
  if (btn) { btn.classList.remove('tab-inactive'); btn.classList.add('tab-active'); }

  // Show/hide DAG PNG export button
  const dagPngBtn = document.getElementById('btn-export-dag-png');
  if (dagPngBtn) dagPngBtn.classList.toggle('hidden', tab !== 'dag');

  if (tab === 'dag' && currentTraceId) loadDAG(currentTraceId);
}

function backToTraces() {
  document.getElementById('view-trace-detail').classList.add('hidden');
  closeSpanDetail();
  try { sessionStorage.removeItem('flowlens-trace-id'); } catch (_) {}
  if (currentView === 'overview') {
    document.getElementById('view-overview').classList.remove('hidden');
  } else {
    document.getElementById('view-traces').classList.remove('hidden');
  }
}

// ==================================================================// Counter Animation
// ==================================================================
function animateCounter(element, targetValue, duration = 800, prefix = '', suffix = '') {
  const startValue = 0;
  const startTime = performance.now();
  const isFloat = String(targetValue).includes('.');

  function update(currentTime) {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);
    // Ease out cubic
    const eased = 1 - Math.pow(1 - progress, 3);
    const current = startValue + (targetValue - startValue) * eased;

    if (isFloat) {
      element.textContent = prefix + current.toFixed(targetValue < 1 ? 1 : 4) + suffix;
    } else {
      element.textContent = prefix + Math.round(current).toLocaleString() + suffix;
    }

    if (progress < 1) requestAnimationFrame(update);
  }
  requestAnimationFrame(update);
}
// ==================================================================// Stats — with time window selector and trend indicators
// ==================================================================
/** Switch stat card time window and reload stats */
function setStatsWindow(window) {
  _statsWindow = window;
  // Update button active states
  ['hour', 'day', 'all'].forEach(w => {
    const btn = document.getElementById('stats-window-' + w);
    if (!btn) return;
    if (w === window) {
      btn.classList.add('active');
      btn.classList.remove('tab-inactive');
    } else {
      btn.classList.remove('active');
      btn.classList.add('tab-inactive');
    }
  });
  loadStats();
}

/** Render a trend arrow with color */
function renderTrend(current, previous) {
  if (!previous || previous === 0) return '';
  const pct = ((current - previous) / previous) * 100;
  const absPct = Math.abs(pct).toFixed(0);
  if (Math.abs(pct) < 1) return '<span class="text-slate-500 text-[10px]">—</span>';
  const up = pct > 0;
  const color = up ? 'stat-trend-up' : 'stat-trend-down';
  const arrow = up ? '↑' : '↓';
  return `<span class="${color} text-[10px] font-medium">${arrow}${absPct}%</span>`;
}

async function loadStats() {
  try {
    // Determine time range params for windowed stats
    const windowHours = _statsWindow === 'hour' ? 1 : _statsWindow === 'day' ? 24 : null;

    // Fetch trends data for the window + previous window (for trend comparison)
    let currentStats = null;
    let previousStats = null;

    if (windowHours) {
      // Use trends endpoint to get windowed aggregate stats
      const [currentTrend, previousTrend] = await Promise.all([
        apiFetch(`/v1/stats/trends?hours=${windowHours}&bucket_minutes=${windowHours <= 1 ? 5 : 60}`),
        apiFetch(`/v1/stats/trends?hours=${windowHours * 2}&bucket_minutes=${windowHours <= 1 ? 5 : 60}`),
      ]);
      // Aggregate current window buckets
      const allBuckets = currentTrend.buckets || [];
      const prevBuckets = (previousTrend.buckets || []).slice(0, Math.floor((previousTrend.buckets || []).length / 2));
      const curBuckets = (previousTrend.buckets || []).slice(Math.floor((previousTrend.buckets || []).length / 2));
      currentStats = {
        total_traces: curBuckets.reduce((s, b) => s + (b.trace_count || 0), 0),
        error_traces: curBuckets.reduce((s, b) => s + (b.error_count || 0), 0),
        total_cost: curBuckets.reduce((s, b) => s + (b.total_cost || 0), 0),
        total_tokens: curBuckets.reduce((s, b) => s + (b.total_tokens || 0), 0),
        avg_duration_ms: curBuckets.length ? curBuckets.reduce((s, b) => s + (b.avg_duration_ms || 0), 0) / curBuckets.length : 0,
        total_spans: allBuckets.reduce((s, b) => s + (b.span_count || 0), 0),
      };
      previousStats = {
        total_traces: prevBuckets.reduce((s, b) => s + (b.trace_count || 0), 0),
        error_traces: prevBuckets.reduce((s, b) => s + (b.error_count || 0), 0),
        total_cost: prevBuckets.reduce((s, b) => s + (b.total_cost || 0), 0),
      };
    } else {
      // All-time stats
      currentStats = await apiFetch('/v1/stats');
      // For all-time, compare against 24h window
      try {
        const trend24h = await apiFetch('/v1/stats/trends?hours=48&bucket_minutes=60');
        const buckets = trend24h.buckets || [];
        const half = Math.floor(buckets.length / 2);
        previousStats = {
          total_traces: buckets.slice(0, half).reduce((s, b) => s + (b.trace_count || 0), 0),
          total_cost: buckets.slice(0, half).reduce((s, b) => s + (b.total_cost || 0), 0),
        };
        currentStats._window_traces = buckets.slice(half).reduce((s, b) => s + (b.trace_count || 0), 0);
        currentStats._window_cost = buckets.slice(half).reduce((s, b) => s + (b.total_cost || 0), 0);
      } catch (_) {}
    }

    const stats = currentStats;

    const tracesEl = document.getElementById('stat-traces');
    const spansEl = document.getElementById('stat-spans');
    animateCounter(tracesEl, stats.total_traces || 0);
    // v17: stat-spans is now a static label "traces", clear any counter animation
    if (spansEl) spansEl.textContent = 'traces';

    // Trend: traces
    const tracesTrendEl = document.getElementById('stat-traces-trend');
    if (tracesTrendEl && previousStats) {
      const cur = windowHours ? stats.total_traces : (stats._window_traces || 0);
      tracesTrendEl.innerHTML = renderTrend(cur, previousStats.total_traces);
    }

    const errorPct = stats.total_traces > 0
      ? (stats.error_traces / stats.total_traces) * 100
      : 0;
    const errorRate = parseFloat(errorPct.toFixed(1));
    const errorRateEl = document.getElementById('stat-error-rate');
    if (errorRateEl) animateCounter(errorRateEl, errorRate, 800, '', '%');
    // stat-error-count was removed from HTML in v17; guard to avoid null error
    const errCountEl = document.getElementById('stat-error-count');
    if (errCountEl) errCountEl.textContent = `${stats.error_traces || 0} error traces`;
    const errorCard = document.getElementById('stat-card-error');
    if (errorCard) {
      // Use warm coral highlight instead of cold red when error rate is high
      errorCard.style.background = errorPct > 10 ? 'var(--color-coral-bg, rgba(224,122,95,0.10))' : '';
      errorCard.style.borderColor = errorPct > 10 ? 'var(--color-coral-border, rgba(224,122,95,0.28))' : '';
    }

    const latencyMs = stats.avg_duration_ms || 0;
    // Display latency in human-readable format: ms under 1s, seconds above
    const latencyEl = document.getElementById('stat-latency');
    const latencyUnitEl = document.getElementById('stat-latency-unit');
    if (latencyEl) {
      if (latencyMs <= 0) {
        latencyEl.textContent = '--';
        if (latencyUnitEl) latencyUnitEl.textContent = 'avg latency';
      } else if (latencyMs < 1000) {
        latencyEl.textContent = Math.round(latencyMs) + 'ms';
        if (latencyUnitEl) latencyUnitEl.textContent = 'avg latency';
      } else {
        latencyEl.textContent = (latencyMs / 1000).toFixed(1) + 's';
        if (latencyUnitEl) latencyUnitEl.textContent = 'avg latency';
      }
    }

    const totalCost = stats.total_cost || 0;
    animateCounter(document.getElementById('stat-cost'), totalCost, 800, '$', '');
    // Keep stat-tokens in DOM (v17 label is now "total cost" but tokens data still loads)
    const tokensEl = document.getElementById('stat-tokens');
    if (tokensEl) tokensEl.textContent = 'total cost';
    const costCard = document.getElementById('stat-card-cost');
    if (costCard) {
      costCard.classList.toggle('bg-amber-500/10', totalCost > 1);
      costCard.classList.toggle('border', totalCost > 1);
      costCard.classList.toggle('border-amber-500/30', totalCost > 1);
    }

    // Trend: cost
    const costTrendEl = document.getElementById('stat-cost-trend');
    if (costTrendEl && previousStats) {
      const cur = windowHours ? stats.total_cost : (stats._window_cost || 0);
      costTrendEl.innerHTML = renderTrend(cur, previousStats.total_cost);
    }

    // Update summary metrics — success rate
    const metricSuccessEl = document.getElementById('metric-success-rate');
    if (metricSuccessEl) {
      const successPct = stats.total_traces > 0
        ? ((1 - (stats.error_traces || 0) / stats.total_traces) * 100).toFixed(1)
        : '--';
      metricSuccessEl.textContent = successPct !== '--' ? successPct + '%' : '--';
    }

    // Update window label in stat cards
    const windowLabel = document.getElementById('stats-window-label');
    if (windowLabel) {
      windowLabel.textContent = _statsWindow === 'hour' ? 'Last Hour' : _statsWindow === 'day' ? 'Last 24h' : 'All Time';
    }

    updateRefreshTime();

    // Load sparklines in stat cards (non-blocking)
    loadSparklines();
  } catch (err) {
    updateWsStatus('error');
  }
}

// ==================================================================// Trace Row Rendering
// ==================================================================
function formatTimeAgo(timestamp) {
  if (!timestamp) return '--';
  const seconds = Math.floor(Date.now() / 1000 - timestamp);
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return Math.floor(seconds / 60) + 'm ago';
  if (seconds < 86400) return Math.floor(seconds / 3600) + 'h ago';
  return Math.floor(seconds / 86400) + 'd ago';
}

/** Build a smart one-line summary from spans array (e.g. "3 Read, 2 Bash, 1 Edit") */
function buildTraceSummary(trace) {
  const spans = trace.spans || [];
  if (spans.length === 0 && (trace.span_count || 0) === 0) return null;

  // Count by tool name (from span name suffix after "/")
  const toolCounts = {};
  spans.forEach(s => {
    const slash = (s.name || '').lastIndexOf('/');
    const tool = slash >= 0 ? s.name.substring(slash + 1) : (s.name || s.kind || 'span');
    toolCounts[tool] = (toolCounts[tool] || 0) + 1;
  });

  if (Object.keys(toolCounts).length === 0) {
    const count = trace.span_count || 0;
    return count > 0 ? `${count} span${count !== 1 ? 's' : ''}` : null;
  }

  // Sort by count desc, top 4 types
  const sorted = Object.entries(toolCounts).sort((a, b) => b[1] - a[1]).slice(0, 4);
  return sorted.map(([tool, n]) => `${n} ${tool}`).join(', ');
}

/** Map a tool name to a CSS pill class */
function _toolPillClass(toolName) {
  const t = (toolName || '').toLowerCase();
  if (t === 'read')    return 'tool-pill-read';
  if (t === 'bash')    return 'tool-pill-bash';
  if (t === 'edit')    return 'tool-pill-edit';
  if (t === 'write')   return 'tool-pill-write';
  if (t === 'glob')    return 'tool-pill-glob';
  if (t === 'grep')    return 'tool-pill-grep';
  if (t.includes('llm') || t.includes('chat') || t.includes('completion') || t.includes('claude') || t.includes('gpt')) return 'tool-pill-llm';
  return 'tool-pill-default';
}

/** Build colored tool pill HTML from span counts (top 4) */
function buildToolPillsHtml(trace) {
  const spans = trace.spans || [];
  if (spans.length === 0) return '';
  const toolCounts = {};
  spans.forEach(s => {
    const slash = (s.name || '').lastIndexOf('/');
    const tool = slash >= 0 ? s.name.substring(slash + 1) : (s.kind || 'span');
    toolCounts[tool] = (toolCounts[tool] || 0) + 1;
  });
  if (Object.keys(toolCounts).length === 0) return '';
  return Object.entries(toolCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([tool, n]) => `<span class="tool-pill ${_toolPillClass(tool)}">${n} ${escHtml(tool)}</span>`)
    .join('');
}

/** Return CSS class for a duration dot based on ms value */
function _durationDotClass(ms) {
  if (ms >= 5000) return 'duration-dot-slow';
  if (ms >= 1000) return 'duration-dot-medium';
  return 'duration-dot-fast';
}

function renderTraceRow(trace, compact = false) {
  const hasErrors = trace.has_errors === true || trace.has_errors === 1;
  const isEmpty = (trace.span_count || 0) === 0 && !(trace.spans && trace.spans.length > 0);
  const statusDot = hasErrors
    ? '<span class="w-2 h-2 rounded-full flex-shrink-0" style="background:var(--color-coral,#e07a5f)"></span>'
    : isEmpty
      ? '<span class="w-2 h-2 rounded-full bg-slate-600 flex-shrink-0" title="Empty trace"></span>'
      : '<span class="w-2 h-2 rounded-full flex-shrink-0" style="background:var(--color-sage,#81b29a)"></span>';

  const tags = trace.tags || {};
  const meta = trace.metadata || {};

  // Extract meaningful name
  const agentName = tags.agent || null;
  const projectName = tags.project || meta.project || (meta.cwd ? meta.cwd.split('/').pop() : null);

  // Build display name and agent badge
  let displayName = agentName || projectName || (trace.trace_id || '').substring(0, 12) + '...';
  let agentBadge = '';
  if (agentName) {
    const profile = getAgentProfile(agentName);
    agentBadge = `<span class="px-1.5 py-0.5 text-[10px] font-medium rounded border ${profile.badgeClass} inline-flex items-center gap-1">${escHtml(profile.name)}</span>`;
    displayName = projectName || trace.service_name || 'session';
  }

  // Smart one-line summary — colored tool pills
  const toolPillsHtml = buildToolPillsHtml(trace);
  const smartSummary = buildTraceSummary(trace);
  const summaryHtml = toolPillsHtml
    ? `<div class="flex flex-wrap gap-1 mt-1">${toolPillsHtml}</div>`
    : (smartSummary ? `<span class="text-[11px] text-slate-500 truncate">${escHtml(smartSummary)}</span>` : '');

  // Time ago and span count
  const timeAgo = formatTimeAgo(trace.start_time);
  const spanCount = trace.span_count || (trace.spans || []).length;
  const spanOps = `${spanCount} ops`;

  const durationNum = trace.duration_ms || 0;
  const duration = durationNum.toFixed(0);
  const cost = (trace.total_cost_usd || 0).toFixed(4);
  const durationDotClass = _durationDotClass(durationNum);

  const isSelected = compareSelection.includes(trace.trace_id);
  const _previewAttrs = !compact
    ? `onmouseenter="showTracePreview('${escHtml(trace.trace_id)}', event)" onmouseleave="hideTracePreview()"`
    : '';

  // Agent border color
  const agentProfile = agentName ? getAgentProfile(agentName) : null;
  const borderColor = agentProfile ? agentProfile.color : 'transparent';
  const errorRowClass = hasErrors ? 'trace-row-error-bg' : '';
  const emptyRowClass = isEmpty ? 'trace-empty-row' : '';

  // Rebuilt agent badge: warm pill using agent color
  let agentBadgeHtml = '';
  if (agentName) {
    const profile = getAgentProfile(agentName);
    agentBadgeHtml = `<span class="trace-agent-badge" style="background:${profile.color}18;color:${profile.color};border:1px solid ${profile.color}30">${escHtml(profile.name)}</span>`;
  }

  // Error count badge: coral style
  const errorBadgeHtml = hasErrors
    ? `<span class="trace-error-badge">${trace.error_count || 1} error${(trace.error_count || 1) > 1 ? 's' : ''}</span>`
    : '';

  // Mini duration bar (proportion of max 10s) — positioned as thin underline via CSS
  const durationPct = Math.min((durationNum / 10000) * 100, 100);
  const durationBarColor = durationNum > 5000 ? '#e07a5f' : durationNum > 2000 ? '#e6a65d' : '#6b5ce7';

  return `
    <div class="trace-row flex items-center gap-4 px-5 cursor-pointer transition group ${errorRowClass} ${emptyRowClass}" data-trace-id="${escHtml(trace.trace_id)}" data-agent="${escHtml(agentName || '')}" onclick="openTrace('${escHtml(trace.trace_id)}')" style="border-left-color:${borderColor}" ${_previewAttrs}>
      ${!compact ? `<input type="checkbox" class="compare-checkbox ${isSelected ? 'checked' : ''} w-3.5 h-3.5 rounded bg-surface-100 border-white/10 text-indigo-500 focus:ring-indigo-500/30 flex-shrink-0" title="Select for comparison" ${isSelected ? 'checked' : ''} onclick="event.stopPropagation(); toggleCompare('${escHtml(trace.trace_id)}', this)" />` : ''}
      ${statusDot}
      <div class="flex-1 min-w-0">
        <div class="flex items-center gap-2 flex-wrap">
          <span class="text-sm font-medium text-slate-200 group-hover:text-white transition">${escHtml(displayName)}</span>
          ${agentBadgeHtml}
          ${!agentName && trace.service_name ? `<span class="px-1.5 py-0.5 text-[10px] font-medium rounded bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">${escHtml(trace.service_name)}</span>` : ''}
          ${errorBadgeHtml}
          ${isEmpty ? '<span class="px-1.5 py-0.5 text-[10px] font-medium rounded bg-slate-700/40 text-slate-500 border border-slate-600/30">empty</span>' : ''}
          ${_feedbackRatedTraces.has(trace.trace_id) ? `<span class="trace-feedback-badge" title="Has feedback">&#9733; ${_tracesFeedbackRatings.has(trace.trace_id) ? _tracesFeedbackRatings.get(trace.trace_id).toFixed(1) : ''}</span>` : ''}
        </div>
        <div class="text-xs text-slate-500 mt-0.5 flex items-center gap-2 flex-wrap">
          <span>${timeAgo}</span>
          ${!compact ? `<span class="text-slate-600">·</span><span>${spanOps}</span>` : ''}
          ${summaryHtml}
        </div>
      </div>
      <div class="flex items-center gap-4 text-xs text-slate-500 trace-row-details flex-shrink-0">
        <div class="text-right w-[68px] flex-shrink-0">
          <div class="flex items-center justify-end gap-1">
            <span class="duration-dot ${durationDotClass}"></span>
            <span class="text-slate-400 tabular-nums">${duration}ms</span>
          </div>
          ${!compact ? `<div class="tabular-nums">$${cost}</div>` : ''}
        </div>
        ${compact ? `<div class="text-right w-[68px] flex-shrink-0"><div class="tabular-nums text-slate-400">$${cost}</div></div>` : ''}
        <svg class="w-4 h-4 text-slate-600 group-hover:text-slate-400 transition" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
      </div>
      ${!compact ? `<div class="trace-mini-duration" title="${duration}ms"><div class="trace-mini-duration-fill" style="width:${durationPct}%;background:${durationBarColor}"></div></div>` : ''}
    </div>
  `;
}

// ==================================================================// Empty State
// ==================================================================
function renderEmptyState(message, subMessage, showGettingStarted) {
  const gettingStarted = showGettingStarted ? `
    <div class="mt-6 w-full max-w-xl text-left empty-state-card rounded-xl p-5">
      <div class="flex items-center gap-2 mb-4">
        <div class="w-6 h-6 rounded-lg bg-indigo-500/15 flex items-center justify-center">
          <svg class="w-3.5 h-3.5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
        </div>
        <h3 class="text-xs font-semibold text-indigo-400 uppercase tracking-wider">Get Started in 3 Steps</h3>
      </div>
      <div class="space-y-4">
        <div class="flex gap-3">
          <span class="flex-shrink-0 w-5 h-5 rounded-full bg-indigo-500/20 text-indigo-400 flex items-center justify-center text-[10px] font-bold">1</span>
          <div class="min-w-0 flex-1">
            <p class="text-xs font-medium empty-state-step-label mb-1">Install FlowLens</p>
            <code class="text-[11px] text-indigo-400 empty-state-code px-3 py-1.5 rounded-lg block font-mono">pip install flowlens</code>
          </div>
        </div>
        <div class="flex gap-3">
          <span class="flex-shrink-0 w-5 h-5 rounded-full bg-indigo-500/20 text-indigo-400 flex items-center justify-center text-[10px] font-bold">2</span>
          <div class="min-w-0 flex-1">
            <p class="text-xs font-medium empty-state-step-label mb-1">Wrap your agent with a trace</p>
            <code class="text-[11px] text-indigo-400 empty-state-code px-3 py-1.5 rounded-lg block font-mono whitespace-pre">from flowlens import tracer
with tracer.start_trace("my-agent"):
    result = my_agent.run()</code>
          </div>
        </div>
        <div class="flex gap-3">
          <span class="flex-shrink-0 w-5 h-5 rounded-full bg-indigo-500/20 text-indigo-400 flex items-center justify-center text-[10px] font-bold">3</span>
          <div class="min-w-0 flex-1">
            <p class="text-xs font-medium empty-state-step-label mb-1">Or run the demo to see it in action</p>
            <code class="text-[11px] empty-state-code px-3 py-1.5 rounded-lg block font-mono" style="color:var(--color-sage,#81b29a)">flowlens demo --dashboard</code>
            <p class="text-[10px] empty-state-hint mt-1.5">Generates sample traces and opens this dashboard automatically.</p>
          </div>
        </div>
      </div>
      <div class="mt-4 pt-3 empty-state-footer flex items-center gap-3">
        <a href="https://github.com/yusenthebot/flowlens#readme" target="_blank" class="text-[11px] text-indigo-400 hover:text-indigo-300 transition hover:underline">Documentation</a>
        <span class="empty-state-divider w-px h-3"></span>
        <a href="https://github.com/yusenthebot/flowlens/tree/main/examples" target="_blank" class="text-[11px] text-indigo-400 hover:text-indigo-300 transition hover:underline">Examples</a>
      </div>
    </div>
  ` : '';

  return `
    <div class="flex flex-col items-center justify-center py-12 px-8">
      <div class="empty-state-illustration">
        <svg width="80" height="64" viewBox="0 0 80 64" fill="none" xmlns="http://www.w3.org/2000/svg">
          <!-- Abstract warm illustration: flow arcs and dots -->
          <ellipse cx="40" cy="52" rx="32" ry="6" fill="url(#es-ground)" opacity="0.35"/>
          <path d="M12 40 Q20 16 40 20 Q60 24 68 40" stroke="url(#es-arc1)" stroke-width="2" stroke-linecap="round" fill="none" opacity="0.6"/>
          <path d="M20 40 Q28 24 40 26 Q52 28 60 40" stroke="url(#es-arc2)" stroke-width="1.5" stroke-linecap="round" fill="none" opacity="0.4"/>
          <circle cx="40" cy="20" r="5" fill="#6b5ce7" opacity="0.6"/>
          <circle cx="22" cy="36" r="3.5" fill="#e07a5f" opacity="0.5"/>
          <circle cx="58" cy="36" r="3.5" fill="#81b29a" opacity="0.5"/>
          <circle cx="40" cy="48" r="2.5" fill="#e6a65d" opacity="0.45"/>
          <circle cx="12" cy="40" r="2.5" fill="#a78bfa" opacity="0.45"/>
          <circle cx="68" cy="40" r="2.5" fill="#a78bfa" opacity="0.45"/>
          <defs>
            <linearGradient id="es-arc1" x1="12" y1="40" x2="68" y2="40" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stop-color="#6b5ce7"/>
              <stop offset="100%" stop-color="#81b29a"/>
            </linearGradient>
            <linearGradient id="es-arc2" x1="20" y1="40" x2="60" y2="40" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stop-color="#e07a5f"/>
              <stop offset="100%" stop-color="#e6a65d"/>
            </linearGradient>
            <linearGradient id="es-ground" x1="8" y1="52" x2="72" y2="52" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stop-color="#6b5ce7" stop-opacity="0"/>
              <stop offset="50%" stop-color="#6b5ce7" stop-opacity="1"/>
              <stop offset="100%" stop-color="#6b5ce7" stop-opacity="0"/>
            </linearGradient>
          </defs>
        </svg>
      </div>
      <p class="text-sm font-medium empty-state-title mb-1">${escHtml(message)}</p>
      <p class="text-xs empty-state-sub">${escHtml(subMessage || '')}</p>
      ${gettingStarted}
    </div>
  `;
}

// ==================================================================// Traces — List + Filtering
// ==================================================================
async function loadRecentTraces() {
  try {
    const data = await apiFetch('/v1/traces?limit=8');
    const container = document.getElementById('recent-traces-list');
    if (!data.traces || data.traces.length === 0) {
      container.innerHTML = renderEmptyState('No traces yet', 'Send traces via the SDK to get started.', true);
      return;
    }
    container.innerHTML = data.traces.map(t => renderTraceRow(t, true)).join('');

    // Load agent count from summary API for accurate Active Agents card
    try {
      const agentSummary = await apiFetch('/v1/agents/summary');
      const agents = (agentSummary.agents || []).filter(a => a.agent && a.agent !== 'unknown');
      const agentsEl = document.getElementById('stat-agents');
      const agentsSubEl = document.getElementById('stat-agents-sub');
      if (agentsEl) agentsEl.textContent = agents.length > 0 ? agents.length.toString() : '0';
      if (agentsSubEl) agentsSubEl.textContent = agents.length === 1 ? 'agent seen' : 'agents seen';
    } catch (_) {
      // fallback: count from trace tags
      const agentSet = new Set();
      for (const t of data.traces) {
        const agentName = (t.tags || {}).agent;
        if (agentName) agentSet.add(agentName);
      }
      const agentsEl = document.getElementById('stat-agents');
      const agentsSubEl = document.getElementById('stat-agents-sub');
      if (agentsEl) agentsEl.textContent = agentSet.size > 0 ? agentSet.size.toString() : '0';
      if (agentsSubEl) agentsSubEl.textContent = agentSet.size === 1 ? 'agent seen' : 'agents seen';
    }
  } catch (err) {
    document.getElementById('recent-traces-list').innerHTML = '<div class="p-8 text-center text-red-400/60 text-sm">Failed to load traces. Is the server running?</div>';
  }
}

let _tracesAgentFilter = null; // current agent filter for traces view
let _tracesStatusFilter = 'all';  // 'all' | 'success' | 'error'
let _tracesDurationFilter = 'all'; // 'all' | '>1s' | '>5s' | '>10s'
let _tracesTimeFilter = 'all';    // 'all' | '1h' | '6h' | '24h' | '7d'
let _tracesHideEmpty = false;     // hide traces with span_count === 0

// Feedback-related state
let _feedbackRatedTraces = new Set();         // trace IDs that have feedback (for badge display)
let _tracesFeedbackRatings = new Map();       // trace_id -> avg rating (for rating filter)
let _selectedStarRating = 0;                  // currently selected star rating in the feedback form

async function loadTraces() {
  renderQuickFilterBar();
  const service = document.getElementById('filter-service').value.trim() || null;
  const errorsOnly = document.getElementById('filter-errors').checked;

  let url = `/v1/traces?limit=${TRACE_LIMIT}&offset=${traceOffset}`;
  if (service) url += `&service=${encodeURIComponent(service)}`;
  if (errorsOnly) url += `&errors_only=true`;

  try {
    const data = await apiFetch(url);
    let traces = data.traces || [];

    // Client-side filtering for filters not supported by API
    traces = applyClientFilters(traces);

    // Compute summary stats before agent filter
    const totalCount = traces.length;
    const errorCount = traces.filter(t => t.has_errors === true || t.has_errors === 1).length;

    // Collect unique agents for filter pills
    const agentSet = new Map();
    traces.forEach(t => {
      const agent = (t.tags || {}).agent;
      if (agent) agentSet.set(agent, (agentSet.get(agent) || 0) + 1);
    });
    _renderTracesAgentPills(agentSet);

    // Apply agent filter
    if (_tracesAgentFilter) {
      traces = traces.filter(t => (t.tags || {}).agent === _tracesAgentFilter);
    }

    // Update summary bar
    const summaryBar = document.getElementById('traces-summary-bar');
    summaryBar.classList.remove('hidden');
    document.getElementById('traces-summary-total').textContent = traces.length;
    document.getElementById('traces-summary-filtered').textContent = totalCount;
    document.getElementById('traces-summary-errors').textContent = errorCount;

    const container = document.getElementById('traces-list');
    if (traces.length === 0) {
      container.innerHTML = renderEmptyState('No traces found', 'Try adjusting your filters.');
      document.getElementById('btn-prev').disabled = true;
      document.getElementById('btn-next').disabled = true;
      document.getElementById('page-info').textContent = 'No results';
      return;
    }
    renderVirtualizedTraces(traces, 'traces-list');

    document.getElementById('btn-prev').disabled = traceOffset === 0;
    document.getElementById('btn-next').disabled = data.traces.length < TRACE_LIMIT;
    document.getElementById('page-info').textContent = `Showing ${traceOffset + 1}-${traceOffset + traces.length}`;
    selectedTraceIndex = -1;
    updateRefreshTime();
  } catch (err) {
    document.getElementById('traces-list').innerHTML = '<div class="p-8 text-center text-red-400/60 text-sm">Failed to load traces.</div>';
  }
}

function _renderTracesAgentPills(agentMap) {
  const container = document.getElementById('traces-agent-pills');
  if (!container) return;
  if (agentMap.size === 0) { container.innerHTML = ''; return; }

  let html = `<span class="agent-filter-pill ${!_tracesAgentFilter ? 'active' : ''}" onclick="_tracesAgentFilter = null; loadTraces();">All</span>`;
  for (const [agent, count] of agentMap) {
    const profile = getAgentProfile(agent);
    const isActive = _tracesAgentFilter === agent;
    html += `<span class="agent-filter-pill ${isActive ? 'active' : ''}" onclick="_tracesAgentFilter = '${escHtml(agent)}'; loadTraces();" style="${isActive ? 'border-color:' + profile.color + ';color:' + profile.color : ''}">
      <span class="w-2 h-2 rounded-full flex-shrink-0" style="background:${profile.color}"></span>
      ${escHtml(profile.name)} <span style="opacity:0.5">(${count})</span>
    </span>`;
  }
  container.innerHTML = html;
}

/** Apply client-side filters (date range, token count, cost, span kind, status, duration, time window, empty) */
function applyClientFilters(traces) {
  const dateFrom = document.getElementById('filter-date-from').value;
  const dateTo = document.getElementById('filter-date-to').value;
  const tokensMin = document.getElementById('filter-tokens-min').value;
  const tokensMax = document.getElementById('filter-tokens-max').value;
  const costMin = document.getElementById('filter-cost-min').value;
  const costMax = document.getElementById('filter-cost-max').value;

  // Span kind filters
  const kindCheckboxes = document.querySelectorAll('.filter-kind:checked');
  const selectedKinds = Array.from(kindCheckboxes).map(cb => cb.value);

  // Time window cutoff
  const timeWindowMs = { '1h': 3600, '6h': 21600, '24h': 86400, '7d': 604800 };
  const cutoffSeconds = _tracesTimeFilter !== 'all'
    ? (Date.now() / 1000) - (timeWindowMs[_tracesTimeFilter] || 0)
    : null;

  // Duration threshold
  const durationThresh = { '>1s': 1000, '>5s': 5000, '>10s': 10000 };
  const minDurationMs = _tracesDurationFilter !== 'all' ? (durationThresh[_tracesDurationFilter] || 0) : 0;

  // Feedback filters
  const hasFeedbackFilter = document.getElementById('filter-has-feedback')?.checked || false;
  const ratingFilter = document.getElementById('filter-rating')?.value || '';

  return traces.filter(t => {
    // Hide empty traces toggle
    if (_tracesHideEmpty && (t.span_count || 0) === 0) return false;

    // Status filter
    if (_tracesStatusFilter === 'error' && !(t.has_errors === true || t.has_errors === 1)) return false;
    if (_tracesStatusFilter === 'success' && (t.has_errors === true || t.has_errors === 1)) return false;

    // Feedback filters (client-side using cached set)
    if (hasFeedbackFilter && !_feedbackRatedTraces.has(t.trace_id)) return false;
    if (ratingFilter === 'bad' && (!_feedbackRatedTraces.has(t.trace_id) || (_tracesFeedbackRatings.get(t.trace_id) || 5) > 2)) return false;
    if (ratingFilter === 'good' && (!_feedbackRatedTraces.has(t.trace_id) || (_tracesFeedbackRatings.get(t.trace_id) || 0) < 4)) return false;

    // Duration filter
    if (minDurationMs > 0 && (t.duration_ms || 0) < minDurationMs) return false;

    // Time window filter
    if (cutoffSeconds && t.start_time > 0 && t.start_time < cutoffSeconds) return false;

    // Date range filter
    if (dateFrom && t.start_time > 0) {
      const traceDate = new Date(t.start_time * 1000);
      const fromDate = new Date(dateFrom);
      if (traceDate < fromDate) return false;
    }
    if (dateTo && t.start_time > 0) {
      const traceDate = new Date(t.start_time * 1000);
      const toDate = new Date(dateTo);
      toDate.setHours(23, 59, 59, 999);
      if (traceDate > toDate) return false;
    }

    // Token count filter
    const tokens = t.total_tokens || 0;
    if (tokensMin && tokens < parseInt(tokensMin)) return false;
    if (tokensMax && tokens > parseInt(tokensMax)) return false;

    // Cost filter
    const cost = t.total_cost_usd || 0;
    if (costMin && cost < parseFloat(costMin)) return false;
    if (costMax && cost > parseFloat(costMax)) return false;

    // Span kind filter — we check if any span in the trace matches selected kinds
    // Note: trace list items may not include spans, so this filter only applies
    // when we have span data. For list view without spans, we skip this filter.
    // The filter will work when spans data is present.
    if (selectedKinds.length > 0 && t.spans && t.spans.length > 0) {
      const traceKinds = t.spans.map(s => (s.kind || '').toLowerCase());
      const hasMatch = selectedKinds.some(k => traceKinds.includes(k));
      if (!hasMatch) return false;
    }

    return true;
  });
}

/** Count active non-default filters for badge display */
function countActiveFilters() {
  let n = 0;
  if (_tracesStatusFilter !== 'all') n++;
  if (_tracesDurationFilter !== 'all') n++;
  if (_tracesTimeFilter !== 'all') n++;
  if (_tracesHideEmpty) n++;
  if (_tracesAgentFilter) n++;
  const dateFrom = document.getElementById('filter-date-from');
  const dateTo = document.getElementById('filter-date-to');
  if (dateFrom && dateFrom.value) n++;
  if (dateTo && dateTo.value) n++;
  const kindCount = document.querySelectorAll('.filter-kind:checked').length;
  n += kindCount;
  return n;
}

/** Render the quick filter bar (status, duration, time window, hide empty) */
function renderQuickFilterBar() {
  const bar = document.getElementById('traces-quick-filter-bar');
  if (!bar) return;

  const activeCount = countActiveFilters();
  const badgeHtml = activeCount > 0
    ? `<span class="ml-1 px-1.5 py-0.5 text-[10px] font-bold rounded-full bg-indigo-500 text-white">${activeCount}</span>`
    : '';

  const statusOptions = [
    { val: 'all', label: 'All Status' },
    { val: 'success', label: 'Success' },
    { val: 'error', label: 'Errors' },
  ];
  const durationOptions = [
    { val: 'all', label: 'Any Duration' },
    { val: '>1s', label: '>1s' },
    { val: '>5s', label: '>5s' },
    { val: '>10s', label: '>10s' },
  ];
  const timeOptions = [
    { val: 'all', label: 'All Time' },
    { val: '1h', label: 'Last 1h' },
    { val: '6h', label: 'Last 6h' },
    { val: '24h', label: 'Last 24h' },
    { val: '7d', label: 'Last 7d' },
  ];

  const selectClass = 'filter-input bg-surface-100 border border-white/10 rounded-lg px-2 py-1.5 text-xs text-slate-300 cursor-pointer transition';

  bar.innerHTML = `
    <div class="flex flex-wrap items-center gap-2">
      <span class="text-xs text-slate-500 font-medium mr-1">Filters${badgeHtml}:</span>

      <select class="${selectClass}" onchange="_tracesStatusFilter = this.value; traceOffset = 0; loadTraces(); renderQuickFilterBar();" title="Filter by status">
        ${statusOptions.map(o => `<option value="${o.val}" ${_tracesStatusFilter === o.val ? 'selected' : ''}>${o.label}</option>`).join('')}
      </select>

      <select class="${selectClass}" onchange="_tracesDurationFilter = this.value; traceOffset = 0; loadTraces(); renderQuickFilterBar();" title="Filter by minimum duration">
        ${durationOptions.map(o => `<option value="${o.val}" ${_tracesDurationFilter === o.val ? 'selected' : ''}>${o.label}</option>`).join('')}
      </select>

      <select class="${selectClass}" onchange="_tracesTimeFilter = this.value; traceOffset = 0; loadTraces(); renderQuickFilterBar();" title="Filter by time window">
        ${timeOptions.map(o => `<option value="${o.val}" ${_tracesTimeFilter === o.val ? 'selected' : ''}>${o.label}</option>`).join('')}
      </select>

      <label class="flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer select-none">
        <input type="checkbox" class="rounded bg-surface-100 border-white/10 text-indigo-500 focus:ring-indigo-500/30" ${_tracesHideEmpty ? 'checked' : ''} onchange="_tracesHideEmpty = this.checked; traceOffset = 0; loadTraces(); renderQuickFilterBar();" />
        <span>Hide empty</span>
      </label>

      ${activeCount > 0 ? `<button onclick="clearQuickFilters()" class="px-2 py-1 text-[11px] text-slate-400 hover:text-white bg-surface-100 rounded-lg border border-white/10 hover:border-white/20 transition">Clear filters</button>` : ''}
    </div>
  `;
}

function clearQuickFilters() {
  _tracesStatusFilter = 'all';
  _tracesDurationFilter = 'all';
  _tracesTimeFilter = 'all';
  _tracesHideEmpty = false;
  _tracesAgentFilter = null;
  traceOffset = 0;
  renderQuickFilterBar();
  loadTraces();
}

function clearFilters() {
  document.getElementById('filter-service').value = '';
  document.getElementById('filter-errors').checked = false;
  const fbFilter = document.getElementById('filter-has-feedback');
  if (fbFilter) fbFilter.checked = false;
  const ratingFilter = document.getElementById('filter-rating');
  if (ratingFilter) ratingFilter.value = '';
  document.getElementById('filter-date-from').value = '';
  document.getElementById('filter-date-to').value = '';
  document.getElementById('filter-tokens-min').value = '';
  document.getElementById('filter-tokens-max').value = '';
  document.getElementById('filter-cost-min').value = '';
  document.getElementById('filter-cost-max').value = '';
  document.querySelectorAll('.filter-kind').forEach(cb => cb.checked = false);
  _tracesAgentFilter = null;
  _tracesStatusFilter = 'all';
  _tracesDurationFilter = 'all';
  _tracesTimeFilter = 'all';
  _tracesHideEmpty = false;
  traceOffset = 0;
  renderQuickFilterBar();
  loadTraces();
}

function paginateTraces(dir) {
  traceOffset = Math.max(0, traceOffset + dir * TRACE_LIMIT);
  loadTraces();
}

// ==================================================================// Feedback UI
// ==================================================================
/** Star label text based on rating value */
const STAR_LABELS = { 1: 'Poor', 2: 'Fair', 3: 'OK', 4: 'Good', 5: 'Excellent' };

/** Highlight stars up to `n` on hover */
function starHover(n) {
  document.querySelectorAll('#star-rating .star-btn').forEach(btn => {
    const val = parseInt(btn.dataset.value, 10);
    btn.classList.toggle('hovered', val <= n);
    btn.classList.remove('selected');
  });
  const label = document.getElementById('star-label');
  if (label) label.textContent = STAR_LABELS[n] || '';
}

/** Reset star hover state, restore selected state */
function starHoverReset() {
  document.querySelectorAll('#star-rating .star-btn').forEach(btn => {
    const val = parseInt(btn.dataset.value, 10);
    btn.classList.remove('hovered');
    btn.classList.toggle('selected', val <= _selectedStarRating);
  });
  const label = document.getElementById('star-label');
  if (label) label.textContent = _selectedStarRating > 0 ? (STAR_LABELS[_selectedStarRating] || '') : '';
}

/** Select a star rating */
function selectStar(n) {
  _selectedStarRating = n;
  starHoverReset();
}

/** Render star string for display (read-only) */
function renderStars(rating, maxStars = 5) {
  let html = '<span class="feedback-stars">';
  for (let i = 1; i <= maxStars; i++) {
    if (i <= rating) {
      html += '&#9733;';
    } else {
      html += '<span class="empty-star">&#9733;</span>';
    }
  }
  html += '</span>';
  return html;
}

/** Submit quick feedback (thumbs up/down) */
async function submitQuickFeedback(rating) {
  if (!currentTraceId) return;
  _selectedStarRating = rating;
  await submitFeedback();
}

/** Submit feedback from the form */
async function submitFeedback() {
  if (!currentTraceId) return;
  if (_selectedStarRating < 1 || _selectedStarRating > 5) {
    const statusEl = document.getElementById('feedback-submit-status');
    if (statusEl) {
      statusEl.textContent = 'Please select a star rating first.';
      statusEl.classList.remove('hidden');
      statusEl.style.color = '#ef4444';
    }
    return;
  }
  const comment = (document.getElementById('feedback-comment')?.value || '').trim() || null;
  const statusEl = document.getElementById('feedback-submit-status');

  try {
    await apiFetch(`/v1/traces/${currentTraceId}/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rating: _selectedStarRating, comment }),
    });

    // Track in client state
    _feedbackRatedTraces.add(currentTraceId);
    const existingRating = _tracesFeedbackRatings.get(currentTraceId);
    // Simple update: use new rating (average will be corrected on next page reload)
    _tracesFeedbackRatings.set(currentTraceId, _selectedStarRating);

    // Clear form
    if (document.getElementById('feedback-comment')) document.getElementById('feedback-comment').value = '';
    _selectedStarRating = 0;
    starHoverReset();

    // Highlight thumbs
    if (comment !== null || true) {
      // Just reload the feedback list
      await loadTraceFeedback(currentTraceId);
    }

    if (statusEl) {
      statusEl.textContent = 'Feedback submitted!';
      statusEl.classList.remove('hidden');
      statusEl.style.color = '#10b981';
      setTimeout(() => statusEl.classList.add('hidden'), 3000);
    }
  } catch (err) {
    if (statusEl) {
      statusEl.textContent = 'Failed to submit feedback.';
      statusEl.classList.remove('hidden');
      statusEl.style.color = '#ef4444';
    }
  }
}

/** Load and render existing feedback for a trace */
async function loadTraceFeedback(traceId) {
  const listEl = document.getElementById('feedback-list');
  if (!listEl) return;

  try {
    const feedbacks = await apiFetch(`/v1/traces/${traceId}/feedback`);
    renderFeedbackList(feedbacks, listEl);

    // Update average badge
    const avgBadge = document.getElementById('feedback-avg-badge');
    if (avgBadge && feedbacks.length > 0) {
      const avg = feedbacks.reduce((s, f) => s + f.rating, 0) / feedbacks.length;
      avgBadge.textContent = `Avg: ${avg.toFixed(1)} (${feedbacks.length})`;
      avgBadge.classList.remove('hidden');
      // Update client-side ratings
      _feedbackRatedTraces.add(traceId);
      _tracesFeedbackRatings.set(traceId, avg);
    } else if (avgBadge) {
      avgBadge.classList.add('hidden');
    }
  } catch (_) {
    listEl.innerHTML = '<p class="text-xs text-slate-500">Could not load existing feedback.</p>';
  }
}

/** Render the list of feedback entries */
function renderFeedbackList(feedbacks, containerEl) {
  if (!feedbacks || feedbacks.length === 0) {
    containerEl.innerHTML = '<p class="text-xs text-slate-600 italic">No feedback yet — be the first to rate this trace.</p>';
    return;
  }

  containerEl.innerHTML = feedbacks.map(fb => {
    const timeStr = fb.created_at ? formatTimeAgo(fb.created_at) : '';
    const commentHtml = fb.comment
      ? `<p class="text-xs text-slate-400 mt-1">${escHtml(fb.comment)}</p>`
      : '';
    return `
      <div class="feedback-card">
        <div class="flex items-center justify-between">
          ${renderStars(fb.rating)}
          <span class="text-[10px] text-slate-600">${timeStr}</span>
        </div>
        ${commentHtml}
      </div>`;
  }).join('');
}

/** Load recent feedback for the Overview panel */
async function loadRecentFeedback() {
  const listEl = document.getElementById('recent-feedback-list');
  const avgEl = document.getElementById('feedback-avg-stat');
  if (!listEl) return;

  try {
    const [feedbacks, summary] = await Promise.all([
      apiFetch('/v1/feedback/recent?limit=5'),
      apiFetch('/v1/feedback/summary'),
    ]);

    // Update avg stat
    if (avgEl && summary.total_count > 0 && summary.avg_rating !== null) {
      avgEl.textContent = `Avg ${summary.avg_rating.toFixed(1)} across ${summary.total_count} rating${summary.total_count !== 1 ? 's' : ''}`;
    } else if (avgEl) {
      avgEl.textContent = '';
    }

    // Populate feedback rated traces set (for trace list badges)
    if (summary.low_rating_traces) {
      summary.low_rating_traces.forEach(r => {
        _feedbackRatedTraces.add(r.trace_id);
        _tracesFeedbackRatings.set(r.trace_id, r.avg_rating);
      });
    }

    if (!feedbacks || feedbacks.length === 0) {
      listEl.innerHTML = '<div class="px-4 py-6 text-center text-xs text-slate-600">No feedback yet. Rate a trace to see it here.</div>';
      return;
    }

    listEl.innerHTML = feedbacks.map(fb => {
      const timeStr = fb.created_at ? formatTimeAgo(fb.created_at) : '';
      const shortId = (fb.trace_id || '').substring(0, 12);
      const commentHtml = fb.comment
        ? `<span class="text-xs text-slate-400 truncate max-w-xs">${escHtml(fb.comment.substring(0, 80))}${fb.comment.length > 80 ? '…' : ''}</span>`
        : `<span class="text-xs text-slate-600 italic">No comment</span>`;

      return `
        <div class="recent-feedback-card" onclick="openTrace('${escHtml(fb.trace_id || '')}')" title="Open trace ${escHtml(fb.trace_id || '')}">
          <div class="flex-shrink-0">${renderStars(fb.rating)}</div>
          <div class="flex-1 min-w-0">
            ${commentHtml}
            <div class="flex items-center gap-2 mt-1">
              <span class="text-[10px] text-indigo-400 font-mono">${escHtml(shortId)}…</span>
              <span class="text-[10px] text-slate-600">${timeStr}</span>
            </div>
          </div>
        </div>`;
    }).join('');
  } catch (_) {
    listEl.innerHTML = '<div class="px-4 py-6 text-center text-xs text-slate-600">Could not load feedback.</div>';
  }
}

// ==================================================================// Trace Detail
// ==================================================================
async function openTrace(traceId) {
  currentTraceId = traceId;
  try { sessionStorage.setItem('flowlens-trace-id', traceId || ''); } catch (_) {}
  // Hide current view, show detail
  document.querySelectorAll('.view-panel').forEach(p => p.classList.add('hidden'));
  const detailPanel = document.getElementById('view-trace-detail');
  detailPanel.classList.remove('hidden');
  detailPanel.classList.remove('view-enter');
  void detailPanel.offsetWidth;
  detailPanel.classList.add('view-enter');

  // Reset to timeline tab
  showDetailTab('timeline');

  // Reset feedback form state
  _selectedStarRating = 0;
  const starRating = document.getElementById('star-rating');
  if (starRating) starRating.querySelectorAll('.star-btn').forEach(b => b.classList.remove('selected', 'hovered'));
  const commentEl = document.getElementById('feedback-comment');
  if (commentEl) commentEl.value = '';
  const statusEl = document.getElementById('feedback-submit-status');
  if (statusEl) statusEl.classList.add('hidden');
  const starLabel = document.getElementById('star-label');
  if (starLabel) starLabel.textContent = '';

  try {
    const data = await apiFetch(`/v1/traces/${traceId}`);
    currentTraceData = data;
    renderTraceDetail(data);
  } catch (err) {
    document.getElementById('timeline-container').innerHTML = `<div class="text-center text-red-400/60 text-sm py-8">Failed to load trace: ${escHtml(err.message)}</div>`;
  }

  // Load existing feedback (non-blocking)
  loadTraceFeedback(traceId).catch(() => {});
}

function renderTraceDetail(data) {
  const hasErrors = data.has_errors === true || data.has_errors === 1;
  const timeStr = data.start_time > 0 ? new Date(data.start_time * 1000).toLocaleString() : '--';

  // Derive agent name and project name from tags/metadata
  const tags = data.tags || {};
  const meta = data.metadata || {};
  const agentName = tags.agent || null;
  const projectName = tags.project || meta.project || (meta.cwd ? meta.cwd.split('/').pop() : null);

  // Update trace ID — monospace, dimmed, with copy button
  const traceIdEl = document.getElementById('detail-trace-id');
  if (traceIdEl) {
    traceIdEl.innerHTML = `
      <span class="flex items-center gap-2 flex-wrap">
        <span class="font-mono text-xs text-slate-500 tracking-tight select-all">${escHtml(data.trace_id)}</span>
        <button onclick="navigator.clipboard.writeText('${escHtml(data.trace_id)}').then(()=>showToast('Trace ID copied','success'))" class="trace-id-copy-btn" title="Copy trace ID" aria-label="Copy trace ID">
          <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/></svg>
        </button>
      </span>`;
  }

  // Token usage breakdown per span kind
  const tokenByKind = {};
  (data.spans || []).forEach(s => {
    const kind = (s.kind || 'custom').toLowerCase();
    if (!tokenByKind[kind]) tokenByKind[kind] = { input: 0, output: 0, cost: 0 };
    if (s.token_usage) {
      tokenByKind[kind].input += s.token_usage.input_tokens || 0;
      tokenByKind[kind].output += s.token_usage.output_tokens || 0;
      tokenByKind[kind].cost += s.token_usage.total_cost_usd || 0;
    }
  });

  let tokenBreakdownHtml = '';
  const hasTokens = Object.values(tokenByKind).some(v => v.input > 0 || v.output > 0);
  if (hasTokens) {
    tokenBreakdownHtml = '<div class="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-2">';
    for (const [kind, usage] of Object.entries(tokenByKind)) {
      if (usage.input === 0 && usage.output === 0) continue;
      const cfg = SPAN_KIND_COLORS[kind] || SPAN_KIND_COLORS.custom;
      tokenBreakdownHtml += `
        <div class="p-2 rounded-lg ${cfg.bg} text-xs">
          <div class="font-medium ${cfg.text} mb-1">${cfg.label}</div>
          <div class="text-slate-400">In: ${usage.input.toLocaleString()}</div>
          <div class="text-slate-400">Out: ${usage.output.toLocaleString()}</div>
          <div style="color:var(--color-sage,#81b29a)">$${usage.cost.toFixed(4)}</div>
        </div>`;
    }
    tokenBreakdownHtml += '</div>';
  }

  // Build header meta: agent info, project, large duration+cost, error badge
  const durationMs = data.duration_ms || 0;
  const costUsd = data.total_cost_usd || 0;
  const errorCount = data.error_count || 0;

  // v17 Premium Feel: horizontal meta strip with prominent agent, monospace ID
  let agentHeaderHtml = '';
  if (agentName) {
    const profile = getAgentProfile(agentName);
    agentHeaderHtml = `
      <div class="flex items-center gap-3 mb-3">
        ${renderAgentAvatar(agentName, 'lg')}
        <div class="flex-1 min-w-0">
          <div class="text-base font-bold leading-tight" style="color:${profile.color}">${escHtml(profile.name)}</div>
          <div class="text-[11px] text-slate-500 mt-0.5">${escHtml(profile.role)}</div>
        </div>
        ${projectName ? `<span class="px-2 py-0.5 text-[10px] font-semibold rounded-full bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 flex-shrink-0">${escHtml(projectName)}</span>` : ''}
      </div>`;
  } else if (projectName) {
    agentHeaderHtml = `<div class="mb-3"><span class="px-2 py-0.5 text-[10px] font-semibold rounded-full bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">${escHtml(projectName)}</span></div>`;
  }

  // Horizontal strip of 4 meta cards
  const statusCard = hasErrors
    ? `<div class="trace-meta-strip-card trace-meta-strip-error">
        <span class="trace-meta-strip-value text-red-400">${errorCount}</span>
        <span class="trace-meta-strip-label">Errors</span>
       </div>`
    : `<div class="trace-meta-strip-card trace-meta-strip-ok">
        <span class="trace-meta-strip-value text-emerald-400">OK</span>
        <span class="trace-meta-strip-label">Status</span>
       </div>`;
  const metaItems = [
    `<div class="flex flex-col items-center p-3 rounded-lg bg-surface-100/50 border border-white/5">
      <span class="text-2xl font-bold text-white tabular-nums">${formatDuration(durationMs)}</span>
      <span class="text-[10px] text-slate-500 mt-0.5 uppercase tracking-wider">Duration</span>
    </div>`,
    `<div class="flex flex-col items-center p-3 rounded-lg bg-surface-100/50 border border-white/5">
      <span class="text-2xl font-bold tabular-nums" style="color:var(--color-sage,#81b29a)">$${costUsd.toFixed(4)}</span>
      <span class="text-[10px] text-slate-500 mt-0.5 uppercase tracking-wider">Cost</span>
    </div>`,
    `<div class="flex flex-col items-center p-3 rounded-lg bg-surface-100/50 border border-white/5">
      <span class="text-2xl font-bold text-white tabular-nums">${data.span_count || (data.spans || []).length}</span>
      <span class="text-[10px] text-slate-500 mt-0.5 uppercase tracking-wider">Spans</span>
    </div>`,
    hasErrors ? `<div class="flex flex-col items-center p-3 rounded-lg" style="background:var(--color-coral-bg,rgba(224,122,95,0.10));border:1px solid var(--color-coral-border,rgba(224,122,95,0.28))">
      <span class="text-2xl font-bold tabular-nums" style="color:var(--color-coral,#e07a5f)">${errorCount}</span>
      <span class="text-[10px] mt-0.5 uppercase tracking-wider" style="color:var(--color-coral,#e07a5f)">Errors</span>
    </div>` : `<div class="flex flex-col items-center p-3 rounded-lg" style="background:var(--color-sage-bg,rgba(129,178,154,0.10));border:1px solid var(--color-sage-border,rgba(129,178,154,0.25))">
      <span class="text-2xl font-bold tabular-nums" style="color:var(--color-sage,#81b29a)">OK</span>
      <span class="text-[10px] mt-0.5 uppercase tracking-wider" style="color:var(--color-sage,#81b29a)">Status</span>
    </div>`,
  ];

  const metaStrip = `
    <div class="trace-meta-strip">
      <div class="trace-meta-strip-card">
        <span class="trace-meta-strip-value">${formatDuration(durationMs)}</span>
        <span class="trace-meta-strip-label">Duration</span>
      </div>
      <div class="trace-meta-strip-card trace-meta-strip-cost">
        <span class="trace-meta-strip-value text-emerald-400">$${costUsd.toFixed(4)}</span>
        <span class="trace-meta-strip-label">Cost</span>
      </div>
      <div class="trace-meta-strip-card">
        <span class="trace-meta-strip-value">${data.span_count || (data.spans || []).length}</span>
        <span class="trace-meta-strip-label">Spans</span>
      </div>
      ${statusCard}
    </div>`;

  // Compact secondary row: tokens + time (service removed — agent name already shown)
  const secondaryRow = `
    <div class="flex flex-wrap items-center gap-4 mt-2">
      <span class="text-xs text-slate-500">Tokens: <strong class="text-slate-300">${(data.total_tokens || 0).toLocaleString()}</strong></span>
      <span class="text-xs text-slate-500">Time: <strong class="text-slate-300">${timeStr}</strong></span>
    </div>`;

  document.getElementById('detail-trace-meta').innerHTML = `
    ${agentHeaderHtml}
    ${metaStrip}
    ${secondaryRow}
    ${tokenBreakdownHtml}
  `;

  renderWaterfallTimeline(data.spans || []);
}

// ==================================================================// Timeline — Waterfall Chart
// ==================================================================
const SPAN_KIND_COLORS = {
  llm:       { bg: 'bg-[#9b8ec4]/20', bar: '#9b8ec4', text: 'text-[#9b8ec4]', label: 'LLM' },
  tool:      { bg: 'bg-[#7ab5a0]/20', bar: '#7ab5a0', text: 'text-[#7ab5a0]', label: 'Tool' },
  agent:     { bg: 'bg-[#a88ec4]/20', bar: '#a88ec4', text: 'text-[#a88ec4]', label: 'Agent' },
  chain:     { bg: 'bg-[#c4b07a]/20', bar: '#c4b07a', text: 'text-[#c4b07a]', label: 'Chain' },
  retrieval: { bg: 'bg-[#7a9eb5]/20', bar: '#7a9eb5', text: 'text-[#7a9eb5]', label: 'Retrieval' },
  custom:    { bg: 'bg-[#a0a09a]/20', bar: '#a0a09a', text: 'text-[#a0a09a]', label: 'Custom' },
};

/**
 * Extract the most useful inline detail for a span to show next to its name.
 * Returns a short string like a file path, command excerpt, or grep pattern.
 */
function extractSpanInlineDetail(span) {
  const attrs = span.attributes || {};
  const toolName = attrs['tool.name'] || attrs['gen_ai.request.model']
    ? attrs['tool.name']
    : null;

  // Detect from span name suffix (e.g. "vr-alpha/Read" => "Read")
  const slash = (span.name || '').lastIndexOf('/');
  const nameTool = slash >= 0 ? span.name.substring(slash + 1) : span.name;
  const tool = toolName || nameTool || '';

  // Try to get a meaningful value from tool.input JSON or individual attrs
  let detail = null;

  // tool.input is often a JSON string with the actual inputs
  const toolInput = attrs['tool.input'];
  if (toolInput) {
    try {
      const parsed = typeof toolInput === 'string' ? JSON.parse(toolInput) : toolInput;
      if (tool === 'Read' || tool === 'Write' || tool === 'Edit') {
        detail = parsed.file_path || parsed.path || parsed.filename || null;
      } else if (tool === 'Bash') {
        const cmd = parsed.command || parsed.cmd || null;
        detail = cmd ? cmd.substring(0, 70) : null;
      } else if (tool === 'Grep') {
        detail = parsed.pattern ? `/${parsed.pattern}/` : null;
      }
    } catch (_) {
      // Not JSON, use raw value trimmed
      detail = String(toolInput).substring(0, 70);
    }
  }

  // Fall back to individual attribute checks
  if (!detail) {
    if (tool === 'Read' || tool === 'Write' || tool === 'Edit') {
      detail = attrs['file_path'] || attrs['path'] || attrs['tool.file_path'] || null;
    } else if (tool === 'Bash') {
      const cmd = attrs['command'] || attrs['tool.command'] || null;
      detail = cmd ? cmd.substring(0, 70) : null;
    } else if (tool === 'Grep') {
      detail = attrs['pattern'] ? `/${attrs['pattern']}/` : null;
    }
  }

  if (detail) {
    // Shorten file paths: keep last 2 segments
    if ((tool === 'Read' || tool === 'Write' || tool === 'Edit') && detail.includes('/')) {
      const parts = detail.split('/');
      detail = '…/' + parts.slice(-2).join('/');
    }
    if (detail.length > 60) detail = detail.substring(0, 60) + '…';
  }

  return detail;
}

/**
 * Extract model name from span attributes (e.g. "claude-sonnet-4-6").
 * Returns a short label like "sonnet-4-6" or null.
 */
function extractModelBadge(span) {
  const attrs = span.attributes || {};
  const model = attrs['gen_ai.request.model'] || attrs['llm.model'] || attrs['model'] || null;
  if (!model) return null;
  // Shorten claude-* model names
  const short = model.replace(/^claude-/i, '').replace(/^anthropic\//i, '');
  return short.length > 0 ? short : null;
}

/** Extract agent name prefix from span name (e.g. "vr-alpha/Read" -> "vr-alpha") */
function extractAgentFromSpanName(spanName) {
  if (!spanName) return null;
  const slashIdx = spanName.indexOf('/');
  if (slashIdx > 0) {
    const prefix = spanName.substring(0, slashIdx);
    if (AGENT_PROFILES[prefix]) return prefix;
  }
  return null;
}

function renderWaterfallTimeline(spans) {
  const container = document.getElementById('timeline-container');
  if (!spans || spans.length === 0) {
    container.innerHTML = renderEmptyState('No spans in this trace', 'Spans appear when the trace includes instrumented operations.');
    return;
  }

  // Sort by start_time
  spans.sort((a, b) => (a.start_time || 0) - (b.start_time || 0));

  const minTime = Math.min(...spans.map(s => s.start_time || 0));
  const maxTime = Math.max(...spans.map(s => s.end_time || s.start_time || 0));
  const totalDuration = maxTime - minTime || 1;
  const totalDurationMs = totalDuration * 1000;

  // Build hierarchy via DFS
  const childMap = {};
  spans.forEach(s => {
    if (s.parent_span_id) {
      childMap[s.parent_span_id] = childMap[s.parent_span_id] || [];
      childMap[s.parent_span_id].push(s);
    }
  });

  const rootSpans = spans.filter(s => !s.parent_span_id || !spans.find(p => p.span_id === s.parent_span_id));
  const flatList = [];
  function dfs(span, depth) {
    flatList.push({ span, depth });
    (childMap[span.span_id] || []).forEach(c => dfs(c, depth + 1));
  }
  rootSpans.forEach(s => dfs(s, 0));

  // Time axis — proper ruler with adaptive tick spacing
  // Choose tick interval based on total duration
  let tickIntervalMs;
  if (totalDurationMs <= 500)       tickIntervalMs = 50;
  else if (totalDurationMs <= 2000) tickIntervalMs = 100;
  else if (totalDurationMs <= 10000) tickIntervalMs = 500;
  else if (totalDurationMs <= 30000) tickIntervalMs = 1000;
  else if (totalDurationMs <= 120000) tickIntervalMs = 5000;
  else tickIntervalMs = 10000;

  // Generate tick positions (always include 0 and end)
  const tickMs = [];
  for (let t = 0; t <= totalDurationMs; t += tickIntervalMs) {
    tickMs.push(t);
  }
  if (tickMs[tickMs.length - 1] < totalDurationMs) tickMs.push(totalDurationMs);

  // Build ruler HTML
  let timeAxisHtml = '<div class="wf-time-ruler">';
  tickMs.forEach((ms, idx) => {
    const pct = (ms / totalDurationMs) * 100;
    const label = formatDuration(ms);
    const isFirst = idx === 0;
    const isLast  = idx === tickMs.length - 1;
    const align = isFirst ? 'left:0;transform:none' : isLast ? 'right:0;transform:none;left:auto' : `left:${pct}%`;
    timeAxisHtml += `<div class="wf-ruler-tick" style="${align}">
      <div class="wf-ruler-tick-mark"></div>
      <div class="wf-ruler-label">${label}</div>
    </div>`;
  });
  timeAxisHtml += '</div>';

  const timeMarkers = 5; // keep for grid lines

  // Collect agents present in these spans for the agent color legend
  const traceAgentTag = currentTraceData && (currentTraceData.tags || {}).agent || null;
  const agentsInTrace = new Map(); // agentKey -> profile color
  flatList.forEach(({ span }) => {
    const _spanAttrs = span.attributes || {};
    const _agentFromAttr = _spanAttrs.agent || _spanAttrs['agent.name'] || traceAgentTag || null;
    const _agentFromName = extractAgentFromSpanName(span.name);
    const _agentKey = _agentFromAttr || _agentFromName;
    if (_agentKey && !agentsInTrace.has(_agentKey)) {
      agentsInTrace.set(_agentKey, getAgentProfile(_agentKey).color);
    }
  });

  // Span-kind legend
  let legendHtml = '<div class="flex flex-wrap gap-3 mb-2 pb-2 border-b border-white/5">';
  for (const [kind, cfg] of Object.entries(SPAN_KIND_COLORS)) {
    legendHtml += `<div class="flex items-center gap-1.5 text-xs ${cfg.text}"><span class="w-3 h-1.5 rounded-full" style="background:${cfg.bar}"></span>${cfg.label}</div>`;
  }
  legendHtml += '</div>';

  // Agent color legend (shown only when agents are detected in spans)
  if (agentsInTrace.size > 0) {
    legendHtml += '<div class="flex flex-wrap gap-3 mb-3 pb-3 border-b border-white/5 items-center">';
    legendHtml += '<span class="text-[10px] text-slate-500 uppercase tracking-wider font-medium mr-1">Agents:</span>';
    agentsInTrace.forEach((color, agentName) => {
      const profile = getAgentProfile(agentName);
      legendHtml += `<div class="flex items-center gap-1.5 text-xs" style="color:${color}">
        ${renderAgentAvatar(agentName, 'sm')}
        <span>${escHtml(profile.name)}</span>
      </div>`;
    });
    legendHtml += '</div>';
  }

  // Vertical gridlines behind bars — aligned to ruler ticks
  let gridHtml = '<div class="absolute inset-0 ml-[280px] mr-[70px] pointer-events-none" style="top:0;bottom:0">';
  tickMs.slice(1, -1).forEach(ms => {
    const pct = (ms / totalDurationMs) * 100;
    gridHtml += `<div class="wf-ruler-gridline" style="left:${pct}%"></div>`;
  });
  gridHtml += '</div>';

  // Track which spans have children for collapse toggle
  const hasChildren = {};
  spans.forEach(s => {
    if (s.parent_span_id) hasChildren[s.parent_span_id] = true;
  });

  let rowsHtml = '';
  flatList.forEach(({ span, depth }, idx) => {
    const kind = (span.kind || 'custom').toLowerCase();
    const cfg = SPAN_KIND_COLORS[kind] || SPAN_KIND_COLORS.custom;
    const isError = span.status === 'error';

    const spanStart = (span.start_time || 0) - minTime;
    const spanDuration = ((span.end_time || span.start_time || 0) - (span.start_time || 0));
    const leftPct = (spanStart / totalDuration) * 100;
    const widthPct = Math.max((spanDuration / totalDuration) * 100, 0.5);
    const durationMs = span.duration_ms || spanDuration * 1000 || 0;
    const durationStr = formatDuration(durationMs);

    // Resolve agent color for bar fill (agent color > kind color; error always red)
    const spanAttrs = span.attributes || {};
    const agentFromAttr = spanAttrs.agent || spanAttrs['agent.name'] || traceAgentTag || null;
    const agentFromName = extractAgentFromSpanName(span.name);
    const spanAgentKey = agentFromAttr || agentFromName;
    const agentBarColor = spanAgentKey ? getAgentProfile(spanAgentKey).color : null;

    const indent = depth * 20;
    const barColor = isError ? '#c47070' : (agentBarColor || cfg.bar);
    const barOpacity = isError ? 0.85 : 0.75;
    const barBorder = isError ? '2px solid #d9a0a0' : 'none';
    const errorTintStyle = isError ? 'box-shadow:inset 0 0 0 9999px rgba(196,112,112,0.18);' : '';

    // Build tooltip data attributes
    const tokens = span.token_usage ? (span.token_usage.total_tokens || (span.token_usage.input_tokens || 0) + (span.token_usage.output_tokens || 0) || 0) : 0;
    const cost = span.token_usage ? (span.token_usage.total_cost_usd || 0) : 0;
    const canCollapse = hasChildren[span.span_id];

    // Inline detail (key attribute for the tool)
    const inlineDetail = extractSpanInlineDetail(span);
    // Model badge for LLM spans
    const modelBadge = kind === 'llm' ? extractModelBadge(span) : null;

    // Agent left-border style (3px colored border by agent, not span kind)
    const agentBorderColor = spanAgentKey ? getAgentProfile(spanAgentKey).color : null;
    const agentBorderStyle = agentBorderColor ? `border-left:3px solid ${agentBorderColor};padding-left:6px;` : '';

    // Error row: red left border + light red background tint
    const rowErrorStyle = isError ? 'border-left:4px solid #c47070;background:rgba(196,112,112,0.06);' : agentBorderStyle;

    rowsHtml += `
      <div class="flex items-center gap-0 py-1 px-2 rounded-lg hover:bg-white/[0.03] cursor-pointer transition group waterfall-row"
           style="${rowErrorStyle}"
           data-span-id="${span.span_id}"
           data-parent-span-id="${span.parent_span_id || ''}"
           data-depth="${depth}"
           onclick="openSpanDetail('${span.span_id}')"
           data-span-name="${escHtml(span.name)}"
           data-span-kind="${cfg.label}"
           data-span-duration="${durationStr}"
           data-span-status="${isError ? 'error' : 'ok'}"
           data-span-tokens="${tokens}"
           data-span-cost="${cost.toFixed(6)}"
           onmouseenter="showWaterfallTooltip(event, this)"
           onmouseleave="hideWaterfallTooltip()">
        <!-- Label column with tree indentation -->
        <div class="span-label-col flex items-center gap-1 w-[280px] min-w-[280px] flex-shrink-0" style="padding-left:${indent}px">
          ${canCollapse ? `<button class="collapsible-chevron rotated w-4 h-4 flex items-center justify-center text-slate-600 hover:text-slate-400 flex-shrink-0 transition" onclick="event.stopPropagation(); toggleSpanChildren('${span.span_id}', this)" title="Collapse/Expand"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg></button>` : (depth > 0 ? '<span class="w-4 flex-shrink-0"></span>' : '')}
          ${isError ? `<svg class="w-3 h-3 flex-shrink-0" style="color:var(--color-coral,#e07a5f)" fill="none" stroke="currentColor" viewBox="0 0 24 24" title="Error"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"/></svg>` : ''}
          <span class="px-1.5 py-0.5 text-[10px] font-medium rounded flex-shrink-0 ${cfg.bg} ${cfg.text}">${cfg.label}</span>
          <div class="min-w-0 flex flex-col">
            <span class="text-xs ${isError ? 'wf-span-error-name' : 'text-slate-300'} truncate group-hover:text-white transition">${escHtml(span.name)}</span>
            ${inlineDetail ? `<span class="text-[10px] text-slate-500 font-mono truncate leading-tight" title="${escHtml(inlineDetail)}">${escHtml(inlineDetail)}</span>` : ''}
          </div>
          ${modelBadge ? `<span class="ml-auto flex-shrink-0 px-1 py-0.5 text-[10px] font-mono font-medium rounded whitespace-nowrap" style="background:var(--color-indigo-bg,rgba(107,92,231,0.10));color:var(--color-indigo-warm,#6b5ce7);border:1px solid var(--color-indigo-border,rgba(107,92,231,0.22))">${escHtml(modelBadge)}</span>` : ''}
        </div>
        <!-- Bar column -->
        <div class="flex-1 relative h-7 min-w-0">
          ${depth > 0 ? `<div class="wf-connector" style="left:${indent - 14}px"></div>` : ''}
          <div class="wf-bar-gradient ${isError ? 'wf-bar-error' : ''} flex items-center overflow-hidden"
               style="left:${leftPct}%;width:${widthPct}%;background:linear-gradient(90deg,${barColor}ee,${barColor}88);opacity:${barOpacity};${barBorder ? `outline:${barBorder};outline-offset:-1px;` : ''}${errorTintStyle}">
            ${widthPct > 8 ? `<span class="px-1.5 text-[10px] font-medium text-white/90 whitespace-nowrap">${durationStr}</span>` : ''}
          </div>
          ${widthPct <= 8 ? `<span class="absolute top-1.5 text-[10px] text-slate-500 whitespace-nowrap" style="left:${leftPct + widthPct + 0.5}%">${durationStr}</span>` : ''}
        </div>
        <!-- Duration column -->
        <div class="text-xs text-slate-500 w-[70px] text-right flex-shrink-0 tabular-nums">${durationStr}</div>
      </div>
    `;
  });

  container.innerHTML = `
    ${legendHtml}
    ${timeAxisHtml}
    <div class="relative">
      ${gridHtml}
      <div class="space-y-0 relative z-10">${rowsHtml}</div>
    </div>
  `;
}

// Waterfall tooltip
let tooltipEl = null;
function showWaterfallTooltip(event, row) {
  if (!tooltipEl) {
    tooltipEl = document.createElement('div');
    tooltipEl.className = 'waterfall-tooltip';
    document.body.appendChild(tooltipEl);
  }

  const name = row.dataset.spanName;
  const kind = row.dataset.spanKind;
  const duration = row.dataset.spanDuration;
  const status = row.dataset.spanStatus;
  const tokens = parseInt(row.dataset.spanTokens);
  const cost = parseFloat(row.dataset.spanCost);

  let html = `
    <div class="font-semibold text-white mb-1">${escHtml(name)}</div>
    <div class="space-y-0.5 text-slate-400">
      <div>Kind: <span class="text-slate-200">${kind}</span></div>
      <div>Duration: <span class="text-slate-200">${duration}</span></div>
      <div>Status: <span style="color:${status === 'error' ? 'var(--color-coral,#e07a5f)' : 'var(--color-sage,#81b29a)'}">${status}</span></div>
      ${tokens > 0 ? `<div>Tokens: <span class="text-slate-200">${tokens.toLocaleString()}</span></div>` : ''}
      ${cost > 0 ? `<div>Cost: <span style="color:var(--color-sage,#81b29a)">$${cost}</span></div>` : ''}
    </div>
  `;
  tooltipEl.innerHTML = html;
  tooltipEl.style.display = 'block';

  // Position near cursor
  const rect = row.getBoundingClientRect();
  tooltipEl.style.top = (rect.top - 10) + 'px';
  tooltipEl.style.left = (event.clientX + 16) + 'px';

  // Keep tooltip within viewport
  const ttRect = tooltipEl.getBoundingClientRect();
  if (ttRect.right > window.innerWidth) {
    tooltipEl.style.left = (event.clientX - ttRect.width - 16) + 'px';
  }
  if (ttRect.top < 0) {
    tooltipEl.style.top = (rect.bottom + 4) + 'px';
  }
}

function hideWaterfallTooltip() {
  if (tooltipEl) tooltipEl.style.display = 'none';
}

// ==================================================================// Span Detail Panel
// ==================================================================
function openSpanDetail(spanId) {
  if (!currentTraceData || !currentTraceData.spans) return;
  const span = currentTraceData.spans.find(s => s.span_id === spanId);
  if (!span) return;

  const panel = document.getElementById('span-detail-panel');
  panel.classList.remove('hidden');
  panel.classList.remove('fade-in');
  void panel.offsetWidth;
  panel.classList.add('fade-in');

  const kind = (span.kind || 'custom').toLowerCase();
  const cfg = SPAN_KIND_COLORS[kind] || SPAN_KIND_COLORS.custom;
  const isError = span.status === 'error';
  const attrs = span.attributes || {};

  // Parse semantic fields from attributes
  const toolName = attrs['tool.name'] || attrs['tool_name'] || attrs['gen_ai.tool.name'] || null;
  const toolInput = attrs['tool.input'] || attrs['tool_input'] || attrs['input'] || null;
  const toolOutput = attrs['tool.output'] || attrs['tool_output'] || attrs['tool.output_summary'] || attrs['output'] || null;
  const llmModel = attrs['gen_ai.request.model'] || attrs['llm.model'] || attrs['model'] || null;
  const llmInputTokens = parseInt(attrs['gen_ai.usage.input_tokens'] || attrs['llm.usage.prompt_tokens'] || 0, 10);
  const llmOutputTokens = parseInt(attrs['gen_ai.usage.output_tokens'] || attrs['llm.usage.completion_tokens'] || 0, 10);
  const llmResponse = attrs['gen_ai.response.text'] || attrs['llm.response'] || attrs['response'] || null;
  const errorType = attrs['error.type'] || attrs['exception.type'] || null;
  const errorMsg = attrs['error.message'] || attrs['exception.message'] || span.error_message ||
    (span.error ? (span.error.message || JSON.stringify(span.error)) : null);

  // Semantic attribute keys to exclude from the "Metadata" section (already shown above)
  const SEMANTIC_KEYS = new Set([
    'tool.name', 'tool_name', 'gen_ai.tool.name',
    'tool.input', 'tool_input', 'input',
    'tool.output', 'tool_output', 'tool.output_summary', 'output',
    'gen_ai.request.model', 'llm.model', 'model',
    'gen_ai.usage.input_tokens', 'llm.usage.prompt_tokens',
    'gen_ai.usage.output_tokens', 'llm.usage.completion_tokens',
    'gen_ai.response.text', 'llm.response', 'response',
    'error.type', 'exception.type',
    'error.message', 'exception.message',
    'agent', 'agent.name',
  ]);

  // Resolve agent for this span
  const sdAgentFromAttr = attrs['agent'] || attrs['agent.name'] || (currentTraceData && (currentTraceData.tags || {}).agent) || null;
  const sdAgentFromName = extractAgentFromSpanName(span.name);
  const sdAgentKey = sdAgentFromAttr || sdAgentFromName;
  const sdAgentProfile = sdAgentKey ? getAgentProfile(sdAgentKey) : null;

  // Timing
  const durationMs = span.duration_ms || ((span.end_time - span.start_time) * 1000) || 0;
  const traceStart = currentTraceData.spans.reduce((mn, s) => Math.min(mn, s.start_time || Infinity), Infinity);
  const traceEnd = currentTraceData.spans.reduce((mx, s) => Math.max(mx, s.end_time || 0), 0);
  const traceDurationMs = (traceEnd - traceStart) * 1000;
  const relOffset = traceStart > 0 && span.start_time > 0 ? ((span.start_time - traceStart) * 1000) : 0;
  const barLeft = traceDurationMs > 0 ? Math.min(99, (relOffset / traceDurationMs) * 100).toFixed(1) : 0;
  const barWidth = traceDurationMs > 0 ? Math.max(1, (durationMs / traceDurationMs) * 100).toFixed(1) : 2;

  let html = '';

  // ---- Error header (prominent, always first if error) ----
  if (isError && errorMsg) {
    html += `
      <div class="mb-4 rounded-xl p-3 span-error-block" style="background:var(--color-coral-bg, rgba(224,122,95,0.10));border:1px solid var(--color-coral-border, rgba(224,122,95,0.35))">
        <div class="flex items-center gap-2 mb-1.5">
          <svg class="w-4 h-4 flex-shrink-0" style="color:var(--color-coral,#e07a5f)" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"/></svg>
          <span class="text-xs font-bold uppercase tracking-wider" style="color:var(--color-coral,#e07a5f)">Error${errorType ? ': ' + escHtml(errorType) : ''}</span>
        </div>
        <p class="text-xs font-mono break-all leading-relaxed" style="color:var(--color-coral,#e07a5f);opacity:0.9">${escHtml(errorMsg)}</p>
      </div>`;
  }

  // ---- Header — agent avatar + kind badge + span name ----
  html += `<div class="mb-4">`;
  if (sdAgentProfile) {
    html += `<div class="flex items-center gap-2 mb-3 p-2 rounded-lg" style="background:${sdAgentProfile.color}18;border:1px solid ${sdAgentProfile.color}30">
      ${renderAgentAvatar(sdAgentKey, 'md')}
      <div class="min-w-0">
        <div class="text-xs font-semibold" style="color:${sdAgentProfile.color}">${escHtml(sdAgentProfile.name)}</div>
        <div class="text-[10px] text-slate-500">${escHtml(sdAgentProfile.role)}</div>
      </div>
    </div>`;
  }
  html += `<div class="flex items-center gap-2 mb-2">
      <span class="px-2 py-0.5 text-xs font-medium rounded ${cfg.bg} ${cfg.text}">${cfg.label}</span>
      ${isError ? '<span class="px-2 py-0.5 text-xs font-medium rounded" style="background:var(--color-coral-bg,rgba(224,122,95,0.12));color:var(--color-coral,#e07a5f);border:1px solid var(--color-coral-border,rgba(224,122,95,0.28))">ERROR</span>' : '<span class="px-2 py-0.5 text-xs font-medium rounded" style="background:var(--color-sage-bg,rgba(129,178,154,0.12));color:var(--color-sage,#81b29a);border:1px solid var(--color-sage-border,rgba(129,178,154,0.28))">OK</span>'}
    </div>
    <h4 class="text-base font-semibold text-white leading-snug">${escHtml(span.name)}</h4>
    <div class="flex items-center gap-1 mt-1">
      <span class="text-[10px] text-slate-500 font-mono truncate">${span.span_id}</span>
      <button onclick="navigator.clipboard.writeText('${span.span_id}');showToast('Span ID copied','success',1500)" class="p-0.5 rounded hover:bg-white/5 text-slate-600 hover:text-slate-400 transition flex-shrink-0" title="Copy span ID">
        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"/></svg>
      </button>
    </div>
  </div>`;

  // ---- Timing with visual bar ----
  const startStr = span.start_time > 0 ? new Date(span.start_time * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 }) : '--';
  const endStr = span.end_time > 0 ? new Date(span.end_time * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 }) : '--';
  html += renderCollapsibleSection('Timing', `
    <div class="space-y-2 text-xs">
      <div class="flex justify-between"><span class="text-slate-500">Start</span><span class="text-slate-300 tabular-nums">${startStr}</span></div>
      <div class="flex justify-between"><span class="text-slate-500">End</span><span class="text-slate-300 tabular-nums">${endStr}</span></div>
      <div class="flex justify-between"><span class="text-slate-500">Duration</span><span class="text-amber-300 font-semibold tabular-nums">${formatDuration(durationMs)}</span></div>
      ${traceDurationMs > 0 ? `<div>
        <div class="text-[10px] text-slate-600 mb-1">Position in trace</div>
        <div class="relative h-4 rounded bg-surface-200 overflow-hidden">
          <div class="absolute h-full rounded" style="left:${barLeft}%;width:${barWidth}%;background:linear-gradient(90deg,${isError ? '#ef4444' : '#7c7aef'},${isError ? '#f87171' : '#9b8ec4'});min-width:4px"></div>
        </div>
        <div class="flex justify-between text-[10px] text-slate-600 mt-0.5">
          <span>+${formatDuration(relOffset)}</span>
          <span>trace: ${formatDuration(traceDurationMs)}</span>
        </div>
      </div>` : ''}
    </div>
  `, true);

  // ---- Tool Input section (for tool spans) ----
  if (toolName || toolInput) {
    const toolHeader = toolName ? `<div class="flex items-center gap-1.5 mb-2">
      <span class="px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider rounded bg-blue-500/15 text-blue-400 border border-blue-500/25">Tool</span>
      <span class="text-xs font-semibold text-white">${escHtml(toolName || span.name)}</span>
    </div>` : '';
    const isPath = toolInput && (toolInput.startsWith('/') || toolInput.match(/^[A-Za-z]:\\/));
    const isCode = toolInput && toolInput.length > 20 && !isPath;
    html += renderCollapsibleSection('Tool Input', `
      ${toolHeader}
      ${toolInput ? `<div class="rounded-lg overflow-hidden border border-white/8">
        <div class="px-2 py-1 text-[9px] text-slate-600 uppercase tracking-wider font-semibold" style="background:rgba(255,255,255,0.03)">${isPath ? 'Path' : isCode ? 'Command / Query' : 'Input'}</div>
        <pre class="p-2.5 text-[11px] text-slate-300 font-mono overflow-x-auto leading-relaxed whitespace-pre-wrap break-words" style="background:rgba(0,0,0,0.2);max-height:160px">${escHtml(String(toolInput))}</pre>
      </div>` : '<span class="text-xs text-slate-500 italic">No input recorded</span>'}
    `, true);
  }

  // ---- Tool Output section ----
  if (toolOutput) {
    const outputStr = String(toolOutput);
    const truncated = outputStr.length > 500;
    html += renderCollapsibleSection('Tool Output', `
      <div class="rounded-lg overflow-hidden border border-white/8">
        <div class="px-2 py-1 text-[10px] text-slate-600 uppercase tracking-wider font-semibold" style="background:rgba(255,255,255,0.03)">Result</div>
        <pre class="p-2.5 text-[11px] font-mono overflow-x-auto leading-relaxed whitespace-pre-wrap break-words" style="color:var(--color-sage,#81b29a);opacity:0.9;background:rgba(129,178,154,0.04);max-height:160px">${escHtml(truncated ? outputStr.substring(0, 500) + '\n… (' + (outputStr.length - 500) + ' more chars)' : outputStr)}</pre>
      </div>
    `, true);
  }

  // ---- LLM Details section ----
  const tu = span.token_usage;
  const hasLlmData = llmModel || tu || llmInputTokens || llmOutputTokens;
  if (hasLlmData) {
    const inputTok = tu ? (tu.input_tokens || 0) : llmInputTokens;
    const outputTok = tu ? (tu.output_tokens || 0) : llmOutputTokens;
    const totalTok = inputTok + outputTok;
    const inputPct = totalTok > 0 ? ((inputTok / totalTok) * 100).toFixed(1) : 0;
    const outputPct = totalTok > 0 ? ((outputTok / totalTok) * 100).toFixed(1) : 0;
    const costUsd = tu ? (tu.total_cost_usd || 0) : 0;
    html += renderCollapsibleSection('LLM Details', `
      <div class="space-y-2.5 text-xs">
        ${llmModel ? `<div class="flex items-center gap-2">
          <span class="text-slate-500">Model</span>
          <span class="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-indigo-500/15 text-indigo-300 border border-indigo-500/25 font-mono">${escHtml(llmModel)}</span>
        </div>` : ''}
        ${totalTok > 0 ? `<div>
          <div class="flex justify-between mb-1">
            <span class="text-slate-500">Tokens</span>
            <span class="text-slate-300 tabular-nums font-mono">${totalTok.toLocaleString()} total</span>
          </div>
          <div class="flex h-3 rounded overflow-hidden gap-px" style="background:rgba(255,255,255,0.05)">
            <div class="rounded-l transition-all" style="width:${inputPct}%;background:var(--color-indigo-warm,#6b5ce7);opacity:0.65" title="Input ${inputPct}%"></div>
            <div class="rounded-r transition-all" style="width:${outputPct}%;background:var(--color-sage,#81b29a);opacity:0.7" title="Output ${outputPct}%"></div>
          </div>
          <div class="flex justify-between text-[10px] text-slate-600 mt-1">
            <span><span class="w-2 h-2 rounded-sm inline-block mr-1" style="background:var(--color-indigo-warm,#6b5ce7);opacity:0.65"></span>Input: ${inputTok.toLocaleString()} (${inputPct}%)</span>
            <span><span class="w-2 h-2 rounded-sm inline-block mr-1" style="background:var(--color-sage,#81b29a);opacity:0.7"></span>Output: ${outputTok.toLocaleString()} (${outputPct}%)</span>
          </div>
        </div>` : ''}
        ${costUsd > 0 ? `<div class="flex justify-between pt-1 border-t border-white/5">
          <span class="text-slate-500">Cost</span>
          <span class="font-semibold tabular-nums" style="color:var(--color-sage,#81b29a)">$${costUsd.toFixed(6)}</span>
        </div>` : ''}
      </div>
    `, true);
  }

  // ---- LLM Response preview (collapsible, closed by default) ----
  if (llmResponse) {
    const respStr = String(llmResponse);
    html += renderCollapsibleSection('Response Preview', `
      <div class="rounded-lg overflow-hidden border border-white/8">
        <pre class="p-2.5 text-[11px] text-slate-300 font-mono overflow-x-auto leading-relaxed whitespace-pre-wrap break-words" style="background:rgba(0,0,0,0.15);max-height:200px">${escHtml(respStr.length > 800 ? respStr.substring(0, 800) + '\n… (' + (respStr.length - 800) + ' more chars)' : respStr)}</pre>
      </div>
    `, false);
  }

  // ---- Parent ----
  if (span.parent_span_id) {
    const parentSpan = currentTraceData.spans.find(s => s.span_id === span.parent_span_id);
    html += renderCollapsibleSection('Parent', `
      <div class="text-xs font-mono text-indigo-400 cursor-pointer hover:text-indigo-300 transition" onclick="openSpanDetail('${span.parent_span_id}')">
        ${parentSpan ? escHtml(parentSpan.name) + ' — ' : ''}${span.parent_span_id}
      </div>
    `, true);
  }

  // ---- Children ----
  const children = currentTraceData.spans.filter(s => s.parent_span_id === span.span_id);
  if (children.length > 0) {
    let childrenHtml = '<div class="space-y-1">';
    children.forEach(child => {
      const childKind = (child.kind || 'custom').toLowerCase();
      const childCfg = SPAN_KIND_COLORS[childKind] || SPAN_KIND_COLORS.custom;
      const childErr = child.status === 'error';
      childrenHtml += `
        <div class="flex items-center gap-2 text-xs cursor-pointer hover:bg-white/[0.03] p-1 rounded transition" onclick="openSpanDetail('${child.span_id}')">
          <span class="px-1 py-0.5 text-[10px] font-medium rounded ${childCfg.bg} ${childCfg.text}">${childCfg.label}</span>
          <span class="text-slate-300 truncate">${escHtml(child.name)}</span>
          ${childErr ? '<span class="w-1.5 h-1.5 rounded-full flex-shrink-0" style="background:var(--color-coral,#e07a5f)"></span>' : ''}
          <span class="text-slate-600 ml-auto text-[10px] tabular-nums">${formatDuration(child.duration_ms || 0)}</span>
        </div>`;
    });
    childrenHtml += '</div>';
    html += renderCollapsibleSection(`Children (${children.length})`, childrenHtml, true);
  }

  // ---- Metadata — remaining attributes not already shown ----
  const remainingAttrs = Object.entries(attrs).filter(([k]) => !SEMANTIC_KEYS.has(k));
  if (remainingAttrs.length > 0) {
    let attrHtml = '<table class="w-full text-xs border-collapse">';
    for (const [key, val] of remainingAttrs) {
      const valStr = String(val);
      const isMono = key.includes('.') || valStr.length > 40 || /^[\w.-]+$/.test(valStr);
      attrHtml += `<tr class="border-b border-white/5 last:border-0">
        <td class="py-1.5 pr-3 text-slate-500 font-medium align-top w-2/5 break-all text-[11px]">${escHtml(key)}</td>
        <td class="py-1.5 text-slate-300 text-right align-top break-all ${isMono ? 'font-mono text-[10px]' : 'text-xs'}">${escHtml(valStr)}</td>
      </tr>`;
    }
    attrHtml += '</table>';
    html += renderCollapsibleSection(`Metadata (${remainingAttrs.length})`, attrHtml, false);
  }

  // ---- Events timeline ----
  const events = span.events || [];
  if (events.length > 0) {
    let eventsHtml = '<div class="space-y-2">';
    events.forEach(ev => {
      const evTime = ev.timestamp > 0 ? new Date(ev.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '--';
      const evOffset = ev.timestamp > 0 && span.start_time > 0 ? formatDuration((ev.timestamp - span.start_time) * 1000) : null;
      eventsHtml += `<div class="p-2 rounded-lg bg-surface-100 border border-white/5">
        <div class="flex justify-between text-xs mb-1">
          <span class="text-slate-300 font-medium">${escHtml(ev.name)}</span>
          <span class="text-slate-600 tabular-nums">${evTime}${evOffset ? ` (+${evOffset})` : ''}</span>
        </div>
        ${Object.keys(ev.attributes || {}).length > 0 ? `<pre class="text-[10px] text-slate-500 mt-1 overflow-x-auto rounded p-1" style="background:rgba(0,0,0,0.15)">${escHtml(JSON.stringify(ev.attributes, null, 2))}</pre>` : ''}
      </div>`;
    });
    eventsHtml += '</div>';
    html += renderCollapsibleSection(`Events (${events.length})`, eventsHtml, false);
  }

  document.getElementById('span-detail-content').innerHTML = html;
}

function closeSpanDetail() {
  document.getElementById('span-detail-panel').classList.add('hidden');
}

// ==================================================================// Causal DAG — with dagre layout, animated edges, zoom controls, legend
// ==================================================================
async function loadDAG(traceId) {
  // Show skeleton loading state
  const cyContainer = document.getElementById('cy-container');
  cyContainer.innerHTML = `
    <div class="flex items-center justify-center h-full">
      <div class="text-center">
        <div class="skeleton w-48 h-4 mb-3 mx-auto"></div>
        <div class="skeleton w-32 h-3 mx-auto"></div>
        <div class="mt-6 flex gap-4 justify-center">
          <div class="skeleton w-10 h-10 rounded-full"></div>
          <div class="skeleton w-10 h-10 rounded-full"></div>
          <div class="skeleton w-10 h-10 rounded-full"></div>
        </div>
        <div class="mt-4 flex gap-2 justify-center">
          <div class="skeleton w-20 h-1 rounded"></div>
          <div class="skeleton w-20 h-1 rounded"></div>
        </div>
      </div>
    </div>`;

  try {
    const data = await apiFetch(`/v1/traces/${traceId}/dag`);
    dagLoaded = true;
    renderDAG(data);
    renderDAGPatterns(data.patterns || []);
  } catch (err) {
    cyContainer.innerHTML = `<div class="flex items-center justify-center h-full text-slate-600 text-sm">Failed to load DAG: ${escHtml(err.message)}</div>`;
  }
}

function renderDAG(dagData) {
  if (cyInstance) { cyInstance.destroy(); cyInstance = null; }

  const kindColors = {
    llm: '#9b8ec4', tool: '#7ab5a0', agent: '#a88ec4', chain: '#c4b07a',
    retrieval: '#7a9eb5', custom: '#a0a09a'
  };

  const nodes = (dagData.nodes || []).map(n => {
    let bgColor = kindColors[n.kind] || '#64748b';
    let borderColor = bgColor;
    let borderWidth = 2;

    if (n.status === 'error') {
      if (n.error_role === 'root_cause') {
        borderColor = '#c47070';
        bgColor = '#c47070';
        borderWidth = 4;
      } else if (n.error_role === 'cascaded') {
        borderColor = '#c49a5c';
        bgColor = '#c49a5c';
        borderWidth = 3;
      }
    }

    return {
      data: {
        id: n.span_id,
        label: n.name.length > 22 ? n.name.substring(0, 20) + '..' : n.name,
        fullName: n.name,
        kind: n.kind,
        status: n.status,
        errorRole: n.error_role,
        bgColor,
        borderColor,
        borderWidth,
        duration: `${(n.duration_ms || 0).toFixed(0)}ms`,
        durationMs: n.duration_ms || 0,
      }
    };
  });

  const edges = (dagData.edges || []).map((e, i) => ({
    data: {
      id: `e${i}`,
      source: e.source,
      target: e.target,
      relation: e.relation,
      lineColor: e.relation === 'caused_by' ? '#c47070' : '#c49a5c',
      isError: e.relation === 'caused_by',
    }
  }));

  // Build parent-child edges from spans if none exist
  if (edges.length === 0 && currentTraceData && currentTraceData.spans) {
    const spanIds = new Set(nodes.map(n => n.data.id));
    currentTraceData.spans.forEach((s, i) => {
      if (s.parent_span_id && spanIds.has(s.parent_span_id) && spanIds.has(s.span_id)) {
        edges.push({
          data: {
            id: `pe${i}`,
            source: s.parent_span_id,
            target: s.span_id,
            relation: 'parent_child',
            lineColor: '#b5b5b0',
            isError: false,
          }
        });
      }
    });
  }

  // Register dagre layout if available
  if (typeof cytoscape !== 'undefined' && typeof cytoscapeDagre !== 'undefined') {
    try { cytoscape.use(cytoscapeDagre); } catch (e) { /* already registered */ }
  }

  // Choose layout — use dagre if available, fallback to breadthfirst
  let layoutConfig;
  if (typeof dagre !== 'undefined') {
    layoutConfig = {
      name: 'dagre',
      rankDir: 'TB',
      nodeSep: 50,
      rankSep: 70,
      edgeSep: 20,
      padding: 40,
    };
  } else {
    layoutConfig = {
      name: 'breadthfirst',
      directed: true,
      spacingFactor: 1.3,
      padding: 30,
    };
  }

  cyInstance = cytoscape({
    container: document.getElementById('cy-container'),
    elements: [...nodes, ...edges],
    style: [
      {
        selector: 'node',
        style: {
          'background-color': 'data(bgColor)',
          'border-color': 'data(borderColor)',
          'border-width': 'data(borderWidth)',
          'label': 'data(label)',
          'color': isDarkTheme ? '#e2e0db' : '#2c2c2a',
          'font-size': '10px',
          'font-family': 'Inter, system-ui, sans-serif',
          'text-valign': 'bottom',
          'text-margin-y': 8,
          'width': 40,
          'height': 40,
          'text-outline-color': isDarkTheme ? '#2a2a28' : '#fafaf8',
          'text-outline-width': 2,
          'transition-property': 'border-color, border-width, background-color',
          'transition-duration': '0.2s',
        }
      },
      {
        selector: 'node:active',
        style: {
          'overlay-opacity': 0.1,
          'overlay-color': '#7c7aef',
        }
      },
      {
        selector: 'edge',
        style: {
          'line-color': 'data(lineColor)',
          'target-arrow-color': 'data(lineColor)',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
          'width': 2,
          'opacity': 0.7,
          'arrow-scale': 0.8,
        }
      },
      {
        selector: 'edge[relation = "caused_by"]',
        style: {
          'line-style': 'solid',
          'width': 3,
          'opacity': 0.9,
          'line-dash-pattern': [8, 4],
          'line-dash-offset': 0,
        }
      },
      {
        selector: 'edge[relation = "preceded_by"]',
        style: { 'line-style': 'dashed' }
      },
    ],
    layout: layoutConfig,
    minZoom: 0.2,
    maxZoom: 4,
  });

  // Click node to show span details
  cyInstance.on('tap', 'node', function(evt) {
    openSpanDetail(evt.target.id());
  });

  // Hover effect on nodes
  cyInstance.on('mouseover', 'node', function(evt) {
    evt.target.style({
      'border-width': Math.max(evt.target.data('borderWidth') + 2, 4),
      'width': 48,
      'height': 48,
    });
    document.getElementById('cy-container').style.cursor = 'pointer';
  });
  cyInstance.on('mouseout', 'node', function(evt) {
    evt.target.style({
      'border-width': evt.target.data('borderWidth'),
      'width': 40,
      'height': 40,
    });
    document.getElementById('cy-container').style.cursor = 'default';
  });

  // Animate error edges (caused_by) with a pulsing dash effect
  animateErrorEdges();
}

/** Animate error propagation edges with flowing dashes */
function animateErrorEdges() {
  if (!cyInstance) return;
  const errorEdges = cyInstance.edges('[relation = "caused_by"]');
  if (errorEdges.length === 0) return;

  let offset = 0;
  function animate() {
    if (!cyInstance) return;
    offset = (offset + 1) % 20;
    errorEdges.forEach(edge => {
      edge.style('line-dash-offset', -offset);
    });
    requestAnimationFrame(animate);
  }
  animate();
}

/** DAG zoom controls */
function dagZoom(action) {
  if (!cyInstance) return;
  const currentZoom = cyInstance.zoom();
  if (action === 'in') {
    cyInstance.animate({ zoom: { level: currentZoom * 1.3, position: cyInstance.pan() }, duration: 200 });
  } else if (action === 'out') {
    cyInstance.animate({ zoom: { level: currentZoom / 1.3, position: cyInstance.pan() }, duration: 200 });
  } else if (action === 'fit') {
    cyInstance.animate({ fit: { padding: 40 }, duration: 300 });
  }
}

function renderDAGPatterns(patterns) {
  const container = document.getElementById('dag-patterns');
  if (!patterns || patterns.length === 0) {
    container.innerHTML = '<div class="glass rounded-xl p-4 text-sm text-slate-500">No patterns detected in this trace.</div>';
    return;
  }

  let html = '<div class="space-y-2">';
  patterns.forEach(p => {
    const sevClass = `severity-${p.severity}`;
    html += `
      <div class="rounded-xl p-4 border ${sevClass}">
        <div class="flex items-center gap-2 mb-1">
          <span class="px-2 py-0.5 text-[10px] font-bold uppercase rounded ${sevClass}">${p.severity}</span>
          <span class="text-xs font-medium text-slate-300">${escHtml(p.pattern)}</span>
        </div>
        <p class="text-xs text-slate-400">${escHtml(p.description)}</p>
      </div>
    `;
  });
  html += '</div>';
  container.innerHTML = html;
}

// ==================================================================// ==================================================================// Patterns
// ==================================================================
// Accumulated patterns (with trace context) for client-side filtering
let _allPatternsData = [];
let _activePatternFilter = 'all';

const SEVERITY_CONFIG = {
  critical: {
    color: 'coral',
    cardClass: 'pattern-card-critical',
    badgeClass: 'pattern-severity-badge-critical',
    icon: `<svg class="w-4 h-4 flex-shrink-0" style="color:var(--color-coral,#e07a5f)" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><circle cx="12" cy="19" r="0.5" fill="currentColor"/></svg>`,
    dotColor: 'severity-dot-critical',
    largeIcon: `<svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z" fill="rgba(224,122,95,0.15)"/><path stroke-linecap="round" stroke-linejoin="round" d="M15 9l-6 6m0-6l6 6" stroke="#e07a5f"/></svg>`,
    iconBg: 'sev-critical',
  },
  warning: {
    color: 'amber',
    cardClass: 'pattern-card-warning',
    badgeClass: 'pattern-severity-badge-warning',
    icon: `<svg class="w-4 h-4 flex-shrink-0" style="color:var(--color-amber-warm,#e6a65d)" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/></svg>`,
    dotColor: 'severity-dot-warning',
    largeIcon: `<svg class="w-5 h-5" viewBox="0 0 24 24" fill="none"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" fill="rgba(230,166,93,0.15)" stroke="#e6a65d" stroke-width="1.5"/><path d="M12 9v4m0 3h.01" stroke="#e6a65d" stroke-width="2" stroke-linecap="round"/></svg>`,
    iconBg: 'sev-warning',
  },
  info: {
    color: 'indigo',
    cardClass: 'pattern-card-info',
    badgeClass: 'pattern-severity-badge-info',
    icon: `<svg class="w-4 h-4 flex-shrink-0" style="color:var(--color-indigo-warm,#6b5ce7)" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>`,
    dotColor: 'severity-dot-info',
    largeIcon: `<svg class="w-5 h-5" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" fill="rgba(107,92,231,0.15)" stroke="#6b5ce7" stroke-width="1.5"/><path d="M12 16v-4m0-4h.01" stroke="#6b5ce7" stroke-width="2" stroke-linecap="round"/></svg>`,
    iconBg: 'sev-info',
  },
};

function renderPatternCard(pattern, traceId) {
  const sev = (pattern.severity || 'info').toLowerCase();
  const cfg = SEVERITY_CONFIG[sev] || SEVERITY_CONFIG.info;
  const patternName = escHtml((pattern.pattern || 'Unknown').replace(/_/g, ' '));
  const description = escHtml(pattern.description || '');
  const recommendation = pattern.recommendation || '';
  const codeSnippet = pattern.code_snippet || pattern.fix_code || null;
  const estimatedSavings = pattern.estimated_savings || null;
  const affectedCount = pattern.involved_spans ? pattern.involved_spans.length : 0;
  const cardId = 'pattern-' + Math.random().toString(36).substring(2, 8);
  const shortTraceId = traceId ? traceId.substring(0, 8) : '?';

  // Savings badge
  let savingsBadgeHtml = '';
  if (estimatedSavings) {
    const parts = [];
    if (estimatedSavings.tokens) parts.push(`~${estimatedSavings.tokens.toLocaleString()} tokens`);
    if (estimatedSavings.cost_usd) parts.push(`$${Number(estimatedSavings.cost_usd).toFixed(4)}`);
    if (estimatedSavings.time_ms) parts.push(`${formatDuration(estimatedSavings.time_ms)}`);
    if (parts.length > 0) {
      savingsBadgeHtml = `<span class="cost-savings-badge">Save: ${escHtml(parts.join(' · '))}</span>`;
    }
  }

  // Involved spans section
  let spansDetailHtml = '';
  if (pattern.involved_spans && pattern.involved_spans.length > 0) {
    const spanItems = pattern.involved_spans.map(s => {
      const spanName = typeof s === 'string' ? s : (s.name || s.span_id || 'unknown');
      const spanRole = typeof s === 'object' ? (s.role || '') : '';
      return `<div class="flex items-center gap-2 px-2 py-1.5 rounded bg-surface-100/50 text-[11px]">
        <span class="w-1.5 h-1.5 rounded-full ${cfg.dotColor} flex-shrink-0"></span>
        <span class="text-slate-300 font-mono truncate">${escHtml(spanName)}</span>
        ${spanRole ? `<span class="text-slate-600 text-[10px]">${escHtml(spanRole)}</span>` : ''}
      </div>`;
    }).join('');
    spansDetailHtml = `
      <div class="mt-2">
        <div class="text-[10px] text-slate-500 uppercase tracking-wider font-semibold mb-1.5">Affected Spans</div>
        <div class="space-y-1 max-h-40 overflow-y-auto">${spanItems}</div>
      </div>`;
  }

  // Code fix section
  let codeFixHtml = '';
  if (codeSnippet) {
    const fixId = cardId + '-fix';
    codeFixHtml = `
      <div class="mt-2 pt-2 border-t border-white/5">
        <button class="flex items-center gap-1.5 text-[10px] text-indigo-400 hover:text-indigo-300 transition font-semibold"
                onclick="event.stopPropagation();var el=document.getElementById('${fixId}');el.classList.toggle('hidden');">
          <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"/></svg>
          Show Code Fix
        </button>
        <div id="${fixId}" class="hidden mt-2 rounded-lg overflow-hidden border border-white/8">
          <div class="px-2 py-1 text-[10px] text-slate-600 uppercase tracking-wider font-semibold" style="background:rgba(255,255,255,0.03)">Recommended Fix</div>
          <pre class="p-2.5 text-[10px] font-mono overflow-x-auto leading-relaxed whitespace-pre-wrap" style="color:var(--color-sage,#81b29a);opacity:0.9;background:rgba(129,178,154,0.04);max-height:200px">${escHtml(codeSnippet)}</pre>
        </div>
      </div>`;
  }

  return `
    <div id="${cardId}" class="glass rounded-xl p-4 border border-white/5 ${cfg.cardClass} glass-hover cursor-pointer transition pattern-card-expandable"
         data-severity="${escHtml(sev)}"
         onclick="this.classList.toggle('expanded');">
      <div class="flex items-start gap-3">
        <div class="pattern-severity-icon ${cfg.iconBg} flex-shrink-0">
          ${cfg.largeIcon}
        </div>
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="text-xs font-bold text-white">${patternName}</span>
            <span class="px-1.5 py-0.5 text-[10px] font-semibold uppercase rounded ${cfg.badgeClass}">${escHtml(sev)}</span>
            ${affectedCount > 0 ? `<span class="pattern-count-badge">${affectedCount} span${affectedCount > 1 ? 's' : ''}</span>` : ''}
            ${savingsBadgeHtml}
            <span class="pattern-expand-chevron text-slate-600 ml-auto">
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
            </span>
          </div>
          <p class="text-xs text-slate-400 mt-1 leading-relaxed">${description}</p>
          <!-- Trace link always visible -->
          <button class="mt-1.5 flex items-center gap-1 text-[10px] text-indigo-400 hover:text-indigo-300 transition"
                  onclick="event.stopPropagation(); openTrace('${escHtml(traceId)}')">
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
            View trace ${shortTraceId}...
          </button>
        </div>
      </div>

      <!-- Expandable detail section -->
      <div class="pattern-detail-section">
        ${recommendation ? `
          <div class="mt-3 p-2.5 rounded-lg border border-white/5 text-xs" style="background:rgba(255,255,255,0.03)">
            <div class="text-[10px] text-slate-500 uppercase tracking-wider font-semibold mb-1">Recommendation</div>
            <p class="text-slate-300 leading-relaxed">${escHtml(recommendation)}</p>
          </div>` : ''}
        ${spansDetailHtml}
        ${codeFixHtml}
      </div>
    </div>
  `;
}

function filterPatterns(severity) {
  _activePatternFilter = severity;

  // Update filter button active states
  document.querySelectorAll('.pattern-filter-btn').forEach(btn => {
    const btnSev = btn.getAttribute('onclick').match(/'([^']+)'/)?.[1];
    if (btnSev === severity) {
      btn.className = 'pattern-filter-btn px-2.5 py-1 text-[10px] rounded bg-indigo-500/20 text-indigo-300 font-medium border border-indigo-500/30 transition active';
    } else {
      btn.className = 'pattern-filter-btn px-2.5 py-1 text-[10px] rounded bg-surface-100 text-slate-400 hover:text-white border border-white/10 hover:border-white/20 transition';
    }
  });

  // Re-render with filter
  _renderFilteredPatterns();
}

function _renderFilteredPatterns() {
  const container = document.getElementById('patterns-list');
  if (!container) return;

  const filtered = _activePatternFilter === 'all'
    ? _allPatternsData
    : _allPatternsData.filter(item => (item.pattern.severity || 'info').toLowerCase() === _activePatternFilter);

  if (filtered.length === 0) {
    const msg = _activePatternFilter === 'all'
      ? 'No anti-patterns detected'
      : `No ${_activePatternFilter} patterns detected`;
    const sub = _activePatternFilter === 'all'
      ? 'Checked recent error traces — all clear.'
      : 'Try a different severity filter.';
    const headerHtml = `
      <div class="flex items-center justify-between mb-4">
        <span class="text-xs text-slate-500">${_allPatternsData.length} total pattern(s) across all severities</span>
      </div>`;
    container.innerHTML = headerHtml + renderEmptyState(msg, sub);
    return;
  }

  const totalCount = _allPatternsData.length;
  const visibleCount = filtered.length;

  // Group by severity: critical → warning → info
  const SEVERITY_ORDER = ['critical', 'warning', 'info'];
  const grouped = {};
  SEVERITY_ORDER.forEach(s => { grouped[s] = []; });
  filtered.forEach(item => {
    const sev = (item.pattern.severity || 'info').toLowerCase();
    if (!grouped[sev]) grouped[sev] = [];
    grouped[sev].push(item);
  });

  const SEV_LABELS = { critical: 'Critical', warning: 'Warning', info: 'Info' };
  const SEV_COLORS = { critical: '#ef4444', warning: '#f59e0b', info: '#3b82f6' };

  let groupsHtml = '';
  SEVERITY_ORDER.forEach(sev => {
    const items = grouped[sev];
    if (!items || items.length === 0) return;
    const color = SEV_COLORS[sev];
    const groupId = 'pgroup-' + sev;
    groupsHtml += `
      <div class="mb-5">
        <div class="flex items-center gap-2 mb-3 collapsible-header" onclick="var g=document.getElementById('${groupId}');g.classList.toggle('collapsed');this.querySelector('.collapsible-chevron').classList.toggle('rotated');">
          <span class="w-2 h-2 rounded-full flex-shrink-0" style="background:${color}"></span>
          <span class="text-xs font-bold uppercase tracking-wider" style="color:${color}">${SEV_LABELS[sev]}</span>
          <span class="px-1.5 py-0.5 rounded text-[10px] font-semibold" style="background:${color}22;color:${color}">${items.length}</span>
          <span class="collapsible-chevron rotated text-slate-600 ml-1">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
          </span>
        </div>
        <div id="${groupId}" class="collapsible-content" style="max-height:9999px">
          <div class="grid grid-cols-1 lg:grid-cols-2 gap-3">
            ${items.map(item => renderPatternCard(item.pattern, item.traceId)).join('')}
          </div>
        </div>
      </div>`;
  });

  container.innerHTML = `
    <div class="flex items-center justify-between mb-4">
      <span class="text-xs text-slate-500">${visibleCount} of ${totalCount} pattern(s) shown</span>
    </div>
    ${groupsHtml}
  `;
}

async function loadAllPatterns() {
  const container = document.getElementById('patterns-list');
  _allPatternsData = [];

  try {
    const tracesData = await apiFetch('/v1/traces?limit=20');
    if (!tracesData.traces || tracesData.traces.length === 0) {
      container.innerHTML = renderEmptyState('No traces available', 'Patterns are detected per-trace via the DAG analysis.');
      return;
    }

    const errorTraces = tracesData.traces.filter(t => t.has_errors === true || t.has_errors === 1);
    if (errorTraces.length === 0) {
      container.innerHTML = `
        <div class="glass rounded-xl p-8 text-center">
          <svg class="w-16 h-16 text-emerald-500/20 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
          <p class="text-sm text-slate-400">No error traces found</p>
          <p class="text-xs text-slate-600 mt-1">Anti-patterns are detected when traces contain errors.</p>
        </div>
      `;
      return;
    }

    // Show loading skeleton
    container.innerHTML = `
      <div class="glass rounded-xl p-6 space-y-3">
        <div class="skeleton skeleton-warm skeleton-text w-48"></div>
        <div class="skeleton skeleton-warm skeleton-bar"></div>
        <div class="skeleton skeleton-warm skeleton-bar"></div>
        <div class="skeleton skeleton-warm skeleton-bar"></div>
      </div>
    `;

    for (const trace of errorTraces.slice(0, 10)) {
      try {
        const dag = await apiFetch(`/v1/traces/${trace.trace_id}/dag`);
        if (dag.patterns && dag.patterns.length > 0) {
          dag.patterns.forEach(p => {
            _allPatternsData.push({ pattern: p, traceId: trace.trace_id });
          });
        }
      } catch (e) {
        // Skip traces that fail DAG analysis
      }
    }

    if (_allPatternsData.length === 0) {
      container.innerHTML = renderEmptyState('No anti-patterns detected', 'Checked recent error traces — all clear.');
    } else {
      // Reset filter to 'all' when reloading
      _activePatternFilter = 'all';
      document.querySelectorAll('.pattern-filter-btn').forEach(btn => {
        const btnSev = btn.getAttribute('onclick').match(/'([^']+)'/)?.[1];
        if (btnSev === 'all') {
          btn.className = 'pattern-filter-btn px-2.5 py-1 text-[10px] rounded bg-indigo-500/20 text-indigo-300 font-medium border border-indigo-500/30 transition active';
        } else {
          btn.className = 'pattern-filter-btn px-2.5 py-1 text-[10px] rounded bg-surface-100 text-slate-400 hover:text-white border border-white/10 hover:border-white/20 transition';
        }
      });
      _renderFilteredPatterns();
    }
  } catch (err) {
    container.innerHTML = `<div class="glass rounded-xl p-8 text-center text-red-400/60 text-sm">Failed to load patterns: ${escHtml(err.message)}</div>`;
  }
}

// ==================================================================// Export Features
// ==================================================================
/** Export current trace data as JSON file */
function exportTraceJSON() {
  if (!currentTraceData) {
    showToast('No trace data to export', 'warning');
    return;
  }
  const json = JSON.stringify(currentTraceData, null, 2);
  const blob = new Blob([json], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `trace-${currentTraceId || 'unknown'}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  showToast('Trace exported as JSON', 'success');
}

/** Export DAG as PNG using Cytoscape's png() method */
function exportDAGPng() {
  if (!cyInstance) {
    showToast('No DAG to export', 'warning');
    return;
  }
  try {
    const pngData = cyInstance.png({ output: 'blob', bg: isDarkTheme ? '#2a2a28' : '#fafaf8', scale: 2, full: true });
    const url = URL.createObjectURL(pngData);
    const a = document.createElement('a');
    a.href = url;
    a.download = `dag-${currentTraceId || 'unknown'}.png`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('DAG exported as PNG', 'success');
  } catch (err) {
    console.error('DAG PNG export error:', err);
    showToast('Failed to export DAG', 'error');
  }
}

/** Copy current trace ID to clipboard */
function copyTraceId() {
  if (!currentTraceId) return;
  navigator.clipboard.writeText(currentTraceId).then(() => {
    showToast('Trace ID copied to clipboard', 'success', 2000);
  }).catch(() => {
    // Fallback for older browsers
    const textarea = document.createElement('textarea');
    textarea.value = currentTraceId;
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
    showToast('Trace ID copied to clipboard', 'success', 2000);
  });
}

// ==================================================================// Connection Status
// ==================================================================
async function healthCheck() {
  try {
    await apiFetch('/health');
    return true;
  } catch {
    updateWsStatus('error');
    return false;
  }
}

// ==================================================================// Keyboard Navigation
// ==================================================================
function setupKeyboardNavigation() {
  document.addEventListener('keydown', (e) => {
    // Close notification panel on Escape
    const notifPanel = document.getElementById('notification-panel');
    if (e.key === 'Escape' && notifPanel && !notifPanel.classList.contains('hidden')) {
      notifPanel.classList.add('hidden');
      return;
    }

    // Close shortcuts modal on Escape
    const shortcutsModal = document.getElementById('shortcuts-modal');
    if (e.key === 'Escape' && !shortcutsModal.classList.contains('hidden')) {
      closeShortcutsModal();
      return;
    }

    // "?" to show shortcuts help — only when not in input
    if (e.key === '?' && !isInputFocused()) {
      e.preventDefault();
      openShortcutsModal();
      return;
    }

    // "/" to focus search — only when not already in an input
    if (e.key === '/' && !isInputFocused()) {
      e.preventDefault();
      const searchInput = document.getElementById('filter-service');
      if (searchInput) {
        switchView('traces');
        setTimeout(() => searchInput.focus(), 100);
      }
      return;
    }

    // "t" to toggle theme
    if (e.key === 't' && !isInputFocused()) {
      toggleTheme();
      return;
    }

    // "r" to refresh
    if (e.key === 'r' && !isInputFocused()) {
      refreshCurrentView();
      return;
    }

    // "n" to toggle notification panel
    if (e.key === 'n' && !isInputFocused()) {
      toggleNotificationPanel();
      return;
    }

    // Number keys + letter shortcuts for view switching
    if (!isInputFocused()) {
      const viewMap = { '1': 'overview', '2': 'traces', '3': 'cost', '4': 'patterns', '5': 'compare', '6': 'agents', 'a': 'agents' };
      if (viewMap[e.key]) {
        switchView(viewMap[e.key]);
        return;
      }
    }

    // Escape to go back or close panels
    if (e.key === 'Escape') {
      const agentModal = document.getElementById('agent-detail-modal');
      if (agentModal && !agentModal.classList.contains('hidden')) {
        closeAgentDetailModal();
        return;
      }
      const spanPanel = document.getElementById('span-detail-panel');
      if (!spanPanel.classList.contains('hidden')) {
        closeSpanDetail();
        return;
      }
      const detailPanel = document.getElementById('view-trace-detail');
      if (!detailPanel.classList.contains('hidden')) {
        backToTraces();
        return;
      }
    }

    // j/k and Arrow keys for trace list navigation
    if (currentView === 'traces' || currentView === 'overview') {
      const listId = currentView === 'traces' ? 'traces-list' : 'recent-traces-list';
      const rows = document.querySelectorAll(`#${listId} .trace-row`);
      if (rows.length === 0) return;

      if ((e.key === 'j' || e.key === 'ArrowDown') && !isInputFocused()) {
        e.preventDefault();
        selectedTraceIndex = Math.min(selectedTraceIndex + 1, rows.length - 1);
        highlightTraceRow(rows);
      } else if ((e.key === 'k' || e.key === 'ArrowUp') && !isInputFocused()) {
        e.preventDefault();
        selectedTraceIndex = Math.max(selectedTraceIndex - 1, 0);
        highlightTraceRow(rows);
      } else if (e.key === 'Enter' && selectedTraceIndex >= 0 && !isInputFocused()) {
        e.preventDefault();
        const traceId = rows[selectedTraceIndex]?.dataset?.traceId;
        if (traceId) openTrace(traceId);
      }
    }
  });
}

function refreshCurrentView() {
  if (currentView === 'overview') {
    loadStats();
    loadRecentTraces();
    loadAgentActivity();
    loadOverviewAgents();
    loadActivityTimeline();
    loadTrendChart(_trendHours || 24);
    loadOverviewCharts();
    loadOverviewGraph();
    loadRecentFeedback();
  }
  else if (currentView === 'traces') { loadTraces(); }
  else if (currentView === 'cost') { loadCostData(); }
  else if (currentView === 'patterns') { loadAllPatterns(); }
  showToast('Refreshed', 'success', 1500);
}

// ==================================================================// Theme Toggle
// ==================================================================
function toggleTheme() {
  isDarkTheme = !isDarkTheme;
  if (isDarkTheme) {
    document.documentElement.classList.add('dark');
    document.body.classList.add('dark');
    localStorage.setItem('flowlens-theme', 'dark');
  } else {
    document.documentElement.classList.remove('dark');
    document.body.classList.remove('dark');
    localStorage.setItem('flowlens-theme', 'light');
  }
  // Update chart colors if charts exist
  updateChartTheme();
}

function updateChartTheme() {
  const textColor = isDarkTheme ? '#94a3b8' : '#64748b';
  const gridColor = isDarkTheme ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.06)';
  for (const [id, chart] of Object.entries(chartInstances)) {
    if (chart && chart.options) {
      if (chart.options.plugins && chart.options.plugins.legend && chart.options.plugins.legend.labels) {
        chart.options.plugins.legend.labels.color = textColor;
      }
      if (chart.options.scales) {
        for (const axis of Object.values(chart.options.scales)) {
          if (axis.ticks) axis.ticks.color = textColor;
          if (axis.grid) axis.grid.color = gridColor;
        }
      }
      chart.update();
    }
  }
}

// ==================================================================// Shortcuts Modal
// ==================================================================
function openShortcutsModal() {
  document.getElementById('shortcuts-modal').classList.remove('hidden');
}
function closeShortcutsModal() {
  document.getElementById('shortcuts-modal').classList.add('hidden');
}

function isInputFocused() {
  const el = document.activeElement;
  return el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT');
}

function highlightTraceRow(rows) {
  rows.forEach((r, i) => {
    r.classList.toggle('trace-row-selected', i === selectedTraceIndex);
  });
  // Scroll selected row into view
  if (rows[selectedTraceIndex]) {
    rows[selectedTraceIndex].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
}

// ==================================================================// Auto-refresh
// ==================================================================
function startAutoRefresh() {
  if (autoRefreshTimer) clearInterval(autoRefreshTimer);
  autoRefreshTimer = setInterval(async () => {
    const ok = await healthCheck();
    if (!ok) return;
    // Only refresh lightweight data — skip heavy charts/agents/graph to avoid lag
    if (currentView === 'overview') { loadStats(); loadRecentTraces(); }
    else if (currentView === 'traces') { loadTraces(); }
  }, 30000); // 30s instead of 15s
}

// ==================================================================// Collapsible Sections Helper
// ==================================================================
function renderCollapsibleSection(title, content, startOpen = true, titleColor = 'text-slate-400') {
  const id = 'section-' + title.replace(/[^a-zA-Z0-9]/g, '-').toLowerCase() + '-' + Math.random().toString(36).substr(2, 4);
  return `<div class="mb-3">
    <div class="collapsible-header flex items-center gap-1.5 mb-2" onclick="toggleCollapsible('${id}', this)">
      <svg class="collapsible-chevron w-3 h-3 ${titleColor} ${startOpen ? 'rotated' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
      <h5 class="text-xs font-semibold ${titleColor} uppercase tracking-wider">${title}</h5>
    </div>
    <div id="${id}" class="collapsible-content ${startOpen ? '' : 'collapsed'}" style="max-height:${startOpen ? '2000px' : '0'}">
      ${content}
    </div>
  </div>`;
}

function toggleCollapsible(id, headerEl) {
  const content = document.getElementById(id);
  const chevron = headerEl.querySelector('.collapsible-chevron');
  if (content.classList.contains('collapsed')) {
    content.classList.remove('collapsed');
    content.style.maxHeight = content.scrollHeight + 'px';
    chevron.classList.add('rotated');
  } else {
    content.style.maxHeight = '0';
    content.classList.add('collapsed');
    chevron.classList.remove('rotated');
  }
}

// ==================================================================// Span Tree Collapse/Expand
// ==================================================================
function toggleSpanChildren(spanId, btn) {
  const rows = document.querySelectorAll('.waterfall-row');
  const isCollapsing = btn.classList.contains('rotated');

  btn.classList.toggle('rotated');

  // Find all descendant spans
  const descendants = new Set();
  function findDescendants(parentId) {
    rows.forEach(row => {
      if (row.dataset.parentSpanId === parentId) {
        descendants.add(row.dataset.spanId);
        findDescendants(row.dataset.spanId);
      }
    });
  }
  findDescendants(spanId);

  rows.forEach(row => {
    if (descendants.has(row.dataset.spanId)) {
      row.style.display = isCollapsing ? 'none' : 'flex';
      // Also reset child collapse buttons when expanding
      if (!isCollapsing) {
        const childBtn = row.querySelector('.collapsible-chevron');
        if (childBtn) childBtn.classList.add('rotated');
      }
    }
  });
}

// ==================================================================// Trace Comparison
// ==================================================================
function toggleCompare(traceId, checkbox) {
  const idx = compareSelection.indexOf(traceId);
  if (idx >= 0) {
    compareSelection.splice(idx, 1);
    checkbox.classList.remove('checked');
  } else {
    if (compareSelection.length >= 2) {
      showToast('Maximum 2 traces can be compared. Deselect one first.', 'warning');
      checkbox.checked = false;
      return;
    }
    compareSelection.push(traceId);
    checkbox.classList.add('checked');
  }
  updateCompareBadge();
}

function updateCompareBadge() {
  const badge = document.getElementById('compare-badge');
  if (compareSelection.length > 0) {
    badge.classList.remove('hidden');
    badge.textContent = compareSelection.length;
  } else {
    badge.classList.add('hidden');
  }
}

function clearComparison() {
  compareSelection = [];
  updateCompareBadge();
  document.querySelectorAll('.compare-checkbox').forEach(cb => {
    cb.checked = false;
    cb.classList.remove('checked');
  });
  renderCompareView();
}

async function renderCompareView() {
  const instructions = document.getElementById('compare-instructions');
  const content = document.getElementById('compare-content');

  if (compareSelection.length < 2) {
    instructions.classList.remove('hidden');
    content.classList.add('hidden');
    return;
  }

  instructions.classList.add('hidden');
  content.classList.remove('hidden');
  content.innerHTML = '<div class="text-center text-sm text-slate-500 py-8">Loading traces for comparison...</div>';

  try {
    const [trace1, trace2] = await Promise.all([
      apiFetch(`/v1/traces/${compareSelection[0]}`),
      apiFetch(`/v1/traces/${compareSelection[1]}`),
    ]);

    // ---- Compute metrics for diff ----
    const dur1 = trace1.duration_ms || 0;
    const dur2 = trace2.duration_ms || 0;
    const cost1 = trace1.total_cost_usd || 0;
    const cost2 = trace2.total_cost_usd || 0;
    const spans1 = trace1.span_count || (trace1.spans || []).length;
    const spans2 = trace2.span_count || (trace2.spans || []).length;
    const errors1 = trace1.has_errors ? 1 : 0;
    const errors2 = trace2.has_errors ? 1 : 0;
    const tokens1 = trace1.total_tokens || 0;
    const tokens2 = trace2.total_tokens || 0;

    // Compute verdict: look at duration + cost (weighted lower-is-better)
    function verdictScore(d1, c1, e1, d2, c2, e2) {
      let improvements = 0, regressions = 0;
      // Duration
      if (d1 > 0 && Math.abs(d2 - d1) / d1 > 0.02) { d2 < d1 ? improvements++ : regressions++; }
      // Cost
      if (c1 > 0 && Math.abs(c2 - c1) / c1 > 0.02) { c2 < c1 ? improvements++ : regressions++; }
      // Errors
      if (e1 !== e2) { e2 < e1 ? improvements++ : regressions++; }
      if (improvements > regressions) return 'improved';
      if (regressions > improvements) return 'regressed';
      return 'similar';
    }
    const verdict = verdictScore(dur1, cost1, errors1, dur2, cost2, errors2);
    const verdictConfig = {
      improved:  { label: 'Improved',  icon: '↑', cls: 'compare-verdict-improved' },
      regressed: { label: 'Regressed', icon: '↓', cls: 'compare-verdict-regressed' },
      similar:   { label: 'Similar',   icon: '≈', cls: 'compare-verdict-similar' },
    }[verdict];

    // ---- Helper: diff bar HTML ----
    function diffBar(v1, v2, lowerBetter) {
      if (v1 === 0 && v2 === 0) return '';
      const pctRaw = v1 > 0 ? (v2 - v1) / v1 : (v2 > 0 ? 1 : 0);
      const absPct = Math.min(Math.abs(pctRaw) * 100, 100);
      const isBetter = lowerBetter ? pctRaw < 0 : pctRaw > 0;
      const barColor = pctRaw === 0 ? '#6366f1' : (isBetter ? '#10b981' : '#ef4444');
      const sign = pctRaw > 0 ? '+' : '';
      const pctLabel = v1 > 0 ? `${sign}${(pctRaw * 100).toFixed(1)}%` : (v2 > 0 ? 'new' : '—');
      return `<div class="flex items-center gap-2 mt-1.5">
        <div class="compare-diff-bar-bg flex-1"><div class="compare-diff-bar-fill" style="width:${absPct}%;background:${barColor}"></div></div>
        <span class="text-[10px] font-medium flex-shrink-0" style="color:${barColor}">${pctLabel}</span>
      </div>`;
    }

    // ---- Summary cards (Trace A vs Trace B) ----
    function summaryCard(t, label, spanCount) {
      const hasErrors = t.has_errors === true || t.has_errors === 1;
      const p = getAgentProfile(t.service_name || '');
      return `
        <div class="glass compare-summary-card">
          <div class="trace-label text-slate-400">${escHtml(label)}</div>
          <div class="flex items-center gap-2 mb-3">
            <span class="text-xs font-mono text-slate-400 truncate">${t.trace_id.substring(0, 16)}…</span>
            ${hasErrors
              ? '<span class="px-1.5 py-0.5 text-[10px] font-medium rounded" style="background:var(--color-coral-bg,rgba(224,122,95,0.10));color:var(--color-coral,#e07a5f);border:1px solid var(--color-coral-border,rgba(224,122,95,0.28))">Error</span>'
              : '<span class="px-1.5 py-0.5 text-[10px] font-medium rounded" style="background:var(--color-sage-bg,rgba(129,178,154,0.10));color:var(--color-sage,#81b29a);border:1px solid var(--color-sage-border,rgba(129,178,154,0.25))">OK</span>'}
            <button onclick="openTrace('${escHtml(t.trace_id)}')" class="ml-auto text-[10px] text-indigo-400 hover:text-indigo-300 transition">View →</button>
          </div>
          <div class="compare-metric-row">
            <span class="text-slate-500">Service</span>
            <span class="text-slate-300 font-medium">${escHtml(t.service_name || 'unknown')}</span>
          </div>
          <div class="compare-metric-row">
            <span class="text-slate-500">Duration</span>
            <span class="text-slate-300 font-medium">${formatDuration(t.duration_ms || 0)}</span>
          </div>
          <div class="compare-metric-row">
            <span class="text-slate-500">Spans</span>
            <span class="text-slate-300 font-medium">${spanCount}</span>
          </div>
          <div class="compare-metric-row">
            <span class="text-slate-500">Cost</span>
            <span class="text-slate-300 font-medium">$${(t.total_cost_usd || 0).toFixed(4)}</span>
          </div>
          <div class="compare-metric-row">
            <span class="text-slate-500">Tokens</span>
            <span class="text-slate-300 font-medium">${(t.total_tokens || 0).toLocaleString()}</span>
          </div>
          <div class="compare-metric-row">
            <span class="text-slate-500">Errors</span>
            ${hasErrors
              ? '<span class="font-medium" style="color:var(--color-coral,#e07a5f)">Yes</span>'
              : '<span class="font-medium" style="color:var(--color-sage,#81b29a)">No</span>'}
          </div>
        </div>`;
    }

    let html = '';

    // ---- Verdict banner ----
    html += `<div class="glass rounded-xl p-4 mb-4 flex items-center gap-4">
      <span class="compare-verdict-badge ${verdictConfig.cls}">
        <span>${verdictConfig.icon}</span> ${verdictConfig.label}
      </span>
      <span class="text-xs text-slate-400">Trace B compared to Trace A</span>
    </div>`;

    // ---- Side-by-side summary cards ----
    html += `<div class="compare-cards-grid grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
      ${summaryCard(trace1, 'Trace A (baseline)', spans1)}
      ${summaryCard(trace2, 'Trace B (comparison)', spans2)}
    </div>`;

    // ---- Diff metrics section ----
    html += `<div class="glass rounded-xl p-4">
      <h3 class="text-sm font-semibold text-white mb-3">Metric Differences  <span class="text-[10px] font-normal text-slate-500">(B vs A)</span></h3>
      <div class="space-y-3">`;

    // Duration diff
    const durDiff = dur2 - dur1;
    const durPct = dur1 > 0 ? (durDiff / dur1 * 100).toFixed(1) : '—';
    const durBetter = durDiff < 0;
    html += `<div class="p-3 rounded-lg ${durDiff === 0 ? '' : (durBetter ? 'compare-diff-better' : 'compare-diff-worse')}">
      <div class="flex items-center justify-between text-xs">
        <span class="text-slate-400 font-medium">Duration</span>
        <div class="flex items-center gap-3">
          <span class="text-slate-300">${formatDuration(dur1)}</span>
          <span class="text-slate-600 text-[10px]">→</span>
          <span class="font-semibold" style="color:${durBetter ? 'var(--color-sage,#81b29a)' : durDiff > 0 ? 'var(--color-coral,#e07a5f)' : 'inherit'}">${formatDuration(dur2)}</span>
        </div>
      </div>
      ${diffBar(dur1, dur2, true)}
    </div>`;

    // Cost diff
    const costDiff = cost2 - cost1;
    const costPct = cost1 > 0 ? (costDiff / cost1 * 100).toFixed(1) : '—';
    const costBetter = costDiff < 0;
    html += `<div class="p-3 rounded-lg ${costDiff === 0 ? '' : (costBetter ? 'compare-diff-better' : 'compare-diff-worse')}">
      <div class="flex items-center justify-between text-xs">
        <span class="text-slate-400 font-medium">Cost</span>
        <div class="flex items-center gap-3">
          <span class="text-slate-300">$${cost1.toFixed(4)}</span>
          <span class="text-slate-600 text-[10px]">→</span>
          <span class="font-semibold" style="color:${costBetter ? 'var(--color-sage,#81b29a)' : costDiff > 0 ? 'var(--color-coral,#e07a5f)' : 'inherit'}">$${cost2.toFixed(4)}</span>
        </div>
      </div>
      ${diffBar(cost1, cost2, true)}
    </div>`;

    // Span count diff
    const spanDiff = spans2 - spans1;
    html += `<div class="p-3 rounded-lg">
      <div class="flex items-center justify-between text-xs">
        <span class="text-slate-400 font-medium">Span Count</span>
        <div class="flex items-center gap-3">
          <span class="text-slate-300">${spans1}</span>
          <span class="text-slate-600 text-[10px]">→</span>
          <span class="font-semibold ${spanDiff !== 0 ? 'text-slate-200' : 'text-slate-300'}">${spans2}${spanDiff !== 0 ? ` <span class="text-slate-500 font-normal">(${spanDiff > 0 ? '+' : ''}${spanDiff})</span>` : ''}</span>
        </div>
      </div>
    </div>`;

    // Error comparison
    const bothOk = errors1 === 0 && errors2 === 0;
    const errorFixed = errors1 === 1 && errors2 === 0;
    const errorAdded = errors1 === 0 && errors2 === 1;
    const errorCls = errorFixed ? 'compare-diff-better' : errorAdded ? 'compare-diff-worse' : '';
    html += `<div class="p-3 rounded-lg ${errorCls}">
      <div class="flex items-center justify-between text-xs">
        <span class="text-slate-400 font-medium">Errors</span>
        <div class="flex items-center gap-2">
          <span style="color:${errors1 ? 'var(--color-coral,#e07a5f)' : 'var(--color-sage,#81b29a)'}">${errors1 ? 'Error' : 'OK'}</span>
          <span class="text-slate-600 text-[10px]">→</span>
          <span class="font-semibold" style="color:${errors2 ? 'var(--color-coral,#e07a5f)' : 'var(--color-sage,#81b29a)'}">${errors2 ? 'Error' : 'OK'}</span>
          ${errorFixed ? `<span class="text-[10px] ml-1" style="color:var(--color-sage,#81b29a)">Fixed</span>` : ''}
          ${errorAdded ? `<span class="text-[10px] ml-1" style="color:var(--color-coral,#e07a5f)">Introduced</span>` : ''}
        </div>
      </div>
    </div>`;

    // Tokens diff
    const tokDiff = tokens2 - tokens1;
    html += `<div class="p-3 rounded-lg ${tokDiff === 0 ? '' : (tokDiff < 0 ? 'compare-diff-better' : 'compare-diff-worse')}">
      <div class="flex items-center justify-between text-xs">
        <span class="text-slate-400 font-medium">Total Tokens</span>
        <div class="flex items-center gap-3">
          <span class="text-slate-300">${tokens1.toLocaleString()}</span>
          <span class="text-slate-600 text-[10px]">→</span>
          <span class="font-semibold" style="color:${tokDiff < 0 ? 'var(--color-sage,#81b29a)' : tokDiff > 0 ? 'var(--color-coral,#e07a5f)' : 'inherit'}">${tokens2.toLocaleString()}</span>
        </div>
      </div>
      ${diffBar(tokens1, tokens2, true)}
    </div>`;

    html += `</div></div>`;

    content.innerHTML = html;
  } catch (err) {
    content.innerHTML = `<div class="glass rounded-xl p-8 text-center text-red-400/60 text-sm">Failed to load traces: ${escHtml(err.message)}</div>`;
  }
}

// ==================================================================// Virtualized Trace List
// ==================================================================
function renderVirtualizedTraces(traces, containerId) {
  const container = document.getElementById(containerId);
  if (!traces || traces.length === 0) {
    container.innerHTML = renderEmptyState('No traces found', 'Try adjusting your filters.');
    return;
  }

  // For small lists, render normally
  if (traces.length <= 50) {
    container.innerHTML = traces.map(t => renderTraceRow(t)).join('');
    return;
  }

  // For large lists, use virtual scrolling
  const rowHeight = 56;
  const totalHeight = traces.length * rowHeight;
  const visibleCount = Math.ceil(600 / rowHeight) + 4; // buffer

  container.innerHTML = `<div class="virtual-scroll-container" style="height:600px" id="vs-${containerId}"><div class="virtual-scroll-spacer" style="height:${totalHeight}px;position:relative" id="vs-spacer-${containerId}"></div></div>`;

  const scrollContainer = document.getElementById(`vs-${containerId}`);
  const spacer = document.getElementById(`vs-spacer-${containerId}`);

  function renderVisibleRows() {
    const scrollTop = scrollContainer.scrollTop;
    const startIdx = Math.max(0, Math.floor(scrollTop / rowHeight) - 2);
    const endIdx = Math.min(traces.length, startIdx + visibleCount);

    let html = '';
    for (let i = startIdx; i < endIdx; i++) {
      const top = i * rowHeight;
      html += `<div style="position:absolute;top:${top}px;left:0;right:0;height:${rowHeight}px">${renderTraceRow(traces[i])}</div>`;
    }
    spacer.innerHTML = html;
  }

  scrollContainer.addEventListener('scroll', renderVisibleRows);
  renderVisibleRows();
}

// ==================================================================// Trace Row Hover Preview
// ==================================================================
let _tracePreviewTimer = null;
let _tracePreviewEl = null;

function showTracePreview(traceId, event) {
  clearTimeout(_tracePreviewTimer);
  _tracePreviewTimer = setTimeout(async () => {
    try {
      const data = await apiFetch(`/v1/traces/${traceId}`);
      const spans = data.spans || [];

      // Count spans by kind
      const kindCounts = { llm: 0, tool: 0, agent: 0 };
      spans.forEach(s => {
        const k = (s.kind || '').toLowerCase();
        if (kindCounts[k] !== undefined) kindCounts[k]++;
      });

      const durationMs = data.duration_ms || 0;
      const hasErrors = data.has_errors === true || data.has_errors === 1;
      const errorMsg = hasErrors
        ? (spans.find(s => s.error || s.error_message))
        : null;
      const errorText = errorMsg
        ? (errorMsg.error ? (errorMsg.error.message || JSON.stringify(errorMsg.error)) : errorMsg.error_message)
        : null;

      // Max duration for visual bar (cap at 10s for proportionality)
      const maxDur = 10000;
      const barWidth = Math.min((durationMs / maxDur) * 100, 100);

      if (!_tracePreviewEl) {
        _tracePreviewEl = document.createElement('div');
        _tracePreviewEl.className = 'trace-preview-tooltip';
        document.body.appendChild(_tracePreviewEl);
      }

      const isDark = document.documentElement.classList.contains('dark');
      const labelColor = isDark ? '#94a3b8' : '#64748b';
      const valueColor = isDark ? '#e2e0db' : '#2c2c2a';

      _tracePreviewEl.innerHTML = `
        <div style="font-weight:600;margin-bottom:6px;font-size:11px;color:${valueColor}">
          ${escHtml((data.service_name || traceId).substring(0, 30))}
        </div>
        <div style="font-size:11px;color:${labelColor};margin-bottom:4px">Span breakdown</div>
        <div style="display:flex;gap:8px;font-size:11px;margin-bottom:8px">
          <span style="color:#9b8ec4">LLM: ${kindCounts.llm}</span>
          <span style="color:#7ab5a0">Tool: ${kindCounts.tool}</span>
          <span style="color:#a88ec4">Agent: ${kindCounts.agent}</span>
        </div>
        <div style="font-size:11px;color:${labelColor};margin-bottom:2px">Duration: <span style="color:${valueColor}">${formatDuration(durationMs)}</span></div>
        <div class="trace-preview-duration-bar">
          <div class="trace-preview-duration-fill" style="width:${barWidth}%"></div>
        </div>
        ${errorText ? `<div style="font-size:10px;color:#f87171;margin-top:6px;white-space:normal;line-height:1.4">${escHtml(errorText.substring(0, 100))}${errorText.length > 100 ? '...' : ''}</div>` : ''}
      `;
      _tracePreviewEl.style.display = 'block';
      _positionTracePreview(event);
    } catch (e) {
      // Silently fail — trace might not be available
    }
  }, 500);
}

function hideTracePreview() {
  clearTimeout(_tracePreviewTimer);
  _tracePreviewTimer = null;
  if (_tracePreviewEl) _tracePreviewEl.style.display = 'none';
}

function _positionTracePreview(event) {
  if (!_tracePreviewEl) return;
  const x = event.clientX + 18;
  const y = event.clientY - 10;
  _tracePreviewEl.style.left = x + 'px';
  _tracePreviewEl.style.top = y + 'px';
  // Keep within viewport
  const rect = _tracePreviewEl.getBoundingClientRect();
  if (rect.right > window.innerWidth - 8) {
    _tracePreviewEl.style.left = (event.clientX - rect.width - 18) + 'px';
  }
  if (rect.bottom > window.innerHeight - 8) {
    _tracePreviewEl.style.top = (window.innerHeight - rect.height - 8) + 'px';
  }
}

// ==================================================================// Session State Persistence
// ==================================================================
function saveScrollState() {
  try {
    const mainEl = document.querySelector('main');
    if (mainEl) sessionStorage.setItem('flowlens-scroll', mainEl.scrollTop);
  } catch (_) {}
}

function saveSearchQuery() {
  try {
    const el = document.getElementById('filter-service');
    if (el) sessionStorage.setItem('flowlens-search', el.value || '');
  } catch (_) {}
}

function restoreState() {
  try {
    // Restore search query
    const savedSearch = sessionStorage.getItem('flowlens-search');
    if (savedSearch) {
      const el = document.getElementById('filter-service');
      if (el) el.value = savedSearch;
    }
    // Restore scroll position (deferred to after render)
    const savedScroll = sessionStorage.getItem('flowlens-scroll');
    if (savedScroll) {
      setTimeout(() => {
        const mainEl = document.querySelector('main');
        if (mainEl) mainEl.scrollTop = parseInt(savedScroll, 10) || 0;
      }, 1000);
    }
    // Restore selected trace ID (re-open detail if trace was being viewed)
    const savedTraceId = sessionStorage.getItem('flowlens-trace-id');
    if (savedTraceId) {
      currentTraceId = savedTraceId;
      // Re-open the trace detail after a short delay (allow initial load to complete)
      setTimeout(() => { if (currentTraceId) openTrace(currentTraceId); }, 1500);
    }
    // Restore current view (navigate to the last active tab)
    const savedView = sessionStorage.getItem('flowlens-view');
    if (savedView && savedView !== 'overview' && !savedTraceId) {
      // Defer until after initial load completes so the switchView data loads run after API is ready
      setTimeout(() => switchView(savedView), 400);
    }
  } catch (_) {}
}

// ==================================================================// Budget Management
// ==================================================================
let _budgetUSD = null; // Current budget in USD (null = not set)

function _getBudgetFromStorage() {
  try {
    const v = localStorage.getItem('flowlens-budget-usd');
    if (v !== null) {
      const n = parseFloat(v);
      return isNaN(n) || n <= 0 ? null : n;
    }
  } catch (_) {}
  return null;
}

function _saveBudgetToStorage(usd) {
  try {
    if (usd === null) {
      localStorage.removeItem('flowlens-budget-usd');
    } else {
      localStorage.setItem('flowlens-budget-usd', String(usd));
    }
  } catch (_) {}
}

function openBudgetModal() {
  const overlay = document.getElementById('budget-modal-overlay');
  if (!overlay) return;
  const input = document.getElementById('budget-input');
  if (input && _budgetUSD !== null) input.value = _budgetUSD.toFixed(2);
  overlay.classList.remove('hidden');
  setTimeout(() => { if (input) input.focus(); }, 50);
}

function closeBudgetModal() {
  const overlay = document.getElementById('budget-modal-overlay');
  if (overlay) overlay.classList.add('hidden');
}

function saveBudget() {
  const input = document.getElementById('budget-input');
  if (!input) return;
  const v = parseFloat(input.value);
  if (isNaN(v) || v <= 0) {
    showToast('Please enter a valid budget amount > 0', 'warning');
    return;
  }
  _budgetUSD = v;
  _saveBudgetToStorage(v);
  closeBudgetModal();
  _refreshBudgetBar();
  showToast(`Budget set to $${v.toFixed(2)}/month`, 'success');
}

function clearBudget() {
  _budgetUSD = null;
  _saveBudgetToStorage(null);
  _refreshBudgetBar();
}

async function _refreshBudgetBar() {
  const alertBar = document.getElementById('budget-alert-bar');
  const setBar = document.getElementById('budget-set-bar');
  if (!alertBar || !setBar) return;

  if (_budgetUSD === null) {
    alertBar.classList.add('hidden');
    setBar.classList.remove('hidden');
    return;
  }

  // Fetch current spend from /v1/cost/budget
  let spent = 0;
  try {
    const data = await apiFetch(`/v1/cost/budget?budget=${_budgetUSD}`);
    spent = data.total_spent_usd || 0;
  } catch (_) {
    // Can't reach API, use 0
  }

  const pct = _budgetUSD > 0 ? Math.min(100, (spent / _budgetUSD) * 100) : 0;
  const pctRounded = Math.round(pct);

  const fill = document.getElementById('budget-progress-fill');
  const label = document.getElementById('budget-bar-label');
  const pctEl = document.getElementById('budget-bar-pct');
  const icon = document.getElementById('budget-bar-icon');

  if (label) label.textContent = `Budget: $${spent.toFixed(2)} / $${_budgetUSD.toFixed(2)} (${pctRounded}%)`;
  if (pctEl) pctEl.textContent = pctRounded + '%';

  // Remove all color classes
  alertBar.classList.remove('budget-bar-green', 'budget-bar-yellow', 'budget-bar-red');
  if (fill) fill.classList.remove('budget-fill-green', 'budget-fill-yellow', 'budget-fill-red');
  if (pctEl) pctEl.className = 'text-xs font-bold';
  if (icon) icon.className = 'w-4 h-4 flex-shrink-0';

  if (pct >= 100) {
    alertBar.classList.add('budget-bar-red');
    if (fill) { fill.classList.add('budget-fill-red'); fill.style.width = '100%'; }
    if (pctEl) pctEl.classList.add('text-red-400');
    if (icon) icon.classList.add('text-red-400');
    if (label) label.textContent = 'Budget exceeded! $' + spent.toFixed(2) + ' / $' + _budgetUSD.toFixed(2);
    // Add notification if not already present
    addNotification('warning', 'Budget Exceeded', `Spend $${spent.toFixed(2)} exceeds budget $${_budgetUSD.toFixed(2)}`);
  } else if (pct >= 80) {
    alertBar.classList.add('budget-bar-yellow');
    if (fill) { fill.classList.add('budget-fill-yellow'); fill.style.width = pct + '%'; }
    if (pctEl) pctEl.classList.add('text-amber-400');
    if (icon) icon.classList.add('text-amber-400');
  } else {
    alertBar.classList.add('budget-bar-green');
    if (fill) { fill.classList.add('budget-fill-green'); fill.style.width = pct + '%'; }
    if (pctEl) pctEl.classList.add('text-emerald-400');
    if (icon) icon.classList.add('text-emerald-400');
  }

  setBar.classList.add('hidden');
  alertBar.classList.remove('hidden');
}

// ==================================================================// Cost Forecast Chart
// ==================================================================
async function loadCostForecast() {
  try {
    const data = await apiFetch('/v1/cost/forecast?days=30&forecast_days=7');

    // Update projection cards
    const monthly = data.monthly_projection_usd || data.projected_monthly_cost || 0;
    const daily = data.daily_avg_usd || data.projected_daily_cost || 0;
    const ci = data.confidence_interval || { lower: 0, upper: 0 };

    const monthlyEl = document.getElementById('forecast-monthly');
    if (monthlyEl) monthlyEl.textContent = '$' + monthly.toFixed(4);

    const dailyEl = document.getElementById('forecast-daily');
    if (dailyEl) dailyEl.textContent = '$' + daily.toFixed(4) + '/day';

    const ciEl = document.getElementById('forecast-ci');
    if (ciEl) ciEl.textContent = `$${(ci.lower || 0).toFixed(4)} – $${(ci.upper || 0).toFixed(4)}`;

    // Update trend badge
    const trend = data.trend || 'stable';
    const badge = document.getElementById('forecast-trend-badge');
    if (badge) {
      badge.classList.remove('hidden', 'forecast-trend-increasing', 'forecast-trend-decreasing', 'forecast-trend-stable');
      badge.classList.add('forecast-trend-' + trend);
      const arrows = { increasing: '↑ increasing', decreasing: '↓ decreasing', stable: '→ stable' };
      badge.textContent = arrows[trend] || trend;
    }

    // Render forecast chart
    _renderForecastChart(data.daily_costs || [], data.forecast || []);
  } catch (err) {
    console.warn('Cost forecast not available:', err);
  }
}

function _renderForecastChart(actualDays, forecastDays) {
  const canvasId = 'chart-cost-forecast';
  if (chartInstances[canvasId]) { chartInstances[canvasId].destroy(); delete chartInstances[canvasId]; }
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  const isDark = document.documentElement.classList.contains('dark');
  const tickColor = isDark ? '#64748b' : '#94a3b8';
  const gridColor = isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.06)';

  // Build combined label array
  const actualLabels = actualDays.map(d => d.date ? d.date.substring(5) : '');  // MM-DD
  const forecastLabels = forecastDays.map(d => d.date ? d.date.substring(5) : '');
  const labels = [...actualLabels, ...forecastLabels];

  const actualCosts = actualDays.map(d => d.cost || 0);
  // Actual dataset: null for forecast points
  const actualDataset = [...actualCosts, ...forecastDays.map(() => null)];
  // Forecast dataset: null for actual points, then forecast values
  const forecastDataset = [...actualDays.map(() => null), ...forecastDays.map(d => d.cost || 0)];
  // Overlap point: last actual = first forecast
  if (actualCosts.length > 0 && forecastDays.length > 0) {
    forecastDataset[actualCosts.length - 1] = actualCosts[actualCosts.length - 1];
  }

  // Confidence interval upper/lower (for band visualization)
  const ciBands = forecastDays.map(d => ({
    lo: d.ci_lower || 0,
    hi: d.ci_upper || 0,
  }));

  const ctx = canvas.getContext('2d');
  const grad = ctx.createLinearGradient(0, 0, 0, canvas.height || 200);
  grad.addColorStop(0, 'rgba(99, 102, 241, 0.22)');
  grad.addColorStop(1, 'rgba(99, 102, 241, 0.02)');

  chartInstances[canvasId] = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Actual',
          data: actualDataset,
          borderColor: '#7c7aef',
          backgroundColor: grad,
          fill: true,
          tension: 0.3,
          pointRadius: 3,
          pointHoverRadius: 6,
          pointBackgroundColor: '#7c7aef',
          borderWidth: 2,
          spanGaps: false,
        },
        {
          label: 'Forecast',
          data: forecastDataset,
          borderColor: '#a5b4fc',
          backgroundColor: 'rgba(165, 180, 252, 0.08)',
          fill: false,
          tension: 0.3,
          pointRadius: 2,
          pointHoverRadius: 5,
          pointBackgroundColor: '#a5b4fc',
          borderWidth: 2,
          borderDash: [5, 4],
          spanGaps: false,
        },
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          display: true,
          position: 'top',
          align: 'end',
          labels: { color: tickColor, font: { family: 'Inter', size: 10 }, boxWidth: 24, padding: 8 }
        },
        tooltip: {
          backgroundColor: isDark ? 'rgba(42,42,40,0.95)' : 'rgba(255,255,255,0.97)',
          borderColor: isDark ? 'rgba(255,255,255,0.1)' : '#e8e6e1',
          borderWidth: 1,
          titleColor: isDark ? '#e2e0db' : '#2c2c2a',
          bodyColor: isDark ? '#94a3b8' : '#64748b',
          callbacks: {
            label: (item) => {
              const v = item.parsed.y;
              if (v === null) return null;
              const datasetLabel = item.dataset.label;
              return ` ${datasetLabel}: $${v.toFixed(6)}`;
            }
          }
        }
      },
      scales: {
        x: {
          ticks: { color: tickColor, font: { size: 10 }, maxRotation: 45 },
          grid: { color: gridColor },
        },
        y: {
          ticks: { color: tickColor, font: { size: 10 }, callback: v => '$' + v.toFixed(4) },
          grid: { color: gridColor },
          beginAtZero: true,
        }
      }
    }
  });
}

// ==================================================================// Cycle 16: Interaction Polish helpers
// ==================================================================
/**
 * Move (or create) the pill-nav sliding indicator to sit under the active tab.
 * Uses CSS `transition` on left+width for a smooth glide effect.
 */
function _movePillGlider(view) {
  const container = document.querySelector('.pill-nav-container');
  if (!container) return;
  const btn = container.querySelector(`[data-tab="${view}"]`);
  if (!btn) return;

  let glider = container.querySelector('.pill-nav-glider');
  if (!glider) {
    glider = document.createElement('div');
    glider.className = 'pill-nav-glider';
    container.prepend(glider);
  }

  // Position relative to nav container
  const containerRect = container.getBoundingClientRect();
  const btnRect = btn.getBoundingClientRect();
  glider.style.left = (btnRect.left - containerRect.left + container.scrollLeft) + 'px';
  glider.style.width = btnRect.width + 'px';
}

/** Scroll the page (main element) smoothly to the top */
function scrollToTop() {
  const main = document.querySelector('main');
  if (main) {
    main.scrollTo({ top: 0, behavior: 'smooth' });
  } else {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
}

/**
 * Show a "Copied!" tooltip on a button element for 1.5s.
 * Button must have position:relative (or a wrapper will be created).
 */
function showCopyTooltip(btn) {
  // Remove any existing tooltip on this button
  const existing = btn.querySelector('.copy-tooltip');
  if (existing) existing.remove();

  const tip = document.createElement('span');
  tip.className = 'copy-tooltip';
  tip.textContent = 'Copied!';
  btn.style.position = 'relative';
  btn.appendChild(tip);

  setTimeout(() => {
    tip.classList.add('fading');
    setTimeout(() => tip.remove(), 200);
  }, 1300);
}

/**
 * Copy text to clipboard and show a tooltip on the trigger element.
 */
function copyWithTooltip(text, triggerEl) {
  navigator.clipboard.writeText(text).then(() => {
    if (triggerEl) showCopyTooltip(triggerEl);
  }).catch(() => {
    showToast('Failed to copy', 'error', 2000);
  });
}

/**
 * Flash a trace row with the "new trace via WebSocket" green border effect.
 */
function flashNewTraceRow(traceId) {
  const row = document.querySelector(`[data-trace-id="${traceId}"]`);
  if (!row) return;
  row.classList.remove('new-trace-ws');
  void row.offsetWidth; // force reflow
  row.classList.add('new-trace-ws');
  row.addEventListener('animationend', () => row.classList.remove('new-trace-ws'), { once: true });
}

/**
 * Add press feedback to a trace row (scale-down 0.9975 → back up).
 */
function _addTraceRowPressListeners(container) {
  container.addEventListener('mousedown', (e) => {
    const row = e.target.closest('.trace-row');
    if (!row) return;
    row.classList.add('pressing');
  }, { passive: true });
  container.addEventListener('mouseup', (e) => {
    const row = e.target.closest('.trace-row');
    if (row) row.classList.remove('pressing');
  }, { passive: true });
  container.addEventListener('mouseleave', (e) => {
    document.querySelectorAll('.trace-row.pressing').forEach(r => r.classList.remove('pressing'));
  }, { passive: true });
}

// ==================================================================// Init
// ==================================================================
document.addEventListener('DOMContentLoaded', async () => {
  // Apply saved theme — default to light
  const savedTheme = localStorage.getItem('flowlens-theme');
  if (savedTheme === 'dark') {
    document.documentElement.classList.add('dark');
    document.body.classList.add('dark');
    isDarkTheme = true;
  } else {
    document.documentElement.classList.remove('dark');
    document.body.classList.remove('dark');
    isDarkTheme = false;
  }

  // Initialize budget bar from localStorage
  _budgetUSD = _getBudgetFromStorage();
  // Refresh budget bar if budget is configured
  if (_budgetUSD !== null) {
    _refreshBudgetBar();
  }

  // Restore persisted session state (search query, scroll position)
  restoreState();

  // Setup keyboard navigation
  setupKeyboardNavigation();

  // Health check + initial data load
  await healthCheck();
  // Critical: load immediately (above the fold)
  loadStats();
  loadRecentTraces();
  // Deferred: load after 500ms (below the fold)
  setTimeout(() => {
    loadAgentActivity();
    loadOverviewAgents();
  }, 500);
  // Lazy: load after 1.5s (charts, graph — expensive)
  setTimeout(() => {
    loadActivityTimeline();
    loadTrendChart(24);
    loadOverviewCharts();
  }, 1500);
  // Very lazy: load after 3s (SVG graph — heaviest)
  setTimeout(() => {
    loadOverviewGraph();
  }, 3000);
  // Load recent feedback after 2s
  setTimeout(() => {
    loadRecentFeedback();
  }, 2000);
  startAutoRefresh();

  // Connect WebSocket for real-time updates
  connectWebSocket();

  // Bind filter events
  document.getElementById('filter-service').addEventListener('keyup', (e) => {
    saveSearchQuery();
    if (e.key === 'Enter') { traceOffset = 0; loadTraces(); }
  });
  document.getElementById('filter-errors').addEventListener('change', () => { traceOffset = 0; loadTraces(); });
  const fbHasFeedback = document.getElementById('filter-has-feedback');
  if (fbHasFeedback) fbHasFeedback.addEventListener('change', () => { traceOffset = 0; loadTraces(); });
  const fbRating = document.getElementById('filter-rating');
  if (fbRating) fbRating.addEventListener('change', () => { traceOffset = 0; loadTraces(); });

  // Persist scroll position on scroll
  const mainEl = document.querySelector('main');
  const backToTopBtn = document.getElementById('back-to-top');
  const headerEl = document.querySelector('header');

  if (mainEl) {
    mainEl.addEventListener('scroll', () => {
      const st = mainEl.scrollTop;

      // Persist state
      try { sessionStorage.setItem('flowlens-scroll', st); } catch (_) {}

      // Header scroll shadow
      if (headerEl) {
        headerEl.classList.toggle('scrolled', st > 20);
      }

      // Back-to-top visibility
      if (backToTopBtn) {
        backToTopBtn.classList.toggle('visible', st > 400);
      }
    }, { passive: true });
  }

  // Also listen on window scroll for the back-to-top (in case main is not the scroll container)
  window.addEventListener('scroll', () => {
    const st = window.scrollY;
    if (headerEl) headerEl.classList.toggle('scrolled', st > 20);
    if (backToTopBtn) backToTopBtn.classList.toggle('visible', st > 400);
  }, { passive: true });

  // Trace row press feedback — delegate from main container
  const mainContent = document.getElementById('main-content');
  if (mainContent) {
    _addTraceRowPressListeners(mainContent);
  }

  // Initialize pill nav glider on current view
  _movePillGlider(currentView || 'overview');

  // Register dagre layout for Cytoscape if both libs loaded
  if (typeof cytoscape !== 'undefined' && typeof cytoscapeDagre !== 'undefined') {
    try { cytoscape.use(cytoscapeDagre); } catch (e) { /* already registered */ }
  }
});

// ==================================================================// Sessions — List + Timeline
// ==================================================================
let _currentSessionId = null;

async function loadSessions() {
  const list = document.getElementById('sessions-list');
  const panel = document.getElementById('session-timeline-panel');
  if (!list) return;

  list.innerHTML = '<div class="flex items-center justify-center py-10"><div class="text-xs text-slate-500">Loading sessions...</div></div>';
  if (panel) { panel.classList.add('hidden'); panel.innerHTML = ''; }
  _currentSessionId = null;

  try {
    const data = await apiFetch('/v1/sessions?limit=30');
    const sessions = data.sessions || [];

    if (sessions.length === 0) {
      list.innerHTML = renderEmptyState(
        'No sessions found',
        'Sessions group multiple traces from the same conversation. Make sure your traces include a session_id field.',
        false
      );
      return;
    }

    list.innerHTML = sessions.map(s => renderSessionCard(s)).join('');
  } catch (err) {
    list.innerHTML = `<div class="text-center py-8 text-red-400/70 text-sm">Failed to load sessions: ${escHtml(err.message)}</div>`;
  }
}

function renderSessionCard(session) {
  const sid = session.session_id || '';
  const shortId = sid.substring(0, 8) + '...';
  const traceCount = session.trace_count || 0;
  const totalSpans = session.total_spans || 0;
  const cost = session.total_cost_usd || 0;
  const hasErrors = session.has_errors;
  const errorCount = session.error_count || 0;
  const project = session.project || 'unknown';
  const agents = session.agents || [];

  // Duration
  let durationStr = '--';
  if (session.first_trace_time && session.last_trace_time) {
    const durMs = (session.last_trace_time - session.first_trace_time) * 1000;
    durationStr = formatDuration(durMs);
  }

  // Time range
  let timeStr = '--';
  if (session.last_trace_time) {
    timeStr = formatTimeAgo(session.last_trace_time);
  }

  // Agent badges (max 3)
  const visibleAgents = agents.slice(0, 3);
  const extraCount = agents.length - 3;
  const agentBadges = visibleAgents.map(a => {
    const p = getAgentProfile(a);
    return `<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium border ${p.badgeClass}">${p.name || a}</span>`;
  }).join('');
  const extraBadge = extraCount > 0
    ? `<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-500/15 text-slate-400 border border-slate-500/25">+${extraCount}</span>`
    : '';

  const statusDot = hasErrors
    ? '<span class="w-2 h-2 rounded-full flex-shrink-0" style="background:var(--color-coral,#e07a5f)"></span>'
    : '<span class="w-2 h-2 rounded-full flex-shrink-0" style="background:var(--color-sage,#81b29a)"></span>';

  const isActive = _currentSessionId === sid;
  const activeClass = isActive ? 'session-card-active' : '';

  return `
    <div class="session-card glass rounded-xl p-4 cursor-pointer hover:bg-white/[0.02] transition ${activeClass}"
         onclick="toggleSessionTimeline('${escHtml(sid)}')" id="session-card-${escHtml(sid)}">
      <div class="flex items-start justify-between gap-4">
        <div class="flex items-start gap-3 min-w-0 flex-1">
          ${statusDot}
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="font-mono text-xs text-slate-400">${escHtml(shortId)}</span>
              <span class="text-[10px] text-slate-600 hidden sm:inline">${escHtml(sid)}</span>
            </div>
            <div class="flex items-center gap-2 mt-1 flex-wrap">
              <span class="text-[11px] font-medium text-slate-300">${escHtml(project)}</span>
              <span class="text-[10px] text-slate-600">·</span>
              <span class="text-[11px] text-slate-500">${timeStr}</span>
            </div>
            <div class="flex items-center gap-1.5 mt-2 flex-wrap">
              ${agentBadges}${extraBadge}
            </div>
          </div>
        </div>
        <div class="flex items-center gap-4 flex-shrink-0 text-right">
          <div class="hidden sm:block">
            <div class="text-[10px] text-slate-500 uppercase tracking-wider">Traces</div>
            <div class="text-sm font-semibold text-white">${traceCount}</div>
          </div>
          <div class="hidden sm:block">
            <div class="text-[10px] text-slate-500 uppercase tracking-wider">Spans</div>
            <div class="text-sm font-semibold text-white">${totalSpans}</div>
          </div>
          <div>
            <div class="text-[10px] text-slate-500 uppercase tracking-wider">Cost</div>
            <div class="text-sm font-semibold text-indigo-400">$${cost.toFixed(4)}</div>
          </div>
          <div class="hidden md:block">
            <div class="text-[10px] text-slate-500 uppercase tracking-wider">Duration</div>
            <div class="text-sm font-semibold text-white">${durationStr}</div>
          </div>
          ${hasErrors ? `<div class="text-[10px] font-medium" style="color:var(--color-coral,#e07a5f)">${errorCount} err${errorCount !== 1 ? 's' : ''}</div>` : ''}
          <svg class="w-4 h-4 text-slate-500 session-chevron transition-transform ${isActive ? 'rotate-90' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>
          </svg>
        </div>
      </div>
    </div>`;
}

async function toggleSessionTimeline(sessionId) {
  const panel = document.getElementById('session-timeline-panel');
  if (!panel) return;

  // If same session clicked again, collapse
  if (_currentSessionId === sessionId) {
    _currentSessionId = null;
    panel.classList.add('hidden');
    panel.innerHTML = '';
    // Update all cards to remove active state
    document.querySelectorAll('.session-card').forEach(c => c.classList.remove('session-card-active'));
    document.querySelectorAll('.session-chevron').forEach(c => c.classList.remove('rotate-90'));
    return;
  }

  _currentSessionId = sessionId;

  // Update card visual states
  document.querySelectorAll('.session-card').forEach(c => c.classList.remove('session-card-active'));
  document.querySelectorAll('.session-chevron').forEach(c => c.classList.remove('rotate-90'));
  const activeCard = document.getElementById(`session-card-${sessionId}`);
  if (activeCard) {
    activeCard.classList.add('session-card-active');
    const chevron = activeCard.querySelector('.session-chevron');
    if (chevron) chevron.classList.add('rotate-90');
  }

  // Scroll panel into view
  panel.classList.remove('hidden');
  panel.innerHTML = `<div class="glass rounded-xl p-6 flex items-center justify-center">
    <div class="text-xs text-slate-500">Loading session timeline...</div>
  </div>`;
  panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

  try {
    const data = await apiFetch(`/v1/sessions/${encodeURIComponent(sessionId)}`);
    renderSessionTimeline(data, panel);
  } catch (err) {
    panel.innerHTML = `<div class="glass rounded-xl p-6 text-center text-red-400/70 text-sm">Failed to load session: ${escHtml(err.message)}</div>`;
  }
}

function renderSessionTimeline(data, container) {
  const traces = data.traces || [];
  const summary = data.summary || {};
  const sessionId = data.session_id || '';

  if (traces.length === 0) {
    container.innerHTML = `<div class="glass rounded-xl p-6 text-center text-slate-500 text-sm">No traces in this session.</div>`;
    return;
  }

  const sessionStartTime = traces[0].start_time || 0;

  // Summary header
  const agents = summary.agents || [];
  const agentBadges = agents.map(a => {
    const p = getAgentProfile(a);
    return `<span class="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium border ${p.badgeClass}">${p.name || a}</span>`;
  }).join('');

  const totalCost = (summary.total_cost_usd || 0).toFixed(4);
  const totalSpans = summary.total_spans || 0;
  const errorCount = summary.error_count || 0;

  const traceNodes = traces.map((trace, idx) => {
    return renderSessionTraceNode(trace, idx, sessionStartTime, traces.length);
  }).join('');

  container.innerHTML = `
    <div class="glass rounded-xl overflow-hidden">
      <!-- Session Summary Header -->
      <div class="px-5 py-4 border-b border-white/5">
        <div class="flex items-start justify-between gap-4">
          <div>
            <div class="text-xs font-medium text-slate-300 mb-1">Session</div>
            <div class="font-mono text-[11px] text-slate-400 break-all">${escHtml(sessionId)}</div>
            <div class="flex items-center gap-2 mt-2 flex-wrap">${agentBadges}</div>
          </div>
          <div class="flex items-center gap-5 flex-shrink-0 text-right">
            <div>
              <div class="text-[10px] text-slate-500 uppercase tracking-wider">Traces</div>
              <div class="text-lg font-bold text-white">${traces.length}</div>
            </div>
            <div>
              <div class="text-[10px] text-slate-500 uppercase tracking-wider">Spans</div>
              <div class="text-lg font-bold text-white">${totalSpans}</div>
            </div>
            <div>
              <div class="text-[10px] text-slate-500 uppercase tracking-wider">Cost</div>
              <div class="text-lg font-bold text-indigo-400">$${totalCost}</div>
            </div>
            ${errorCount > 0 ? `<div>
              <div class="text-[10px] text-slate-500 uppercase tracking-wider">Errors</div>
              <div class="text-lg font-bold" style="color:var(--color-coral,#e07a5f)">${errorCount}</div>
            </div>` : ''}
          </div>
        </div>
      </div>

      <!-- Timeline -->
      <div class="px-5 py-4">
        <div class="session-timeline">
          ${traceNodes}
        </div>
      </div>
    </div>`;
}

function renderSessionTraceNode(trace, idx, sessionStartTime, totalTraces) {
  const hasErrors = trace.has_errors === true || trace.has_errors === 1;
  const traceId = trace.trace_id || '';
  const spanCount = trace.span_count || 0;
  const cost = (trace.total_cost_usd || 0).toFixed(4);
  const durationMs = trace.duration_ms || 0;
  const duration = formatDuration(durationMs);

  // Compute offset from session start
  const offsetMs = ((trace.start_time || 0) - sessionStartTime) * 1000;
  const offsetStr = offsetMs > 0 ? `+${formatDuration(offsetMs)}` : 'start';

  // Time string
  const timeStr = trace.start_time > 0
    ? new Date(trace.start_time * 1000).toLocaleTimeString()
    : '--';

  // Extract agent from tags
  const tags = trace.tags || {};
  const agent = tags.agent || trace.service_name || '';
  const p = getAgentProfile(agent);

  // Tool pills from spans
  const toolPillsHtml = buildToolPillsHtml(trace);

  // Duration color
  const durDotClass = _durationDotClass(durationMs);

  const nodeColor = hasErrors ? '#ef4444' : p.color;
  const isLast = idx === totalTraces - 1;

  // Agent avatar: colored circle with initial
  const avatarLetter = (p.name || agent || '?').charAt(0).toUpperCase();

  return `
    <div class="session-timeline-node ${isLast ? 'last' : ''}">
      <!-- Connector line -->
      <div class="session-timeline-connector">
        <div class="session-timeline-dot" style="background:${nodeColor};box-shadow:0 0 8px ${nodeColor}44"></div>
        ${!isLast ? '<div class="session-timeline-line"></div>' : ''}
      </div>
      <!-- Node Content -->
      <div class="session-timeline-content glass-hover rounded-xl p-4 mb-3 cursor-pointer transition"
           onclick="openTrace('${escHtml(traceId)}')" title="Click to open trace detail">
        <div class="flex items-start justify-between gap-3">
          <div class="flex items-start gap-3 min-w-0 flex-1">
            <!-- Agent avatar (colored dot with initial) -->
            <div class="session-node-avatar flex-shrink-0 mt-0.5" style="background:${p.color};">
              ${escHtml(avatarLetter)}
            </div>
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2 mb-1 flex-wrap">
                <span class="text-xs font-semibold" style="color:${p.color}">${escHtml(p.name || agent)}</span>
                ${hasErrors ? `<span class="session-node-error-dot" title="Has errors"></span>` : ''}
                <span class="text-[10px] text-slate-500">${timeStr}</span>
                <span class="text-[10px] text-slate-600">${offsetStr}</span>
              </div>
              <div class="font-mono text-[10px] text-slate-600 truncate">${escHtml(traceId)}</div>
              ${toolPillsHtml ? `<div class="session-tool-pills">${toolPillsHtml}</div>` : ''}
            </div>
          </div>
          <div class="flex items-center gap-3 flex-shrink-0 text-right">
            <div>
              <div class="text-[10px] text-slate-500">spans</div>
              <div class="text-sm font-semibold text-white">${spanCount}</div>
            </div>
            <div>
              <div class="text-[10px] text-slate-500">duration</div>
              <div class="text-sm font-semibold text-white flex items-center justify-end gap-1">
                <span class="duration-dot ${durDotClass}"></span>${duration}
              </div>
            </div>
            <div>
              <div class="text-[10px] text-slate-500">cost</div>
              <div class="text-sm font-semibold text-indigo-400">$${cost}</div>
            </div>
            <svg class="w-4 h-4 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/>
            </svg>
          </div>
        </div>
      </div>
    </div>`;
}

function getTraceSpanSummary(trace) {
  // Use top-level span_count + metadata if available; deep scan if spans array present
  const spans = trace.spans || [];
  if (spans.length === 0) {
    return trace.span_count > 0 ? `${trace.span_count} spans` : '';
  }
  const kindCounts = {};
  spans.forEach(s => {
    const k = s.kind || 'unknown';
    kindCounts[k] = (kindCounts[k] || 0) + 1;
  });
  const parts = Object.entries(kindCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)
    .map(([k, n]) => `${n} ${k.charAt(0).toUpperCase() + k.slice(1)}`);
  return parts.join(', ');
}
