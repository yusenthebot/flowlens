# Task Board — FlowLens Development

## Cycle 13: In Progress (2026-03-14) — ACTIONABLE INTELLIGENCE

### In Progress

- [ ] **Sessions API endpoint** — Alpha — Priority: high — /v1/sessions groups traces by session_id tag; returns session metadata (ID, agent count, trace count, duration, error count, cost). New query pattern: fetch all traces with matching session_id tag — `flowlens/server/app.py`

- [ ] **Sessions tab UI** — Alpha — Priority: high — New dashboard tab showing session cards: session ID, agent involvement breakdown, span/error counts, cost per session, time range (start/end). Session cards are clickable for detail drill-down — `flowlens/server/dashboard.html`, `flowlens/server/static/sessions.js`, `flowlens/server/static/sessions.css`

- [ ] **Session timeline detail view** — Alpha — Priority: high — Click session to view vertical timeline of traces within that session, showing execution order and inter-trace timing gaps. Waterfall-style visualization similar to trace detail but at session level — `flowlens/server/static/sessions.js`

- [ ] **Session filtering** — Alpha — Priority: medium — Filter by agent (multi-select), status (all-pass / has-error), cost range, date range. Client-side filters with server-side API parameter support for persistence — `flowlens/server/static/sessions.js`

- [ ] **Session export** — Alpha — Priority: medium — Export session details (JSON/CSV) with all related traces for offline analysis and sharing — `flowlens/server/app.py`, `flowlens/server/static/sessions.js`

- [ ] **Star rating system** — Beta — Priority: high — 1-5 star rating per trace (default: no rating), persistent in SQLite. Add star_rating (int, 1-5, nullable) column to traces table (v7 schema migration) — `flowlens/storage/schema.py`, `flowlens/storage/storage.py`

- [ ] **Trace comment field** — Beta — Priority: high — Free-text comment per trace (max 500 chars) for notes about trace quality, expected behavior, debugging observations. Add feedback_comment (text, nullable) column to traces table — `flowlens/storage/schema.py`, `flowlens/storage/storage.py`

- [ ] **Feedback aggregation API** — Beta — Priority: high — /v1/traces/:id/feedback GET/POST endpoints, includes rating, comment, modified_at timestamp. Persist and retrieve feedback efficiently — `flowlens/server/app.py`

- [ ] **Feedback UI in trace detail panel** — Beta — Priority: high — Star rating widget (interactive 1-5 stars) + comment editor below trace metadata in detail panel, quick-edit inline, auto-save on change — `flowlens/server/dashboard.html`, `flowlens/server/static/traces.js`

- [ ] **Feedback filter for Traces tab** — Beta — Priority: medium — Filter Traces tab by star rating (1-5 stars, or "unrated"), enables rapid access to problematic/exemplary traces. Client-side with server support — `flowlens/server/static/traces.js`

- [ ] **Feedback statistics display** — Beta — Priority: medium — Trace card shows average rating badge (★★★★☆ 4.2) for quick visual scanning. Aggregate feedback counts in trace list — `flowlens/server/dashboard.html`, `flowlens/server/static/traces.js`

- [ ] **Cost forecast model** — Gamma — Priority: high — Analyze 24h cost trend data, extrapolate to monthly projection (assume steady state), compute confidence interval based on variance. New /v1/cost/forecast endpoint — `flowlens/server/app.py`

- [ ] **Budget progress bar** — Gamma — Priority: high — Visual indicator of budget spent vs limit, color-coded (green: <70%, yellow: 70-90%, red: >90%), projected end-of-month status shown explicitly. New card on Cost tab — `flowlens/server/dashboard.html`, `flowlens/server/static/cost.js`, `flowlens/server/static/cost.css`

- [ ] **Cost-by-model breakdown chart** — Gamma — Priority: high — Pie/donut chart showing cost contribution by model (GPT-4, GPT-3.5, Claude, etc.), top-3 drivers highlighted. New /v1/cost/by-model endpoint — `flowlens/server/app.py`, `flowlens/server/dashboard.html`, `flowlens/server/static/cost.js`

- [ ] **Optimization quick-wins detection** — Gamma — Priority: high — Query cost data to identify: high-cost retries (>2 retries per trace), N+1 patterns (>5 spans from same agent in <100ms), high token count (>2000), suggest batch size increase. New /v1/cost/quick-wins endpoint — `flowlens/server/app.py`

- [ ] **Monthly projection card** — Gamma — Priority: medium — Show projected month-end cost with warning if >110% of budget, updated hourly. Display on Overview or Cost tab — `flowlens/server/dashboard.html`, `flowlens/server/static/cost.js`

- [ ] **Cost anomaly detection** — Gamma — Priority: medium — Spike alert if hourly cost >2σ above daily average. WebSocket notification on spike — `flowlens/server/app.py`, `flowlens/server/static/cost.js`

- [ ] **Integration testing for Session, Feedback, and Cost features** — All — Priority: high — E2E tests verifying session timeline, feedback persistence, cost forecast accuracy. Performance benchmarking (session query <100ms, feedback UI <50ms) — `tests/test_server.py`, new E2E test files

- [ ] **Schema v7 migration** — Beta — Priority: high — Migrate traces table from v6 to v7, add star_rating and feedback_comment columns. Validate existing data integrity — `flowlens/storage/schema.py`, `flowlens/storage/storage.py`

---

## Cycle 12: Complete (2026-03-14) — DASHBOARD USABILITY

### Done (2026-03-14)
- [x] **Overview stat cards with trend indicators + time window selector** — Beta — Added `setStatsWindow()` function with "1h / 24h / All" toggle buttons above stat cards; `renderTrend()` helper shows ↑/↓ percentage arrows (green=up, red=down) in Traces and Cost cards by comparing current vs previous equal window using `/v1/stats/trends`; `stats-window-label` updates to show active window name — `flowlens/server/static/dashboard.js`, `flowlens/server/dashboard.html`
- [x] **Live activity feed on Overview** — Beta — `addToLiveFeed()` + `renderLiveFeed()` functions maintain a circular buffer of 15 events; each WebSocket `trace_ingested` event pushes an entry (agent avatar, action, status dot, relative timestamp); feed displays in a compact panel alongside Live Monitor; `live-activity-feed` container in dashboard.html — `flowlens/server/static/dashboard.js`, `flowlens/server/static/websocket.js`, `flowlens/server/dashboard.html`
- [x] **Light theme comprehensive fixes** — Beta — Added 80+ CSS rules in dashboard.css covering: notification panel (`.notif-title`, `.notif-msg`, `.notif-time`), live feed (`.live-feed-time`, `.live-feed-action`), empty state (`.empty-state-*`), agents grid, agent detail modal, waterfall timeline, trace detail meta panel — `flowlens/server/static/dashboard.css`
- [x] **Improved empty state with getting-started guide** — Beta — `renderEmptyState()` now shows a 3-step card: install (`pip install flowlens`), instrument (3-line code example), demo (`flowlens demo --dashboard`); theme-aware styling via CSS custom classes; docs and examples links — `flowlens/server/static/dashboard.js`

---

## Cycle 11: Complete (2026-03-14) — APP.PY MODULARIZATION

### Done (2026-03-14)
- [x] **app.py route modularization** — Beta — Refactored 2003-line monolithic app.py into focused route modules: routes/traces.py (15 endpoints), routes/cost.py (5 endpoints), routes/agents.py (5 endpoints), routes/stats.py (9 endpoints), routes/alerts.py (5 endpoints), routes/system.py (5 endpoints); shared utils.py with security helpers and _AGENT_PROFILES — Commit 7af0433 — `flowlens/server/app.py`, `flowlens/server/utils.py`, `flowlens/server/routes/`

---

## Cycle 10: In Progress (2026-03-14) — DASHBOARD PERFORMANCE & MODULARIZATION

### In Progress

- [ ] **SVG-based agent network visualization** — Alpha — Priority: high — Replace Three.js WebGL 3D rendering with lightweight SVG network using animated particles, glow effects, pulsing nodes, curved connections. Lazy-load Three.js as fallback. Target: 60-70% reduction in initial load time. Files: `flowlens/server/dashboard.html`, new `flowlens/server/network.js`

- [ ] **Dashboard.html modularization** — Beta — Priority: high — Refactor 5664-line monolithic HTML into modular structure: separate CSS files (overview.css, traces.css, agents.css, compare.css, network.css, patterns.css, costs.css) + JS modules (api.js, views.js, events.js, utils.js). Reduce main HTML to ~500 lines. Improve code organization and reduce merge conflicts. Files: `flowlens/server/dashboard.html`, new CSS/JS files

- [ ] **Integration testing for modularized dashboard** — Alpha, Beta — Priority: high — E2E tests verifying all tabs work correctly after modularization; performance benchmarking (load time, render FPS, memory usage)

- [ ] **Performance benchmarking baseline** — Beta — Priority: medium — Measure load time, FPS, memory usage before/after refactoring; document in cycle report

---

## Cycle 9: Complete (2026-03-14) — VISUAL ENHANCEMENTS & LIVE MONITORING

### Done (2026-03-14)
- [x] **Sparklines in stat cards** — Lead — Lightweight SVG path approximation mini trend-lines in Overview stat cards (Traces, Spans, Errors, Latency, Cost) rendering in <1ms per card for at-a-glance visual context — Commit 4587523 — `flowlens/server/dashboard.html`
- [x] **Activity feed styling enhancements** — Lead — Redesigned activity timeline with colored left borders per-agent (matching AGENT_PROFILES colors), pill-shaped status badges (active/idle/error), improved typography and spacing — Commit 4587523 — `flowlens/server/dashboard.html`
- [x] **Dark gradient background** — Lead — Updated Overview background from solid dark to gradient (#1a1a18→#0f0f0e) for subtle visual depth improvement — Commit 4587523 — `flowlens/server/dashboard.html`
- [x] **Agent graph CSS fallback strategy** — Lead — Agent network graph gracefully falls back to Cytoscape.js if Three.js CDN fails; ensures dashboard usability with CDN unavailability — Commit 4587523 — `flowlens/server/dashboard.html`
- [x] **Cost chart enhancements** — Lead — Dual-axis visualization for cost trends (primary: cost, secondary: count) for better volume correlation — Commit 4587523 — `flowlens/server/dashboard.html`
- [x] **Compact overview layout** — Alpha — Denser agent strip (removed padding), removed mini 3D graph (#agent-graph-mini) for performance, expanded trend chart height/width, summary metrics row (Active Now, Ops/1h, Success Rate) — Commit d0f8849 — `flowlens/server/dashboard.html`
- [x] **Live Agent Monitor widget** — Beta — Real-time agent status updates via WebSocket, flash highlighting (0.5s pulse) on state changes, connection status indicator, auto-reconnect on disconnect for on-call observability — Commit 0e97e3b — `flowlens/server/dashboard.html`, `flowlens/server/app.py`
- [x] **Three.js CDN rollback** — Fix — Downgraded Three.js CDN from 0.162.0→0.160.0 with local fallback for browser compatibility — Commit ab7f295 — `flowlens/server/dashboard.html`
- [x] **Dashboard version footer** — Chore — Updated footer version to v1.0.0, adjusted compact layout height — Commit d58d1c7 — `flowlens/server/dashboard.html`

---

## Archive: Cycle Backlog (Deferred for Future)

The following tasks were proposed for future cycles but are deprioritized given project completion:

- [ ] **ML-based anomaly detection** — Priority: high — Statistical anomaly detection on span metrics, configurable sensitivity, built on /v1/stats/trends API
- [ ] **Trace sampling strategies** — Priority: medium — Probabilistic, head-based, tail-based sampling with rate limiting
- [ ] **Kubernetes operator** — Priority: low — Custom resource definitions, controller, scaling policies
- [ ] **Documentation website (mkdocs)** — Priority: medium — Auto-generated API docs, architecture guides, troubleshooting
- [ ] **PyPI publishing** — Priority: medium — Package distribution, releases, versioning strategy
- [ ] **Performance benchmarks** — Priority: medium — LocalCollector concurrent ingest benchmark (target: 10k ops/sec), memory profiling
- [ ] **Graceful degradation for exporter failures** — Priority: medium — Circuit breaker pattern for exporter timeouts without losing traces
- [ ] **Pattern threshold validation** — Priority: low — Reject negative/invalid config values, document env var ranges
- [ ] **Agent dashboard advanced filtering** — Priority: low — Filter by error rate threshold, latency threshold, time range
- [ ] **Production deployment runbook** — Priority: high — Finalize docs/deployment.md, env var reference, scaling guidance

---

## Metrics Summary

| Metric | Value |
|--------|-------|
| Total Cycles | 13 |
| Total Commits | 50+ (Cycle 13 in progress) |
| Total Features | 45+ (Cycle 13 in progress) |
| Total Tests | 1071 |
| Test Pass Rate | 100% |
| Lines Added | ~4500 (source + tests, through Cycle 12) |
| Active Blockers | 0 |
| File Conflicts | 0 (Alpha, Beta, Gamma coordinating on app.py and dashboard sections) |
| Deployment Status | Production-ready (v1.0.0, enhanced with Cycle 13) |
| Project Duration | 1 day (12 complete cycles, Cycle 13 in progress) |

---

## Legend

- `[x]` = done (date in Cycle header)
- `[ ]` = in progress / backlog / deferred
- Agent = responsible developer (Lead, Alpha, Beta, Gamma)
- Priority = critical/high/medium/low
- Status: 12 cycles complete, Cycle 13 in progress — Actionable Intelligence with session timeline, feedback, and cost forecasting in active development
