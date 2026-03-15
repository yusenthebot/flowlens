/* FlowLens Dashboard — Chart.js wrapper and helper functions */
'use strict';

// =========================================================================
// Chart.js Global Defaults — warm, clean aesthetic (Cycle 14)
// =========================================================================
(function applyChartDefaults() {
  if (typeof Chart === 'undefined') return;

  // Warm palette (used as default color cycle)
  const WARM_PALETTE = [
    '#6b5ce7', // warm indigo
    '#e07a5f', // coral
    '#81b29a', // sage
    '#e6a65d', // amber
    '#a78bfa', // lavender
    '#9ca3af', // warm gray
    '#f0c27f', // gold
    '#c4a882', // tan
  ];

  const isDark = () => document.documentElement.classList.contains('dark');

  // Font
  Chart.defaults.font.family = 'Inter, system-ui, sans-serif';
  Chart.defaults.font.size = 11;

  // Color
  Chart.defaults.color = '#64748b';

  // No border on chart area
  Chart.defaults.borderColor = 'transparent';

  // Animation: easeOutQuart, 600ms
  Chart.defaults.animation = { duration: 600, easing: 'easeOutQuart' };
  Chart.defaults.transitions = {
    active: { animation: { duration: 200, easing: 'easeOutQuart' } },
  };

  // Line charts: draw left-to-right using clip animation on x axis
  // Applies globally to all line charts; individual charts can override
  if (Chart.defaults.controllers && Chart.defaults.controllers.line) {
    Chart.defaults.controllers.line.clip = true;
  }

  // Doughnut/Pie: ensure rotate + scale reveal is enabled globally
  Chart.defaults.animation.animateRotate = true;
  Chart.defaults.animation.animateScale = false; // scale can look odd for doughnuts

  // Legend: bottom position, small point style instead of rectangles
  Chart.defaults.plugins.legend.position = 'bottom';
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
  Chart.defaults.plugins.legend.labels.pointStyle = 'circle';
  Chart.defaults.plugins.legend.labels.pointStyleWidth = 8;
  Chart.defaults.plugins.legend.labels.boxWidth = 8;
  Chart.defaults.plugins.legend.labels.padding = 14;
  Chart.defaults.plugins.legend.labels.font = { family: 'Inter, system-ui, sans-serif', size: 11 };

  // Tooltip: rounded, warm, backdrop blur styling
  Chart.defaults.plugins.tooltip.backgroundColor = 'rgba(26,26,24,0.96)';
  Chart.defaults.plugins.tooltip.borderColor = 'rgba(255,255,255,0.1)';
  Chart.defaults.plugins.tooltip.borderWidth = 1;
  Chart.defaults.plugins.tooltip.titleColor = '#e2e0db';
  Chart.defaults.plugins.tooltip.bodyColor = '#94a3b8';
  Chart.defaults.plugins.tooltip.cornerRadius = 10;
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.titleFont = { family: 'Inter, system-ui, sans-serif', size: 11, weight: '600' };
  Chart.defaults.plugins.tooltip.bodyFont = { family: 'Inter, system-ui, sans-serif', size: 11 };
  Chart.defaults.plugins.tooltip.displayColors = true;
  Chart.defaults.plugins.tooltip.boxWidth = 8;
  Chart.defaults.plugins.tooltip.boxHeight = 8;
  Chart.defaults.plugins.tooltip.usePointStyle = true;

  // Scales: very faint grid, no outer border
  const faintGridDark  = 'rgba(255,255,255,0.03)';
  const faintGridLight = 'rgba(0,0,0,0.03)';

  if (Chart.defaults.scales) {
    ['linear', 'category', 'logarithmic'].forEach(scaleType => {
      if (!Chart.defaults.scales[scaleType]) return;
      Chart.defaults.scales[scaleType].grid = {
        color: faintGridDark,
        drawBorder: false,
      };
      Chart.defaults.scales[scaleType].border = { display: false };
      Chart.defaults.scales[scaleType].ticks = {
        color: '#64748b',
        font: { family: 'Inter, system-ui, sans-serif', size: 10 },
      };
    });
  }

  // Expose warm palette for reuse
  window.CHART_WARM_PALETTE = WARM_PALETTE;
})();

// Helper: get theme-aware grid color
function _chartGridColor() {
  return document.documentElement.classList.contains('dark')
    ? 'rgba(255,255,255,0.03)'
    : 'rgba(0,0,0,0.03)';
}

// Helper: get theme-aware tick color
function _chartTickColor() {
  return document.documentElement.classList.contains('dark') ? '#64748b' : '#94a3b8';
}

// Helper: get theme-aware tooltip config
function _chartTooltipConfig() {
  const dark = document.documentElement.classList.contains('dark');
  return {
    backgroundColor: dark ? 'rgba(26,26,24,0.96)' : 'rgba(255,255,255,0.97)',
    borderColor: dark ? 'rgba(255,255,255,0.1)' : '#e8e6e1',
    borderWidth: 1,
    titleColor: dark ? '#e2e0db' : '#2c2c2a',
    bodyColor: dark ? '#94a3b8' : '#64748b',
    cornerRadius: 10,
    padding: 10,
    titleFont: { family: 'Inter, system-ui, sans-serif', size: 11, weight: '600' },
    bodyFont: { family: 'Inter, system-ui, sans-serif', size: 11 },
    usePointStyle: true,
    boxWidth: 8,
    boxHeight: 8,
  };
}

// =========================================================================
// Doughnut center label helper
// =========================================================================
function _addDoughnutCenterLabel(canvasId, valueText, subText) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const wrapper = canvas.parentElement;
  if (!wrapper) return;

  // Ensure wrapper is positioned
  if (getComputedStyle(wrapper).position === 'static') {
    wrapper.style.position = 'relative';
  }

  // Remove any existing label
  const existing = wrapper.querySelector('.doughnut-center-label');
  if (existing) existing.remove();

  const label = document.createElement('div');
  label.className = 'doughnut-center-label';
  label.innerHTML = `
    <div class="doughnut-center-value">${valueText}</div>
    <div class="doughnut-center-sub">${subText}</div>
  `;
  wrapper.appendChild(label);
}

// =========================================================================
async function loadOverviewCharts() {
  try {
    const summary = await apiFetch('/v1/agents/summary');
    console.log('[FlowLens] loadOverviewCharts: got', summary?.agents?.length, 'agents');
    if (!summary || !summary.agents || summary.agents.length === 0) return;
    // Prefer named agents; fall back to including 'unknown' if that's all we have
    let agents = summary.agents.filter(a => a.agent !== 'unknown');
    if (agents.length === 0) agents = summary.agents; // include unknown as fallback
    if (agents.length === 0) return;
    console.log('[FlowLens] Rendering charts for', agents.length, 'agents, costs:', agents.map(a => a.total_cost_usd));

    /** Helper: trigger chart-reveal animation on a canvas wrapper */
    function _revealChartContainer(canvasId) {
      const el = document.getElementById(canvasId);
      if (!el || !el.parentElement) return;
      const wrap = el.parentElement;
      wrap.classList.remove('chart-reveal');
      void wrap.offsetWidth; // force reflow to restart animation
      wrap.classList.add('chart-reveal');
    }

    // Doughnut: Cost by Agent — warm colors, rounded, center label
    const pieCanvas = document.getElementById('overview-pie-agent');
    if (pieCanvas) {
      if (chartInstances['overview-pie-agent']) chartInstances['overview-pie-agent'].destroy();
      const labels = agents.map(a => getAgentProfile(a.agent).name || a.agent);
      const costs = agents.map(a => a.total_cost_usd || a.total_cost || a.cost || 0);
      const totalCost = costs.reduce((s, c) => s + c, 0);
      // Warm palette: use agent colors if available, else fall back to warm palette
      const colors = agents.map((a, i) => {
        const base = getAgentProfile(a.agent).color;
        return base || (window.CHART_WARM_PALETTE || ['#6b5ce7','#e07a5f','#81b29a','#e6a65d'])[i % 8];
      });
      chartInstances['overview-pie-agent'] = new Chart(pieCanvas, {
        type: 'doughnut',
        data: { labels, datasets: [{ data: costs, backgroundColor: colors.map(c => c + 'cc'), borderColor: colors, borderWidth: 1.5, borderRadius: 4, hoverOffset: 6 }] },
        options: {
          responsive: true, maintainAspectRatio: false,
          cutout: '62%',
          plugins: {
            legend: { position: 'right', labels: { color: _chartTickColor(), font: { size: 10 }, padding: 10 } },
            tooltip: { ..._chartTooltipConfig(), callbacks: { label: ctx => ` $${costs[ctx.dataIndex].toFixed(5)}` } },
          },
          animation: { duration: 600, easing: 'easeOutQuart' },
        }
      });
      // Center label: total cost
      _addDoughnutCenterLabel('overview-pie-agent', `$${totalCost.toFixed(4)}`, 'total');
      _revealChartContainer('overview-pie-agent');
    }

    // Horizontal Bar: Traces by Agent — rounded bars, clean labels
    const barCanvas = document.getElementById('overview-bar-agent');
    if (barCanvas) {
      if (chartInstances['overview-bar-agent']) chartInstances['overview-bar-agent'].destroy();
      const labels = agents.map(a => getAgentProfile(a.agent).name || a.agent);
      const traces = agents.map(a => a.trace_count || 0);
      const colors = agents.map((a, i) => {
        const base = getAgentProfile(a.agent).color;
        return base || (window.CHART_WARM_PALETTE || ['#6b5ce7','#e07a5f'])[i % 8];
      });
      const gc = _chartGridColor();
      const tc = _chartTickColor();
      chartInstances['overview-bar-agent'] = new Chart(barCanvas, {
        type: 'bar',
        data: { labels, datasets: [{ label: 'Traces', data: traces, backgroundColor: colors.map(c => c + 'aa'), borderColor: colors, borderWidth: 1, borderRadius: 6, borderSkipped: false }] },
        options: {
          indexAxis: 'y',
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: { ..._chartTooltipConfig(), callbacks: { label: ctx => ` ${ctx.parsed.x} traces` } },
          },
          scales: {
            x: { ticks: { color: tc, font: { size: 10 } }, grid: { color: gc }, border: { display: false }, beginAtZero: true },
            y: { type: 'category', ticks: { color: tc, font: { size: 10 }, autoSkip: false }, grid: { display: false }, border: { display: false } }
          },
          animation: { duration: 600, easing: 'easeOutQuart' },
        }
      });
      _revealChartContainer('overview-bar-agent');
    }

    // Doughnut: Error Distribution — coral errors, sage success, center label
    const errCanvas = document.getElementById('overview-pie-errors');
    if (errCanvas) {
      if (chartInstances['overview-pie-errors']) chartInstances['overview-pie-errors'].destroy();
      const totalErrors = agents.reduce((s, a) => s + (a.error_count || 0), 0);
      const totalOk = Math.max(0, agents.reduce((s, a) => s + (a.trace_count || 0), 0) - totalErrors);
      const total = totalOk + totalErrors;
      chartInstances['overview-pie-errors'] = new Chart(errCanvas, {
        type: 'doughnut',
        data: {
          labels: ['Success', 'Errors'],
          datasets: [{
            data: [totalOk, totalErrors],
            backgroundColor: ['#81b29acc', '#e07a5fcc'],
            borderColor: ['#81b29a', '#e07a5f'],
            borderWidth: 1.5,
            borderRadius: 4,
            hoverOffset: 6,
          }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          cutout: '62%',
          plugins: {
            legend: { position: 'right', labels: { color: _chartTickColor(), font: { size: 10 }, padding: 10 } },
            tooltip: { ..._chartTooltipConfig() },
          },
          animation: { duration: 600, easing: 'easeOutQuart' },
        }
      });
      // Center label: success rate
      const rate = total > 0 ? ((totalOk / total) * 100).toFixed(0) + '%' : 'N/A';
      _addDoughnutCenterLabel('overview-pie-errors', rate, 'success');
      _revealChartContainer('overview-pie-errors');
    }
  } catch (err) {
    console.error('Overview charts error:', err);
    // Show a gentle placeholder — don't expose raw error to users
    const containers = ['overview-pie-agent', 'overview-bar-agent', 'overview-pie-errors'];
    containers.forEach(id => {
      const el = document.getElementById(id);
      if (el && el.parentElement) {
        el.parentElement.innerHTML = '<p style="color:#64748b;font-size:11px;padding:20px;text-align:center">No chart data yet</p>';
      }
    });
  }
}



// =========================================================================
// Sparkline Helper
// =========================================================================
// v17 Premium Feel: thin line (2px), no fill, smooth curve, no points
function renderSparkline(canvasId, data, color) {
  const canvas = document.getElementById(canvasId);
  if (!canvas || !data || !data.length) return;
  // Ensure parent has fixed dimensions to prevent Chart.js resize loops
  const parent = canvas.parentElement;
  if (parent) {
    parent.style.height = '36px';
    parent.style.position = 'relative';
  }
  // Destroy previous chart on this canvas
  if (chartInstances[canvasId]) { chartInstances[canvasId].destroy(); delete chartInstances[canvasId]; }
  chartInstances[canvasId] = new Chart(canvas, {
    type: 'line',
    data: {
      labels: data.map((_, i) => i),
      datasets: [{
        data: data,
        borderColor: color,
        backgroundColor: 'transparent',
        fill: false,
        tension: 0.45,
        pointRadius: 0,
        pointHoverRadius: 0,
        borderWidth: 1.5,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      scales: { x: { display: false }, y: { display: false, beginAtZero: true } },
      layout: { padding: { top: 2, bottom: 2 } },
    }
  });
}

/**
 * Render a tiny inline SVG sparkline (60x20px, no axes).
 * Color is sage (#81b29a) for upward trend, coral (#e07a5f) for downward.
 * @param {string} containerId - element to inject SVG into
 * @param {number[]} data - raw data array
 */
function renderSVGSparkline(containerId, data) {
  const container = document.getElementById(containerId);
  if (!container || !data || data.length < 2) return;

  const W = 60, H = 20;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;

  // Determine trend direction (last third vs first third)
  const third = Math.max(1, Math.floor(data.length / 3));
  const firstAvg = data.slice(0, third).reduce((a, b) => a + b, 0) / third;
  const lastAvg  = data.slice(-third).reduce((a, b) => a + b, 0) / third;
  const isUp = lastAvg >= firstAvg;
  const strokeColor = isUp ? '#81b29a' : '#e07a5f';  // sage up, coral down
  const fillColor   = isUp ? 'rgba(129,178,154,0.18)' : 'rgba(224,122,95,0.18)';

  // Build polyline points
  const step = (W - 2) / (data.length - 1);
  const points = data.map((v, i) => {
    const x = 1 + i * step;
    const y = H - 2 - ((v - min) / range) * (H - 4);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  // Area fill path (close to bottom)
  const areaPath = `M${points[0]} L${points.join(' L')} L${(1 + (data.length - 1) * step).toFixed(1)},${H - 1} L1,${H - 1} Z`;

  container.innerHTML = `<svg class="stat-sparkline" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <path d="${areaPath}" fill="${fillColor}" stroke="none"/>
    <polyline points="${points.join(' ')}" fill="none" stroke="${strokeColor}" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>
  </svg>`;
}

/**
 * Inject a secondary stat line below the primary number in a stat card.
 * @param {string} elId - id of the element to inject into
 * @param {string} text - secondary stat text (e.g. "avg 2.3/hr")
 */
function _setStatSecondary(elId, text) {
  let el = document.getElementById(elId);
  if (!el) return;
  el.innerHTML = `<span class="stat-secondary">${escHtml(text)}</span>`;
}

async function loadSparklines() {
  try {
    const data = await apiFetch('/v1/stats/trends?hours=24&bucket_minutes=60');
    const buckets = data.buckets || [];
    if (buckets.length === 0) return;

    const traceCounts = buckets.map(b => b.traces || b.trace_count || 0);
    const errorCounts = buckets.map(b => b.errors || b.error_count || 0);
    const latencies = buckets.map(b => b.avg_duration_ms || 0);
    const costs = buckets.map(b => b.cost || b.total_cost || 0);

    // v17 Premium Feel: thin Chart.js sparklines — no fill, smooth, no secondary text injection
    // Use card-specific accent colors (indigo, coral, amber, emerald)
    renderSparkline('sparkline-traces', traceCounts, '#6b5ce7');
    renderSparkline('sparkline-errors', errorCounts, '#e07a5f');
    renderSparkline('sparkline-latency', latencies, '#e6a65d');
    renderSparkline('sparkline-cost', costs, '#81b29a');

    // SVG sparklines still available for any containers that reference them
    renderSVGSparkline('stat-sparkline-traces', traceCounts);
    renderSVGSparkline('stat-sparkline-errors', errorCounts);
    renderSVGSparkline('stat-sparkline-latency', latencies);
    renderSVGSparkline('stat-sparkline-cost', costs);

    // v17: No secondary stat text injection — cards show only number + label + sparkline
  } catch (e) { /* sparklines are non-critical */ }
}


// Activity Timeline
// =========================================================================
async function loadActivityTimeline() {
  const container = document.getElementById('activity-timeline');
  // Show skeleton rows while loading (only when container is empty to avoid flash on refresh)
  if (container && !container.children.length) {
    container.innerHTML = [1,2,3].map(() => `
      <div class="flex items-start gap-2.5 px-4 py-2.5 border-l-2 border-slate-700">
        <div class="flex-1 space-y-1">
          <div class="skeleton skeleton-text w-48"></div>
          <div class="skeleton skeleton-warm h-1.5 w-24 rounded"></div>
        </div>
        <div class="skeleton skeleton-text w-10 flex-shrink-0"></div>
      </div>`).join('');
  }
  try {
    const data = await apiFetch('/v1/activity/stream?limit=30');
    const countEl = document.getElementById('timeline-count');

    if (!data.events || data.events.length === 0) {
      container.innerHTML = '<p class="p-4 text-xs text-slate-500">No activity yet</p>';
      countEl.textContent = '';
      return;
    }

    countEl.textContent = `${data.events.length} events`;

    // Agent color mapping (must match AGENT_PROFILES if available)
    const colors = {
      'vr-alpha': '#3b82f6', 'vr-beta': '#10b981', 'vr-gamma': '#8b5cf6',
      'vr-lead': '#f59e0b', 'vr-scribe': '#6b7280', 'main': '#6366f1',
      'Explore': '#06b6d4'
    };

    // Compute max duration for relative progress bars
    const maxDuration = data.events.reduce((max, e) => Math.max(max, e.duration_ms || 0), 1);

    container.innerHTML = data.events.map(e => {
      const color = colors[e.agent] || '#9ca3af';
      const isError = e.status === 'error';
      const statusIcon = isError
        ? '<span class="w-1.5 h-1.5 rounded-full bg-red-500 flex-shrink-0"></span>'
        : '<span class="w-1.5 h-1.5 rounded-full bg-emerald-500 flex-shrink-0"></span>';
      const dur = e.duration_ms ? `${Math.round(e.duration_ms)}ms` : '';
      const durPct = e.duration_ms ? Math.max(4, (e.duration_ms / maxDuration) * 100) : 0;
      const timeAgo = typeof formatTimeAgo === 'function' ? formatTimeAgo(e.timestamp) : '--';
      const errorText = isError && e.error ? `<div class="text-[9px] text-red-400 truncate mt-0.5">${escHtml(e.error.substring(0, 80))}</div>` : '';
      const errorClass = isError ? ' activity-error' : '';

      // Determine pill style based on tool/kind
      const toolLower = (e.tool || '').toLowerCase();
      let pillClass = 'activity-pill-default';
      if (toolLower.includes('llm') || toolLower.includes('chat') || toolLower.includes('completion') || toolLower.includes('gpt') || toolLower.includes('claude')) pillClass = 'activity-pill-llm';
      else if (toolLower.includes('tool') || toolLower.includes('bash') || toolLower.includes('read') || toolLower.includes('write') || toolLower.includes('grep') || toolLower.includes('glob') || toolLower.includes('edit')) pillClass = 'activity-pill-tool';
      else if (toolLower.includes('agent') || toolLower.includes('spawn') || toolLower.includes('delegate')) pillClass = 'activity-pill-agent';

      const durationBar = durPct > 0 ? `<div class="activity-duration-bar"><div class="activity-duration-fill" style="width:${durPct}%"></div></div>` : '';

      return `
        <div class="activity-event-row flex items-start gap-2.5 px-4 py-2.5 hover:bg-white/[0.02] transition cursor-pointer${errorClass}" style="border-left:3px solid ${color}" onclick="openTrace('${escHtml(e.trace_id || '')}')">
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-1.5 flex-wrap">
              ${statusIcon}
              <span class="text-[10px] font-medium" style="color:${color}">${escHtml(e.agent)}</span>
              <span class="text-[10px] text-slate-500">&rarr;</span>
              <span class="activity-pill ${pillClass}">${escHtml(e.tool)}</span>
              ${dur ? `<span class="text-[10px] text-slate-600 ml-auto font-mono">${dur}</span>` : ''}
            </div>
            ${errorText}
            ${durationBar}
          </div>
          <span class="text-[9px] text-slate-600 flex-shrink-0 mt-0.5">${timeAgo}</span>
        </div>`;
    }).join('');
  } catch (e) {
    // Non-critical — show placeholder if container is empty
    const container = document.getElementById('activity-timeline');
    if (container && !container.children.length) {
      container.innerHTML = '<p class="p-4 text-xs text-slate-600 italic">Activity unavailable</p>';
    }
  }
}


// =========================================================================
// Trace Volume Trend Chart
// =========================================================================
let _trendHours = 24; // Currently active window

async function loadTrendChart(hours) {
  _trendHours = hours;
  console.log('[FlowLens] loadTrendChart called with hours=' + hours);

  // Update button active states
  document.querySelectorAll('.trend-btn').forEach(btn => {
    btn.classList.remove('active');
    // Reset to inactive styling
    btn.className = 'trend-btn px-2 py-1 text-[10px] rounded bg-surface-100 text-slate-400 hover:text-white transition';
  });
  // Find and activate the clicked button
  document.querySelectorAll('.trend-btn').forEach(btn => {
    if (btn.getAttribute('onclick') === `loadTrendChart(${hours})`) {
      btn.className = 'trend-btn px-2 py-1 text-[10px] rounded bg-indigo-500/20 text-indigo-300 active';
    }
  });

  const bucketMinutes = hours <= 6 ? 10 : hours <= 24 ? 60 : 360;
  let data;
  try {
    data = await apiFetch(`/v1/stats/trends?hours=${hours}&bucket_minutes=${bucketMinutes}`);
  } catch (err) {
    console.warn('Trend chart: API not available, using empty data');
    data = { buckets: [] };
  }

  const buckets = data.buckets || [];

  // Show fallback message if no data
  if (!buckets || buckets.length === 0 || buckets.every(b => (b.traces || b.trace_count || 0) === 0)) {
    const canvas = document.getElementById('chart-trend');
    if (canvas) {
      const container = canvas.parentElement;
      // Remove any previous fallback message
      const existing = container.querySelector('.trend-no-data');
      if (existing) existing.remove();
      const msg = document.createElement('p');
      msg.className = 'trend-no-data text-center text-sm text-slate-500 py-8';
      msg.textContent = 'No activity trend data available. Start tracing to see trends.';
      container.appendChild(msg);
    }
    return;
  }

  // Remove any previous fallback message if data now exists
  const trendContainer = document.getElementById('chart-trend')?.parentElement;
  if (trendContainer) {
    const oldMsg = trendContainer.querySelector('.trend-no-data');
    if (oldMsg) oldMsg.remove();
  }

  // Format time labels
  function formatTrendLabel(ts) {
    const d = new Date(ts * 1000);
    if (hours <= 24) {
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
    }
    return d.toLocaleDateString([], { weekday: 'short' });
  }

  const labels = buckets.map(b => formatTrendLabel(b.timestamp || b.bucket_start || 0));
  const traceCounts = buckets.map(b => b.traces || b.trace_count || 0);
  const errorCounts = buckets.map(b => b.errors || b.error_count || 0);

  // Destroy existing chart if present
  if (chartInstances['chart-trend']) {
    chartInstances['chart-trend'].destroy();
    delete chartInstances['chart-trend'];
  }

  const canvas = document.getElementById('chart-trend');
  if (!canvas) return;

  // Build canvas gradient for Traces dataset — indigo fading to transparent
  const ctx = canvas.getContext('2d');
  const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height || 200);
  gradient.addColorStop(0, 'rgba(107,92,231,0.30)');
  gradient.addColorStop(0.6, 'rgba(107,92,231,0.08)');
  gradient.addColorStop(1, 'rgba(107,92,231,0.00)');

  const gc = _chartGridColor();
  const tc = _chartTickColor();
  const tt = _chartTooltipConfig();

  chartInstances['chart-trend'] = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Traces',
          data: traceCounts,
          borderColor: '#6b5ce7',
          backgroundColor: gradient,
          fill: true,
          tension: 0.4,
          pointRadius: 0,         // no dots by default
          pointHoverRadius: 5,
          pointHoverBackgroundColor: '#6b5ce7',
          pointHoverBorderColor: '#fff',
          pointHoverBorderWidth: 2,
          borderWidth: 2.5,
          borderCapStyle: 'round',
          borderJoinStyle: 'round',
        },
        {
          label: 'Errors',
          data: errorCounts,
          borderColor: '#e07a5f',
          backgroundColor: 'transparent',
          fill: false,
          tension: 0.4,
          borderDash: [5, 4],
          pointRadius: 0,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: '#e07a5f',
          pointHoverBorderColor: '#fff',
          pointHoverBorderWidth: 2,
          borderWidth: 1.5,
          borderCapStyle: 'round',
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
          labels: {
            color: tc,
            font: { family: 'Inter, system-ui, sans-serif', size: 10 },
            padding: 12,
            usePointStyle: true,
            pointStyle: 'circle',
            pointStyleWidth: 7,
          }
        },
        tooltip: { ...tt },
      },
      scales: {
        x: {
          ticks: { color: tc, font: { size: 10 }, maxTicksLimit: 8 },
          grid: { color: gc },
          border: { display: false },
        },
        y: {
          ticks: { color: tc, font: { size: 10 }, stepSize: 1, precision: 0 },
          grid: { color: gc },
          border: { display: false },
          beginAtZero: true,
        }
      },
      // Draw line left-to-right: stagger dataset animations
      animation: { duration: 700, easing: 'easeOutQuart' },
      animations: {
        x: {
          type: 'number',
          easing: 'easeOutQuart',
          duration: 700,
          from: NaN,
          delay(ctx) {
            if (ctx.type !== 'data' || ctx.xStarted) return 0;
            ctx.xStarted = true;
            return ctx.datasetIndex * 120;
          },
        },
      },
    }
  });
  // Trigger chart container reveal animation
  if (canvas && canvas.parentElement) {
    const wrap = canvas.parentElement;
    wrap.classList.remove('chart-reveal');
    void wrap.offsetWidth;
    wrap.classList.add('chart-reveal');
  }
}

// =========================================================================

// =========================================================================
// Cost Analysis
// =========================================================================
async function loadCostData() {
  // Show skeleton loading state in summary cards area before data arrives
  const summaryCardsEl = document.getElementById('cost-summary-cards');
  if (summaryCardsEl) {
    summaryCardsEl.innerHTML = [1,2,3,4].map(() => `
      <div class="cost-summary-card">
        <div class="skeleton skeleton-warm h-8 w-20 mb-2 rounded"></div>
        <div class="skeleton skeleton-warm skeleton-text w-16"></div>
      </div>`).join('');
  }

  try {
    const [byService, byKind, byName, agentSummary, costTrends, optimization, tracesData] = await Promise.all([
      apiFetch('/v1/cost/breakdown?group_by=service_name').catch(() => []),
      apiFetch('/v1/cost/breakdown?group_by=kind').catch(() => []),
      apiFetch('/v1/cost/breakdown?group_by=name').catch(() => []),
      apiFetch('/v1/agents/summary').catch(() => ({ agents: [] })),
      apiFetch('/v1/cost/trends?granularity=daily&limit=30').catch(() => []),
      apiFetch('/v1/cost/optimization').catch(() => null),
      apiFetch('/v1/traces?limit=50').catch(() => ({ traces: [] })),
    ]);

    // Render cost summary cards
    _renderCostSummaryCards(byService, byKind, costTrends);

    // Render cost over time line chart
    _renderCostTrendsChart(costTrends, 'daily');

    // Load forecast section (async, non-blocking)
    if (typeof loadCostForecast === 'function') {
      loadCostForecast().catch(e => console.warn('Forecast load error:', e));
    }

    // Refresh budget bar with latest spend data
    if (typeof _refreshBudgetBar === 'function') {
      _refreshBudgetBar().catch(() => {});
    }

    renderCostChart('chart-cost-service', byService, 'doughnut');
    renderCostChart('chart-cost-kind', byKind, 'doughnut');
    renderCostChart('chart-cost-name', byName, 'bar');
    renderAgentCostChart('chart-cost-agent', agentSummary.agents || []);

    // Render token distribution pie chart
    _renderTokenDistributionChart(byKind);

    // Enhanced: Cost by Model breakdown
    if (optimization && optimization.by_model) {
      _renderModelCostChart('chart-cost-model', optimization.by_model);
    }

    // Enhanced: Top 5 most expensive traces
    _renderTopExpensiveTraces(tracesData.traces || []);

    // Enhanced: Optimization suggestions
    _renderOptimizationSuggestions(optimization);

    updateRefreshTime();
  } catch (err) {
    console.error('Cost load error:', err);
    // Show user-friendly error in summary cards area
    if (summaryCardsEl) {
      summaryCardsEl.innerHTML = `
        <div class="col-span-full flex items-center gap-2 py-4 text-sm text-red-400/80">
          <svg class="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
          Failed to load cost data${err && err.message ? ': ' + err.message : ''}. Check server connection.
        </div>`;
    }
  }
}

function _renderModelCostChart(canvasId, byModel) {
  if (chartInstances[canvasId]) { chartInstances[canvasId].destroy(); delete chartInstances[canvasId]; }
  const canvas = document.getElementById(canvasId);
  if (!canvas || !byModel) return;

  // byModel may be an object {model_name: {cost, tokens, count}} or an array
  let modelArray;
  if (Array.isArray(byModel)) {
    modelArray = byModel;
  } else if (typeof byModel === 'object') {
    modelArray = Object.entries(byModel).map(([model, data]) => ({
      model,
      total_cost_usd: data.cost || data.total_cost_usd || 0,
      total_tokens: data.tokens || data.total_tokens || 0,
      count: data.count || 0,
    }));
  } else {
    return;
  }
  if (modelArray.length === 0) return;

  const sorted = [...modelArray].sort((a, b) => (b.count || b.total_cost_usd || 0) - (a.count || a.total_cost_usd || 0));
  const labels = sorted.map(m => m.model || m.dimension || 'unknown');
  const costs = sorted.map(m => m.total_cost_usd || m.cost || 0);
  const tokens = sorted.map(m => m.total_tokens || m.tokens || 0);

  // Warm color palette for models
  const MODEL_COLORS = ['#6b5ce7', '#e07a5f', '#81b29a', '#e6a65d', '#a78bfa', '#9ca3af'];
  const colors = labels.map((_, i) => MODEL_COLORS[i % MODEL_COLORS.length] + 'cc');
  const borders = labels.map((_, i) => MODEL_COLORS[i % MODEL_COLORS.length]);
  const tc = _chartTickColor();
  const tt = _chartTooltipConfig();
  const counts = sorted.map(m => m.count || 0);

  // Use call counts as chart data when all costs are zero (common for span-level model tracking)
  const hasCostData = costs.some(c => c > 0);
  const chartData = hasCostData ? costs : counts;

  chartInstances[canvasId] = new Chart(canvas.getContext('2d'), {
    type: 'doughnut',
    data: { labels, datasets: [{ data: chartData, backgroundColor: colors, borderColor: borders, borderWidth: 1.5, borderRadius: 4, hoverOffset: 8 }] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '62%',
      plugins: {
        legend: { position: 'right', labels: { color: tc, font: { family: 'Inter, system-ui, sans-serif', size: 10 }, padding: 10, usePointStyle: true, pointStyle: 'circle' } },
        tooltip: {
          ...tt,
          callbacks: {
            label: (ctx) => {
              const idx = ctx.dataIndex;
              const total = chartData.reduce((s, c) => s + c, 0);
              const pct = total > 0 ? ((chartData[idx] / total) * 100).toFixed(1) : 0;
              const costStr = `$${costs[idx].toFixed(6)}`;
              const callStr = `${counts[idx].toLocaleString()} calls`;
              return hasCostData
                ? ` ${costStr} (${pct}%) | ${tokens[idx].toLocaleString()} tokens`
                : ` ${callStr} (${pct}%) | ${costStr}`;
            }
          }
        }
      },
      animation: { duration: 600, easing: 'easeOutQuart' },
    }
  });
  // Center label: total cost, or total call count if costs are all zero
  const modelTotal = costs.reduce((s, c) => s + c, 0);
  const totalCalls = sorted.reduce((s, m) => s + (m.count || 0), 0);
  if (modelTotal > 0) {
    _addDoughnutCenterLabel(canvasId, `$${modelTotal.toFixed(4)}`, 'total');
  } else if (totalCalls > 0) {
    _addDoughnutCenterLabel(canvasId, totalCalls.toLocaleString(), 'calls');
  } else {
    _addDoughnutCenterLabel(canvasId, `$${modelTotal.toFixed(4)}`, 'total');
  }
}

function _renderTopExpensiveTraces(traces) {
  const container = document.getElementById('cost-top-traces');
  if (!container) return;

  // Sort by cost descending; fall back to duration
  const sorted = [...traces]
    .filter(t => t.total_cost_usd > 0 || t.cost > 0)
    .sort((a, b) => ((b.total_cost_usd || b.cost || 0) - (a.total_cost_usd || a.cost || 0)));

  if (sorted.length === 0) {
    container.innerHTML = '<p class="text-xs text-slate-500 italic py-2">No cost data available for traces yet.</p>';
    return;
  }

  const top5 = sorted.slice(0, 5);
  const maxCost = top5[0].total_cost_usd || top5[0].cost || 0;

  container.innerHTML = top5.map((t, i) => {
    const cost = t.total_cost_usd || t.cost || 0;
    const barPct = maxCost > 0 ? ((cost / maxCost) * 100).toFixed(1) : 0;
    const agent = (t.tags && t.tags.agent) || t.agent || 'unknown';
    const shortId = (t.trace_id || '').substring(0, 8);
    const durationStr = t.duration_ms ? (t.duration_ms < 1000 ? t.duration_ms.toFixed(0) + 'ms' : (t.duration_ms / 1000).toFixed(2) + 's') : '--';
    const isError = t.has_errors === true || t.has_errors === 1;

    return `
      <div class="flex items-center gap-3 py-2 border-b border-white/5 last:border-0 group cursor-pointer hover:bg-white/[0.02] transition rounded px-1"
           onclick="typeof openTrace === 'function' ? openTrace('${escHtml(t.trace_id)}') : null">
        <span class="text-[11px] text-slate-600 tabular-nums w-4 flex-shrink-0">#${i + 1}</span>
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-1.5 mb-0.5">
            <span class="text-[11px] text-slate-300 font-mono truncate">${shortId}...</span>
            ${isError ? '<span class="w-1.5 h-1.5 rounded-full bg-red-500 flex-shrink-0"></span>' : ''}
            <span class="text-[10px] text-slate-600 ml-auto flex-shrink-0">${durationStr}</span>
          </div>
          <div class="flex items-center gap-1.5">
            <span class="text-[10px] text-slate-600">${escHtml(agent)}</span>
            <div class="flex-1 h-1.5 rounded overflow-hidden" style="background:rgba(255,255,255,0.05)">
              <div class="h-full rounded" style="width:${barPct}%;background:linear-gradient(90deg,#7c7aef,#9b8ec4)"></div>
            </div>
          </div>
        </div>
        <span class="text-xs font-semibold text-emerald-400 tabular-nums flex-shrink-0 group-hover:text-emerald-300 transition">$${cost.toFixed(5)}</span>
        <svg class="w-3 h-3 text-slate-600 flex-shrink-0 opacity-0 group-hover:opacity-100 transition" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
      </div>`;
  }).join('');
}

function _renderOptimizationSuggestions(optimization) {
  const container = document.getElementById('cost-optimization-tips');
  if (!container) return;

  if (!optimization || !optimization.suggestions || optimization.suggestions.length === 0) {
    container.innerHTML = `
      <div class="flex items-center gap-2 py-3">
        <svg class="w-4 h-4 text-emerald-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
        <span class="text-xs text-slate-400">No optimization opportunities detected — usage looks efficient.</span>
      </div>`;
    return;
  }

  const totalSavings = optimization.total_estimated_monthly_savings_usd || 0;
  const suggestions = optimization.suggestions.slice(0, 5);

  const headerHtml = totalSavings > 0 ? `
    <div class="flex items-center gap-2 mb-3 p-2.5 rounded-lg" style="background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.2)">
      <svg class="w-4 h-4 text-emerald-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/></svg>
      <span class="text-xs text-emerald-300">Estimated monthly savings: <strong>$${totalSavings.toFixed(4)}</strong></span>
    </div>` : '';

  const TIP_ICONS = {
    model: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>',
    context: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>',
    retry: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>',
    default: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>',
  };

  const tipsHtml = suggestions.map(s => {
    // API returns: type, description, span_name, model, suggested_model, estimated_monthly_savings_usd
    const rawTitle = s.title || s.suggestion || (s.type === 'model_switch' ? `Switch ${s.model} → ${s.suggested_model}` : s.type === 'caching' ? `Cache "${s.span_name}"` : 'Optimization tip');
    const title = escHtml(rawTitle);
    const detail = escHtml(s.detail || s.description || '');
    const savings = s.estimated_monthly_savings_usd ? `<span class="text-[10px] text-emerald-400 font-semibold">~$${Number(s.estimated_monthly_savings_usd).toFixed(4)}/mo</span>` : '';
    const category = (s.type || s.category || '').toLowerCase();
    const iconKey = category.includes('model') ? 'model' : category.includes('cach') ? 'retry' : category.includes('context') ? 'context' : 'default';
    const iconPath = TIP_ICONS[iconKey] || TIP_ICONS.default;
    return `
      <div class="flex items-start gap-2.5 py-2.5 border-b border-white/5 last:border-0">
        <div class="w-6 h-6 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5" style="background:rgba(99,102,241,0.12)">
          <svg class="w-3.5 h-3.5 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">${iconPath}</svg>
        </div>
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="text-xs font-semibold text-white">${title}</span>
            ${savings}
          </div>
          ${detail ? `<p class="text-[11px] text-slate-400 mt-0.5 leading-relaxed">${detail}</p>` : ''}
        </div>
      </div>`;
  }).join('');

  container.innerHTML = headerHtml + tipsHtml;
}

function _renderCostSummaryCards(byService, byKind, trends) {
  const container = document.getElementById('cost-summary-cards');
  if (!container) return;

  const totalCost = (byService || []).reduce((s, d) => s + (d.total_cost_usd || 0), 0);
  const totalTokens = (byService || []).reduce((s, d) => s + (d.total_tokens || 0), 0);
  const totalTraces = (byService || []).reduce((s, d) => s + (d.trace_count || 0), 0);
  const avgCostPerTrace = totalTraces > 0 ? totalCost / totalTraces : 0;

  container.innerHTML = `
    <div class="cost-summary-card card-fade-in">
      <div class="card-value text-emerald-400">$${totalCost.toFixed(4)}</div>
      <div class="card-label text-slate-400">Total Cost</div>
    </div>
    <div class="cost-summary-card card-fade-in">
      <div class="card-value text-white">${totalTokens.toLocaleString()}</div>
      <div class="card-label text-slate-400">Total Tokens</div>
    </div>
    <div class="cost-summary-card card-fade-in">
      <div class="card-value text-indigo-400">${totalTraces.toLocaleString()}</div>
      <div class="card-label text-slate-400">Traces</div>
    </div>
    <div class="cost-summary-card card-fade-in">
      <div class="card-value text-amber-400">$${avgCostPerTrace.toFixed(6)}</div>
      <div class="card-label text-slate-400">Avg Cost/Trace</div>
    </div>
  `;
}

function _renderCostTrendsChart(trends, granularity) {
  const canvasId = 'chart-cost-trends';
  if (chartInstances[canvasId]) { chartInstances[canvasId].destroy(); delete chartInstances[canvasId]; }

  const canvas = document.getElementById(canvasId);
  if (!canvas || !trends || trends.length === 0) {
    if (canvas) {
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#475569'; ctx.font = '14px Inter'; ctx.textAlign = 'center';
      ctx.fillText('No cost trend data available', canvas.width / 2, canvas.height / 2);
    }
    return;
  }

  const labels = trends.map(t => {
    const bucket = t.bucket || '';
    if (granularity === 'hourly') {
      const parts = bucket.split('T');
      return parts.length > 1 ? parts[1].substring(0, 5) : bucket;
    }
    return bucket.substring(5); // MM-DD
  });
  const costs = trends.map(t => t.total_cost_usd || 0);
  const tokens = trends.map(t => t.total_tokens || 0);

  const ctx = canvas.getContext('2d');
  const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height || 256);
  gradient.addColorStop(0, 'rgba(107,92,231,0.28)');
  gradient.addColorStop(0.65, 'rgba(107,92,231,0.06)');
  gradient.addColorStop(1, 'rgba(107,92,231,0.00)');

  const gc = _chartGridColor();
  const tc = _chartTickColor();
  const tt = _chartTooltipConfig();

  chartInstances[canvasId] = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: 'Cost (USD)',
        data: costs,
        borderColor: '#6b5ce7',
        backgroundColor: gradient,
        fill: true,
        tension: 0.4,
        pointRadius: 0,
        pointHoverRadius: 5,
        pointHoverBackgroundColor: '#6b5ce7',
        pointHoverBorderColor: '#fff',
        pointHoverBorderWidth: 2,
        borderWidth: 2.5,
        borderCapStyle: 'round',
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          ...tt,
          callbacks: {
            label: (item) => ` $${costs[item.dataIndex].toFixed(6)} | ${tokens[item.dataIndex].toLocaleString()} tokens`
          }
        }
      },
      scales: {
        x: { ticks: { color: tc, font: { size: 10 }, maxRotation: 45 }, grid: { color: gc }, border: { display: false } },
        y: { ticks: { color: tc, font: { size: 10 }, callback: v => '$' + v.toFixed(4) }, grid: { color: gc }, border: { display: false } },
      },
      animation: { duration: 600, easing: 'easeOutQuart' },
    }
  });
}

async function loadCostTrends(granularity) {
  // Update button styles
  document.querySelectorAll('.cost-trend-btn').forEach(btn => {
    if (btn.dataset.granularity === granularity) {
      btn.className = 'cost-trend-btn px-2.5 py-1 text-[10px] rounded bg-indigo-500/20 text-indigo-300 font-medium border border-indigo-500/30 transition';
    } else {
      btn.className = 'cost-trend-btn px-2.5 py-1 text-[10px] rounded bg-surface-100 text-slate-400 hover:text-white border border-white/10 hover:border-white/20 transition';
    }
  });

  try {
    const limit = granularity === 'hourly' ? 48 : 30;
    const trends = await apiFetch(`/v1/cost/trends?granularity=${granularity}&limit=${limit}`);
    _renderCostTrendsChart(trends, granularity);
  } catch (err) {
    console.warn('Cost trends unavailable:', err.message || err);
    // Show fallback on canvas
    const canvas = document.getElementById('chart-cost-trends');
    if (canvas) {
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = '#475569';
      ctx.font = '13px Inter, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('Cost trend data unavailable', canvas.width / 2, canvas.height / 2);
    }
  }
}

function _renderTokenDistributionChart(byKind) {
  const canvasId = 'chart-token-distribution';
  if (chartInstances[canvasId]) { chartInstances[canvasId].destroy(); delete chartInstances[canvasId]; }

  const canvas = document.getElementById(canvasId);
  if (!canvas || !byKind || byKind.length === 0) {
    if (canvas) {
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#475569'; ctx.font = '14px Inter'; ctx.textAlign = 'center';
      ctx.fillText('No token data available', canvas.width / 2, canvas.height / 2);
    }
    return;
  }

  // Aggregate input vs output tokens
  let totalInput = 0, totalOutput = 0;
  byKind.forEach(d => {
    totalInput += d.input_tokens || 0;
    totalOutput += d.output_tokens || 0;
  });

  // If no separate input/output data, estimate from total tokens
  if (totalInput === 0 && totalOutput === 0) {
    const totalTokens = byKind.reduce((s, d) => s + (d.total_tokens || 0), 0);
    totalInput = Math.round(totalTokens * 0.6);
    totalOutput = totalTokens - totalInput;
  }

  if (totalInput === 0 && totalOutput === 0) {
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#475569'; ctx.font = '14px Inter'; ctx.textAlign = 'center';
    ctx.fillText('No token data available', canvas.width / 2, canvas.height / 2);
    return;
  }

  const tt = _chartTooltipConfig();
  chartInstances[canvasId] = new Chart(canvas.getContext('2d'), {
    type: 'doughnut',
    data: {
      labels: ['Input Tokens', 'Output Tokens'],
      datasets: [{
        data: [totalInput, totalOutput],
        backgroundColor: ['#6b5ce7cc', '#81b29acc'],
        borderColor: ['#6b5ce7', '#81b29a'],
        borderWidth: 1.5,
        borderRadius: 4,
        hoverOffset: 8,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '62%',
      plugins: {
        legend: {
          position: 'right',
          labels: { color: _chartTickColor(), font: { family: 'Inter, system-ui, sans-serif', size: 11 }, padding: 12 },
        },
        tooltip: {
          ...tt,
          callbacks: {
            label: (ctx) => {
              const total = totalInput + totalOutput;
              const pct = total > 0 ? ((ctx.parsed / total) * 100).toFixed(1) : 0;
              return ` ${ctx.parsed.toLocaleString()} tokens (${pct}%)`;
            }
          }
        }
      },
      animation: { duration: 600, easing: 'easeOutQuart' },
    }
  });
  // Center label: total tokens
  const totalToks = totalInput + totalOutput;
  _addDoughnutCenterLabel(canvasId, totalToks >= 1000 ? (totalToks / 1000).toFixed(1) + 'K' : String(totalToks), 'tokens');
}

function renderAgentCostChart(canvasId, agents) {
  if (chartInstances[canvasId]) { chartInstances[canvasId].destroy(); delete chartInstances[canvasId]; }

  const canvas = document.getElementById(canvasId);
  const summaryEl = document.getElementById('cost-agent-summary');
  if (!canvas || !agents || agents.length === 0) {
    if (canvas) {
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#475569';
      ctx.font = '14px Inter';
      ctx.textAlign = 'center';
      ctx.fillText('No agent cost data available', canvas.width / 2, canvas.height / 2);
    }
    if (summaryEl) summaryEl.textContent = '';
    return;
  }

  // Update summary label
  const totalAgentCost = agents.reduce((s, a) => s + (a.total_cost_usd || 0), 0);
  if (summaryEl) summaryEl.textContent = `${agents.length} agents | $${totalAgentCost.toFixed(4)} total`;

  // Sort agents by cost descending
  const sorted = [...agents].sort((a, b) => (b.total_cost_usd || 0) - (a.total_cost_usd || 0));
  const labels = sorted.map(a => a.agent);
  const costs = sorted.map(a => a.total_cost_usd || 0);

  // Use agent profile colors if available
  const agentColorMap = {
    'vr-alpha': '#3b82f6', 'vr-beta': '#10b981', 'vr-gamma': '#8b5cf6',
    'vr-lead': '#f59e0b', 'vr-scribe': '#6b7280', 'main': '#6366f1',
    'Explore': '#06b6d4'
  };
  // Create gradient fills per agent bar
  const ctx2d = canvas.getContext('2d');
  const barColors = labels.map(l => {
    const baseColor = agentColorMap[l] || '#9b8ec4';
    const grad = ctx2d.createLinearGradient(0, 0, canvas.width || 600, 0);
    grad.addColorStop(0, baseColor + 'dd');
    grad.addColorStop(1, baseColor + '44');
    return grad;
  });
  const borderColors = labels.map(l => agentColorMap[l] || '#9b8ec4');

  const gc = _chartGridColor();
  const tc = _chartTickColor();
  const tt = _chartTooltipConfig();

  chartInstances[canvasId] = new Chart(ctx2d, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'Cost (USD)',
        data: costs,
        backgroundColor: barColors,
        borderColor: borderColors,
        borderWidth: 1,
        borderRadius: 6,
        borderSkipped: false,
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          ...tt,
          callbacks: {
            label: (ctx) => ` $${costs[ctx.dataIndex].toFixed(6)}`
          }
        }
      },
      scales: {
        x: { ticks: { color: tc, font: { size: 10 }, callback: v => '$' + v.toFixed(4) }, grid: { color: gc }, border: { display: false } },
        y: { ticks: { color: tc, font: { size: 11 } }, grid: { display: false }, border: { display: false } },
      },
      animation: { duration: 600, easing: 'easeOutQuart' },
    }
  });
}

// Warm chart color palette (fallback for generic charts)
const CHART_COLORS = ['#6b5ce7', '#e07a5f', '#81b29a', '#e6a65d', '#a78bfa', '#9ca3af', '#f0c27f', '#c4a882'];

function renderCostChart(canvasId, data, type) {
  if (chartInstances[canvasId]) { chartInstances[canvasId].destroy(); delete chartInstances[canvasId]; }

  const canvas = document.getElementById(canvasId);
  if (!canvas || !data || data.length === 0) {
    if (canvas) {
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#475569';
      ctx.font = '14px Inter';
      ctx.textAlign = 'center';
      ctx.fillText('No cost data available', canvas.width / 2, canvas.height / 2);
    }
    return;
  }

  const labels = data.map(d => d.dimension || 'unknown');
  const costs = data.map(d => d.total_cost_usd || 0);
  const tokens = data.map(d => d.total_tokens || 0);

  // Create gradient for bar charts
  let barBg = CHART_COLORS[0] + '80';
  if (type === 'bar') {
    const ctx = canvas.getContext('2d');
    const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height || 288);
    gradient.addColorStop(0, CHART_COLORS[0] + 'cc');
    gradient.addColorStop(1, CHART_COLORS[0] + '33');
    barBg = gradient;
  }

  // Better doughnut colors with slight transparency for depth
  const doughnutColors = CHART_COLORS.slice(0, labels.length).map(c => c + 'dd');
  const doughnutBorders = CHART_COLORS.slice(0, labels.length);

  const gc = _chartGridColor();
  const tc = _chartTickColor();
  const tt = _chartTooltipConfig();

  const chartConfig = {
    type,
    data: {
      labels,
      datasets: [{
        label: 'Cost (USD)',
        data: costs,
        backgroundColor: type === 'doughnut' ? doughnutColors : barBg,
        borderColor: type === 'doughnut' ? doughnutBorders : CHART_COLORS[0],
        borderWidth: type === 'doughnut' ? 1.5 : 1,
        borderRadius: type === 'bar' ? 6 : 4,
        borderSkipped: false,
        hoverOffset: type === 'doughnut' ? 8 : 0,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: type === 'doughnut' ? '62%' : undefined,
      plugins: {
        legend: {
          display: type === 'doughnut',
          position: 'right',
          labels: { color: tc, font: { family: 'Inter, system-ui, sans-serif', size: 11 }, padding: 12 },
        },
        tooltip: {
          ...tt,
          callbacks: {
            label: (ctx) => {
              const idx = ctx.dataIndex;
              return ` $${costs[idx].toFixed(6)} | ${tokens[idx].toLocaleString()} tokens`;
            }
          }
        }
      },
      scales: type === 'bar' ? {
        x: { ticks: { color: tc, font: { size: 10 } }, grid: { color: gc }, border: { display: false } },
        y: { ticks: { color: tc, font: { size: 10 }, callback: v => '$' + v.toFixed(4) }, grid: { color: gc }, border: { display: false } },
      } : undefined,
      animation: { duration: 600, easing: 'easeOutQuart' },
    }
  };

  chartInstances[canvasId] = new Chart(canvas.getContext('2d'), chartConfig);
}

