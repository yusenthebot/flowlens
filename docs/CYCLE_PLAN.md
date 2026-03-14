# FlowLens — Improvement Cycle Plans

## Philosophy
We operate as a self-improving agent team. Each cycle:
1. Plan improvements across all layers
2. Execute in parallel with isolated worktrees
3. Merge, test, and validate
4. Retrospective → plan next cycle

## Cycle 1: Foundation (Current)
### Goals
- Transform prototype dashboard into production-ready UI
- Add real-time capabilities (WebSocket)
- Enable zero-code instrumentation
- Establish CI/CD and quality gates

### Success Criteria
- All tests pass on Python 3.10, 3.11, 3.12
- Dashboard connects to live API
- Auto-instrumentation works for at least 2 providers
- Docker image builds and runs successfully
- CI pipeline runs on push

### Risk Mitigation
- Each agent works in isolated git worktree
- Changes merged sequentially to avoid conflicts
- Tests run after each merge
- Rollback plan: git revert if merge breaks tests

### Implementation Strategy
#### Frontend (Opus)
- Rebuild dashboard HTML/CSS for better UX
- Implement API client in JavaScript
- Create DAG visualization using Cytoscape
- Add real-time WebSocket listener for trace updates
- Integrate chart.js for metrics display

#### Backend (Sonnet)
- Add WebSocket server support to FastAPI
- Implement new API endpoints: DELETE /traces/{id}, GET /search, POST /cleanup, GET /trends, GET /summary
- Improve SQLite schema for better query performance
- Add comprehensive error handling
- Implement trace streaming via WebSocket

#### SDK (Sonnet)
- Create auto-instrumentation module for Anthropic SDK
- Create auto-instrumentation module for OpenAI SDK
- Create auto-instrumentation module for LangChain
- Add streaming response support
- Improve token counting for all providers
- Update model pricing database

#### DevOps (Sonnet)
- Set up GitHub Actions workflows (lint, test, coverage)
- Create Dockerfile with multi-stage build
- Create docker-compose.yml for local dev
- Create Makefile for common tasks
- Set up pre-commit hooks for code quality
- Improve pyproject.toml configuration

### Merge Order (Low to High Conflict Risk)
1. DevOps changes (isolated config files, no code impact)
2. Backend API endpoints (server-only changes)
3. SDK instrumentation (new module, minimal conflicts)
4. Frontend dashboard (HTML/JS, mostly isolated)
5. Integration testing (confirms all work together)

## Cycle 2: Enhancement
### Goals
- OpenTelemetry OTLP export
- Performance benchmarking suite
- Advanced analysis algorithms
- Documentation website

### Prerequisites from Cycle 1
- Stable CI pipeline
- Working dashboard
- Clean test suite

### Key Deliverables
- OTLP protocol support for exporting traces
- Benchmarking suite with memory/performance profiling
- Pattern detection improvements (heuristics)
- Cost analysis enhancements
- mkdocs site with guides and examples

## Cycle 3: Release Prep
### Goals
- PyPI publishing
- Security hardening
- Community templates
- v0.2.0 release

### Key Deliverables
- Security audit and fixes
- Issue/PR/discussion templates
- CONTRIBUTING.md guidelines
- CODE_OF_CONDUCT.md
- License audit (dependencies)
- Changelog generation automation
- Release notes for v0.2.0

## Agent Team Pattern
This "agent company" pattern can be reused:
1. **Explore agent** analyzes project thoroughly
2. **PM agent (Haiku)** creates plans and tracks progress
3. **Specialist agents** work in parallel on isolated worktrees
4. **Coordinator** merges, tests, and launches next cycle
5. Repeat until goals met

### Model Selection Guide
- **Opus**: Architecture decisions, complex UI, code review
- **Sonnet**: Feature implementation, refactoring, testing
- **Haiku**: Planning, documentation, status tracking, coordination
