# FlowLens — Project Status & Roadmap

## Current Version: 0.1.0 (Alpha)

## Agent Team Improvement Cycles

### Cycle 1 — Foundation Improvements (In Progress)
Started: 2026-03-14

#### Workstreams:
| Agent | Role | Model | Tasks | Status |
|-------|------|-------|-------|--------|
| Frontend Engineer | Dashboard UI | Opus | Rebuild dashboard, API integration, DAG visualization | 🔄 In Progress |
| Backend Engineer | Server & Storage | Sonnet | WebSocket, new endpoints, storage improvements | 🔄 In Progress |
| SDK Engineer | SDK & Instrumentation | Sonnet | Auto-instrument, streaming, token extraction | 🔄 In Progress |
| DevOps Engineer | CI/CD & Quality | Sonnet | GitHub Actions, Docker, Makefile, pre-commit | 🔄 In Progress |
| Project Manager | Coordination | Haiku | Progress tracking, planning, documentation | 🔄 Active |

#### Cycle 1 Deliverables:
- [ ] Live dashboard served by FastAPI with real API data
- [ ] WebSocket real-time trace streaming
- [ ] Auto-instrumentation for Anthropic, OpenAI, LangChain
- [ ] Streaming LLM response tracing
- [ ] GitHub Actions CI pipeline
- [ ] Docker containerization
- [ ] Developer tooling (Makefile, pre-commit)

### Cycle 2 — Planned Improvements
- Performance optimization and benchmarking
- OpenTelemetry OTLP export integration
- Advanced pattern detection algorithms
- Multi-trace correlation and systemic analysis
- Documentation site (mkdocs or similar)
- PyPI package publishing preparation

### Cycle 3 — Polish & Release
- End-to-end integration tests
- Security audit
- API versioning strategy
- Community contribution templates
- v0.2.0 release preparation

## Architecture Overview
```
SDK Layer (decorators, auto-instrument)
  → Analysis Layer (DAG, patterns, advisor)
    → Server Layer (FastAPI, SQLite, WebSocket)
      → Dashboard (HTML/JS, Cytoscape, Chart.js)
```

## Key Metrics to Track
- Test count: 88 → target: 150+
- Code coverage: ~80% → target: 90%+
- API endpoints: 8 → target: 15+
- Supported LLM providers: 6 → target: 10+

## Team Model Allocation Strategy
| Model | Role | Rationale |
|-------|------|-----------|
| Opus | Creative/complex tasks (Frontend, Architecture) | High quality for UI/UX decisions |
| Sonnet | Implementation tasks (Backend, SDK, DevOps) | Good balance of speed and quality |
| Haiku | Coordination, docs, planning | Fast and cost-effective for text tasks |
