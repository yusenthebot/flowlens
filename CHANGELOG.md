# Changelog

All notable changes to FlowLens will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Planned
- Web Dashboard — real-time trace viewer with interactive DAG visualization
- OpenTelemetry OTLP export — send traces to Jaeger, Grafana Tempo, and other collectors
- LangChain / CrewAI auto-instrumentation — zero-code tracing for popular agent frameworks
- Streaming support — trace streamed LLM responses token-by-token
- Alerting — webhook alerts triggered by detected anti-patterns
- Multi-trace correlation — surface systemic failure patterns across hundreds of traces

---

## [0.1.0] — 2026-03-14

Initial public release of FlowLens — Agent Observability Platform.

### Added

#### SDK Layer (`flowlens/sdk/`)
- `FlowLens` singleton class for trace lifecycle management with configurable exporters
- `@trace_agent` decorator — wraps agent entry points, creates root trace spans
- `@trace_llm` decorator — wraps LLM calls, captures model name, token usage, and cost
- `@trace_tool` decorator — wraps tool calls, captures input parameters and outputs
- All decorators support both `async` and synchronous functions transparently
- Async-safe context propagation via `contextvars.ContextVar` for correct parent-child span linking across `asyncio` tasks
- Four built-in exporters:
  - `ConsoleExporter` — colored, hierarchical output for local development
  - `JSONLExporter` — append-only JSONL file for offline analysis
  - `HTTPExporter` — sends traces to a running FlowLens server
  - `CallbackExporter` — calls a user-supplied function (useful for testing)
- `Span` and `Trace` data models with full `to_dict()` serialization
- `TokenUsage` model with per-model pricing for 11+ models:
  - Anthropic: Claude Opus 4, Claude Sonnet 4, Claude Haiku 3.5
  - OpenAI: GPT-4o, GPT-4o-mini, o1, o1-mini
  - Google: Gemini 1.5 Pro, Gemini 1.5 Flash
  - DeepSeek: DeepSeek V3, DeepSeek R1

#### Analysis Layer (`flowlens/analysis/`)
- `build_causal_dag()` — constructs a directed acyclic graph from trace spans, classifying each error node as `ROOT_CAUSE`, `CASCADED`, or `INDEPENDENT`
- `CausalDAG`, `CausalNode`, `CausalEdge`, and `DetectedPattern` models
- `detect_patterns()` — runs five anti-pattern detectors over a trace/DAG:
  - **Retry Storm** — same tool called 5+ times
  - **Infinite Loop** — repeating tool call sequences (A→B→A→B→...)
  - **Context Overflow** — token usage exceeds 90% of model context window
  - **Timeout Cascade** — timeout error causing downstream failures
  - **Empty Response** — LLM returns zero output tokens
- Pattern results include severity rating, affected span IDs, and human-readable detail messages

#### Server Layer (`flowlens/server/`)
- FastAPI application (`create_app()` factory) with async SQLite storage via `aiosqlite`
- Eight REST endpoints:
  - `POST /v1/traces/ingest` — receive trace data from SDK exporters
  - `POST /v1/traces/import` — bulk import from JSONL trace files
  - `GET  /v1/traces` — list traces with pagination and error/service filters
  - `GET  /v1/traces/{id}` — retrieve full trace with all spans
  - `GET  /v1/traces/{id}/dag` — on-demand causal DAG analysis
  - `GET  /v1/cost/breakdown` — multi-dimensional cost attribution (group by service, kind, or name)
  - `GET  /v1/stats` — global statistics (trace count, error rate, total cost)
  - `GET  /health` — liveness check
- `TraceStore` class with async CRUD operations and indexed queries

#### Testing
- 46 tests across four modules using `pytest` + `pytest-asyncio` (async-native)
  - `tests/test_models.py` — 15 tests for `Span`, `Trace`, and cost estimation
  - `tests/test_decorators.py` — 8 tests for decorator behaviour and nested spans
  - `tests/test_dag.py` — 10 tests for DAG builder and pattern detection
  - `tests/test_server.py` — 13 tests for storage CRUD and API endpoints

#### Examples & Documentation
- `examples/demo_agent.py` — runnable demo with an intentionally failing research agent demonstrating root cause identification and pattern detection
- `examples/demo_dashboard.html` — standalone interactive trace visualization
- `docs/flowlens-handbook.md` — architecture decisions, design principles, and extension guide
- `CONTRIBUTING.md` — development setup, code style guide, test writing guide, and PR process

#### Project Infrastructure
- `pyproject.toml` — PEP 517/518 build config with `[dev]` and `[otlp]` optional dependency groups
- MIT License

### Technical Notes
- Zero external runtime dependencies beyond FastAPI, Uvicorn, aiosqlite, and Pydantic
- Requires Python 3.10+ (uses `match` statements and modern type hint syntax)
- Framework-agnostic — works with LangChain, CrewAI, AutoGen, and any custom Python agent

---

[Unreleased]: https://github.com/niceyusen/flowlens/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/niceyusen/flowlens/releases/tag/v0.1.0
