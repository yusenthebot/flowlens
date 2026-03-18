<p align="right">
  <a href="README_EN.md">English</a> | <a href="README.md">中文</a>
</p>

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

> **Try it now:** [**Live Interactive Dashboard**](https://yusenthebot.github.io/flowlens/demo_dashboard.html) | [**Product Tour**](https://yusenthebot.github.io/flowlens/demo_autoplay.html) — no install needed

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
# Open http://localhost:8585 🎉
```

That's it. You'll see a dashboard with sample traces, live agent monitoring, and cost tracking.

---

## What You Get

### Real-time Agent Terminal
*Like htop for your AI agents*

<p align="center">
  <img src="examples/screenshot_terminal.png" alt="Live Terminal" width="820">
</p>

Click any agent to open a tmux-style terminal pane. Watch file reads, bash commands, grep patterns, and LLM calls stream in live. Auto-arranges into a grid when you're monitoring multiple agents. Draggable, resizable, and connected via WebSocket for zero-latency updates.

**Why it matters:** You'll catch a stuck agent in seconds instead of discovering it when the bill arrives.

### Trace Waterfall
*See exactly where time and money go*

<p align="center">
  <img src="examples/screenshot_traces.png" alt="Traces" width="820">
</p>

Every trace gets a smart summary — "3 Read, 2 Bash, 1 LLM" — instead of a meaningless UUID. Filter by agent, status, duration, or time window. Click into any trace to see an agent-colored waterfall timeline with inline file paths, commands, and cost breakdowns.

**Why it matters:** When a request takes 45 seconds, you'll know exactly which 3-second tool call caused the 42-second cascade.

### Smart Pattern Detection
*12 anti-patterns caught automatically*

<p align="center">
  <img src="examples/screenshot_patterns.png" alt="Pattern Detection" width="820">
</p>

FlowLens watches for retry storms, infinite loops, context overflow, timeout cascades, token waste, and more. Each detector has configurable thresholds via environment variables. No rules to write — it just works.

**Why it matters:** The patterns that burn the most money are the ones you don't know about.

### Cost Intelligence
*Know your spend before the bill arrives*

<p align="center">
  <img src="examples/screenshot_cost.png" alt="Cost Analysis" width="820">
</p>

Token and cost breakdown by model, tool, or service across 16+ models. Monthly projection with confidence intervals. Budget alerts with compound AND conditions.

**Why it matters:** "We spent $200 yesterday" is less useful than "Agent-3 is using GPT-4 for tasks that Claude Haiku handles fine."

### Session Timeline
*Replay any conversation, step by step*

<p align="center">
  <img src="examples/screenshot_sessions.png" alt="Sessions" width="820">
</p>

Group traces by session. See the full chronological story — which agents were involved, how long each step took, what failed, and why.

### Agent Network
*See how your agents collaborate*

<p align="center">
  <img src="examples/screenshot_agents.png" alt="Agents" width="820">
</p>

Every agent gets a unique avatar, color, and dashboard card. See trace counts, error rates, cost, latency, and activity sparklines at a glance. An interactive SVG network shows spawn hierarchies with animated particles.

### Permissions
*View all Claude Code agent permissions*

See every permission granted or denied to each agent — file reads, bash execution, network access, and more. Permissions are read directly from `.claude/settings.local.json` with no additional configuration required. Instantly identify high-privilege agents for security review and compliance auditing.

### Evaluation Engine
*5 built-in evaluators + LLM Judge + datasets*

Systematically evaluate agent output quality. Five built-in evaluators (ExactMatch, ContainsKeywords, JsonSchemaValid, CostThreshold, LatencyThreshold) plus an LLM-based semantic judge. Supports dataset management and batch evaluation runs.

```bash
flowlens eval run   --trace-id <id> --evaluator exact_match   # run a single evaluation
flowlens eval gate  --dataset <name> --threshold 0.8           # batch quality gate
```

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

Or skip decorators with auto-instrumentation:

```python
from flowlens import FlowLens
from flowlens.sdk.auto_instrument import auto_instrument

lens = FlowLens(service_name="my-agent", export_to="http")
auto_instrument(lens)  # patches Anthropic, OpenAI, LangChain
```

---

## How It Compares

|  | Langfuse | LangSmith | Opik | **FlowLens** |
|---|:---:|:---:|:---:|:---:|
| Open Source | ✅ | ❌ | ✅ | **✅** |
| Causal DAG Analysis | — | — | — | **✅** |
| Anti-Pattern Detection | — | — | — | **15+ configurable** |
| Agent Team Monitoring | — | Partial | — | **Real-time + terminal** |
| Session Timeline | — | — | — | **✅** |
| Cost Forecasting | — | — | — | **Monthly + CI** |
| Auto-Instrumentation | Partial | ✅ | — | **✅** |
| WebSocket Live Feed | — | — | — | **✅** |
| Self-Hosted | Docker | ❌ | Docker | **pip + Docker** |

---

## Architecture

```
+------------------------------------------------------------------+
|                         Your Agent Code                          |
|   @trace_agent  .  @trace_llm  .  @trace_tool                   |
+---------------+--------------------------------------------------+
                |
        +-------v--------+            +-----------------------------+
        |   SDK Layer     |            |      Analysis Layer         |
        |                 |            |                             |
        | . TraceContext   |            | . Causal DAG Builder        |
        | . Exporters x7   |            | . 15+ Pattern Detectors     |
        | . Auto-Instrument|            | . Cost Engine (16+ models)  |
        | . Plugins        |            | . Budget Alert Engine       |
        +-------+---------+            +-----------^-----------------+
                |                                  |
                +------------------>  +------------+------------------+
                      export          |       Server Layer             |
                                      |                                |
                                      | . FastAPI REST API (25+ routes)|
                                      | . WebSocket live feed          |
                                      | . SQLite + FTS5 full-text      |
                                      | . SVG Dashboard (single-page)  |
                                      +--------------------------------+
```

---

## CLI Reference

```bash
flowlens serve    [--host HOST] [--port PORT] [--db PATH]    # start dashboard
flowlens analyze  <trace-file.jsonl>                          # analyze traces
flowlens export   [--format json|csv|jsonl] [--output FILE]   # export from DB
flowlens import   <json-file> [--db PATH]                     # import traces
flowlens stats    [--db PATH]                                 # show statistics
flowlens health   [--db PATH]                                 # health check
flowlens demo     [--all] [--dashboard] [--quick]             # run demos
flowlens eval run  --trace-id <id> [--evaluator NAME]         # run an evaluation
flowlens eval gate --dataset <name> [--threshold FLOAT]       # batch quality gate
flowlens version                                              # show version
```

---

## Examples

No API keys needed:

```bash
python3 examples/quickstart.py           # basic tracing
python3 examples/rag_pipeline.py         # full RAG pipeline
python3 examples/multi_agent.py          # 4-agent collaboration
python3 examples/cost_optimizer.py       # compare model costs
python3 examples/live_dashboard.py       # launch dashboard
```

| Example | Description |
|---|---|
| [`quickstart.py`](examples/quickstart.py) | Basic tracing with decorators |
| [`rag_pipeline.py`](examples/rag_pipeline.py) | RAG: embed, search, rerank, generate |
| [`multi_agent.py`](examples/multi_agent.py) | Multi-agent with retry logic |
| [`cost_optimizer.py`](examples/cost_optimizer.py) | Compare model strategies |
| [`demo_dashboard.html`](https://yusenthebot.github.io/flowlens/demo_dashboard.html) | Interactive dashboard (no install) |
| [`demo_autoplay.html`](https://yusenthebot.github.io/flowlens/demo_autoplay.html) | Product tour (no install) |

---

## Documentation

| Doc | Description |
|---|---|
| [Quickstart Guide](docs/quickstart.md) | Step-by-step getting started |
| [API Reference](docs/api-reference.md) | Complete REST API |
| [Architecture](docs/architecture.md) | Internals and design |
| [Deployment](docs/deployment.md) | Docker, production setup |
| [Troubleshooting](docs/troubleshooting.md) | Common issues |

---

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md).

```bash
git clone https://github.com/yusenthebot/flowlens.git
cd flowlens
pip install -e ".[dev]"
python3 -m pytest tests/ -q   # 1156 tests
```

---

## Ready to see what your agents are doing?

```bash
pip install flowlens && flowlens demo --dashboard
```

**Star this repo** if FlowLens saved you from a $50 retry loop. ⭐

---

[MIT](LICENSE) — Copyright (c) 2024-2026 FlowLens Contributors
