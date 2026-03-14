# Task Board — FlowLens Development

## Cycle 2: Complete (2026-03-14)

### Done (2026-03-14)
- [x] **Configurable pattern detection thresholds** — Alpha — 6 env var fields in config.py, all detect_*() updated — Commit a8047ce — `flowlens/config.py`, `flowlens/analysis/patterns.py`
- [x] **LocalCollector + LocalExporter** — Beta — Thread-safe SQLite access without HTTP, query/ingest/search/pagination/stats methods — Commit d3ebcff — `flowlens/local.py`, `flowlens/sdk/exporters.py`
- [x] **Agent observability dashboard** — Gamma — New "Agents" tab with card grid, color-coded error rates, click-to-filter — Commit 5181d89 — `flowlens/server/app.py`, `flowlens/server/dashboard.html`
- [x] **Agent summary API** — Gamma — /v1/agents/summary endpoint groups stats by tags.agent — Commit 5181d89 — `flowlens/server/app.py`
- [x] **LocalCollector stress tests** — Beta — 35 test cases, 10-thread concurrent ingest + read+write — Commit d3ebcff — `tests/test_local_collector.py`
- [x] **Pattern config tests** — Alpha — 84 lines test_config.py, 119 lines test_analysis.py — Commit a8047ce — `tests/test_config.py`, `tests/test_analysis.py`
- [x] **Agent summary API tests** — Gamma — 5 test cases covering grouping, sort, empty DB, fallback, error rate — Commit 5181d89 — `tests/test_server.py`

## Cycle 3: Backlog (proposed)

### In Progress
None

### Backlog
- [ ] **Performance benchmarks** — Priority: high — Suggested agent: Any — Estimate: 1.5 days — LocalCollector concurrent ingest benchmark (target: 10k ops/sec), memory profiling
- [ ] **Graceful degradation for exporter failures** — Priority: high — Suggested agent: Gamma — Estimate: 1 day — Circuit breaker pattern for exporter timeouts without losing traces
- [ ] **Pattern threshold validation** — Priority: medium — Suggested agent: Alpha — Estimate: 0.5 day — Reject negative/invalid config values, document env var ranges
- [ ] **Agent dashboard advanced filtering** — Priority: medium — Suggested agent: Gamma — Estimate: 1 day — Filter by error rate threshold, latency threshold, time range
- [ ] **ML-based anomaly detection** — Priority: low — Suggested agent: Any — Estimate: 3+ days — Statistical anomaly detection on span metrics, configurable sensitivity
- [ ] **Runtime error handling review** — Priority: medium — Suggested agent: Lead — Estimate: 1 day — Follow up on any issues reported from 1025 test suite, document edge cases
- [ ] **Production deployment runbook** — Priority: high — Suggested agent: Scribe — Estimate: 1 day — Finalize docs/deployment.md, env var reference, scaling guidance

## Legend
- `[x]` = done (date)
- `[ ]` = backlog
- Agent = responsible developer
- Estimate = story points or days
- Priority = critical/high/medium/low
