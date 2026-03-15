<p align="center">
  <h1 align="center">FlowLens</h1>
  <p align="center"><strong>Agent Observability Platform — trace, analyze, and optimize your AI agent teams</strong></p>
</p>

<p align="center">
  <a href="https://pypi.org/project/flowlens/"><img src="https://img.shields.io/pypi/v/flowlens.svg" alt="PyPI version"></a>
  <a href="https://github.com/yusenthebot/flowlens/actions"><img src="https://img.shields.io/github/actions/workflow/status/yusenthebot/flowlens/ci.yml?branch=main&label=tests" alt="Tests"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python 3.10+"></a>
  <a href="https://github.com/yusenthebot/flowlens/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://opentelemetry.io/"><img src="https://img.shields.io/badge/OpenTelemetry-compatible-blueviolet.svg" alt="OTEL Compatible"></a>
</p>

> FlowLens shows you **why** your AI agent failed, not just *that* it failed.

It traces every LLM call, tool execution, and decision point — then builds **causal error graphs** to pinpoint root causes instantly. Built for teams running multi-agent systems where a single failure can cascade through a dozen services.

<p align="center">
  <img src="examples/dashboard_full.png" alt="FlowLens Dashboard" width="820">
</p>

> **Try it now:** [**Live Interactive Dashboard**](https://yusenthebot.github.io/flowlens/demo_dashboard.html) · [**Product Tour**](https://yusenthebot.github.io/flowlens/demo_autoplay.html) — no install needed.

---

## Key Features

| Feature | Description |
|---|---|
| **Causal DAG Analysis** | Distinguishes root causes from cascaded failures in error graphs |
| **15+ Anti-Pattern Detectors** | Retry storms, infinite loops, context overflow, timeout cascades, token waste, cold start penalty, and more — all configurable via env vars |
| **Zero-Intrusion Tracing** | Decorators instrument any Python agent without touching business logic |
| **Auto-Instrumentation** | One call patches Anthropic, OpenAI, and LangChain automatically |
| **Lightweight SVG Agent Network** | Interactive agent relationship graph with animated particles and glow effects. Drag to rotate, hover to highlight, click for details. Lazy-loads Three.js for advanced 3D as fallback |
| **Real-time Agent Team Monitoring** | WebSocket live feed of agent activity with status tracking, per-agent activity timelines, and tmux-style floating terminal |
| **Live Monitor Terminal** | Click agent to open terminal-style activity pane; auto grid layout (1/2/4 agents); draggable, resizable from all edges; real-time WebSocket push per pane; rich detail with file paths, commands, grep patterns, model names |
| **Session Timeline View** | Group traces by session_id; vertical timeline showing related traces and interactions in chronological order |
| **Trace Feedback & Annotations** | Star rating (5-point scale), quick reactions (thumbs up/down), optional comments; filter traces by rating; recent feedback overview on dashboard |
| **Cost Forecasting** | Monthly projection based on daily trend; daily trend + forecast chart with confidence intervals; budget alerts with progress bar (green/yellow/red) |
| **Agent Avatar System** | SVG icons per agent with unique color identities from AGENT_PROFILES |
| **Cost Attribution** | Token + cost breakdown by model, tool, or service (16+ models priced); cost insights, trends, optimization suggestions |
| **LocalCollector** | Direct SQLite access — no server required, thread-safe ingest and query |
| **FTS5 Full-Text Search** | Fast full-text search over trace and span content with LIKE fallback |
| **Budget Alerts with AND conditions** | Compound alert rules using `&&` / `AND` operators on any metric; localStorage persistence across page reloads |
| **Notification Panel** | WebSocket-driven alert notifications in the dashboard with bell icon badge |
| **Plugin System** | Extensible plugin registry with entry-point discovery |
| **Multiple Exporters** | Console, HTTP, OTLP, CSV, JSONL, Local — with batch and gzip support |
| **CLI Tools** | 8 commands: `serve`, `analyze`, `export`, `import`, `stats`, `health`, `demo`, `version` |
| **Configurable Pattern Thresholds** | Override any detector threshold via environment variables |
| **Trace Ingest Validation** | Validates incoming traces for data integrity: detects span cycles (self-refs, bidirectional), orphan references, size limits. Three validation levels (strict/warning/informational) for gradual adoption |
| **Smart Trace Summaries** | Instead of UUID display: "3 Read, 2 Bash, 1 Edit" summary per trace showing span kind breakdown |
| **Quick Filter Bar** | Agent/status/duration/time window dropdowns for rapid trace filtering |
| **Enhanced Waterfall** | Inline file paths, commands, grep patterns per span; agent-colored visualization |
| **Overview Stat Cards** | Trend indicators (↑↓ percentage changes); sparkline micro visualizations for at-a-glance metrics |
| **Structured Span Detail** | Tool I/O display; LLM tokens/cost; timing bar; error highlighting; model name |
| **Comprehensive Light Theme** | 80+ CSS rules ensuring readability in light mode across all tabs |
| **SessionStorage State Persistence** | Tab selection, active filters, scroll position preserved across page reloads |

---

## Quick Start

### 1. Install

```bash
pip install flowlens
```

### 2. Instrument

```python
from flowlens import FlowLens, trace_agent, trace_llm, trace_tool

lens = FlowLens(service_name="my-agent", export_to="console")

@trace_agent(name="research_bot")
def run(task):
    result = search(task)
    return summarize(result)

@trace_tool(name="web_search")
def search(query):
    return ["result1", "result2"]

@trace_llm(model="claude-sonnet-4-20250514")
def summarize(data):
    return "Summary of findings..."

run("What is agentic AI?")
```

Console output:

```
[FlowLens] Trace a1b2c3d4... | 3 spans | 142ms | 525 tokens | $0.0026 | OK
```

### 3. Visualize

```bash
flowlens serve                   # dashboard at http://localhost:8585
```

```python
# send traces to the dashboard
lens = FlowLens(service_name="my-agent", export_to="http",
                endpoint="http://localhost:8585/v1/traces/ingest")
```

### 4. No Server? Use LocalCollector

```python
from flowlens.local import LocalCollector

collector = LocalCollector(db_path="./traces.db")
collector.ingest(trace)
results = collector.search("timeout")
stats = collector.stats()
```

---

## Dashboard

<p align="center">
  <img src="examples/screenshot_overview.png" alt="Trace Overview" width="820">
</p>

<p align="center">
  <img src="examples/screenshot_dag.png" alt="Causal Error DAG" width="820">
</p>

<p align="center">
  <img src="examples/screenshot_cost.png" alt="Cost Analysis" width="820">
</p>

<p align="center">
  <img src="examples/screenshot_patterns.png" alt="Pattern Detection" width="820">
</p>

**Key views:**
- **Overview** — stat cards with trend indicators and sparklines, trace volume charts, live activity feed, agent details with per-agent activity feeds, live monitor terminal, cost forecasting
- **Sessions** — group traces by session_id, vertical timeline of related traces, interaction flow visualization
- **Agents** — real-time agent team status with SVG avatars, error rates, activity timelines, relationship graph
- **Traces** — smart trace summaries with quick filter bar (agent/status/duration/time window), hover previews, trace feedback/rating badges
- **Trace detail** — agent-colored waterfall timeline with inline paths/commands, structured span detail panel, error highlights, and root cause identification
- **Causal DAG** — interactive graph showing error propagation and root causes
- **Cost analysis** — cost breakdown by model, service, and agent with trend charts and forecasting
- **Pattern alerts** — detected anti-patterns with severity levels and click-to-filter
- **Compare** — side-by-side trace comparison with verdict badge and diff progress bars
- **Feedback** — recent trace annotations with star ratings and comments

> [**Open Live Dashboard Demo**](https://yusenthebot.github.io/flowlens/demo_dashboard.html) — interactive preview with 10 embedded sample traces, no install needed.

---

## Agent Team Monitoring

FlowLens is built for monitoring AI agent teams. Each agent gets:

- A unique SVG avatar and color identity drawn from a global `AGENT_PROFILES` registry
- Real-time status tracking (active / idle) with per-agent activity timeline showing what each agent is doing
- SVG-based agent network visualization with animated particles, glow effects, and drag-to-interact controls
- Relationship graph showing spawn hierarchies and call patterns across complex multi-agent systems
- Per-agent cost breakdown and error analysis across all traces
- Comprehensive agent detail modal with profile, roles, recent activity, related agents, and spawn hierarchy
- Live terminal-style activity pane (click to open; auto grid layout for multiple agents; draggable/resizable; rich detail with file paths, commands, model names)

The dashboard Agents tab shows your entire team at a glance. The Overview includes live activity feeds per agent. The Session Timeline reveals causal relationships between traces and spans. Agent relationship graphs reveal spawn hierarchies and call patterns without requiring a separate 3D navigation step.

---

## Examples

Run any example — no API keys needed (all use simulated data):

```bash
python3 examples/quickstart.py           # basic tracing in 30 seconds
python3 examples/rag_pipeline.py         # full RAG: embed → search → rerank → generate
python3 examples/multi_agent.py          # 4-agent collaboration with retry logic
python3 examples/cost_optimizer.py       # compare 4 model strategies, find savings
python3 examples/live_dashboard.py       # launch dashboard with sample data
python3 examples/auto_instrument_example.py  # zero-decorator auto-instrumentation
```

Or use the CLI / Makefile:

```bash
flowlens demo                            # run quickstart demo
flowlens demo --all                      # run all demos
make demo                               # run all demos via Makefile
```

| Example | What it demonstrates |
|---|---|
| [`quickstart.py`](examples/quickstart.py) | Basic tracing with 4 decorators, colored trace tree output |
| [`rag_pipeline.py`](examples/rag_pipeline.py) | RAG pipeline: embedding, vector search, reranking, generation |
| [`multi_agent.py`](examples/multi_agent.py) | Planner → Researcher → Writer → Reviewer with rejection/retry |
| [`cost_optimizer.py`](examples/cost_optimizer.py) | Compare sonnet+haiku vs opus vs gpt-4o, cost bar charts |
| [`live_dashboard.py`](examples/live_dashboard.py) | Generate traces, start server, open browser to dashboard |
| [`auto_instrument_example.py`](examples/auto_instrument_example.py) | Patch Anthropic/OpenAI/LangChain with zero decorators |
| [`demo_dashboard.html`](https://yusenthebot.github.io/flowlens/demo_dashboard.html) | Interactive dashboard ([live demo](https://yusenthebot.github.io/flowlens/demo_dashboard.html)) |
| [`demo_autoplay.html`](https://yusenthebot.github.io/flowlens/demo_autoplay.html) | Auto-playing product tour ([live demo](https://yusenthebot.github.io/flowlens/demo_autoplay.html)) |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                         Your Agent Code                          │
│   @trace_agent  ·  @trace_llm  ·  @trace_tool                   │
│   @trace_chain  ·  @trace_retrieval  ·  auto_instrument()        │
└──────────────┬───────────────────────────────────────────────────┘
               │
       ┌───────▼────────┐            ┌────────────────────────────┐
       │   SDK Layer     │            │      Analysis Layer         │
       │                │            │                             │
       │ · TraceContext  │            │ · Causal DAG Builder        │
       │ · SpanContext   │            │ · 15+ Pattern Detectors     │
       │ · Exporters     │            │   (configurable thresholds) │
       │   Console/CSV   │            │ · Root Cause Identification │
       │   HTTP/OTLP     │            │ · Cost Engine (16+ models)  │
       │   JSONL/Local   │            │ · Multi-Trace Correlator    │
       │ · Plugins       │            │ · Budget Alert Engine       │
       │ · LocalCollector│            │   (AND compound conditions) │
       └───────┬────────┘            └──────────▲─────────────────┘
               │                                │
               └────────────────►  ┌────────────┴──────────────────┐
                     export        │       Server Layer             │
                                   │                                │
                                   │ · FastAPI REST API (25+ routes)│
                                   │ · 6 Modular route modules      │
                                   │ · Trace ingest validation      │
                                   │ · WebSocket live feed          │
                                   │ · SQLite + FTS5 full-text      │
                                   │ · Agent APIs (profiles, net)   │
                                   │ · Stats & Trends APIs          │
                                   │ · Export & Report APIs         │
                                   │ · SVG Dashboard (single-page)  │
                                   └────────────────────────────────┘
```

**Three-layer architecture:**

1. **SDK Layer** (`flowlens/sdk/`): Instrumentation via decorators and auto-patching, context propagation, data collection, and export.
2. **Analysis Layer** (`flowlens/analysis/`): Post-trace processing — causal DAG construction, error classification, pattern detection, cost estimation.
3. **Server Layer** (`flowlens/server/`): FastAPI REST API with 6 modular route modules (traces.py, cost.py, agents.py, stats.py, alerts.py, system.py), shared utils.py, validation.py for trace ingest integrity, real-time WebSocket broadcasting, persistence, querying, and static dashboard serving.

---

## Integrations

### Auto-Instrumentation (zero decorators)

```python
from flowlens import FlowLens
from flowlens.sdk.auto_instrument import auto_instrument

lens = FlowLens(service_name="my-agent", export_to="console")
auto_instrument(lens)  # patches Anthropic, OpenAI, LangChain

# your existing code works — traces created automatically
```

### Plugin System

```python
from flowlens.plugins import load_plugin

load_plugin("anthropic")   # or "openai", "langchain"
```

| Framework | What is traced |
|---|---|
| Anthropic | `messages.create`, `messages.stream` |
| OpenAI | `chat.completions.create` (sync/async/streaming) |
| LangChain | Chains, Agents, Tools |

### Decorator-Based (any framework)

```python
@trace_agent(name="my_bot")        # root span, creates the trace
@trace_llm(model="gpt-4o")         # LLM calls — token + cost tracking
@trace_tool(name="search")         # external tools — params + results
@trace_chain(name="pipeline")      # multi-step workflows
@trace_retrieval(name="rag")       # vector search — result count
@trace_embedding(model="ada-002")  # embedding calls — dimensions
```

### Configurable Pattern Thresholds

Override any detector threshold via environment variables:

```bash
export FLOWLENS_RETRY_STORM_THRESHOLD=3       # default: 5
export FLOWLENS_LOOP_REPEAT_THRESHOLD=2       # default: 3
export FLOWLENS_CONTEXT_OVERFLOW_PCT=0.85     # default: 0.90
export FLOWLENS_COLD_START_MS=2000            # default: 5000
```

---

## CLI Reference

```bash
flowlens serve    [--host HOST] [--port PORT] [--db PATH]    # start dashboard server
flowlens analyze  <trace-file.jsonl>                          # analyze trace file
flowlens export   [--format json|csv|jsonl] [--output FILE]   # export traces from DB
flowlens import   <json-file> [--db PATH]                     # import traces
flowlens stats    [--db PATH]                                 # show trace statistics
flowlens health   [--db PATH]                                 # check server & DB status
flowlens demo     [--all] [--dashboard] [--quick]             # run demo examples
flowlens version                                              # show version
```

---

## API Reference

Base URL: `http://localhost:8585` — interactive docs at `/docs`.

### Traces

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/v1/traces/ingest` | Ingest a single trace from the SDK |
| `POST` | `/v1/traces/import` | Bulk import from JSONL file |
| `GET` | `/v1/traces` | List traces with pagination and filters |
| `GET` | `/v1/traces/{trace_id}` | Get complete trace with all spans |
| `DELETE` | `/v1/traces/{trace_id}` | Delete a trace |
| `GET` | `/v1/traces/{trace_id}/dag` | Causal DAG + pattern analysis |
| `GET` | `/v1/traces/errors` | Error traces only |
| `GET` | `/v1/traces/search?q=<query>` | FTS5 full-text search |
| `POST` | `/v1/traces/cleanup` | Delete traces older than N days |
| `POST` | `/v1/traces/{trace_id}/feedback` | Submit trace feedback/annotation (rating, reaction, comment) |
| `GET` | `/v1/feedback/recent` | Get recent trace feedback |

### Agents

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/v1/agents/summary` | Aggregated stats grouped by agent tag |
| `GET` | `/v1/agents/activity` | Recent agent activity events |
| `GET` | `/v1/agents/profiles` | All agent profiles with SVG avatars and roles |
| `GET` | `/v1/agents/network` | Enriched topology for visualization (nodes with color, size, status) |
| `GET` | `/v1/agents/relationships` | Agent spawn graph with call counts and timing |

### Activity & Stats

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/v1/activity/stream` | Time-series activity events with filtering and pagination |
| `GET` | `/v1/stats/trends` | Trace volume trends (hourly/daily) with per-agent breakdown |
| `GET` | `/v1/stats/summary` | Aggregate statistics with per-agent breakdown |
| `GET` | `/v1/stats` | Global aggregate statistics |

### Cost

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/v1/cost/breakdown` | Cost by service, kind, or operation name |
| `GET` | `/v1/cost/trends` | Cost over time (hour/day/week intervals) |
| `GET` | `/v1/cost/forecast` | Monthly cost projection with confidence intervals |

### Patterns & Alerts

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/v1/patterns/summary` | Aggregated pattern counts and rates |
| `GET` | `/v1/alerts/rules` | Configured alert rules |

### Export

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/v1/export/report` | Comprehensive activity report (JSON/CSV/Markdown) |

### Realtime & Health

| Method | Endpoint | Description |
|---|---|---|
| `WS` | `/ws/traces` | WebSocket — broadcasts every ingested trace |
| `GET` | `/health` | Server and database health check |

---

## Documentation

| Doc | Description |
|---|---|
| [Quickstart Guide](docs/quickstart.md) | Step-by-step getting started |
| [API Reference](docs/api-reference.md) | Complete REST API reference |
| [Architecture](docs/architecture.md) | Internals and design decisions |
| [Deployment](docs/deployment.md) | Docker, Docker Compose, production setup |
| [Troubleshooting](docs/troubleshooting.md) | Common issues and solutions |

API docs also available at `http://localhost:8585/docs` when the server is running.

---

## How It Compares

|  | Langfuse | LangSmith | Opik | **FlowLens 1.0** |
|---|:---:|:---:|:---:|:---:|
| Open Source | Yes | No | Yes | **Yes** |
| **Causal DAG Analysis** | No | No | No | **Yes** |
| **Error Cascade Detection** | No | No | No | **Yes** |
| **Anti-Pattern Detection** | No | No | No | **15+ configurable** |
| **SVG Agent Network** | No | No | No | **Yes (lightweight + 3D fallback)** |
| **Agent Team Monitoring** | No | Partial | No | **Yes (real-time + live terminal)** |
| **Agent Avatar System** | No | No | No | **Yes (SVG)** |
| **Session Timeline** | No | No | No | **Yes** |
| **Trace Feedback/Annotations** | No | Partial | No | **Yes (star, emoji, comments)** |
| **Cost Forecasting** | No | No | No | **Yes (monthly projection + confidence)** |
| **LocalCollector (no server)** | No | No | No | **Yes (SQLite)** |
| **FTS5 Full-Text Search** | No | No | No | **Yes** |
| **Budget Alerts (AND rules)** | No | Partial | No | **Yes** |
| Auto-Instrumentation | Partial | Yes | No | **Yes** |
| Plugin System | No | No | No | **Yes** |
| Streaming Support | No | Partial | No | **Yes** |
| WebSocket Live Feed | No | No | No | **Yes** |
| Multiple Exporters | 2 | 1 | 1 | **7** |
| CLI Tools | No | Yes | No | **8 commands** |
| Self-Hosted | Docker | No | Docker | **pip + Docker** |
| Cost Attribution Models | — | — | — | **16+** |

---

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

```bash
git clone https://github.com/yusenthebot/flowlens.git
cd flowlens
pip install -e ".[dev]"
python3 -m pytest tests/ -q   # 1156 tests — all must pass
```

---

## License

[MIT](LICENSE) — Copyright (c) 2024-2026 FlowLens Contributors
