/* FlowLens Dashboard — Chart.js wrapper and helper functions */
'use strict';


async function loadOverviewCharts() {
  try {
    const summary = await apiFetch('/v1/agents/summary');
    console.log('[FlowLens] loadOverviewCharts: got', summary?.agents?.length, 'agents');
    if (!summary || !summary.agents || summary.agents.length === 0) return;
    const agents = summary.agents.filter(a => a.agent !== 'unknown'); // Skip unknown for cleaner charts
    if (agents.length === 0) return;
    console.log('[FlowLens] Rendering charts for', agents.length, 'agents, costs:', agents.map(a => a.total_cost_usd));

    // Doughnut: Cost by Agent
    const pieCanvas = document.getElementById('overview-pie-agent');
    if (pieCanvas) {
      if (chartInstances['overview-pie-agent']) chartInstances['overview-pie-agent'].destroy();
      const labels = agents.map(a => getAgentProfile(a.agent).name || a.agent);
      const costs = agents.map(a => a.total_cost_usd || a.total_cost || a.cost || 0);
      const colors = agents.map(a => getAgentProfile(a.agent).color || '#6366f1');
      chartInstances['overview-pie-agent'] = new Chart(pieCanvas, {
        type: 'doughnut',
        data: { labels, datasets: [{ data: costs, backgroundColor: colors }] },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { position: 'right', labels: { color: '#94a3b8', font: { size: 10 } } } }
        }
      });
    }

    // Horizontal Bar: Traces by Agent
    const barCanvas = document.getElementById('overview-bar-agent');
    if (barCanvas) {
      if (chartInstances['overview-bar-agent']) chartInstances['overview-bar-agent'].destroy();
      const labels = agents.map(a => getAgentProfile(a.agent).name || a.agent);
      const traces = agents.map(a => a.trace_count || 0);
      const colors = agents.map(a => getAgentProfile(a.agent).color || '#6366f1');
      chartInstances['overview-bar-agent'] = new Chart(barCanvas, {
        type: 'bar',
        data: { labels, datasets: [{ label: 'Traces', data: traces, backgroundColor: colors, borderRadius: 4 }] },
        options: {
          indexAxis: 'y',
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.04)' }, beginAtZero: true },
            y: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { display: false } }
          }
        }
      });
    }

    // Doughnut: Error Distribution
    const errCanvas = document.getElementById('overview-pie-errors');
    if (errCanvas) {
      if (chartInstances['overview-pie-errors']) chartInstances['overview-pie-errors'].destroy();
      const totalErrors = agents.reduce((s, a) => s + (a.error_count || 0), 0);
      const totalOk = agents.reduce((s, a) => s + (a.trace_count || 0), 0) - totalErrors;
      chartInstances['overview-pie-errors'] = new Chart(errCanvas, {
        type: 'doughnut',
        data: {
          labels: ['Success', 'Errors'],
          datasets: [{ data: [Math.max(0, totalOk), totalErrors], backgroundColor: ['#10b981', '#ef4444'] }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { position: 'right', labels: { color: '#94a3b8', font: { size: 10 } } } }
        }
      });
    }
  } catch (err) {
    console.error('Overview charts error:', err);
    // Show error visually
    const containers = ['overview-pie-agent', 'overview-bar-agent', 'overview-pie-errors'];
    containers.forEach(id => {
      const el = document.getElementById(id);
      if (el && el.parentElement) {
        el.parentElement.innerHTML = '<p style="color:#ef4444;font-size:11px;padding:20px;text-align:center">Chart error: ' + (err.message || err) + '</p>';
      }
    });
  }
}



// =========================================================================
// Sparkline Helper
// =========================================================================
function renderSparkline(canvasId, data, color) {
  const canvas = document.getElementById(canvasId);
  if (!canvas || !data || !data.length) return;
  // Ensure parent has fixed dimensions to prevent Chart.js resize loops
  const parent = canvas.parentElement;
  if (parent) {
    parent.style.height = '40px';
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
        backgroundColor: color + '30',
        fill: true,
        tension: 0.4,
        pointRadius: 0,
        borderWidth: 2,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      scales: { x: { display: false }, y: { display: false, beginAtZero: true } },
    }
  });
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

    renderSparkline('sparkline-traces', traceCounts, '#6366f1');
    renderSparkline('sparkline-errors', errorCounts, '#ef4444');
    renderSparkline('sparkline-latency', latencies, '#f59e0b');
    renderSparkline('sparkline-cost', costs, '#10b981');
  } catch (e) { /* sparklines are non-critical */ }
}


// Activity Timeline
// =========================================================================
async function loadActivityTimeline() {
  try {
    const data = await apiFetch('/v1/activity/stream?limit=30');
    const container = document.getElementById('activity-timeline');
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
  } catch (e) { /* silently fail */ }
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

  // Build canvas gradient for Traces dataset
  const ctx = canvas.getContext('2d');
  const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height);
  gradient.addColorStop(0, 'rgba(99, 102, 241, 0.25)');
  gradient.addColorStop(1, 'rgba(99, 102, 241, 0.01)');

  const isDark = document.documentElement.classList.contains('dark');
  const gridColor = isDark ? 'rgba(255,255,255,0.04)' : 'rgba(0,0,0,0.06)';
  const tickColor = isDark ? '#64748b' : '#94a3b8';

  chartInstances['chart-trend'] = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Traces',
          data: traceCounts,
          borderColor: 'rgba(99, 102, 241, 0.8)',
          backgroundColor: gradient,
          fill: true,
          tension: 0.4,
          pointRadius: 2,
          pointHoverRadius: 5,
          borderWidth: 2,
        },
        {
          label: 'Errors',
          data: errorCounts,
          borderColor: '#ef4444',
          backgroundColor: 'transparent',
          fill: false,
          tension: 0.4,
          borderDash: [5, 4],
          pointRadius: 2,
          pointHoverRadius: 5,
          borderWidth: 1.5,
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
            color: tickColor,
            font: { family: 'Inter', size: 10 },
            boxWidth: 24,
            padding: 8,
            usePointStyle: true,
            pointStyleWidth: 8,
          }
        },
        tooltip: {
          backgroundColor: isDark ? 'rgba(42,42,40,0.95)' : 'rgba(255,255,255,0.97)',
          borderColor: isDark ? 'rgba(255,255,255,0.1)' : '#e8e6e1',
          borderWidth: 1,
          titleColor: isDark ? '#e2e0db' : '#2c2c2a',
          bodyColor: isDark ? '#94a3b8' : '#64748b',
          titleFont: { family: 'Inter', size: 11 },
          bodyFont: { family: 'Inter', size: 11 },
        }
      },
      scales: {
        x: {
          ticks: { color: tickColor, font: { size: 10 }, maxTicksLimit: 8 },
          grid: { color: gridColor },
          border: { color: gridColor },
        },
        y: {
          ticks: { color: tickColor, font: { size: 10 }, stepSize: 1, precision: 0 },
          grid: { color: gridColor },
          border: { color: gridColor },
          beginAtZero: true,
        }
      }
    }
  });
}

// =========================================================================

// =========================================================================
// Cost Analysis
// =========================================================================
async function loadCostData() {
  try {
    const [byService, byKind, byName, agentSummary, costTrends] = await Promise.all([
      apiFetch('/v1/cost/breakdown?group_by=service_name'),
      apiFetch('/v1/cost/breakdown?group_by=kind'),
      apiFetch('/v1/cost/breakdown?group_by=name'),
      apiFetch('/v1/agents/summary').catch(() => ({ agents: [] })),
      apiFetch('/v1/cost/trends?granularity=daily&limit=30').catch(() => []),
    ]);

    // Render cost summary cards
    _renderCostSummaryCards(byService, byKind, costTrends);

    // Render cost over time line chart
    _renderCostTrendsChart(costTrends, 'daily');

    renderCostChart('chart-cost-service', byService, 'doughnut');
    renderCostChart('chart-cost-kind', byKind, 'doughnut');
    renderCostChart('chart-cost-name', byName, 'bar');
    renderAgentCostChart('chart-cost-agent', agentSummary.agents || []);

    // Render token distribution pie chart
    _renderTokenDistributionChart(byKind);

    updateRefreshTime();
  } catch (err) {
    console.error('Cost load error:', err);
  }
}

function _renderCostSummaryCards(byService, byKind, trends) {
  const container = document.getElementById('cost-summary-cards');
  if (!container) return;

  const totalCost = (byService || []).reduce((s, d) => s + (d.total_cost_usd || 0), 0);
  const totalTokens = (byService || []).reduce((s, d) => s + (d.total_tokens || 0), 0);
  const totalTraces = (byService || []).reduce((s, d) => s + (d.trace_count || 0), 0);
  const avgCostPerTrace = totalTraces > 0 ? totalCost / totalTraces : 0;

  container.innerHTML = `
    <div class="cost-summary-card">
      <div class="card-value text-emerald-400">$${totalCost.toFixed(4)}</div>
      <div class="card-label text-slate-400">Total Cost</div>
    </div>
    <div class="cost-summary-card">
      <div class="card-value text-white">${totalTokens.toLocaleString()}</div>
      <div class="card-label text-slate-400">Total Tokens</div>
    </div>
    <div class="cost-summary-card">
      <div class="card-value text-indigo-400">${totalTraces.toLocaleString()}</div>
      <div class="card-label text-slate-400">Traces</div>
    </div>
    <div class="cost-summary-card">
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
  gradient.addColorStop(0, 'rgba(124, 122, 239, 0.25)');
  gradient.addColorStop(1, 'rgba(124, 122, 239, 0.02)');

  chartInstances[canvasId] = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: 'Cost (USD)',
        data: costs,
        borderColor: '#7c7aef',
        backgroundColor: gradient,
        fill: true,
        tension: 0.3,
        pointRadius: 3,
        pointHoverRadius: 6,
        pointBackgroundColor: '#7c7aef',
        pointBorderColor: '#1e1b4b',
        pointBorderWidth: 2,
        borderWidth: 2,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (item) => ` $${costs[item.dataIndex].toFixed(6)} | ${tokens[item.dataIndex].toLocaleString()} tokens`
          }
        }
      },
      scales: {
        x: { ticks: { color: '#64748b', font: { size: 10 }, maxRotation: 45 }, grid: { color: 'rgba(255,255,255,0.03)' } },
        y: { ticks: { color: '#64748b', font: { size: 10 }, callback: v => '$' + v.toFixed(4) }, grid: { color: 'rgba(255,255,255,0.03)' } },
      }
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
    console.error('Cost trends error:', err);
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

  chartInstances[canvasId] = new Chart(canvas.getContext('2d'), {
    type: 'doughnut',
    data: {
      labels: ['Input Tokens', 'Output Tokens'],
      datasets: [{
        data: [totalInput, totalOutput],
        backgroundColor: ['#6366f1', '#10b981'],
        borderWidth: 0,
        hoverOffset: 8,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '60%',
      plugins: {
        legend: {
          position: 'right',
          labels: { color: '#94a3b8', font: { family: 'Inter', size: 11 }, padding: 12 },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const total = totalInput + totalOutput;
              const pct = total > 0 ? ((ctx.parsed / total) * 100).toFixed(1) : 0;
              return ` ${ctx.parsed.toLocaleString()} tokens (${pct}%)`;
            }
          }
        }
      }
    }
  });
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
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => ` $${costs[ctx.dataIndex].toFixed(6)}`
          }
        }
      },
      scales: {
        x: { ticks: { color: '#64748b', font: { size: 10 }, callback: v => '$' + v.toFixed(4) }, grid: { color: 'rgba(255,255,255,0.03)' } },
        y: { ticks: { color: '#94a3b8', font: { size: 11 } }, grid: { color: 'rgba(255,255,255,0.03)' } },
      }
    }
  });
}

const CHART_COLORS = ['#9b8ec4', '#7ab5a0', '#c49a5c', '#7a9eb5', '#c47070', '#b5a082', '#a88ec4', '#c4b07a'];

function renderCostChart(canvasId, data, type) {
  if (chartInstances[canvasId]) { chartInstances[canvasId].destroy(); }

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

  const chartConfig = {
    type,
    data: {
      labels,
      datasets: [{
        label: 'Cost (USD)',
        data: costs,
        backgroundColor: type === 'doughnut' ? doughnutColors : barBg,
        borderColor: type === 'doughnut' ? doughnutBorders : CHART_COLORS[0],
        borderWidth: type === 'doughnut' ? 1 : 1,
        borderRadius: type === 'bar' ? 6 : 0,
        hoverOffset: type === 'doughnut' ? 8 : 0,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: type === 'doughnut',
          position: 'right',
          labels: { color: '#94a3b8', font: { family: 'Inter', size: 11 }, padding: 12 },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const idx = ctx.dataIndex;
              return ` $${costs[idx].toFixed(6)} | ${tokens[idx].toLocaleString()} tokens`;
            }
          }
        }
      },
      scales: type === 'bar' ? {
        x: { ticks: { color: '#64748b', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.03)' } },
        y: { ticks: { color: '#64748b', font: { size: 10 }, callback: v => '$' + v.toFixed(4) }, grid: { color: 'rgba(255,255,255,0.03)' } },
      } : undefined,
    }
  };

  chartInstances[canvasId] = new Chart(canvas.getContext('2d'), chartConfig);
}

