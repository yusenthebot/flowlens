# Dashboard Visualization Fix Plan

**Date:** 2026-03-14
**File:** `/Users/yusenthebot/Desktop/cowork_space/flowlens/flowlens/server/dashboard.html` (5276 lines)
**Server:** http://localhost:8585 -- confirmed healthy, all APIs returning real data.

---

## Executive Summary

The user reports: "Activity Trend chart is empty, 3D visuals not visible, bar charts and pie charts not visible."

Three distinct root causes were identified:

| Issue | Root Cause | Severity |
|-------|-----------|----------|
| Activity Trend appears empty | Canvas height collapse: `maintainAspectRatio: false` + no CSS height on parent container | HIGH |
| Bar/pie charts not visible | Charts exist ONLY in `view-cost` tab which is `hidden` on Overview | HIGH |
| 3D visuals not visible | `loadAgentGraphMini()` was gutted (line 2243-2246); full 3D only in hidden `view-agents` tab | HIGH |

**Secondary issues found:**
- Sparkline stat cards show flat zero for latency and cost (API returns `cost` not `total_cost`, and does not return `avg_duration_ms`)
- Script load order: `cytoscape-dagre` (line 18) loads before `dagre` (line 19)

---

## Issue 1: Activity Trend Chart Empty

### Evidence

- **Canvas element:** Line 687 -- `<canvas id="chart-trend" height="180"></canvas>`
- **Parent container:** Line 678 -- `<div class="glass rounded-xl p-4 mb-6">` (NO explicit CSS height)
- **Chart.js config:** Line 3882-3883 -- `responsive: true, maintainAspectRatio: false`
- **API data:** `/v1/stats/trends?hours=24&bucket_minutes=60` returns 24 buckets, 20 non-zero. Field names `traces` and `errors` match the JS code at line 3829.
- **Function called:** `loadTrendChart(24)` is called at DOMContentLoaded (line 5257) and on `switchView('overview')` (line 1629).

### Root Cause

When Chart.js `responsive: true` and `maintainAspectRatio: false`, Chart.js sizes the canvas to match its **parent container's CSS dimensions**. The parent `<div class="glass rounded-xl p-4 mb-6">` has no explicit height. Unlike the sparkline canvases (which have `style="height:45px"` on the canvas itself), `chart-trend` only has `height="180"` as an HTML attribute, which Chart.js ignores when in responsive mode.

The chart renders but at approximately 0px height -- it exists but is invisible.

### Fix

**Option A (minimal, recommended):** Wrap the canvas in a div with explicit height.

At line 687, replace:
```html
<canvas id="chart-trend" height="180"></canvas>
```
With:
```html
<div style="height:200px;position:relative"><canvas id="chart-trend"></canvas></div>
```

**Option B (alternative):** Add `style="height:200px"` to the canvas itself:
```html
<canvas id="chart-trend" style="height:200px;display:block"></canvas>
```

Option A is preferred because it follows the Chart.js recommended pattern for responsive charts.

---

## Issue 2: Bar Charts and Pie Charts Not Visible

### Evidence

- **Cost charts location:** Lines 939-984, inside `<div id="view-cost" class="view-panel hidden">`
- **Canvas IDs:** `chart-cost-trends` (line chart), `chart-cost-service` (doughnut), `chart-cost-kind` (doughnut), `chart-token-distribution` (pie), `chart-cost-name` (bar), `chart-cost-agent` (bar)
- **Data loading:** `loadCostData()` only called on `switchView('cost')` (line 1631)
- **API data:** `/v1/cost/breakdown` returns real data (747 traces, $40 cost)

### Root Cause

All cost-related charts (doughnuts, bars, pie) exist exclusively within the Cost Analysis tab (`view-cost`), which is `hidden` when the user is on the Overview tab. The Overview tab has NO charts or visualizations for cost data -- only numeric stat cards and sparklines.

### Fix

Add overview-specific mini charts to the Overview tab HTML, between the "Summary Metrics Row" (line 662) and the "Trace Volume Trend" section (line 677).

**Add new HTML after line 675** (after the Summary Metrics closing div):

```html
<!-- Overview Mini Charts -->
<div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
  <div class="glass rounded-xl p-4">
    <div class="flex items-center justify-between mb-3">
      <h2 class="text-sm font-semibold text-white">Cost by Agent</h2>
      <button onclick="switchView('cost')" class="text-[10px] text-indigo-400 hover:text-indigo-300">Details</button>
    </div>
    <div style="height:180px;position:relative"><canvas id="overview-pie-agent"></canvas></div>
  </div>
  <div class="glass rounded-xl p-4">
    <div class="flex items-center justify-between mb-3">
      <h2 class="text-sm font-semibold text-white">Traces by Agent</h2>
      <button onclick="switchView('cost')" class="text-[10px] text-indigo-400 hover:text-indigo-300">Details</button>
    </div>
    <div style="height:180px;position:relative"><canvas id="overview-bar-agent"></canvas></div>
  </div>
</div>
```

**Add new JS function** `loadOverviewCharts()`:

```javascript
async function loadOverviewCharts() {
  try {
    const breakdown = await apiFetch('/v1/cost/breakdown');
    if (!breakdown || breakdown.length === 0) return;

    // Pie chart: cost by agent/dimension
    const pieCanvas = document.getElementById('overview-pie-agent');
    if (pieCanvas) {
      if (chartInstances['overview-pie-agent']) {
        chartInstances['overview-pie-agent'].destroy();
      }
      const labels = breakdown.map(d => d.dimension || d.service_name || 'unknown');
      const costs = breakdown.map(d => d.total_cost_usd || 0);
      const colors = ['#6366f1','#8b5cf6','#a78bfa','#c4b5fd','#e0e7ff'];
      chartInstances['overview-pie-agent'] = new Chart(pieCanvas, {
        type: 'doughnut',
        data: { labels, datasets: [{ data: costs, backgroundColor: colors.slice(0, labels.length) }] },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { position: 'right', labels: { color: '#94a3b8', font: { size: 10 } } } }
        }
      });
    }

    // Bar chart: traces by agent/dimension
    const barCanvas = document.getElementById('overview-bar-agent');
    if (barCanvas) {
      if (chartInstances['overview-bar-agent']) {
        chartInstances['overview-bar-agent'].destroy();
      }
      const labels = breakdown.map(d => d.dimension || d.service_name || 'unknown');
      const traces = breakdown.map(d => d.trace_count || 0);
      chartInstances['overview-bar-agent'] = new Chart(barCanvas, {
        type: 'bar',
        data: { labels, datasets: [{ label: 'Traces', data: traces, backgroundColor: '#6366f1', borderRadius: 4 }] },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { display: false } },
            y: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { color: 'rgba(255,255,255,0.04)' }, beginAtZero: true }
          }
        }
      });
    }
  } catch (err) { console.warn('Overview charts error:', err); }
}
```

**Call it from two places:**

1. DOMContentLoaded (line 5257, after `loadTrendChart`): add `loadOverviewCharts();`
2. `switchView('overview')` (line 1629): add `loadOverviewCharts();` to the call chain

---

## Issue 3: 3D Visuals Not Visible

### Evidence

- **Mini graph function (line 2243-2246):**
  ```javascript
  async function loadAgentGraphMini() {
    // Removed -- 3D mini graph no longer shown on Overview; use Agents tab for full 3D view
    return;
  }
  ```
- **Full 3D graph:** Container at line 1052 (`<div id="agent-graph" style="width:100%;height:400px;">`) inside `view-agents` which is `hidden`.
- **Three.js CDN:** Loads successfully (HTTP 200).
- **API data:** `/v1/agents/network` returns 9 nodes and 13 edges.

### Root Cause

The `loadAgentGraphMini()` function was intentionally removed (commented out to just `return`). The full 3D agent graph renders only in the Agents tab. The user on the Overview tab sees nothing.

### Fix

**Restore the mini 3D agent graph on Overview.** Add a container in the Overview HTML after the Activity Trend chart (after line 688):

```html
<!-- Mini Agent Network -->
<div class="glass rounded-xl p-4 mb-6">
  <div class="flex items-center justify-between mb-3">
    <h2 class="text-sm font-semibold text-white">Agent Network</h2>
    <button onclick="switchView('agents')" class="text-[10px] text-indigo-400 hover:text-indigo-300">Full View</button>
  </div>
  <div id="agent-graph-mini" style="width:100%;height:250px;position:relative"></div>
</div>
```

**Restore `loadAgentGraphMini()` at line 2243.** Replace the gutted function with a working implementation that reuses the existing `buildThreeGraph()` function (defined at line 1906) but targets the `agent-graph-mini` container:

```javascript
async function loadAgentGraphMini() {
  try {
    const data = await apiFetch('/v1/agents/network');
    if (!data || !data.nodes || data.nodes.length === 0) return;
    const container = document.getElementById('agent-graph-mini');
    if (!container || container.clientWidth === 0) return;

    // Use Cytoscape for the mini view (lighter weight than Three.js)
    if (typeof cytoscape !== 'undefined') {
      _loadAgentGraphCytoscape(data, 'agent-graph-mini');
    }
  } catch (err) { console.warn('Mini agent graph error:', err); }
}
```

Note: The Cytoscape fallback function `_loadAgentGraphCytoscape` at line 2150 currently hardcodes the container ID. It needs a parameter to accept an alternative container ID, OR a separate mini version should be created. The simplest approach is to pass the container ID as a parameter.

**Call `loadAgentGraphMini()` from:**
1. DOMContentLoaded (line 5257)
2. `switchView('overview')` (line 1629)

---

## Issue 4 (Secondary): Sparkline Data Mismatch

### Evidence

Line 2481-2482:
```javascript
const latencies = buckets.map(b => b.avg_duration_ms || 0);   // FIELD DOES NOT EXIST
const costs = buckets.map(b => b.total_cost || 0);             // WRONG: field is "cost" not "total_cost"
```

API returns: `{"timestamp": ..., "traces": 7, "errors": 2, "cost": 1.5281}` -- no `avg_duration_ms`, no `total_cost`.

### Fix

Line 2482, change `b.total_cost` to `b.cost`:
```javascript
const costs = buckets.map(b => b.cost || b.total_cost || 0);
```

For latency, the trend API does not return per-bucket latency. Either:
- A) Add `avg_duration_ms` to the trend API response in the server
- B) Remove the latency sparkline or leave it as zero (current behavior, not great)

Option A is recommended. The server endpoint at `/v1/stats/trends` should include `avg_duration_ms` in each bucket.

---

## Issue 5 (Secondary): Script Load Order

### Evidence

Lines 17-19:
```html
<script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.28.1/cytoscape.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/cytoscape-dagre@2.5.0/cytoscape-dagre.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dagre@0.8.5/dist/dagre.min.js"></script>
```

`cytoscape-dagre` (line 18) depends on `dagre` (line 19) but loads before it.

### Fix

Swap lines 18 and 19:
```html
<script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.28.1/cytoscape.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dagre@0.8.5/dist/dagre.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/cytoscape-dagre@2.5.0/cytoscape-dagre.min.js"></script>
```

---

## Implementation Priority

1. **Fix trend chart height** (5 min) -- Immediate, fixes the #1 reported issue
2. **Fix sparkline cost field** (1 min) -- One-line fix
3. **Fix script load order** (1 min) -- Swap two lines
4. **Add overview mini charts** (30 min) -- New HTML + JS function for pie/bar on Overview
5. **Restore mini agent graph** (30 min) -- Restore `loadAgentGraphMini()`, add HTML container
6. **Add `avg_duration_ms` to trend API** (20 min) -- Server-side change

---

## Files to Modify

| File | Changes |
|------|---------|
| `flowlens/server/dashboard.html` | Lines 17-19 (script order), line 687 (canvas wrapper), lines 675+ (new mini charts HTML), line 2243 (restore mini graph), line 2482 (cost field fix), line 1629 (call new loaders), line 5257 (call new loaders) |
| `flowlens/server/routes.py` (or equivalent) | Add `avg_duration_ms` to trend bucket response (if implementing latency sparkline fix) |
