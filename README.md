<div align="center">
  <img src="examples/logo.svg" width="80" alt="FlowLens">
  <h1>FlowLens</h1>
  <p><strong>See what your AI agents are actually doing.</strong></p>
  <p>The observability platform built for LLM agent teams. Think Chrome DevTools, but for your AI.</p>
</div>

<p align="center">
  <a href="https://pypi.org/project/flowlens/"><img src="https://img.shields.io/pypi/v/flowlens.svg" alt="PyPI version"></a>
  <a href="https://github.com/yusenthebot/flowlens/actions"><img src="https://img.shields.io/github/actions/workflow/status/yusenthebot/flowlens/ci.yml?branch=main&label=tests" alt="Tests"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python 3.10+"></a>
  <a href="https://github.com/yusenthebot/flowlens/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://opentelemetry.io/"><img src="https://img.shields.io/badge/OpenTelemetry-compatible-blueviolet.svg" alt="OTEL Compatible"></a>
</p>

<div align="center">
  <img src="examples/screenshot_terminal.png" width="700" alt="Monitor your agents in real-time">
  <br>
  <em>Watch Alpha, Beta, and Gamma work in parallel — every tool call, every file read, every decision.</em>
</div>

---

Ever had an agent burn through $50 in tokens on a retry loop you didn't know about? Or spent an hour debugging a multi-agent workflow, only to discover the root cause was three services away?

We built FlowLens because we were tired of flying blind. When you're running AI agent teams, things break in ways that traditional logging can't catch. An agent silently retries 47 times. Context windows overflow. One slow tool call cascades into a full system stall.

**FlowLens catches all of that in real-time.** It traces every LLM call, tool execution, and decision point — then builds causal error graphs to pinpoint root causes instantly.

> **Try it now:** [**Live Interactive Dashboard**](https://yusenthebot.github.io/flowlens/demo_dashboard.html) | [**Product Tour**](https://yusenthebot.github.io/flowlens/demo_autoplay.html) — no install needed.

---

## Quick Start — Give This to Your Agent

Paste this into Claude Code, Cursor, or any AI coding assistant:

> Set up FlowLens agent observability for this project.
> Install flowlens, add the hook, and start the dashboard.
> Repo: https://github.com/yusenthebot/flowlens

Or do it yourself in 30 seconds:

```bash
pip install flowlens
flowlens demo --dashboard
# Open http://localhost:8585
```

That's it. You'll see a dashboard with sample traces, live agent monitoring, and cost tracking.

---

## What You Get

### Real-time Agent Terminal
*Like htop for your AI agents*

<p align="center">
  <img src="examples/screenshot_terminal.png" alt="Live Terminal — tmux-style floating terminal monitoring agents in real-time" width="820">
</p>

Click any agent to open a tmux-style terminal pane. Watch file reads, bash commands, grep patterns, and LLM calls stream in live. Auto-arranges into a grid when you're monitoring multiple agents. Draggable, resizable, and connected via WebSocket for zero-latency updates.

**Why it matters:** You'll catch a stuck agent in seconds instead of discovering it when the bill arrives.

### Trace Waterfall
*See exactly where time and money go*

<p align="center">
  <img src="examples/screenshot_traces.png" alt="Traces — filterable trace list with agent pills, duration bars, tool breakdowns" width="820">
</p>

Every trace gets a smart summary — "3 Read, 2 Bash, 1 LLM" — instead of a meaningless UUID. Filter by agent, status, duration, or time window. Click into any trace to see an agent-colored waterfall timeline with inline file paths, commands, and cost breakdowns.

**Why it matters:** When a request takes 45 seconds, you'll know exactly which 3-second tool call caused the 42-second cascade.

### Smart Pattern Detection
*12 anti-patterns caught automatically*

<p align="center">
  <img src="examples/screenshot_patterns.png" alt="Pattern Detection — anti-pattern alerts with severity indicators" width="820">
</p>

FlowLens watches for retry storms, infinite loops, context overflow, timeout cascades, token waste, cold start penalties, and more. Each detector has configurable thresholds via environment variables. No rules to write — it just works.

**Why it matters:** The patterns that burn the most money are the ones you don't know about.

### Cost Intelligence
*Know your spend before the bill arrives*

<p align="center">
  <img src="examples/screenshot_cost.png" alt="Cost Analysis — total cost summary, monthly forecast with confidence interval" width="820">
</p>

Token and cost breakdown by model, tool, or service across 16+ models. Monthly projection with confidence intervals. Budget alerts with compound AND conditions that persist across sessions.

**Why it matters:** "We spent $200 yesterday" is less useful than "Agent-3 is using GPT-4 for tasks that Claude Haiku handles fine."

### Session Timeline
*Replay any conversation, step by step*

<p align="center">
  <img src="examples/screenshot_sessions.png" alt="Sessions — session timeline grouped by session_id with trace and span counts" width="820">
</p>

Group traces by session. See the full chronological story of what happened — which agents were involved, how long each step took, what failed, and why. Agent avatars, tool pills, and duration indicators make scanning fast.

**Why it matters:** Debugging a multi-turn conversation without a timeline is like reading a novel with the pages shuffled.

### Agent Network
*See how your agents collaborate*

<p align="center">
  <img src="examples/screenshot_agents.png" alt="Agents — team dashboard with per-agent cards, activity sparklines, and status indicators" width="820">
</p>

Every agent gets a unique SVG avatar, color identity, and dashboard card. See trace counts, error rates, cost, latency, activity sparklines, and recent tool calls at a glance. An interactive SVG network visualization shows spawn hierarchies and call patterns with animated particles and glow effects.

**Why it matters:** In a 5-agent system, knowing *which* agent is the bottleneck saves hours of guesswork.

---

## Instrument in 5 Lines

```python
from flowlens import FlowLens, trace_agent, trace_llm, trace_tool

lens = FlowLens(service_name="my-agent", export_to="http")

@trace_agent(name="researcher")
async def research(topic):
    plan = await plan_research(topic)     # Automatically traced
    docs = await search_knowledge(plan)   # Costs tracked
    return await synthesize(docs)         # Errors caught
```

Or skip decorators entirely with auto-instrumentation:

```python
from flowlens import FlowLens
from flowlens.sdk.auto_instrument import auto_instrument

lens = FlowLens(service_name="my-agent", export_to="http")
auto_instrument(lens)  # patches Anthropic, OpenAI, LangChain — done
```

Console output:
```
[FlowLens] Trace a1b2c3d4... | 3 spans | 142ms | 525 tokens | $0.0026 | OK
```

---

## The Full Dashboard

<p align="center">
  <img src="examples/dashboard_full.png" alt="FlowLens Dashboard — full overview with stat cards, agent team strip, and detail cards" width="820">
  <br><em>Overview: stat cards with trend indicators, agent team strip, per-agent detail cards with cost and error rates</em>
</p>

**Key views:**

| View | What you see |
|---|---|
| **Overview** | Stat cards with sparklines, agent team strip, live activity feed, cost forecasting |
| **Traces** | Smart summaries, quick filter bar, star badges for rated traces, hover preview |
| **Trace Detail** | Agent-colored waterfall, adaptive time ruler, inline file paths, error root cause |
| **Sessions** | Timeline grouped by session_id, trace/span counts, cost, duration per session |
| **Agents** | Team dashboard, per-agent cards, activity sparklines, SVG network graph |
| **Causal DAG** | Interactive error propagation graph, root cause vs cascaded error coloring |
| **Cost** | Cost summary, monthly forecast with confidence intervals, budget alerts |
| **Patterns** | Anti-pattern cards with severity, configurable thresholds, click-to-filter |
| **Compare** | Side-by-side trace comparison with verdict badges and diff progress bars |
| **Feedback** | Star ratings, emoji reactions, comments on any trace |

---

## How It Compares

|  | Langfuse | LangSmith | Opik | **FlowLens** |
|---|:---:|:---:|:---:|:---:|
| Open Source | Yes | No | Yes | **Yes** |
| Causal DAG Analysis | -- | -- | -- | **Yes** |
| Error Cascade Detection | -- | -- | -- | **Yes** |
| Anti-Pattern Detection | -- | -- | -- | **15+ configurable** |
| Agent Team Monitoring | -- | Partial | -- | **Real-time + live terminal** |
| Session Timeline | -- | -- | -- | **Yes** |
| Cost Forecasting | -- | -- | -- | **Monthly + confidence** |
| LocalCollector (no server) | -- | -- | -- | **SQLite** |
| FTS5 Full-Text Search | -- | -- | -- | **Yes** |
| Auto-Instrumentation | Partial | Yes | -- | **Yes** |
| WebSocket Live Feed | -- | -- | -- | **Yes** |
| Exporters | 2 | 1 | 1 | **7** |
| CLI Commands | -- | Yes | -- | **8** |
| Self-Hosted | Docker | No | Docker | **pip + Docker** |

---

## Examples

No API keys needed — all examples use simulated data:

```bash
python3 examples/quickstart.py           # basic tracing in 30 seconds
python3 examples/rag_pipeline.py         # full RAG: embed, search, rerank, generate
python3 examples/multi_agent.py          # 4-agent collaboration with retry logic
python3 examples/cost_optimizer.py       # compare model strategies, find savings
python3 examples/live_dashboard.py       # launch dashboard with sample data
python3 examples/auto_instrument_example.py  # zero-decorator auto-instrumentation
```

| Example | What it demonstrates |
|---|---|
| [`quickstart.py`](examples/quickstart.py) | Basic tracing with 4 decorators, colored trace tree output |
| [`rag_pipeline.py`](examples/rag_pipeline.py) | RAG pipeline: embedding, vector search, reranking, generation |
| [`multi_agent.py`](examples/multi_agent.py) | Planner, Researcher, Writer, Reviewer with rejection and retry |
| [`cost_optimizer.py`](examples/cost_optimizer.py) | Compare sonnet+haiku vs opus vs gpt-4o, cost bar charts |
| [`live_dashboard.py`](examples/live_dashboard.py) | Generate traces, start server, open browser to dashboard |
| [`auto_instrument_example.py`](examples/auto_instrument_example.py) | Patch Anthropic/OpenAI/LangChain with zero decorators |
| [`demo_dashboard.html`](https://yusenthebot.github.io/flowlens/demo_dashboard.html) | Interactive dashboard demo (no install) |
| [`demo_autoplay.html`](https://yusenthebot.github.io/flowlens/demo_autoplay.html) | Auto-playing product tour (no install) |

---

## Architecture

```
+------------------------------------------------------------------+
|                         Your Agent Code                          |
|   @trace_agent  .  @trace_llm  .  @trace_tool                   |
|   @trace_chain  .  @trace_retrieval  .  auto_instrument()        |
+---------------+--------------------------------------------------+
                |
        +-------v--------+            +-----------------------------+
        |   SDK Layer     |            |      Analysis Layer         |
        |                 |            |                             |
        | . TraceContext   |            | . Causal DAG Builder        |
        | . SpanContext    |            | . 15+ Pattern Detectors     |
        | . Exporters      |            |   (configurable thresholds) |
        |   Console/CSV    |            | . Root Cause Identification |
        |   HTTP/OTLP      |            | . Cost Engine (16+ models)  |
        |   JSONL/Local    |            | . Multi-Trace Correlator    |
        | . Plugins        |            | . Budget Alert Engine       |
        | . LocalCollector |            |   (AND compound conditions) |
        +-------+---------+            +-----------^-----------------+
                |                                  |
                +------------------>  +------------+------------------+
                      export          |       Server Layer             |
                                      |                                |
                                      | . FastAPI REST API (25+ routes)|
                                      | . 6 Modular route modules      |
                                      | . Trace ingest validation      |
                                      | . WebSocket live feed          |
                                      | . SQLite + FTS5 full-text      |
                                      | . Agent APIs (profiles, net)   |
                                      | . SVG Dashboard (single-page)  |
                                      +--------------------------------+
```

**Three layers:**

1. **SDK Layer** (`flowlens/sdk/`): Instrumentation via decorators and auto-patching, context propagation, data collection, and export.
2. **Analysis Layer** (`flowlens/analysis/`): Post-trace processing — causal DAG construction, error classification, pattern detection, cost estimation.
3. **Server Layer** (`flowlens/server/`): FastAPI REST API with 6 modular route modules, real-time WebSocket broadcasting, persistence, and static dashboard serving.

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
| `POST` | `/v1/traces/{trace_id}/feedback` | Submit trace feedback (rating, reaction, comment) |
| `GET` | `/v1/feedback/recent` | Get recent trace feedback |

### Agents

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/v1/agents/summary` | Aggregated stats grouped by agent tag |
| `GET` | `/v1/agents/activity` | Recent agent activity events |
| `GET` | `/v1/agents/profiles` | All agent profiles with SVG avatars |
| `GET` | `/v1/agents/network` | Enriched topology for visualization |
| `GET` | `/v1/agents/relationships` | Agent spawn graph with call counts |

### Activity & Stats

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/v1/activity/stream` | Time-series activity events |
| `GET` | `/v1/stats/trends` | Trace volume trends (hourly/daily) |
| `GET` | `/v1/stats/summary` | Aggregate statistics with per-agent breakdown |
| `GET` | `/v1/stats` | Global aggregate statistics |

### Cost

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/v1/cost/breakdown` | Cost by service, kind, or operation |
| `GET` | `/v1/cost/trends` | Cost over time (hour/day/week) |
| `GET` | `/v1/cost/forecast` | Monthly projection with confidence intervals |

### Patterns & Alerts

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/v1/patterns/summary` | Aggregated pattern counts and rates |
| `GET` | `/v1/alerts/rules` | Configured alert rules |

### Export & Realtime

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/v1/export/report` | Comprehensive activity report (JSON/CSV/Markdown) |
| `WS` | `/ws/traces` | WebSocket — broadcasts every ingested trace |
| `GET` | `/health` | Server and database health check |

---

## Integrations

### Decorator-Based (any framework)

```python
@trace_agent(name="my_bot")        # root span, creates the trace
@trace_llm(model="gpt-4o")         # LLM calls — token + cost tracking
@trace_tool(name="search")         # external tools — params + results
@trace_chain(name="pipeline")      # multi-step workflows
@trace_retrieval(name="rag")       # vector search — result count
@trace_embedding(model="ada-002")  # embedding calls — dimensions
```

### Auto-Instrumentation (zero decorators)

| Framework | What is traced |
|---|---|
| Anthropic | `messages.create`, `messages.stream` |
| OpenAI | `chat.completions.create` (sync/async/streaming) |
| LangChain | Chains, Agents, Tools |

### Configurable Pattern Thresholds

```bash
export FLOWLENS_RETRY_STORM_THRESHOLD=3       # default: 5
export FLOWLENS_LOOP_REPEAT_THRESHOLD=2       # default: 3
export FLOWLENS_CONTEXT_OVERFLOW_PCT=0.85     # default: 0.90
export FLOWLENS_COLD_START_MS=2000            # default: 5000
```

### LocalCollector (no server needed)

```python
from flowlens.local import LocalCollector

collector = LocalCollector(db_path="./traces.db")
collector.ingest(trace)
results = collector.search("timeout")
stats = collector.stats()
```

### Plugin System

```python
from flowlens.plugins import load_plugin

load_plugin("anthropic")   # or "openai", "langchain"
```

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

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

```bash
git clone https://github.com/yusenthebot/flowlens.git
cd flowlens
pip install -e ".[dev]"
python3 -m pytest tests/ -q   # 1156 tests — all must pass
```

---

## Ready to see what your agents are doing?

```bash
pip install flowlens && flowlens demo --dashboard
```

**Star this repo** if FlowLens saved you from a $50 retry loop.

---

[MIT](LICENSE) — Copyright (c) 2024-2026 FlowLens Contributors
