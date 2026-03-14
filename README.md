<p align="center">
  <h1 align="center">🔍 FlowLens</h1>
  <p align="center"><strong>Agent Observability Platform — Chrome DevTools for LLM Agents</strong></p>
</p>

<p align="center">
  <a href="https://pypi.org/project/flowlens/"><img src="https://img.shields.io/pypi/v/flowlens.svg" alt="PyPI version"></a>
  <a href="https://pypi.org/project/flowlens/"><img src="https://img.shields.io/pypi/dm/flowlens.svg" alt="PyPI downloads"></a>
  <a href="https://github.com/niceyusen/flowlens/actions"><img src="https://img.shields.io/github/actions/workflow/status/niceyusen/flowlens/ci.yml?branch=main&label=tests" alt="Tests"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python 3.10+"></a>
  <a href="https://github.com/niceyusen/flowlens/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://opentelemetry.io/"><img src="https://img.shields.io/badge/OpenTelemetry-compatible-blueviolet.svg" alt="OTEL Compatible"></a>
</p>

> FlowLens shows you **why** your AI agent failed, not just *that* it failed. It traces every LLM call, tool execution, and decision point — then builds **causal error graphs** so you can pinpoint root causes instantly.

<p align="center">
  <img src="examples/dashboard_full.png" alt="FlowLens Dashboard" width="820">
</p>

> **Try the interactive demo:** Open [`examples/demo_dashboard.html`](examples/demo_dashboard.html) in your browser — no server needed.

---

## ✨ Features

- **Causal DAG Analysis** — distinguishes root causes from cascaded failures across your entire agent run
- **5 Anti-Pattern Detectors** — retry storms, infinite loops, context overflow, timeout cascades, empty responses
- **Zero-Intrusion Tracing** — five decorators instrument any Python agent without touching business logic
- **Auto-Instrumentation** — one call patches Anthropic, OpenAI, and LangChain automatically
- **Multi-Dimensional Cost Attribution** — token + cost breakdown by model, tool, task, or service (16+ models)
- **Streaming Trace Support** — accurate token counts for streamed LLM responses
- **Real-Time Dashboard** — FastAPI server with WebSocket live feed at `http://localhost:8585`
- **Framework Agnostic** — works with LangChain, CrewAI, AutoGen, or any custom Python agent

---

## 🚀 Quick Start

### 1. Install

```bash
pip install flowlens
```

### 2. Instrument

```python
from flowlens import FlowLens, trace_agent, trace_llm, trace_tool

lens = FlowLens(service_name="my-agent", export_to="console")

@trace_agent(name="research_bot")
async def run_agent(task: str):
    plan = await think(task)
    result = await search(plan)
    return result

@trace_llm(model="claude-sonnet-4-20250514")
async def think(task: str):
    return await anthropic_client.messages.create(...)

@trace_tool(name="web_search")
async def search(query: str):
    return await search_api.query(query)
```

### 3. Visualize

```bash
flowlens-server          # starts dashboard at http://localhost:8585
```

Switch your exporter to send traces to the server:

```python
lens = FlowLens(service_name="my-agent", export_to="http",
                endpoint="http://localhost:8585/v1/traces/ingest")
```

Console output on every run:

```
[FlowLens] Trace a1b2c3d4 | 8 spans | 1847ms | 2967 tokens | $0.0190 | ERROR
  agent research_bot (1847ms)
  ├─ llm think (312ms) [856 tok]
  ├─ tool web_search (2003ms) ERROR timeout
  ├─ tool fetch_page (5ms) ERROR no input from search
  └─ llm synthesize (278ms) [1666 tok]
```

---

## 📊 Dashboard

<p align="center">
  <img src="examples/screenshot_overview.png" alt="Trace Overview" width="720">
</p>

<p align="center">
  <img src="examples/screenshot_dag.png" alt="Causal Error DAG" width="720">
</p>

The dashboard gives you:

- **Trace list** — filterable by service, status, cost, and time range
- **Span timeline** — waterfall view of every LLM call and tool execution
- **Causal DAG** — visual graph showing how one failure cascades into others
- **Cost trends** — token spend over time, broken down by model or task type
- **Pattern alerts** — anti-patterns surfaced automatically per trace

> Open [`examples/demo_dashboard.html`](examples/demo_dashboard.html) for a fully interactive preview with sample data — no installation required.

---

## 🔧 Examples

| File | What it shows |
|---|---|
| [`examples/quickstart.py`](examples/quickstart.py) | Five progressive examples from zero to full observability |
| [`examples/demo_agent.py`](examples/demo_agent.py) | Full RAG research agent with intentional failures and causal analysis |
| [`examples/auto_instrument_example.py`](examples/auto_instrument_example.py) | Zero-code tracing via auto-instrumentation |
| [`examples/multi_trace_analysis.py`](examples/multi_trace_analysis.py) | Fleet-wide pattern analysis across many traces |
| [`examples/server_demo.py`](examples/server_demo.py) | API server walkthrough with live WebSocket feed |

Run the demo agent (no LLM API key needed — uses mocked responses):

```bash
python3 examples/quickstart.py
python3 examples/demo_agent.py
```

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     Your Agent Code                       │
│   @trace_agent  ·  @trace_llm  ·  @trace_tool            │
│   @trace_chain  ·  @trace_retrieval  ·  auto_instrument() │
└──────────────┬───────────────────────────────────────────┘
               │
       ┌───────▼───────┐            ┌─────────────────────┐
       │   SDK Layer    │            │   Analysis Layer     │
       │               │            │                      │
       │ · TraceContext │            │ · DAG Builder        │
       │ · SpanContext  │            │ · Pattern Detectors  │
       │ · Exporters    │            │ · Root Cause ID      │
       │   Console      │            │ · Cost Engine        │
       │   JSONL        │            └──────────▲──────────┘
       │   HTTP         │                       │
       │   OTLP         │            ┌──────────┴──────────┐
       │ · Auto-Instr.  │            │    Server Layer      │
       └───────┬───────┘            │                      │
               └───────────────►    │ · FastAPI REST API   │
                    export          │ · WebSocket feed     │
                                    │ · SQLite storage     │
                                    │ · Live Dashboard     │
                                    └─────────────────────┘
```

**SDK** (`flowlens/sdk/`) — Async-safe tracing via `contextvars`. Builds parent-child span trees automatically. Four exporters: Console, JSONL, HTTP, OTLP.

**Analysis** (`flowlens/analysis/`) — Causal DAG engine classifies errors as ROOT_CAUSE, CASCADED, or INDEPENDENT. Five pattern detectors surface anti-patterns.

**Server** (`flowlens/server/`) — FastAPI with async SQLite. 15+ REST endpoints plus real-time WebSocket broadcast.

---

## 🔌 Integrations

### Auto-Instrumentation (zero decorators)

```python
from flowlens import FlowLens
from flowlens.sdk.auto_instrument import auto_instrument

lens = FlowLens(service_name="my-agent", export_to="http")
auto_instrument(lens)  # patches Anthropic, OpenAI, LangChain at import time

# Your existing code — unchanged
import anthropic
client = anthropic.Anthropic()
response = client.messages.create(model="claude-sonnet-4-20250514", ...)
# A trace was created automatically
```

| Framework | What is traced |
|---|---|
| `anthropic` | All `messages.create` and `messages.stream` calls |
| `openai` | All `chat.completions.create` calls |
| `langchain` | LLM calls, tool invocations, chain executions |

### Decorator-Based (any framework)

```python
@trace_agent(name="my_bot")        # trace root, creates the trace
@trace_llm(model="gpt-4o")         # LLM calls — token + cost tracking
@trace_tool(name="search")         # external tools — params + results
@trace_chain(name="pipeline")      # multi-step workflows
@trace_retrieval(name="rag")       # vector search — result count
```

---

## 📖 Documentation

| Doc | Description |
|---|---|
| [docs/quickstart.md](docs/quickstart.md) | Step-by-step getting started guide |
| [docs/api-reference.md](docs/api-reference.md) | Complete REST API reference (15+ endpoints) |
| [docs/architecture.md](docs/architecture.md) | Internals, design decisions, and extension points |
| [docs/deployment.md](docs/deployment.md) | Docker, Docker Compose, and production deployment |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common issues and solutions |

Interactive API docs are available at `http://localhost:8585/docs` when the server is running.

---

## How It Compares

|  | Langfuse | LangSmith | Opik | **FlowLens** |
|---|:---:|:---:|:---:|:---:|
| Open Source | Yes | No | Yes | **Yes** |
| Framework Agnostic | Yes | No | Yes | **Yes** |
| **Causal DAG Analysis** | No | No | No | **Yes** |
| **Error Cascade Detection** | No | No | No | **Yes** |
| **Anti-Pattern Detection** | No | No | No | **Yes** |
| Auto-Instrumentation | Partial | Yes | No | **Yes** |
| Streaming Trace Support | No | Partial | No | **Yes** |
| WebSocket Live Feed | No | No | No | **Yes** |
| Cost Attribution | Basic | Basic | Basic | **Multi-dim** |
| Self-Hosted | Docker | No | Docker | **pip + Docker** |

---

## 🤝 Contributing

Contributions are welcome. Please feel free to submit a Pull Request. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

```bash
git clone https://github.com/niceyusen/flowlens.git
cd flowlens
pip install -e ".[dev]"
python3 -m pytest tests/ -q   # 746 tests — all must pass before submitting
```

---

## 📄 License

[MIT](LICENSE) — Copyright (c) 2026 Yusen
