/* FlowLens Dashboard — Agent Network Visualization (Three.js + Cytoscape fallback) */
'use strict';


// =========================================================================
// Agent Relationship Graph — Three.js 3D Visualization
// =========================================================================

let _three3D = null;    // main 3D scene state
let _threeMini = null;  // mini 3D scene state (overview)
let _agentRelData = null; // cached relationship data shared between scenes

/** Dispose all Three.js resources in a scene state object. */
function _disposeThreeScene(state) {
  if (!state) return;
  if (state.animFrameId) { cancelAnimationFrame(state.animFrameId); }
  if (state.labelContainer && state.labelContainer.parentNode) {
    state.labelContainer.parentNode.removeChild(state.labelContainer);
  }
  if (state.resizeObserver) { state.resizeObserver.disconnect(); }
  (state.meshes || []).forEach(m => {
    if (m.geometry) m.geometry.dispose();
    if (m.material) m.material.dispose();
  });
  (state.lines || []).forEach(l => {
    if (l.geometry) l.geometry.dispose();
    if (l.material) l.material.dispose();
  });
  if (state.particleGeom) state.particleGeom.dispose();
  if (state.particleMat) state.particleMat.dispose();
  if (state.renderer) {
    state.renderer.dispose();
    if (state.renderer.domElement && state.renderer.domElement.parentNode) {
      state.renderer.domElement.parentNode.removeChild(state.renderer.domElement);
    }
  }
}

/** Compute circle positions for n nodes at radius r. */
function _circlePositions(n, r) {
  const pos = [];
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2 - Math.PI / 2;
    pos.push([Math.cos(a) * r, Math.sin(a) * r, 0]);
  }
  return pos;
}

/** Parse '#rrggbb' to {r,g,b} in [0,1]. */
function _hexToRgb01(hex) {
  const h = (hex || '#9ca3af').replace('#', '');
  return {
    r: parseInt(h.substring(0, 2), 16) / 255,
    g: parseInt(h.substring(2, 4), 16) / 255,
    b: parseInt(h.substring(4, 6), 16) / 255,
  };
}

/**
 * Build and start a Three.js 3D scene inside `container`.
 * opts: { showLabels, autoRotate, miniMode }
 * Returns a state object to pass to _disposeThreeScene().
 */
function _buildThreeScene(container, data, opts) {
  if (typeof THREE === 'undefined') return null;
  opts = Object.assign({ showLabels: true, autoRotate: true, miniMode: false }, opts);

  const bgColor = isDarkTheme ? 0x0f172a : 0xfafaf8;
  const cw = container.clientWidth || 600;
  const ch = container.clientHeight || 350;

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(cw, ch);
  renderer.setClearColor(bgColor, 1);
  renderer.domElement.style.cssText = 'display:block;width:100%;height:100%;';
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(55, cw / ch, 0.1, 1000);
  camera.position.set(0, 0, opts.miniMode ? 4.5 : 5.5);

  scene.add(new THREE.AmbientLight(0xffffff, 0.4));
  const ptLight = new THREE.PointLight(0xffffff, 1.2, 50);
  ptLight.position.set(0, 5, 5);
  scene.add(ptLight);

  const nodes = data.nodes || [];
  const edges = data.edges || [];
  const maxCount = nodes.reduce((acc, n) => Math.max(acc, n.trace_count || 1), 1);
  const maxEdgeCount = edges.reduce((acc, e) => Math.max(acc, e.count || 1), 1);
  const radius = Math.max(1.4, nodes.length * 0.38);
  const positions = _circlePositions(nodes.length, radius);

  const nodeIndex = {};
  nodes.forEach((n, i) => { nodeIndex[n.id] = i; });

  const meshes = [];
  const lines = [];
  const rotationGroup = new THREE.Group();
  scene.add(rotationGroup);

  // Spheres (one per agent node)
  nodes.forEach((n, i) => {
    const p = getAgentProfile(n.id);
    const rgb = _hexToRgb01(p.color);
    const color = new THREE.Color(rgb.r, rgb.g, rgb.b);
    const normSize = 0.3 + ((n.trace_count || 1) / maxCount) * 0.7;
    const r = opts.miniMode ? normSize * 0.7 : normSize;
    const geo = new THREE.SphereGeometry(r, 32, 32);
    const isActive = n.status === 'active';
    const mat = new THREE.MeshPhongMaterial({
      color, emissive: color,
      emissiveIntensity: isActive ? 0.55 : 0.1,
      transparent: !isActive, opacity: isActive ? 1.0 : 0.45,
      shininess: 120, specular: new THREE.Color(0x444466),
      reflectivity: 0.6,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(...positions[i]);
    mesh.userData = { agentId: n.id, baseEmissive: isActive ? 0.55 : 0.1, isActive };
    rotationGroup.add(mesh);
    meshes.push(mesh);
  });

  // Glowing lines for spawn-relationship edges (core + outer glow)
  edges.forEach(e => {
    const si = nodeIndex[e.source], ti = nodeIndex[e.target];
    if (si === undefined || ti === undefined) return;
    const pts = [new THREE.Vector3(...positions[si]), new THREE.Vector3(...positions[ti])];
    const opacity = 0.2 + ((e.count || 1) / maxEdgeCount) * 0.5;

    // Outer glow line (thicker, very transparent)
    const geoGlow = new THREE.BufferGeometry().setFromPoints(pts);
    const matGlow = new THREE.LineBasicMaterial({
      color: 0x6366f1, transparent: true, opacity: opacity * 0.25, linewidth: 3,
    });
    const glowLine = new THREE.Line(geoGlow, matGlow);
    rotationGroup.add(glowLine);
    lines.push(glowLine);

    // Core line (dashed, brighter)
    const geoL = new THREE.BufferGeometry().setFromPoints(pts);
    const matL = new THREE.LineDashedMaterial({
      color: 0x818cf8, transparent: true, opacity, dashSize: 0.18, gapSize: 0.09,
    });
    const line = new THREE.Line(geoL, matL);
    line.computeLineDistances();
    rotationGroup.add(line);
    lines.push(line);
  });

  // Floating particle background
  const particleCount = 200;
  const particleGeom = new THREE.BufferGeometry();
  const particlePositions = new Float32Array(particleCount * 3);
  for (let i = 0; i < particleCount; i++) {
    particlePositions[i * 3]     = (Math.random() - 0.5) * 20;
    particlePositions[i * 3 + 1] = (Math.random() - 0.5) * 20;
    particlePositions[i * 3 + 2] = (Math.random() - 0.5) * 20;
  }
  particleGeom.setAttribute('position', new THREE.BufferAttribute(particlePositions, 3));
  const particleMat = new THREE.PointsMaterial({ color: 0x6366f1, size: 0.05, transparent: true, opacity: 0.3 });
  const particles = new THREE.Points(particleGeom, particleMat);
  scene.add(particles);

  // HTML labels positioned via 3D projection (main scene only)
  let labelContainer = null;
  const labelEls = [];
  if (opts.showLabels) {
    container.style.position = 'relative';
    labelContainer = document.createElement('div');
    labelContainer.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;overflow:hidden;';
    container.appendChild(labelContainer);

    nodes.forEach((n) => {
      const p = getAgentProfile(n.id);
      const el = document.createElement('div');
      el.style.cssText = [
        'position:absolute', 'transform:translate(-50%,-100%)', 'pointer-events:none', 'white-space:nowrap',
        'font-family:Inter,system-ui,sans-serif', 'line-height:1.3', 'padding:2px 6px', 'border-radius:4px',
        isDarkTheme ? 'background:rgba(42,42,38,0.85)' : 'background:rgba(250,250,248,0.85)',
        'backdrop-filter:blur(4px)', 'border:1px solid rgba(255,255,255,0.08)',
      ].join(';');
      el.innerHTML = `<span style="font-size:10px;font-weight:600;color:${p.color}">${p.name || n.id}</span>`
        + `<br><span style="font-size:9px;color:${isDarkTheme ? '#94a3b8' : '#64748b'}">${p.role || ''}</span>`;
      labelContainer.appendChild(el);
      labelEls.push(el);
    });
  }

  // Mouse drag to rotate, hover highlight, click to open agent detail modal
  let isDragging = false;
  let lastMouseX = 0, lastMouseY = 0;
  let rotX = 0, rotY = 0;
  let hoveredMesh = null;
  const raycaster = new THREE.Raycaster();
  const mouse2D = new THREE.Vector2();

  function onMouseDown(e) { isDragging = true; lastMouseX = e.clientX; lastMouseY = e.clientY; }
  function onMouseMove(e) {
    const rect = renderer.domElement.getBoundingClientRect();
    mouse2D.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    mouse2D.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    if (isDragging) {
      rotY += (e.clientX - lastMouseX) * 0.008;
      rotX += (e.clientY - lastMouseY) * 0.008;
      rotX = Math.max(-1.2, Math.min(1.2, rotX));
      lastMouseX = e.clientX; lastMouseY = e.clientY;
    }
    raycaster.setFromCamera(mouse2D, camera);
    const hits = raycaster.intersectObjects(meshes);
    if (hits.length > 0) {
      const hit = hits[0].object;
      if (hoveredMesh !== hit) {
        if (hoveredMesh) { hoveredMesh.scale.setScalar(1.0); hoveredMesh.material.emissiveIntensity = hoveredMesh.userData.baseEmissive; }
        hoveredMesh = hit;
        hit.scale.setScalar(1.3);
        hit.material.emissiveIntensity = Math.min(1.0, hit.userData.baseEmissive + 0.4);
      }
      renderer.domElement.style.cursor = 'pointer';
    } else {
      if (hoveredMesh) { hoveredMesh.scale.setScalar(1.0); hoveredMesh.material.emissiveIntensity = hoveredMesh.userData.baseEmissive; hoveredMesh = null; }
      renderer.domElement.style.cursor = 'default';
    }
  }
  function onMouseUp(e) {
    if (!isDragging) return;
    isDragging = false;
    if (Math.abs(e.clientX - lastMouseX) < 4 && Math.abs(e.clientY - lastMouseY) < 4) {
      raycaster.setFromCamera(mouse2D, camera);
      const hits = raycaster.intersectObjects(meshes);
      if (hits.length > 0) { openAgentDetailModal(hits[0].object.userData.agentId); }
    }
  }
  function onMouseLeave() { isDragging = false; }

  if (!opts.miniMode) {
    renderer.domElement.addEventListener('mousedown', onMouseDown);
    renderer.domElement.addEventListener('mousemove', onMouseMove);
    renderer.domElement.addEventListener('mouseup', onMouseUp);
    renderer.domElement.addEventListener('mouseleave', onMouseLeave);
  }

  // requestAnimationFrame render loop
  let frame = 0;
  let animFrameId = null;
  function animate() {
    animFrameId = requestAnimationFrame(animate);
    frame++;
    if (!isDragging && opts.autoRotate) rotY += 0.0008;
    rotationGroup.rotation.y = rotY;
    rotationGroup.rotation.x = rotX;

    // Pulse emissive intensity for active agents
    meshes.forEach(m => {
      if (m.userData.isActive && m !== hoveredMesh) {
        m.material.emissiveIntensity = 0.55 + Math.sin(frame * 0.05) * 0.25;
      }
    });

    // Slowly rotate particle field
    particles.rotation.y += 0.0003;
    particles.rotation.x += 0.0001;

    renderer.render(scene, camera);

    // Update HTML label screen positions
    if (opts.showLabels && labelContainer) {
      const elW = container.clientWidth, elH = container.clientHeight;
      nodes.forEach((n, i) => {
        if (!labelEls[i] || !meshes[i]) return;
        const wp = new THREE.Vector3();
        meshes[i].getWorldPosition(wp);
        const proj = wp.clone().project(camera);
        const sx = (proj.x * 0.5 + 0.5) * elW;
        const wpTop = wp.clone();
        wpTop.y += (meshes[i].geometry.parameters.radius || 0.5);
        const sy = (-(wpTop.clone().project(camera).y) * 0.5 + 0.5) * elH;
        labelEls[i].style.left = sx + 'px';
        labelEls[i].style.top = sy + 'px';
        labelEls[i].style.display = proj.z < 1 ? 'block' : 'none';
      });
    }
  }
  animate();

  // Responsive resize
  const resizeObserver = new ResizeObserver(() => {
    const nw = container.clientWidth, nh = container.clientHeight;
    if (nw && nh) {
      renderer.setSize(nw, nh);
      camera.aspect = nw / nh;
      camera.updateProjectionMatrix();
    }
  });
  resizeObserver.observe(container);

  return { renderer, scene, camera, meshes, lines, rotationGroup, labelContainer, labelEls, resizeObserver, animFrameId, particles, particleGeom, particleMat };
}

// Cytoscape fallback when THREE.js is unavailable
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

async function loadAgentGraph() {
  try {
    const data = await apiFetch('/v1/agents/relationships');
    _agentRelData = data;

    if (!data.nodes || data.nodes.length === 0) {
      // Fallback: try agent summary for at least showing agent cards
      try {
        const summary = await apiFetch('/v1/agents/summary');
        if (summary.agents && summary.agents.length > 0) {
          _renderAgentGridFallback('agent-graph', summary.agents.map(a => ({ id: a.agent, trace_count: a.trace_count, status: 'active' })));
        }
      } catch (_) {}
      return;
    }

    if (typeof THREE !== 'undefined') {
      const container = document.getElementById('agent-graph');
      if (!container) return;
      if (_three3D) { _disposeThreeScene(_three3D); _three3D = null; }
      container.innerHTML = '';
      container.style.height = '400px';
      _three3D = _buildThreeScene(container, data, { showLabels: true, autoRotate: true, miniMode: false });
    } else if (typeof cytoscape !== 'undefined') {
      _loadAgentGraphCytoscape(data);
    } else {
      // Pure CSS fallback
      _renderAgentGridFallback('agent-graph', data.nodes);
    }
  } catch (e) {
    // On error, try showing agent summary as grid fallback
    try {
      const summary = await apiFetch('/v1/agents/summary');
      if (summary.agents && summary.agents.length > 0) {
        _renderAgentGridFallback('agent-graph', summary.agents.map(a => ({ id: a.agent, trace_count: a.trace_count, status: 'active' })));
      }
    } catch (_) {}
  }
}

async function loadAgentGraphMini() {
  try {
    const data = await apiFetch('/v1/agents/network');
    if (!data || !data.nodes || data.nodes.length === 0) return;
    const container = document.getElementById('agent-graph-mini');
    if (!container || container.clientWidth === 0) return;

    // Clean up previous
    container.innerHTML = '';

    if (typeof cytoscape === 'undefined') return;

    const elements = [];
    data.nodes.forEach(n => {
      const p = getAgentProfile(n.id);
      elements.push({ data: { id: n.id, label: p.name || n.id, color: p.color || '#6366f1' } });
    });
    (data.edges || []).forEach(e => {
      elements.push({ data: { source: e.source, target: e.target, label: 'x' + (e.count || 1) } });
    });

    cytoscape({
      container: container,
      elements: elements,
      style: [
        { selector: 'node', style: {
          'label': 'data(label)',
          'background-color': 'data(color)',
          'color': '#e2e8f0',
          'font-size': '9px',
          'text-valign': 'center',
          'text-halign': 'center',
          'width': 30, 'height': 30,
          'border-width': 2,
          'border-color': '#1e293b',
        }},
        { selector: 'edge', style: {
          'width': 1.5,
          'line-color': '#475569',
          'target-arrow-color': '#6366f1',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
          'opacity': 0.6,
        }}
      ],
      layout: { name: 'cose', animate: false, padding: 20 },
    });
  } catch (e) { console.warn('Mini graph:', e); }
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

// --- Overview 3D cleanup state ---
let _overview3D = null;
let _forceGraph = null;

function _cleanupOverview3D() {
  if (_forceGraph) { try { _forceGraph._destructor(); } catch(e){} _forceGraph = null; }
  _overview3D = null;
  const c = document.getElementById('overview-agent-graph');
  if (c) c.innerHTML = '';
}

async function loadOverviewGraph() {
  try {
    const [relData, netData] = await Promise.all([
      apiFetch('/v1/agents/relationships'),
      apiFetch('/v1/agents/network'),
    ]);

    const container = document.getElementById('overview-agent-graph');
    if (!container) return;

    _cleanupOverview3D();

    const nodes = (netData?.nodes || []).filter(n => n.id !== 'Agent');
    const edges = relData?.edges || [];
    if (nodes.length === 0) { container.innerHTML = '<p class="text-center text-slate-500 py-20">No agent data</p>'; return; }

    const W = container.clientWidth || 800;
    const H = container.clientHeight || 450;

    // Position nodes in an elliptical layout
    const cx = W / 2, cy = H / 2;
    const rx = W * 0.35, ry = H * 0.3;
    const nodePositions = {};

    // Find "main"/"unknown" -> put in center
    const mainNode = nodes.find(n => n.id === 'main' || n.id === 'unknown');
    const otherNodes = nodes.filter(n => n !== mainNode);

    if (mainNode) {
      nodePositions[mainNode.id] = { x: cx, y: cy };
    }
    otherNodes.forEach((n, i) => {
      const angle = (i / otherNodes.length) * Math.PI * 2 - Math.PI / 2;
      nodePositions[n.id] = {
        x: cx + Math.cos(angle) * rx,
        y: cy + Math.sin(angle) * ry,
      };
    });

    // Build SVG
    let svg = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">`;

    // Defs: gradients, filters, animations
    svg += `<defs>
      <radialGradient id="bg-grad"><stop offset="0%" stop-color="#ffffff"/><stop offset="100%" stop-color="#f8fafc"/></radialGradient>
      <filter id="glow"><feGaussianBlur stdDeviation="4" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
      <filter id="glow-strong"><feGaussianBlur stdDeviation="8" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    </defs>`;

    // Background
    svg += `<rect width="${W}" height="${H}" fill="url(#bg-grad)"/>`;

    // Grid dots background
    for (let gx = 30; gx < W; gx += 40) {
      for (let gy = 30; gy < H; gy += 40) {
        svg += `<circle cx="${gx}" cy="${gy}" r="0.5" fill="#cbd5e1" opacity="0.3"/>`;
      }
    }

    // Draw edges (connections) with animated particles
    edges.forEach((edge, idx) => {
      const src = nodePositions[edge.source];
      const tgt = nodePositions[edge.target];
      if (!src || !tgt) return;

      const srcProfile = getAgentProfile(edge.source);
      const color = srcProfile.color || '#6366f1';

      // Curved path
      const mx = (src.x + tgt.x) / 2;
      const my = (src.y + tgt.y) / 2 - 30 - Math.random() * 20;
      const pathId = `path-${idx}`;
      const d = `M${src.x},${src.y} Q${mx},${my} ${tgt.x},${tgt.y}`;

      // Connection line (outer glow + inner)
      svg += `<path d="${d}" stroke="${color}" stroke-width="3" fill="none" opacity="0.08" filter="url(#glow-strong)"/>`;
      svg += `<path id="${pathId}" d="${d}" stroke="${color}" stroke-width="1.5" fill="none" opacity="0.25"/>`;

      // Animated particles along path
      const particleCount = 1 + (edge.count || 1);
      for (let p = 0; p < particleCount; p++) {
        const delay = (p / particleCount) * 3;
        const dur = 2.5 + Math.random() * 1.5;
        svg += `<circle r="2.5" fill="${color}" filter="url(#glow)">
          <animateMotion dur="${dur}s" repeatCount="indefinite" begin="${delay}s"><mpath href="#${pathId}"/></animateMotion>
          <animate attributeName="opacity" values="0;1;1;0" dur="${dur}s" repeatCount="indefinite" begin="${delay}s"/>
        </circle>`;
      }
    });

    // Draw nodes
    nodes.forEach(node => {
      const pos = nodePositions[node.id];
      if (!pos) return;
      const profile = getAgentProfile(node.id);
      const color = profile.color || '#6366f1';
      const isActive = node.status === 'active';
      const size = 18 + Math.min((node.trace_count || 0) / 10, 20);

      // Outer glow ring (pulsing for active)
      if (isActive) {
        svg += `<circle cx="${pos.x}" cy="${pos.y}" r="${size + 15}" fill="none" stroke="${color}" stroke-width="1" opacity="0.15">
          <animate attributeName="r" values="${size+10};${size+20};${size+10}" dur="2s" repeatCount="indefinite"/>
          <animate attributeName="opacity" values="0.1;0.25;0.1" dur="2s" repeatCount="indefinite"/>
        </circle>`;
      } else {
        svg += `<circle cx="${pos.x}" cy="${pos.y}" r="${size + 15}" fill="none" stroke="${color}" stroke-width="1" opacity="0.15"/>`;
      }

      // Second glow ring
      svg += `<circle cx="${pos.x}" cy="${pos.y}" r="${size + 8}" fill="${color}" opacity="0.06" filter="url(#glow-strong)"/>`;

      // Core circle
      svg += `<circle cx="${pos.x}" cy="${pos.y}" r="${size}" fill="${color}" opacity="0.85" filter="url(#glow)" style="cursor:pointer" onclick="filterTracesByAgent('${escHtml(node.id)}')">
        <title>${escHtml(profile.name || node.id)}: ${node.trace_count || 0} traces</title>
      </circle>`;

      // Inner highlight
      svg += `<circle cx="${pos.x - size*0.25}" cy="${pos.y - size*0.25}" r="${size*0.35}" fill="white" opacity="0.2"/>`;

      // Label
      svg += `<text x="${pos.x}" y="${pos.y + size + 18}" text-anchor="middle" fill="#1e293b" font-size="12" font-weight="600" font-family="Inter,system-ui,sans-serif">${escHtml(profile.name || node.id)}</text>`;
      svg += `<text x="${pos.x}" y="${pos.y + size + 32}" text-anchor="middle" fill="#64748b" font-size="10" font-family="Inter,system-ui,sans-serif">${node.trace_count || 0} traces \u00b7 $${(node.cost || 0).toFixed(1)}</text>`;
    });

    svg += `</svg>`;
    container.innerHTML = svg;

  } catch (e) { console.warn('Network graph:', e); }
}

