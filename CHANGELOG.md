# Changelog

All notable changes to FlowLens will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Planned
- ML-based anomaly detection
- Trace sampling strategies
- Kubernetes operator
- Documentation website (mkdocs)
- PyPI publishing

---
## [0.5.3] — 2026-03-14

Agent observability UI enhancements with avatar system and activity stream APIs. 1035 → 1048 tests across 1 post-cycle enhancement cycle.

### Added

#### Cycle 4 Features (2026-03-14 — Post-Cycle Enhancement)
- **Agent avatar system**: Global `AGENT_PROFILES` configuration with 7 SVG avatar icons and role metadata. New `renderAgentAvatar()` helper function for consistent avatar rendering across all agent-related UI elements. Visual branding consistency with gradient avatar tiles and status indicators (commit df64acd)
- **Agent profiles API**: New `/v1/agents/profiles` REST endpoint returning all configured agent profiles with avatars, roles, and metadata. Enables external dashboards and CLI tools to display agent information (commit acda768)
- **Activity stream API**: New `/v1/activity/stream` endpoint returning time-series activity events with agent, event type, timestamp, and metrics. Supports filtering and pagination for real-time monitoring (commit acda768)
- **Activity Timeline UI**: Interactive Activity Timeline panel on Overview dashboard (left column) rendering `/v1/activity/stream` events with per-agent color-coded status bars, status icons (success/error/in-progress), and time-ago labels. Provides parallel view of agent activity vs. system traces (commit dc60023)
- **Cost by Agent visualization**: New horizontal bar chart in Cost Analysis section using agent profile colors. Better cost attribution to agents for financial tracking (commit dc60023)
- **Enhanced agent cards**: Agent cards in Agents tab redesigned with colored initial-letter avatars instead of SVG icons. Improved visual consistency and space efficiency (commit dc60023)

### Changed
- Version bumped to 0.5.3
- Overview dashboard layout: replaced Agent Activity grid with horizontal Team Status bar
- Agent cards visual design: SVG icons → colored initial-letter avatars
- Overview dashboard panels: added Activity Timeline as companion to Recent Traces

### Technical Decisions
- **AGENT_PROFILES as single source of truth**: Centralized agent metadata configuration, easy extensibility for new agents
- **Avatar rendering abstraction**: `renderAgentAvatar()` function encapsulates SVG generation, enables consistent styling across all UI contexts
- **Activity stream generics**: Generic event structure allows future extensibility without breaking existing API clients
- **Color consistency**: Agent colors derived from profile avatars, propagated through timeline bars and cost charts
- **Timeline UI co-location**: Activity Timeline placed side-by-side with Recent Traces for parallel observability without UI clutter

---

## [0.5.2] — 2026-03-14

Advanced alerting with budget controls and full-text search. 1025 → 1035 tests across 1 final development cycle.

### Added

#### Cycle 3 Features (2026-03-14)
- **Budget alerts with cost_total metric**: New cumulative `cost_total` field for tracking total trace cost. Enables budget-based alerting and cost control workflows (commit 88c2582)
- **AND compound conditions in alerting**: Extended alert condition engine to support AND operators (`&&` / `AND`) for sophisticated multi-condition logic. Example: "cost > $10 AND error_rate > 5%" (commit 88c2582)
- **FTS5 full-text search**: New schema v6 migration with `spans_fts` virtual table for blazing-fast full-text search across span service names, span names, tags, and metadata. Uses SQLite FTS5 MATCH syntax (commit 7706c8f)
- **FTS search LIKE fallback**: Graceful degradation for edge cases where FTS returns empty results (e.g., service_name with special characters). Automatically falls back to LIKE-based search without user intervention (commit a63dfb1)

### Changed
- Version bumped to 0.5.2
- Database schema version: 5 → 6
- Alert condition syntax extended to support AND operators for multi-condition scenarios

### Technical Decisions
- **FTS5 virtual table architecture**: Separate `spans_fts` table keeps index isolated, enables safe rollback, and maintains referential integrity via hidden docid column
- **Fallback strategy**: Two-tier search approach (FTS MATCH → LIKE fallback) ensures search always returns results without user-facing failures
- **Cost tracking**: Cumulative `cost_total` field computed from individual span costs, enabling budget-aware alerting separate from per-span analysis

---

## [0.5.1] — 2026-03-14

Configuration flexibility, offline capabilities, and agent observability. 966 → 1025 tests across 1 development cycle of features and enhancements.

### Added

#### Cycle 2 Features (2026-03-14)
- **Configurable pattern detection thresholds**: 6 new env var config fields in `config.py` (FLOWLENS_PATTERN_*_THRESHOLD) for context window, retry storm, cold start, timeout cascade, empty response, and infinite loop detection. All `detect_*()` functions in `patterns.py` updated to use config values at runtime (commit a8047ce)
- **LocalCollector + LocalExporter**: New `flowlens/local.py` module with thread-safe direct SQLite access, bypassing HTTP server entirely. Query, ingest, search, pagination, and stats methods. Designed for embedded use cases (sync frameworks, CLI tools). LocalExporter added to SDK `create_exporter()` factory under `export_to="local"` (commit d3ebcff)
- **Agent observability dashboard tab**: New 6th "Agents" tab with responsive card grid, color-coded error rates (green <1%, yellow 1-10%, red >10%), click-to-filter traces by agent. Keyboard shortcut '6' switches to Agents view (commit 5181d89)
- **Agent summary API**: New `/v1/agents/summary` endpoint groups trace stats by `tags.agent`, returning trace count, error rate, avg latency, total cost, span count per agent sorted by trace count descending (commit 5181d89)
- **LocalCollector stress tests**: 35 test cases in `test_local_collector.py` covering ingest/query roundtrip, pagination, search, stats, 10-thread concurrent ingest, concurrent read+write (commit d3ebcff)
- **Pattern config tests**: 84 lines in `test_config.py` validating config field types and defaults; 119 lines in `test_analysis.py` testing pattern detection with various config thresholds (commit a8047ce)
- **Agent summary tests**: 5 new test cases in `test_server.py` covering basic grouping, sort order, empty DB, unknown-agent fallback, error-rate calculation (commit 5181d89)

### Changed
- Version bumped to 0.5.1
- Pattern detection behavior: thresholds now configurable via environment variables instead of hardcoded constants

### Technical Decisions
- **Thread-safe SQLite access**: LocalCollector uses single `threading.Lock` to serialize all DB cursor operations on shared primary connection
- **Agent grouping**: Fallback to "unknown-agent" for traces without `tags.agent` tag value
- **Error rate visualization**: Color-coded UI indicators for quick agent health assessment
- **No HTTP overhead**: LocalCollector designed for scenarios where HTTPExporter would introduce unnecessary latency

---

## [0.5.0] — 2026-03-14

Major release: plugin system, batch exporters, full CLI toolset, production hardening, UI redesign, and polished demos. 88 → 966 tests across 1 development cycle of bug fixes.

### Added

#### Cycle 1 Bug Fixes (2026-03-14)
- **WebSocket route handling**: Fixed /ws/traces 404 errors by adding scope type check in HTTP middleware to prevent intercepting WebSocket upgrades (commit 4e8f9d4)
- **Thread-safe exporters**: Added `threading.Lock` to JSONLExporter, CSVExporter, and JSONLStreamExporter for safe concurrent writes (commit c05f1b6)
- **Configurable HTTP timeout**: Made HTTPExporter timeout configurable via `timeout_sec` parameter (default 30s) (commit c05f1b6)
- **FK constraint resilience**: Force trace_id consistency in storage.py to prevent foreign key constraint failures (commit 70b94c8)
- **Improved model cost matching**: Changed from substring to longest-match-first strategy for accurate model cost estimation (commit 70b94c8)
- **New edge case tests**: Added 69 lines to test_storage_edge.py, 153 lines to test_exporters.py for thread safety and constraint validation

#### Plugin System (Cycle 5)
- `BasePlugin` abstract class with `name`, `version`, `patch()`, `unpatch()` interface
- `PluginRegistry` singleton for registering and discovering plugins
- Entry-point discovery via `importlib.metadata` (`flowlens.plugins` group)
- `load_plugin(name)` for loading plugins by name or `module:Class` path
- Built-in plugins: `AnthropicPlugin`, `OpenAIPlugin`, `LangChainPlugin`

#### Batch Exporters (Cycle 5)
- `OTLPBatchExporter` — batches traces before sending, configurable batch size and flush interval, gzip compression, exponential backoff retry (max 3), background flush thread
- `CSVExporter` — export traces/spans to CSV with configurable columns
- `JSONLStreamExporter` — newline-delimited JSON export to file or stdout

#### CLI Tools (Cycle 5)
- `flowlens export` — export traces from DB as JSON/CSV/JSONL with service/time/limit filters
- `flowlens import` — bulk load traces from JSON/JSONL files
- `flowlens stats` — trace count, span count, error rate, tokens, cost, top services
- `flowlens health` — check server status, DB size, config summary
- `flowlens demo` — run demos with `--all`, `--dashboard`, `--quick` flags

#### Production Hardening (Cycle 5–6)
- Enhanced `/health` endpoint: version, uptime, trace count, DB size
- Request logging middleware (excludes health checks)
- Graceful shutdown with DB connection cleanup
- `FLOWLENS_MAX_TRACES` auto-cleanup (default 100,000)
- Custom exception hierarchy: `FlowLensError`, `StorageError`, `ExportError`, `ValidationError`, `RateLimitError`
- `POST /v1/traces/batch-delete` endpoint (max 100 IDs)
- Optional API key authentication via `FLOWLENS_API_KEY`
- `pytest-cov` support, registered async markers

#### Analysis Engine (Cycle 4–5)
- 3 new pattern detectors: `context_window_pressure`, `retry_storm_quick`, `cold_start_penalty`
- `detect_performance_degradation()` — compare recent traces against baseline
- `detect_cost_anomalies()` — flag traces with 3x+ average cost
- `generate_weekly_report()` — summary stats over configurable time window
- `AnalysisReporter` class with `generate_trace_report()`, `generate_summary_report()`, `export_report_markdown()`
- `priority` field on recommendations (critical/high/medium/low)
- `estimated_savings` on cost-related recommendations

#### SDK Enhancements (Cycle 4)
- OpenAI auto-instrumentation with streaming support
- Legacy `openai.ChatCompletion` patching (openai < 1.0)
- LangChain auto-instrumentation: `Chain.__call__`, `AgentExecutor._call`
- `@trace_embedding` decorator for embedding API calls
- `SpanKind.CHAIN` and `SpanKind.EMBEDDING` enum values

#### UI & Demos (Post-Cycle)
- Soft warm color palette redesign (off-white `#fafaf8`, muted pastels)
- Dark theme: warm dark gray `#2a2a28` instead of pitch black
- `examples/demo_dashboard.html` — standalone interactive dashboard with 10 embedded traces
- `examples/demo_autoplay.html` — auto-playing 8-scene product showcase
- `examples/quickstart.py` — basic tracing with colored trace tree output
- `examples/rag_pipeline.py` — full RAG pipeline demo
- `examples/multi_agent.py` — 4-agent collaboration with retry logic
- `examples/cost_optimizer.py` — compare 4 model strategies with cost tables
- `examples/live_dashboard.py` — generate traces, start server, open browser
- `examples/_utils.py` — shared ANSI color helpers, trace tree printer, table formatter
- `examples/take_screenshots.py` — Playwright-based screenshot generation

#### Test Coverage (Cycles 1–6)
- 1035 tests across 19 test files
- New test files: `test_context.py`, `test_dag_builder.py`, `test_decorators_advanced.py`, `test_exporters.py`, `test_plugins.py`, `test_storage_edge.py`, `test_new_features.py`
- Edge cases: Unicode, large traces (500+ spans), concurrent writes, SQL injection attempts, FTS5 schema migration

#### Documentation
- `docs/deployment.md` — Docker, manual install, env vars, nginx, production checklist
- `docs/troubleshooting.md` — common errors, FAQ, debug mode, performance tips
- `CONTRIBUTING.md` — dev setup, code style, PR process
- README overhaul with accurate screenshots, CLI reference, comparison table
- `MANIFEST.in` for PyPI packaging
- `LICENSE` updated to 2024-2026 FlowLens Contributors
- PyPI classifiers, keywords, entry points configured

### Changed
- Version bumped to 0.5.0
- Default dashboard theme: light (warm off-white) instead of dark
- Span kind colors: soft violet/teal/lavender/gold/blue palette
- CLI entry point fixed: `flowlens.cli:cli`
- GitHub URLs corrected to `yusenthebot/flowlens`

### Fixed
- WebSocket /ws/traces 404 (Cycle 1 — commit 4e8f9d4)
- WebSocket double-reconnect scheduling
- `asyncio.iscoroutinefunction` deprecation (Python 3.16)
- `on_event("shutdown")` FastAPI deprecation → lifespan context manager
- Click `CliRunner(mix_stderr=False)` incompatibility with Click 8.2+
- `re.ASCII | re.UNICODE` incompatibility in Python 3.14
- Flaky timing tests (`span.duration_ms == 0` on fast machines)
- Rate limiter stale cleanup test race condition
- httpx null byte rejection in security tests
- FK constraint failures in storage (Cycle 1 — commit 70b94c8)
- Model cost estimation with longest-match-first (Cycle 1 — commit 70b94c8)

---

## [0.1.0] — 2026-03-14

Initial public release of FlowLens — Agent Observability Platform.

### Added
- `FlowLens` singleton with configurable exporters (Console, JSONL, HTTP, Callback)
- `@trace_agent`, `@trace_llm`, `@trace_tool` decorators (sync + async)
- Async-safe context propagation via `contextvars`
- `Span`, `Trace`, `TokenUsage` data models with 11+ model pricing
- `build_causal_dag()` — causal error graph with ROOT_CAUSE/CASCADED/INDEPENDENT classification
- `detect_patterns()` — 5 anti-pattern detectors (retry storm, infinite loop, context overflow, timeout cascade, empty response)
- FastAPI server with 8 REST endpoints + async SQLite storage
- 88 tests across 4 modules
- Demo agent and interactive dashboard HTML

---

## Project Complete

This changelog documents the evolution of FlowLens from initial release (v0.1.0) through three development cycles:

- **Cycle 1** (2026-03-14): 5 critical bug fixes addressing WebSocket routing, thread safety, FK constraints, model cost accuracy, and HTTP timeout configurability. Grew test suite from 88 to 966 tests.
- **Cycle 2** (2026-03-14): 3 major features adding runtime configurability of pattern thresholds, offline SQLite access via LocalCollector, and comprehensive agent observability dashboard. Grew tests from 966 to 1025.
- **Cycle 3** (2026-03-14): 2 advanced features delivering budget-aware alerting with AND compound conditions and production-grade full-text search with FTS5. Grew tests from 1025 to 1035.

**Total improvements**: 10 features/fixes across 3 cycles, 1035 comprehensive tests, schema versions 1→6, 4 version releases (0.1.0 → 0.5.2). The system is now production-ready with observability, cost control, offline capabilities, and advanced search.

---

[Unreleased]: https://github.com/yusenthebot/flowlens/compare/v0.5.2...HEAD
[0.5.2]: https://github.com/yusenthebot/flowlens/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/yusenthebot/flowlens/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/yusenthebot/flowlens/compare/v0.1.0...v0.5.0
[0.1.0]: https://github.com/yusenthebot/flowlens/releases/tag/v0.1.0
