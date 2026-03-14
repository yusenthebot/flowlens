# Changelog

All notable changes to FlowLens will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Planned
- ML-based anomaly detection (leverage /v1/stats/trends API for statistical analysis)
- Trace sampling strategies (probabilistic, head-based, tail-based)
- Kubernetes operator (custom resource definitions, controller)
- Documentation website (mkdocs with auto-generated API docs)
- PyPI publishing and distribution

---

## [0.7.0] — 2026-03-14

Comparison view enhancements and agent relationship visualization cycle. Enhanced trace comparison with verdict badges and diff indicators, new APIs for agent relationship graphs and activity reports, and interactive Cytoscape-based relationship visualization. 1053 → 1066 tests across 1 comparison and visualization cycle.

### Added

#### Cycle 6 Features (2026-03-14 — Comparison & Relationship Visualization)

- **Enhanced Compare view with verdict badge**: Redesigned Compare view with side-by-side Trace A/B summary cards showing all key metrics (duration, cost, tokens, spans, errors) with clear visual diff indicators. Duration, cost, and token diffs rendered as colored progress bars (green=improvement, red=regression) with percentage change labels. Verdict badge ("Improved", "Regressed", "Similar") computed from weighted score across duration, cost, and error metrics for balanced assessment (commit 29e55e9)

- **Responsive mobile layout**: Responsive grid layouts with breakpoints at 768px (tablet) and 480px (phone). Stat-grid changes from multi-column to single-column with stacked cards for readability on small screens. Compare view and overview panels fully responsive for tablet and phone users (commit 29e55e9)

- **Dark mode polish**: Consistent warm dark gray (#2a2a28) with muted pastels across all UI sections for better eye comfort and accessibility. Color scheme validated against WCAG AA contrast ratios (commit 29e55e9)

- **Agent relationship graph API**: New `/v1/agents/relationships` endpoint returning spawn graph of agent relationships showing which agents spawn which other agents (agent -> spawned_agents mapping), call counts, and timing data. Enables visualization of agent hierarchy and collaboration patterns (commit cd10258)

- **Activity report export API**: New `/v1/export/report` endpoint exporting comprehensive activity reports with agent metrics, relationship data, and trace summaries. Supports multiple formats (JSON, CSV, Markdown) with configurable time range and agent filtering. Foundation for SRE team workflows and incident post-mortems (commit cd10258)

- **Interactive agent relationship visualization**: Cytoscape.js-based interactive directed graph visualization showing agent spawn hierarchy. Nodes represent agents with color-coded avatars from AGENT_PROFILES. Edges show spawn relationships with call count labels. Force-directed layout with automatic zoom-to-fit for large hierarchies. Click-to-highlight shows agent spawn path and dependents (commit 5580ce1)

- **Agent detail modal**: Comprehensive agent information modal displaying profile, avatar, roles, recent activity, error rate, total spans, cost contribution, and related agents. Quick drill-down to individual agent metrics and relationships without leaving dashboard (commit 5580ce1)

- **Keyboard shortcuts for agent graph**: Global keyboard navigation: arrow keys to navigate graph, 'D' for detail modal, 'C' for compare mode, 'E' for export, 'R' to reset graph layout. Enables power-user workflows for rapid multi-agent system analysis (commit 5580ce1)

### Changed

- Version bumped to 0.7.0
- Compare view: added side-by-side cards with diff progress bars and verdict badge
- Dashboard layout: agent relationship graph visualization panel with Cytoscape.js
- Mobile UI: responsive grid layouts and single-column stacking for small screens
- Dark mode: warm palette (#2a2a28) with muted pastels, consistent across all sections

### Technical Decisions

- **Compare view verdict badge**: Weighted score (duration 40%, cost 35%, error count 25%) for balanced assessment across different system priorities
- **Responsive breakpoints**: 768px for tablet (2-col → 1-col), 480px for phone (stacked cards). Mobile-first approach with progressive enhancement
- **Cytoscape.js selection**: Force-directed layout algorithm for automatic node spacing and edge routing. Supports zoom/pan for large agent hierarchies
- **Report export architecture**: Generic report structure (JSON) with adapters for CSV and Markdown. Enables future format additions without core changes
- **Keyboard shortcut design**: Non-intrusive defaults (D, C, E, R) avoiding browser conflicts. Arrow key navigation for graph exploration

---

## [0.6.0] — 2026-03-14

Advanced analytics and trace visualization cycle. Agent-colored waterfall trace debugging, comprehensive trend analysis APIs with per-agent breakdown, interactive activity trend charts, and visual pattern detection dashboard. 1048 → 1053 tests across 1 analytics cycle.

### Added

#### Cycle 5 Features (2026-03-14 — Analytics & Visualization)

- **Trace detail waterfall visualization**: Agent-colored waterfall diagram showing complete span hierarchy with color-coded agents, duration bars, and error highlights. New span detail panel displays agent avatars, status icons, and performance metrics. SVG-based rendering enables crisp interactive debugging of complex traces (commit 860d44b)

- **Trace volume trend analytics API**: New `/v1/stats/trends` endpoint returning time-series trace volume trends over configurable time windows (hourly/daily buckets) with per-agent breakdown. Enables visualization of which agents contribute to traffic patterns and anomalies (commit 4ef045d)

- **Aggregate statistics API with agent breakdown**: New `/v1/stats/summary` endpoint returning aggregate statistics (total traces, spans, errors, cost, average latency) with per-agent breakdown. Supports cost attribution, agent performance comparison, and SLA monitoring (commit 4ef045d)

- **Interactive activity trend charts**: New Activity Analysis dashboard panel with trend line chart showing 24-hour trace volume and error rate trends. Per-agent stacked area visualization shows agent contribution to overall system metrics (commit b2442cd)

- **Visual pattern detection cards**: Dashboard cards displaying detected anti-patterns (retry storms, timeout cascades, context overflow, cold starts, empty responses, infinite loops) with severity icons (critical/high/medium/low), occurrence count badges, and click-to-filter functionality. Color-coded severity indicators (red/orange/yellow/green) enable quick pattern assessment (commit acdbe78)

### Changed

- Version bumped to 0.6.0
- Trace detail view: added interactive waterfall visualization component
- Analytics dashboard: new Activity Analysis panel with trend charts
- Dashboard layout: added pattern detection cards to primary observability view

### Technical Decisions

- **Waterfall visualization color scheme**: Agent colors mapped from AGENT_PROFILES configuration for consistency with timeline and cost charts. Error spans highlighted in red with context for immediate issue identification. SVG-based rendering supports future interactivity (logs, metrics linkage)

- **Trend analytics query optimization**: Aggregation performed at database layer using SQL GROUP BY/time buckets rather than post-processing. Architecture ready for Redis caching layer in future versions

- **Per-agent stacking strategy**: Stacked area charts show agent contribution percentages rather than absolute values, preventing large agents from obscuring smaller ones. Color consistency with agent profiles enables team member identification

- **Pattern card filtering**: Click-to-filter from pattern cards updates main traces view with MATCH clause. Supports both pattern type and severity filtering for rapid RCA workflows

- **Analytics API extensibility**: Trend and summary endpoints accept optional time range, agent filter, and service filter parameters. Generic structure supports future metric types without breaking existing clients

### Fixed

- Schema version consistency validated across all analytics queries

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
- 1053 tests across 19 test files
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

This changelog documents the evolution of FlowLens from initial release (v0.1.0) through five development cycles:

- **Cycle 1** (2026-03-14): 5 critical bug fixes addressing WebSocket routing, thread safety, FK constraints, model cost accuracy, and HTTP timeout configurability. Grew test suite from 88 to 966 tests.
- **Cycle 2** (2026-03-14): 3 major features adding runtime configurability of pattern thresholds, offline SQLite access via LocalCollector, and comprehensive agent observability dashboard. Grew tests from 966 to 1025.
- **Cycle 3** (2026-03-14): 2 advanced features delivering budget-aware alerting with AND compound conditions and production-grade full-text search with FTS5. Grew tests from 1025 to 1035.
- **Cycle 4** (2026-03-14): 6 UI/UX enhancements including agent avatar system, agent observability APIs, activity timeline, and cost visualization. Grew tests from 1035 to 1048.
- **Cycle 5** (2026-03-14): 5 advanced analytics and visualization features including waterfall trace debugging, trend analysis APIs, activity trend charts, and pattern detection cards. Grew tests from 1048 to 1053.

**Total improvements**: 19 features/fixes across 5 cycles, 1053 comprehensive tests, schema versions 1→6, 6 version releases (0.1.0 → 0.6.0). The system is now production-ready with comprehensive observability, agent attribution, cost control, offline capabilities, advanced search, and data-driven analytics.

---

[Unreleased]: https://github.com/yusenthebot/flowlens/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/yusenthebot/flowlens/compare/v0.5.3...v0.6.0
[0.5.3]: https://github.com/yusenthebot/flowlens/compare/v0.5.2...v0.5.3
[0.5.2]: https://github.com/yusenthebot/flowlens/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/yusenthebot/flowlens/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/yusenthebot/flowlens/compare/v0.1.0...v0.5.0
[0.1.0]: https://github.com/yusenthebot/flowlens/releases/tag/v0.1.0
