# Cycle 11 Report — Robustness & Polish

## Summary

Robustness and polish cycle focusing on backend refactoring and data validation. Alpha addresses Overview dashboard visual issues (trend chart sizing, cost widgets, agent network persistence). Beta refactors app.py (2003 lines) into modular route files to improve maintainability and enable independent endpoint scaling. Gamma adds comprehensive trace ingest validation covering span cycle detection, orphan reference detection, and size limits with an expanded test suite.

## Goals

- **Alpha**: Fix Overview dashboard visual inconsistencies — trend chart height rendering, cost widget layout, mini agent network state persistence across tab switches
- **Beta**: Modularize app.py (2003 lines) into separate route modules for traces, cost, agents, stats, alerts, and system endpoints — reducing per-module complexity and enabling parallel development
- **Gamma**: Add trace ingest validation layer with cycle detection, orphan span reference detection, configurable size limits, and new test suite (target: 50+ new test cases)

## Completed

(In Progress — started 2026-03-14)

## In Progress

- **[alpha] Overview dashboard visual fixes** — Correct trend chart aspect ratio, cost widget width, agent network graph state restoration on tab navigation. Target: all visual elements stable and proportional.
- **[beta] App.py modularization** — Extract routes into separate modules: `flowlens/server/routes/traces.py`, `flowlens/server/routes/costs.py`, `flowlens/server/routes/agents.py`, `flowlens/server/routes/stats.py`, `flowlens/server/routes/alerts.py`, `flowlens/server/routes/system.py`. Main app.py reduced to ~200 lines (init, middleware, router registration).
- **[gamma] Trace ingest validation** — Add validators for: span cycle detection (prevent self-references and loops), orphan span detection (spans missing parent), configurable size limits (max span size, max trace size), batch validation. New test suite in `tests/test_ingest_validation.py`.

## Blocked

None

## Technical Decisions

### 1. Route Modules vs FastAPI Sub-Applications

**Decision**: Use separate route modules (Starlette `APIRouter`) rather than FastAPI sub-applications.

**Rationale**:
- Sub-applications require separate middleware and duplicate configuration (auth, CORS, error handlers)
- APIRouter allows shared middleware stack while isolating route logic
- Simpler testing: dependency injection works across routes without app initialization
- Easier parameter passing (db, config) via `Depends()` pattern

### 2. Validation Strategy: Warn vs Reject

**Decision**: Implement three validation levels:
- **Level 1 (strict)**: Reject malformed traces (cycle detection, orphan spans) with HTTP 422
- **Level 2 (warning)**: Log and tag traces that exceed soft size limits (suggest user optimization)
- **Level 3 (informational)**: Metrics-only for borderline cases (no action, only observability)

**Rationale**:
- Backwards compatibility: existing instruments won't break on update
- Gradual adoption: users can monitor warnings before enforcing limits
- Operational flexibility: on-call can override validation level via config for emergency ingestion

### 3. Test Coverage Expansion

**Decision**: Add 50+ validation test cases organized by category:
- Cycle detection (self-refs, bidirectional, transitive cycles, 5+ depth)
- Orphan detection (missing root, unreferenced leaf)
- Size validation (span > 1MB, trace > 100MB, batch > 1000 items)
- Timing validation (span duration negative, start after end)
- Reference integrity (invalid parent_span_id, circular trace_id refs)
- Edge cases (empty batch, null fields, unicode handling)

## Next Cycle Goals

- [ ] Complete all visual fixes and verify across browsers (Chrome, Safari, Firefox)
- [ ] Finish route modularization and run full integration test suite
- [ ] Deploy validation layer to staging and monitor ingest error metrics
- [ ] Measure app.py startup time improvement (goal: <2s baseline, <1s after refactor)
- [ ] Plan Cycle 12: either E2E testing improvements or performance benchmarking

## Metrics

| Metric | Target | Notes |
|--------|--------|-------|
| Tests | 1071 + 50+ new validation tests | New test suite expansion |
| Commits | 8-12 (3 agents × 2-4 commits each) | — |
| app.py refactoring | 2003 → ~200 lines main + 6 route files | Avg 250-350 lines per route module |
| Dashboard visual elements | 100% stable layout | Trend chart, cost widgets, network state |
| Validation coverage | 50+ test cases | Cycle, orphan, size, timing, reference, edge cases |
| Code organization | 0 file conflicts | Alpha/Beta/Gamma work on distinct files |
| Estimated User Impact | High | Polished dashboard UX + robust backend |

## Files Affected

**Alpha** (Overview fixes):
- `flowlens/server/dashboard.html` — trend chart sizing, cost widget layout, network state persistence

**Beta** (Route modularization):
- `flowlens/server/app.py` — reduced to router registration and middleware
- `flowlens/server/routes/traces.py` — POST/GET trace endpoints, stream handler
- `flowlens/server/routes/costs.py` — cost analysis endpoints
- `flowlens/server/routes/agents.py` — agent profiles, network, summary, activity
- `flowlens/server/routes/stats.py` — stats/trends, stats/summary
- `flowlens/server/routes/alerts.py` — alert CRUD endpoints
- `flowlens/server/routes/system.py` — health, version, export endpoints

**Gamma** (Validation):
- `flowlens/storage/validation.py` — new validation module with cycle detection, orphan detection, size limits
- `tests/test_ingest_validation.py` — 50+ test cases (new file)
- `flowlens/server/app.py` — updated ingest route to use validation layer

## Potential File Conflicts

- **Beta modifies app.py heavily**: Coordinate with Alpha on any dashboard-specific app endpoints
- **Gamma adds ingest validation to app.py**: Beta should integrate validation into traces route module after Beta completes modularization
