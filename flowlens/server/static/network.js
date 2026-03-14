/* FlowLens Dashboard — Agent Network Visualization (Lightweight SVG) */
'use strict';

// =========================================================================
// Agent Relationship Graph — 2D SVG Visualization
// =========================================================================
// Replaces the previous Three.js WebGL implementation.
// Uses SVG + CSS/SMIL animations for GPU-composited rendering with
// dramatically lower memory and CPU usage.

let _agentRelData = null;        // cached relationship data
let _agentGraphResizeObserver = null;
let _agentGraphResizeTimer = null;

/**
 * Build a 2D SVG network graph inside `container` using data.nodes / data.edges.
 * Particles flow along edges via SVG animateMotion (GPU-composited, no JS loop).
 * Active nodes pulse via CSS animation class.
 */
function _buildSVGNetwork(container, data) {
  const nodes = data.nodes || [];
  const edges = data.edges || [];
  if (nodes.length === 0) {
    container.innerHTML = '<p style="text-align:center;padding:60px 0;color:#94a3b8;font-size:13px;">No agent data</p>';
    return;
  }

  const W = container.clientWidth || 700;
  const H = container.clientHeight || 400;
  const dark = isDarkTheme;

  // Layout: hub-and-spoke — main/unknown in center, others on ellipse
  const cx = W / 2, cy = H / 2;
  const rx = Math.min(W * 0.36, 240), ry = Math.min(H * 0.32, 140);
  const nodePos = {};

  const mainNode = nodes.find(n => n.id === 'main' || n.id === 'unknown');
  const others = nodes.filter(n => n !== mainNode);
  if (mainNode) nodePos[mainNode.id] = { x: cx, y: cy };
  others.forEach((n, i) => {
    const angle = (i / Math.max(others.length, 1)) * Math.PI * 2 - Math.PI / 2;
    nodePos[n.id] = { x: cx + Math.cos(angle) * rx, y: cy + Math.sin(angle) * ry };
  });

  const maxCount = nodes.reduce((a, n) => Math.max(a, n.trace_count || 1), 1);
  const maxEdge  = edges.reduce((a, e) => Math.max(a, e.count || 1), 1);
  const bgColor  = dark ? '#0f172a' : '#fafaf8';
  const dotColor = dark ? 'rgba(148,163,184,0.15)' : 'rgba(100,116,139,0.12)';

  const ns = 'http://www.w3.org/2000/svg';

  // ---- Build SVG string ----
  let defs = `<defs>
    <filter id="svg-glow" x="-40%" y="-40%" width="180%" height="180%">
      <feGaussianBlur stdDeviation="4" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="svg-glow-sm" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="2.5" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>`;
  // Radial gradient per agent color
  nodes.forEach(n => {
    const p = getAgentProfile(n.id);
    const c = p.color || '#6366f1';
    defs += `<radialGradient id="ng-${n.id}" cx="38%" cy="35%" r="65%">
      <stop offset="0%" stop-color="${c}" stop-opacity="1"/>
      <stop offset="100%" stop-color="${c}" stop-opacity="0.6"/>
    </radialGradient>`;
  });
  defs += '</defs>';

  // Background
  let body = `<rect width="${W}" height="${H}" fill="${bgColor}"/>`;

  // Grid dots
  const step = 40;
  for (let gx = step; gx < W; gx += step) {
    for (let gy = step; gy < H; gy += step) {
      body += `<circle cx="${gx}" cy="${gy}" r="0.7" fill="${dotColor}"/>`;
    }
  }

  // Edges
  edges.forEach((edge, idx) => {
    const src = nodePos[edge.source], tgt = nodePos[edge.target];
    if (!src || !tgt) return;
    const p = getAgentProfile(edge.source);
    const color = p.color || '#6366f1';
    const opacity = 0.18 + ((edge.count || 1) / maxEdge) * 0.45;

    // Quadratic bezier with mid-point offset for curve
    const mx = (src.x + tgt.x) / 2;
    const my = (src.y + tgt.y) / 2 - 28;
    const d = `M${src.x.toFixed(1)},${src.y.toFixed(1)} Q${mx.toFixed(1)},${my.toFixed(1)} ${tgt.x.toFixed(1)},${tgt.y.toFixed(1)}`;
    const pathId = `ep${idx}`;

    // Glow + core path
    body += `<path d="${d}" stroke="${color}" stroke-width="3.5" fill="none" opacity="${(opacity * 0.18).toFixed(3)}" filter="url(#svg-glow)"/>`;
    body += `<path id="${pathId}" d="${d}" stroke="${color}" stroke-width="1.5" fill="none" opacity="${opacity.toFixed(3)}" stroke-dasharray="5 4">
      <animate attributeName="stroke-dashoffset" from="0" to="-18" dur="1.6s" repeatCount="indefinite"/>
    </path>`;

    // Animated particles (1-3 depending on edge weight)
    const numParticles = Math.min(3, 1 + Math.floor(((edge.count || 1) / maxEdge) * 2));
    for (let pi = 0; pi < numParticles; pi++) {
      const delay = (pi / numParticles) * 2.8;
      const dur = 2.2 + pi * 0.4;
      body += `<circle r="2.8" fill="${color}" filter="url(#svg-glow-sm)" opacity="0.9">
        <animateMotion dur="${dur.toFixed(1)}s" repeatCount="indefinite" begin="${delay.toFixed(1)}s"><mpath href="#${pathId}"/></animateMotion>
        <animate attributeName="opacity" values="0;0.9;0.9;0" dur="${dur.toFixed(1)}s" repeatCount="indefinite" begin="${delay.toFixed(1)}s"/>
      </circle>`;
    }
  });

  // Nodes
  nodes.forEach(node => {
    const pos = nodePos[node.id];
    if (!pos) return;
    const profile = getAgentProfile(node.id);
    const color = profile.color || '#6366f1';
    const isActive = node.status === 'active';
    const normSize = 0.35 + ((node.trace_count || 0) / maxCount) * 0.65;
    const r = Math.round(16 + normSize * 16); // 16..32px radius
    const { x, y } = pos;

    // Outer pulse ring (CSS animated for active, static for idle)
    const pulseR = r + 12;
    if (isActive) {
      body += `<circle cx="${x}" cy="${y}" r="${pulseR}" fill="none" stroke="${color}" stroke-width="1.5" opacity="0.2" class="svg-net-pulse">
        <animate attributeName="r" values="${pulseR};${pulseR+8};${pulseR}" dur="2.2s" repeatCount="indefinite"/>
        <animate attributeName="opacity" values="0.18;0.05;0.18" dur="2.2s" repeatCount="indefinite"/>
      </circle>`;
    } else {
      body += `<circle cx="${x}" cy="${y}" r="${pulseR}" fill="none" stroke="${color}" stroke-width="1" opacity="0.1"/>`;
    }

    // Soft glow halo
    body += `<circle cx="${x}" cy="${y}" r="${r + 6}" fill="${color}" opacity="0.08" filter="url(#svg-glow)"/>`;

    // Core node circle — clickable, opens agent detail modal
    const nodeOpacity = isActive ? '0.9' : '0.55';
    body += `<circle cx="${x}" cy="${y}" r="${r}" fill="url(#ng-${node.id})" opacity="${nodeOpacity}" class="node-core" filter="url(#svg-glow-sm)" onclick="openAgentDetailModal('${escHtml(node.id)}')">
      <title>${escHtml(profile.name || node.id)}: ${node.trace_count || 0} traces</title>
    </circle>`;

    // Specular highlight
    body += `<circle cx="${(x - r*0.28).toFixed(1)}" cy="${(y - r*0.28).toFixed(1)}" r="${(r*0.32).toFixed(1)}" fill="white" opacity="0.22" pointer-events="none"/>`;

    // Label — name
    const textColor = dark ? '#e2e8f0' : '#1e293b';
    const subColor  = dark ? '#64748b' : '#64748b';
    body += `<text x="${x}" y="${y + r + 17}" text-anchor="middle" fill="${textColor}" font-size="12" font-weight="600" font-family="Inter,system-ui,sans-serif">${escHtml(profile.name || node.id)}</text>`;

    // Sub-label: trace count + cost
    const cost = node.cost != null ? `$${Number(node.cost).toFixed(2)}` : '';
    const sub = [node.trace_count ? `${node.trace_count} traces` : '', cost].filter(Boolean).join(' \u00b7 ');
    if (sub) {
      body += `<text x="${x}" y="${y + r + 31}" text-anchor="middle" fill="${subColor}" font-size="10" font-family="Inter,system-ui,sans-serif">${escHtml(sub)}</text>`;
    }
  });

  const svgStr = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" xmlns="${ns}" style="display:block;width:100%;height:100%;">${defs}${body}</svg>`;
  container.innerHTML = svgStr;
}


// =========================================================================
// Cytoscape fallback (when relationship data is unavailable)
// =========================================================================

let _agentCyInstance = null;

function _loadAgentGraphCytoscape(data) {
  const container = document.getElementById('agent-graph');
  if (!container || typeof cytoscape === 'undefined') return;
  if (_agentCyInstance) { try { _agentCyInstance.destroy(); } catch (_) {} _agentCyInstance = null; }
  const elements = [];
  data.nodes.forEach(n => {
    const p = getAgentProfile(n.id);
    elements.push({ data: { id: n.id, label: p.name || n.id }, style: { 'background-color': p.color || '#6366f1' } });
  });
  data.edges.forEach(e => {
    elements.push({ data: { source: e.source, target: e.target, label: `\u00d7${e.count}` } });
  });
  _agentCyInstance = cytoscape({
    container, elements,
    style: [
      { selector: 'node', style: { 'label': 'data(label)', 'text-valign': 'center', 'color': '#e2e0db', 'font-size': '11px', 'width': 40, 'height': 40, 'border-width': 2, 'border-color': '#3a3a36' } },
      { selector: 'edge', style: { 'label': 'data(label)', 'font-size': '9px', 'color': '#8a8a86', 'width': 2, 'line-color': '#4a4a46', 'target-arrow-color': '#6366f1', 'target-arrow-shape': 'triangle', 'curve-style': 'bezier' } },
    ],
    layout: { name: 'dagre', rankDir: 'TB', nodeSep: 50, rankSep: 60 },
  });
  _agentCyInstance.on('mouseover', 'node', evt => { evt.target.style('border-color', getAgentProfile(evt.target.id()).color || '#6366f1'); });
  _agentCyInstance.on('mouseout', 'node', evt => { evt.target.style('border-color', '#3a3a36'); });
  _agentCyInstance.on('tap', 'node', evt => { filterTracesByAgent(evt.target.id()); });
}


// =========================================================================
// CSS-grid fallback (no external lib needed)
// =========================================================================

function _renderAgentGridFallback(containerId, agents) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = '';
  const grid = document.createElement('div');
  grid.className = 'agent-grid-fallback';
  (agents || []).forEach(n => {
    const p = getAgentProfile(n.id || n.agent);
    const card = document.createElement('div');
    card.className = 'agent-fallback-card glass';
    card.onclick = () => openAgentDetailModal(n.id || n.agent);
    const statusDot = (n.status === 'active')
      ? '<span class="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-emerald-500 pulse-dot border border-black/20"></span>'
      : '';
    card.innerHTML = `
      <div class="agent-fallback-dot relative" style="background:${p.color}22;border:2px solid ${p.color}">
        <span style="color:${p.color}">${p.icon || p.name.charAt(0)}</span>
        ${statusDot}
      </div>
      <span class="text-xs font-semibold text-white">${escHtml(p.name || n.id)}</span>
      <span class="text-[9px] text-slate-500">${escHtml(p.role || '')}</span>
      ${n.trace_count ? `<span class="text-[9px] text-slate-600">${n.trace_count} traces</span>` : ''}
    `;
    grid.appendChild(card);
  });
  container.appendChild(grid);
}


// =========================================================================
// Public entry point — loadAgentGraph
// =========================================================================

async function loadAgentGraph() {
  const container = document.getElementById('agent-graph');
  if (!container) return;

  // Disconnect any previous resize observer
  if (_agentGraphResizeObserver) { _agentGraphResizeObserver.disconnect(); _agentGraphResizeObserver = null; }

  try {
    const data = await apiFetch('/v1/agents/relationships');
    _agentRelData = data;

    if (!data.nodes || data.nodes.length === 0) {
      try {
        const summary = await apiFetch('/v1/agents/summary');
        if (summary.agents && summary.agents.length > 0) {
          _renderAgentGridFallback('agent-graph', summary.agents.map(a => ({ id: a.agent, trace_count: a.trace_count, status: 'active' })));
        }
      } catch (_) {}
      return;
    }

    // Use IntersectionObserver to defer render until visible (saves work if tab is hidden)
    const render = () => {
      container.innerHTML = '';
      container.style.height = '400px';
      _buildSVGNetwork(container, data);

      // Debounced responsive resize: re-render SVG on container size change
      _agentGraphResizeObserver = new ResizeObserver(() => {
        clearTimeout(_agentGraphResizeTimer);
        _agentGraphResizeTimer = setTimeout(() => {
          if (container.clientWidth > 0 && _agentRelData) {
            _buildSVGNetwork(container, _agentRelData);
          }
        }, 150);
      });
      _agentGraphResizeObserver.observe(container);
    };

    if ('IntersectionObserver' in window) {
      const io = new IntersectionObserver(entries => {
        if (entries[0].isIntersecting) {
          io.disconnect();
          render();
        }
      }, { threshold: 0.1 });
      io.observe(container);
    } else {
      render();
    }

  } catch (e) {
    try {
      const summary = await apiFetch('/v1/agents/summary');
      if (summary.agents && summary.agents.length > 0) {
        _renderAgentGridFallback('agent-graph', summary.agents.map(a => ({ id: a.agent, trace_count: a.trace_count, status: 'active' })));
      }
    } catch (_) {}
  }
}


// =========================================================================
// Mini graph + Overview graph
// =========================================================================

async function loadAgentGraphMini() {
  // Mini graph is no longer needed with SVG — the main graph is already lightweight
  return;
}

async function loadOverviewAgents() {
  try {
    const [summaryData, activityData] = await Promise.all([
      apiFetch('/v1/agents/summary'),
      apiFetch('/v1/agents/activity').catch(() => ({ agents: [] })),
    ]);

    if (!summaryData?.agents) return;
    const agents = summaryData.agents.filter(a => a.agent !== 'unknown');
    if (agents.length === 0) return;
    const activityMap = {};
    (activityData?.agents || []).forEach(a => { activityMap[a.agent] = a; });

    const container = document.getElementById('overview-agents-grid');
    if (!container) return;

    container.innerHTML = agents.map(a => {
      const p = getAgentProfile(a.agent);
      const activity = activityMap[a.agent] || {};
      const isActive = activity.status === 'active';
      const tools = (activity.recent_tools || []).slice(0, 3);
      const errPct = (a.error_rate * 100).toFixed(1);
      const errColor = a.error_rate < 0.05 ? 'text-emerald-400' : a.error_rate < 0.20 ? 'text-yellow-400' : 'text-red-400';
      const latency = a.avg_duration_ms >= 1000
        ? (a.avg_duration_ms / 1000).toFixed(2) + 's'
        : a.avg_duration_ms.toFixed(0) + 'ms';
      const cost = a.total_cost_usd < 0.01
        ? '$' + a.total_cost_usd.toFixed(6)
        : '$' + a.total_cost_usd.toFixed(4);

      // Mini activity bar: 24 dots
      const activityDots = [];
      for (let h = 0; h < 24; h++) {
        const hasActivity = activity.hourly_counts ? (activity.hourly_counts[h] || 0) > 0 : (Math.random() < Math.min(0.7, (a.trace_count || 1) / 100));
        const dotColor = hasActivity ? (isActive ? '#34d399' : '#6366f1') : '#1e293b';
        activityDots.push(`<span style="display:inline-block;width:6px;height:14px;border-radius:2px;background:${dotColor};margin-right:1px;" title="Hour ${h}"></span>`);
      }

      return `
        <div class="glass rounded-xl p-4 card-3d-hover cursor-pointer" onclick="filterTracesByAgent('${escHtml(a.agent)}')">
          <div class="flex items-center gap-3 mb-3">
            ${renderAgentAvatar(a.agent, 'md')}
            <div class="min-w-0 flex-1">
              <div class="text-sm font-semibold text-white truncate">${escHtml(p.name)}</div>
              <div class="text-[10px] text-slate-500">${escHtml(p.role)}</div>
            </div>
            ${isActive ? '<span class="ml-auto w-2 h-2 rounded-full bg-emerald-500 pulse-dot"></span>' : '<span class="ml-auto w-2 h-2 rounded-full bg-slate-600"></span>'}
          </div>
          <div class="grid grid-cols-4 gap-2 text-center mb-3">
            <div><div class="text-sm font-bold text-white">${a.trace_count}</div><div class="text-[9px] text-slate-500">Traces</div></div>
            <div><div class="text-sm font-bold ${errColor}">${errPct}%</div><div class="text-[9px] text-slate-500">Errors</div></div>
            <div><div class="text-sm font-bold text-white">${cost}</div><div class="text-[9px] text-slate-500">Cost</div></div>
            <div><div class="text-sm font-bold text-white">${latency}</div><div class="text-[9px] text-slate-500">Avg</div></div>
          </div>
          <div class="mb-2">
            <div style="display:flex;align-items:flex-end;height:16px;">${activityDots.join('')}</div>
          </div>
          ${tools.length > 0 ? `<div class="flex gap-1 flex-wrap">${tools.map(t => `<span class="px-1.5 py-0.5 text-[9px] rounded bg-indigo-500/10 text-indigo-300">${escHtml(t)}</span>`).join('')}</div>` : ''}
        </div>`;
    }).join('');
  } catch (e) { console.warn('Overview agents:', e); }
}


// --- Overview graph uses same SVG approach ---

async function loadOverviewGraph() {
  try {
    const [relData, netData] = await Promise.all([
      apiFetch('/v1/agents/relationships'),
      apiFetch('/v1/agents/network'),
    ]);

    const container = document.getElementById('overview-agent-graph');
    if (!container) return;

    container.innerHTML = '';

    const nodes = (netData?.nodes || []).filter(n => n.id !== 'Agent');
    const edges = relData?.edges || [];
    if (nodes.length === 0) { container.innerHTML = '<p class="text-center text-slate-500 py-20">No agent data</p>'; return; }

    // Reuse the same SVG builder
    _buildSVGNetwork(container, { nodes, edges });

  } catch (e) { console.warn('Network graph:', e); }
}
