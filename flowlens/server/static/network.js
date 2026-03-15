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

  // Responsive scaling — reduce node radius and ellipse on narrow containers
  const isNarrow = W < 480;
  const isMedium  = W < 640;

  // Layout: hub-and-spoke — main/unknown in center, others on ellipse
  const cx = W / 2, cy = H / 2;
  const rxBase = isNarrow ? W * 0.30 : (isMedium ? W * 0.33 : W * 0.36);
  const rx = Math.min(rxBase, isNarrow ? 120 : 240);
  const ry = Math.min(H * 0.32, isNarrow ? 80 : 140);
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

  // Theme-aware colors
  const bgDark  = '#0a0f1e';
  const bgLight = '#faf9f7';
  const bgColor = dark ? bgDark : bgLight;
  const ns = 'http://www.w3.org/2000/svg';

  // ---- Build SVG defs ----
  let defs = `<defs>
    <!-- Deep glow filter for edges and halos -->
    <filter id="svg-glow" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="5" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <!-- Soft glow for particles and node rings -->
    <filter id="svg-glow-sm" x="-40%" y="-40%" width="180%" height="180%">
      <feGaussianBlur stdDeviation="2.5" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <!-- Ultra-soft glow for outer rings -->
    <filter id="svg-glow-xs" x="-60%" y="-60%" width="220%" height="220%">
      <feGaussianBlur stdDeviation="8" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <!-- Background radial gradient: lighter center -->
    <radialGradient id="bg-radial" cx="50%" cy="50%" r="60%">
      <stop offset="0%" stop-color="${dark ? 'rgba(99,102,241,0.04)' : 'rgba(107,92,231,0.03)'}"/>
      <stop offset="100%" stop-color="${dark ? 'rgba(0,0,0,0)' : 'rgba(0,0,0,0)'}"/>
    </radialGradient>`;

  // Per-agent gradients (radial — lighter at top-left for 3D feel, dark theme brighter)
  nodes.forEach(n => {
    const p = getAgentProfile(n.id);
    const c = p.color || '#6b5ce7';
    // Lighten the center color for the gradient stop
    defs += `
    <radialGradient id="ng-${n.id}" cx="35%" cy="30%" r="70%">
      <stop offset="0%" stop-color="${c}" stop-opacity="${dark ? '1' : '0.85'}"/>
      <stop offset="60%" stop-color="${c}" stop-opacity="${dark ? '0.88' : '0.72'}"/>
      <stop offset="100%" stop-color="${c}" stop-opacity="${dark ? '0.65' : '0.5'}"/>
    </radialGradient>
    <radialGradient id="ng-mid-${n.id}" cx="50%" cy="50%" r="50%">
      <stop offset="0%" stop-color="${c}" stop-opacity="${dark ? '0.22' : '0.14'}"/>
      <stop offset="100%" stop-color="${c}" stop-opacity="0"/>
    </radialGradient>`;
  });

  // Edge gradient per source→target pair
  edges.forEach((edge, idx) => {
    const sp = getAgentProfile(edge.source);
    const tp = getAgentProfile(edge.target);
    const sc = sp.color || '#6b5ce7';
    const tc = tp.color || '#a78bfa';
    const src = nodePos[edge.source], tgt = nodePos[edge.target];
    if (!src || !tgt) return;
    defs += `
    <linearGradient id="eg-${idx}" x1="${src.x}" y1="${src.y}" x2="${tgt.x}" y2="${tgt.y}" gradientUnits="userSpaceOnUse">
      <stop offset="0%" stop-color="${sc}"/>
      <stop offset="100%" stop-color="${tc}"/>
    </linearGradient>`;
  });

  defs += '</defs>';

  // ---- Background ----
  let body = `<rect width="${W}" height="${H}" fill="${bgColor}"/>`;
  // Subtle radial gradient overlay for depth
  body += `<rect width="${W}" height="${H}" fill="url(#bg-radial)" opacity="1"/>`;

  // ---- Edges ----
  edges.forEach((edge, idx) => {
    const src = nodePos[edge.source], tgt = nodePos[edge.target];
    if (!src || !tgt) return;
    const sp = getAgentProfile(edge.source);
    const edgeWeight = (edge.count || 1) / maxEdge;
    const opacity = dark
      ? (0.20 + edgeWeight * 0.50)
      : (0.15 + edgeWeight * 0.35);
    const strokeW = 1.0 + edgeWeight * 1.8; // thickness based on connection strength

    // Quadratic bezier — perpendicular offset for clear curvature
    const dx = tgt.x - src.x, dy = tgt.y - src.y;
    const len = Math.sqrt(dx*dx + dy*dy) || 1;
    const perpX = -dy / len, perpY = dx / len;
    const curvature = Math.min(len * 0.22, 45);
    const mx = (src.x + tgt.x) / 2 + perpX * curvature;
    const my = (src.y + tgt.y) / 2 + perpY * curvature;
    const d = `M${src.x.toFixed(1)},${src.y.toFixed(1)} Q${mx.toFixed(1)},${my.toFixed(1)} ${tgt.x.toFixed(1)},${tgt.y.toFixed(1)}`;
    const pathId = `ep${idx}`;
    const color = sp.color || '#6b5ce7';

    // Outer glow path (very transparent, thick)
    body += `<path d="${d}" stroke="url(#eg-${idx})" stroke-width="${(strokeW * 3.5).toFixed(1)}" fill="none" opacity="${(opacity * 0.12).toFixed(3)}" filter="url(#svg-glow)"/>`;
    // Core animated dashed path with gradient color
    body += `<path id="${pathId}" d="${d}" stroke="url(#eg-${idx})" stroke-width="${strokeW.toFixed(1)}" fill="none" opacity="${opacity.toFixed(3)}" stroke-dasharray="6 5">
      <animate attributeName="stroke-dashoffset" from="0" to="-22" dur="1.8s" repeatCount="indefinite"/>
    </path>`;

    // Animated particles — softer, smaller, agent-colored
    const numParticles = Math.min(3, 1 + Math.floor(edgeWeight * 2));
    for (let pi = 0; pi < numParticles; pi++) {
      const delay = (pi / numParticles) * 3.0;
      const dur   = 2.4 + pi * 0.5;
      const pr    = isNarrow ? 1.6 : 2.0; // smaller particles
      body += `<circle r="${pr}" fill="${color}" filter="url(#svg-glow-sm)" opacity="0">
        <animateMotion dur="${dur.toFixed(1)}s" repeatCount="indefinite" begin="${delay.toFixed(1)}s"><mpath href="#${pathId}"/></animateMotion>
        <animate attributeName="opacity" values="0;0.75;0.75;0" keyTimes="0;0.15;0.85;1" dur="${dur.toFixed(1)}s" repeatCount="indefinite" begin="${delay.toFixed(1)}s"/>
        <animate attributeName="r" values="${pr};${(pr*1.4).toFixed(1)};${pr}" dur="${dur.toFixed(1)}s" repeatCount="indefinite" begin="${delay.toFixed(1)}s"/>
      </circle>`;
    }
  });

  // ---- Nodes ----
  nodes.forEach(node => {
    const pos = nodePos[node.id];
    if (!pos) return;
    const profile = getAgentProfile(node.id);
    const color = profile.color || '#6b5ce7';
    const isActive = node.status === 'active';
    const normSize = 0.30 + ((node.trace_count || 0) / maxCount) * 0.70;
    const baseR = isNarrow ? 13 : 16;
    const maxR  = isNarrow ? 22 : 28;
    const r = Math.round(baseR + normSize * (maxR - baseR));
    const { x, y } = pos;

    // Layer 1 — Outermost soft ambient glow (very subtle, filter-blurred)
    body += `<circle cx="${x}" cy="${y}" r="${r + 18}" fill="${color}" opacity="${dark ? '0.05' : '0.04'}" filter="url(#svg-glow-xs)" pointer-events="none"/>`;

    // Layer 2 — Middle ring at 20% agent color opacity
    if (isActive) {
      // Animated pulse for active nodes
      body += `<circle cx="${x}" cy="${y}" r="${r + 10}" fill="url(#ng-mid-${node.id})" opacity="0.6" pointer-events="none">
        <animate attributeName="r" values="${r+8};${r+16};${r+8}" dur="2.6s" repeatCount="indefinite" calcMode="spline" keySplines="0.4 0 0.2 1;0.4 0 0.2 1"/>
        <animate attributeName="opacity" values="0.5;0.08;0.5" dur="2.6s" repeatCount="indefinite" calcMode="spline" keySplines="0.4 0 0.2 1;0.4 0 0.2 1"/>
      </circle>`;
      // Thin animated outer stroke ring
      body += `<circle cx="${x}" cy="${y}" r="${r + 7}" fill="none" stroke="${color}" stroke-width="1" opacity="0.18" pointer-events="none">
        <animate attributeName="r" values="${r+5};${r+13};${r+5}" dur="2.6s" repeatCount="indefinite" calcMode="spline" keySplines="0.4 0 0.2 1;0.4 0 0.2 1"/>
        <animate attributeName="opacity" values="0.22;0.04;0.22" dur="2.6s" repeatCount="indefinite" calcMode="spline" keySplines="0.4 0 0.2 1;0.4 0 0.2 1"/>
      </circle>`;
    } else {
      // Static subtle ring for idle nodes
      body += `<circle cx="${x}" cy="${y}" r="${r + 9}" fill="${color}" opacity="${dark ? '0.06' : '0.05'}" pointer-events="none"/>`;
      body += `<circle cx="${x}" cy="${y}" r="${r + 9}" fill="none" stroke="${color}" stroke-width="0.8" opacity="${dark ? '0.12' : '0.10'}" pointer-events="none"/>`;
    }

    // Layer 3 — Inner ring (colored border at 20% opacity)
    body += `<circle cx="${x}" cy="${y}" r="${r + 3}" fill="none" stroke="${color}" stroke-width="1.5" opacity="${dark ? '0.22' : '0.18'}" pointer-events="none"/>`;

    // Layer 4 — Core circle with radial gradient (lighter center)
    const nodeOpacity = isActive ? (dark ? '1' : '0.92') : (dark ? '0.65' : '0.55');
    // Encode node data for tooltip as JSON-safe attributes
    const nodeTraces = node.trace_count || 0;
    const nodeCost = node.cost != null ? Number(node.cost).toFixed(4) : null;
    const nodeStatus = node.status || 'idle';
    const nodeLastActive = node.last_active || '';
    body += `<circle cx="${x}" cy="${y}" r="${r}" fill="url(#ng-${node.id})" opacity="${nodeOpacity}" class="node-core"
      onclick="openAgentDetailModal('${escHtml(node.id)}')"
      onmouseenter="_showNetworkNodeTooltip(event,'${escHtml(profile.name || node.id)}','${escHtml(profile.role || '')}',${nodeTraces},${nodeCost !== null ? `'$${nodeCost}'` : 'null'},'${escHtml(nodeStatus)}','${escHtml(nodeLastActive)}')"
      onmousemove="_moveNetworkNodeTooltip(event)"
      onmouseleave="_hideNetworkNodeTooltip()">
      <title>${escHtml(profile.name || node.id)}: ${nodeTraces} traces</title>
    </circle>`;

    // Layer 5 — Soft inner glow overlay
    body += `<circle cx="${x}" cy="${y}" r="${r}" fill="${color}" opacity="${dark ? '0.08' : '0.05'}" filter="url(#svg-glow-sm)" pointer-events="none"/>`;

    // Layer 6 — Specular highlight (top-left glass effect)
    body += `<circle cx="${(x - r*0.25).toFixed(1)}" cy="${(y - r*0.25).toFixed(1)}" r="${(r*0.28).toFixed(1)}" fill="white" opacity="${dark ? '0.28' : '0.35'}" pointer-events="none"/>`;

    // Agent initial letter — centered, white/light
    const letterSize = isNarrow ? Math.max(10, r * 0.72) : Math.max(11, r * 0.70);
    const letterColor = '#ffffff';
    const letter = (profile.name || node.id || '?').charAt(0).toUpperCase();
    body += `<text x="${x}" y="${(y + letterSize * 0.36).toFixed(1)}" text-anchor="middle" dominant-baseline="middle" fill="${letterColor}" font-size="${letterSize.toFixed(0)}" font-weight="700" font-family="Inter,system-ui,sans-serif" pointer-events="none" opacity="0.95">${escHtml(letter)}</text>`;

    // Labels — skip if very narrow to avoid overlap
    if (!isNarrow || r >= 16) {
      const labelGap = isNarrow ? 12 : 16;
      const textColor = dark ? '#e2e8f0' : '#1e293b';
      const subColor  = dark ? '#64748b' : '#94a3b8';

      // Agent name — 12px, weight 600
      body += `<text x="${x}" y="${(y + r + labelGap).toFixed(1)}" text-anchor="middle" fill="${textColor}" font-size="12" font-weight="600" font-family="Inter,system-ui,sans-serif" pointer-events="none">${escHtml(profile.name || node.id)}</text>`;

      // Stats sub-label — 10px, muted — only if not too narrow
      if (!isNarrow) {
        const cost = node.cost != null ? `$${Number(node.cost).toFixed(2)}` : '';
        const sub = [node.trace_count ? `${node.trace_count} traces` : '', cost].filter(Boolean).join(' \u00b7 ');
        if (sub) {
          body += `<text x="${x}" y="${(y + r + labelGap + 15).toFixed(1)}" text-anchor="middle" fill="${subColor}" font-size="10" font-family="Inter,system-ui,sans-serif" pointer-events="none">${escHtml(sub)}</text>`;
        }
      }
    }
  });

  // viewBox stays fixed to W×H so SVG scales responsively via CSS width:100%
  const svgStr = `<svg viewBox="0 0 ${W} ${H}" xmlns="${ns}" style="display:block;width:100%;height:100%;">${defs}${body}</svg>`;
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
    const data = await apiFetch('/v1/agents/relationships');

    const container = document.getElementById('overview-agent-graph');
    if (!container) return;

    container.innerHTML = '';

    if (!data.nodes || data.nodes.length === 0) {
      container.innerHTML = '<p class="text-center text-slate-500 py-20">No agent data</p>';
      return;
    }

    // Use the same SVG network as the Agents tab
    _buildSVGNetwork(container, data);

  } catch (e) { console.warn('Network graph:', e); }
}


// =========================================================================
// Agent Network Node Tooltip
// =========================================================================

let _netTooltip = null;

function _getOrCreateNetTooltip() {
  if (_netTooltip) return _netTooltip;
  _netTooltip = document.createElement('div');
  _netTooltip.id = 'agent-node-tooltip';
  document.body.appendChild(_netTooltip);
  return _netTooltip;
}

function _showNetworkNodeTooltip(event, name, role, traceCount, cost, status, lastActive) {
  const tip = _getOrCreateNetTooltip();

  const costLine  = cost ? `<div class="agent-tooltip-row"><span>Cost</span><span>${cost}</span></div>` : '';
  const lastLine  = lastActive
    ? `<div class="agent-tooltip-row"><span>Last active</span><span>${(typeof formatTimeAgo === 'function' ? formatTimeAgo(parseFloat(lastActive)) : lastActive)}</span></div>`
    : '';
  const statusColor = status === 'active' ? '#34d399' : '#64748b';
  const statusDot = `<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:${statusColor};margin-right:4px;vertical-align:middle;"></span>`;

  tip.innerHTML = `
    <div class="agent-tooltip-name">${escHtml(name)}</div>
    ${role ? `<div style="font-size:10px;color:#64748b;margin-bottom:6px;">${escHtml(role)}</div>` : ''}
    <div class="agent-tooltip-row"><span>${statusDot}Status</span><span>${escHtml(status)}</span></div>
    <div class="agent-tooltip-row"><span>Traces</span><span>${traceCount}</span></div>
    ${costLine}
    ${lastLine}
  `;

  _positionNetTooltip(event);
  tip.classList.add('visible');
}

function _moveNetworkNodeTooltip(event) {
  if (_netTooltip) _positionNetTooltip(event);
}

function _positionNetTooltip(event) {
  const tip = _netTooltip;
  if (!tip) return;
  const margin = 14;
  let x = event.clientX + margin;
  let y = event.clientY + margin;
  // Keep in viewport
  const r = tip.getBoundingClientRect();
  if (x + r.width + margin > window.innerWidth)  x = event.clientX - r.width - margin;
  if (y + r.height + margin > window.innerHeight) y = event.clientY - r.height - margin;
  tip.style.left = x + 'px';
  tip.style.top  = y + 'px';
}

function _hideNetworkNodeTooltip() {
  if (_netTooltip) _netTooltip.classList.remove('visible');
}
