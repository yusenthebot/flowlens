# Task Board — FlowLens Development

## PROJECT COMPLETE — 2026-03-14

All planned improvements delivered. All tasks closed. System production-ready.

---

## Cycle 3: Complete (2026-03-14) — FINAL CYCLE

### Done (2026-03-14)
- [x] **Budget alerts with cost_total metric** — Alpha — Cumulative cost tracking field + budget-aware alerting — Commit 88c2582 — `flowlens/alerting/*`
- [x] **AND compound conditions in alerting** — Alpha — Extended alert condition parser to support AND operators (`&&` / `AND`) — Commit 88c2582 — `flowlens/alerting/*`
- [x] **FTS5 full-text search** — Beta — Schema v6 migration, spans_fts virtual table, FTS MATCH queries — Commit 7706c8f — `flowlens/storage/schema.py`, `flowlens/storage/storage.py`
- [x] **FTS search LIKE fallback** — (Fix) — Two-tier search (FTS MATCH → LIKE fallback) for robust edge case handling — Commit a63dfb1 — `flowlens/storage/storage.py`
- [x] **Schema v6 test validation** — (Fix) — Updated schema version test to v6, validated migration path — Commit a63dfb1 — `tests/test_storage.py`

---

## Cycle 2: Complete (2026-03-14)

### Done (2026-03-14)
- [x] **Configurable pattern detection thresholds** — Alpha — 6 env var fields in config.py, all detect_*() updated — Commit a8047ce — `flowlens/config.py`, `flowlens/analysis/patterns.py`
- [x] **LocalCollector + LocalExporter** — Beta — Thread-safe SQLite access without HTTP, query/ingest/search/pagination/stats methods — Commit d3ebcff — `flowlens/local.py`, `flowlens/sdk/exporters.py`
- [x] **Agent observability dashboard** — Gamma — New "Agents" tab with card grid, color-coded error rates, click-to-filter — Commit 5181d89 — `flowlens/server/app.py`, `flowlens/server/dashboard.html`
- [x] **Agent summary API** — Gamma — /v1/agents/summary endpoint groups stats by tags.agent — Commit 5181d89 — `flowlens/server/app.py`
- [x] **LocalCollector stress tests** — Beta — 35 test cases, 10-thread concurrent ingest + read+write — Commit d3ebcff — `tests/test_local_collector.py`
- [x] **Pattern config tests** — Alpha — 84 lines test_config.py, 119 lines test_analysis.py — Commit a8047ce — `tests/test_config.py`, `tests/test_analysis.py`
- [x] **Agent summary API tests** — Gamma — 5 test cases covering grouping, sort, empty DB, fallback, error rate — Commit 5181d89 — `tests/test_server.py`

---

## Cycle 1: Complete (2026-03-14)

### Done (2026-03-14)
- [x] **WebSocket route handling** — Alpha — Fixed /ws/traces 404 by skipping HTTP middleware for WS upgrades — Commit 4e8f9d4 — `flowlens/server/app.py`
- [x] **Thread-safe exporters** — Gamma — Added `threading.Lock` to JSONLExporter, CSVExporter, JSONLStreamExporter — Commit c05f1b6 — `flowlens/sdk/exporters.py`
- [x] **Configurable HTTP timeout** — Gamma — HTTPExporter timeout_sec parameter (default 30s) — Commit c05f1b6 — `flowlens/sdk/exporters.py`
- [x] **FK constraint resilience** — Beta — Force trace_id consistency to prevent foreign key failures — Commit 70b94c8 — `flowlens/storage/storage.py`
- [x] **Improved model cost matching** — Beta — Longest-match-first strategy instead of substring — Commit 70b94c8 — `flowlens/analysis/cost.py`
- [x] **Edge case tests** — All — 69 lines test_storage_edge.py, 153 lines test_exporters.py — Commits 70b94c8, c05f1b6 — `tests/test_storage_edge.py`, `tests/test_exporters.py`

---

## Archive: Cycle Backlog (Considered for Future)

The following tasks were proposed for future cycles but are deprioritized given project completion:

- [ ] **Performance benchmarks** — Priority: high — LocalCollector concurrent ingest benchmark (target: 10k ops/sec), memory profiling
- [ ] **Graceful degradation for exporter failures** — Priority: high — Circuit breaker pattern for exporter timeouts without losing traces
- [ ] **Pattern threshold validation** — Priority: medium — Reject negative/invalid config values, document env var ranges
- [ ] **Agent dashboard advanced filtering** — Priority: medium — Filter by error rate threshold, latency threshold, time range
- [ ] **ML-based anomaly detection** — Priority: low — Statistical anomaly detection on span metrics, configurable sensitivity
- [ ] **Production deployment runbook** — Priority: high — Finalize docs/deployment.md, env var reference, scaling guidance
- [ ] **Kubernetes operator** — Priority: low — Custom resource definitions, controller, scaling policies
- [ ] **Trace sampling strategies** — Priority: medium — Probabilistic, head-based, tail-based sampling with rate limiting
- [ ] **Documentation website (mkdocs)** — Priority: medium — Auto-generated API docs, architecture guides, troubleshooting
- [ ] **PyPI publishing** — Priority: medium — Package distribution, releases, versioning strategy

---

## Legend

- `[x]` = done (date in Cycle header)
- `[ ]` = backlog / deferred
- Agent = responsible developer (Alpha, Beta, Gamma, Scribe)
- Priority = critical/high/medium/low
- Status: Project Complete — All planned deliverables closed
