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

## [0.5.0] — 2026-03-14

Major release: plugin system, batch exporters, full CLI toolset, production hardening, UI redesign, and polished demos. 88 → 754 tests across 6 development cycles.

### Added

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
- 754 tests across 18 test files
- New test files: `test_context.py`, `test_dag_builder.py`, `test_decorators_advanced.py`, `test_exporters.py`, `test_plugins.py`, `test_storage_edge.py`, `test_new_features.py`
- Edge cases: Unicode, large traces (500+ spans), concurrent writes, SQL injection attempts

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
- WebSocket double-reconnect scheduling
- `asyncio.iscoroutinefunction` deprecation (Python 3.16)
- `on_event("shutdown")` FastAPI deprecation → lifespan context manager
- Click `CliRunner(mix_stderr=False)` incompatibility with Click 8.2+
- `re.ASCII | re.UNICODE` incompatibility in Python 3.14
- Flaky timing tests (`span.duration_ms == 0` on fast machines)
- Rate limiter stale cleanup test race condition
- httpx null byte rejection in security tests

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

[Unreleased]: https://github.com/yusenthebot/flowlens/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/yusenthebot/flowlens/compare/v0.1.0...v0.5.0
[0.1.0]: https://github.com/yusenthebot/flowlens/releases/tag/v0.1.0
