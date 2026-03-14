# Task Board — FlowLens Development

## Cycle 1: Complete (2026-03-14)

### Done (2026-03-14)
- [x] **WebSocket /ws/traces 404 fix** — Alpha — HTTP middleware scope check — Commit 4e8f9d4 — `flowlens/server/app.py`
- [x] **FK constraint failures** — Beta — Force trace_id consistency in storage.py — Commit 70b94c8 — `flowlens/server/storage.py`
- [x] **Model cost matching** — Beta — Longest-match-first instead of substring — Commit 70b94c8 — `flowlens/sdk/models.py`
- [x] **Thread-safe JSONLExporter** — Gamma — Added threading.Lock — Commit c05f1b6 — `flowlens/sdk/exporters.py`
- [x] **Thread-safe CSVExporter** — Gamma — Added threading.Lock — Commit c05f1b6 — `flowlens/sdk/exporters.py`
- [x] **Thread-safe JSONLStreamExporter** — Gamma — Added threading.Lock — Commit c05f1b6 — `flowlens/sdk/exporters.py`
- [x] **HTTPExporter timeout config** — Gamma — Made timeout_sec configurable (default 30s) — Commit c05f1b6 — `flowlens/sdk/exporters.py`
- [x] **Storage edge case tests** — Beta — 69 lines new tests — Commit 70b94c8 — `tests/test_storage_edge.py`
- [x] **Exporter thread safety tests** — Gamma — 153 lines new tests — Commit c05f1b6 — `tests/test_exporters.py`
- [x] **Model cost matching tests** — Beta — 28 lines additions — Commit 70b94c8 — `tests/test_models.py`
- [x] **Server routing tests** — Alpha — 11 lines additions — Commit 4e8f9d4 — `tests/test_server.py`

## Cycle 2: Backlog (proposed)

### In Progress
None

### Backlog
- [ ] **Graceful degradation for exporter failures** — Priority: high — Suggested agent: Gamma — Estimate: 1 day — Design pattern for handling exporter timeouts without losing traces
- [ ] **Performance benchmarks** — Priority: medium — Suggested agent: Any — Estimate: 2 days — Concurrent trace ingestion stress tests (100, 1k, 10k ops/sec)
- [ ] **Thread safety stress tests** — Priority: high — Suggested agent: Gamma — Estimate: 1 day — Load test exporters with 10+ concurrent writers
- [ ] **Runtime error handling** — Priority: medium — Suggested agent: Lead — Estimate: 1 day — Follow up on any reported issues from 966 test suite
- [ ] **Production deployment checklist** — Priority: high — Suggested agent: Scribe — Estimate: 1 day — Finalize docs/deployment.md, verify all env vars documented

## Legend
- `[x]` = done (date)
- `[ ]` = backlog
- Agent = responsible developer
- Estimate = story points or days
- Priority = critical/high/medium/low
