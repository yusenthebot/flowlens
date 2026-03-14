<p align="center">
  <h1 align="center">FlowLens</h1>
  <p align="center"><strong>Agent Observability Platform — Chrome DevTools for LLM Agents</strong></p>
</p>

<p align="center">
  <a href="https://github.com/niceyusen/flowlens/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python 3.10+"></a>
  <a href="https://pypi.org/project/flowlens/"><img src="https://img.shields.io/badge/version-0.1.0-green.svg" alt="Version"></a>
  <a href="https://github.com/niceyusen/flowlens/actions"><img src="https://img.shields.io/badge/tests-46%20passed-brightgreen.svg" alt="Tests"></a>
  <a href="https://opentelemetry.io/"><img src="https://img.shields.io/badge/OpenTelemetry-compatible-blueviolet.svg" alt="OTEL"></a>
</p>

<p align="center">
  FlowLens helps you understand <em>why</em> your AI agent failed, not just <em>that</em> it failed.<br>
  It traces every LLM call, tool execution, and decision point, then automatically builds<br>
  <strong>causal error graphs</strong> so you can see exactly how failures propagate through your agent.
</p>

---

## The Problem

You built an LLM agent. It works 80% of the time. When it fails, you stare at logs wondering:

- Was it a bad LLM response? A tool timeout? A cascading error from three steps ago?
- How much did that failed run cost?
- Is this the same failure pattern you saw last week?

Existing tools (Langfuse, LangSmith, Opik) show you *what* happened. **FlowLens shows you *why*.**

## Demo

<p align="center">
  <img src="examples/dashboard_full.png" alt="FlowLens Dashboard" width="800">
</p>

<details>
<summary>📊 Trace Overview & Execution Timeline</summary>
<p align="center">
  <img src="examples/screenshot_overview.png" alt="Trace Overview" width="700">
</p>
</details>

<details>
<summary>🔍 Causal Error DAG</summary>
<p align="center">
  <img src="examples/screenshot_dag.png" alt="Causal DAG" width="700">
</p>
</details>

## Key Features

### 🔬 Causal DAG Analysis
Not just "what failed" but "why it failed and how the error spread." FlowLens builds directed acyclic graphs showing error propagation paths, distinguishing **root causes** from **cascaded failures**.

### 🎯 Zero-Intrusion Tracing
Three decorators instrument your code without changing any business logic. Framework-agnostic — works with **any** Python agent (LangChain, CrewAI, AutoGen, custom).

```python
@trace_agent(name="my_bot")    # Wraps agent entry point
@trace_llm(model="claude-4")   # Wraps LLM calls, extracts tokens
@trace_tool(name="search")     # Wraps tool calls, captures params
```

### 🔄 Pattern Detection
Automatically detects 5 anti-patterns in agent execution:

| Pattern | Description |
|---|---|
| **Retry Storm** | Same tool called ≥5 times (flaky API, bad retry logic) |
| **Infinite Loop** | Repeating tool sequences (A→B→A→B→A→B) |
| **Context Overflow** | Token usage >90% of model's context window |
| **Timeout Cascade** | Timeout causing downstream failures |
| **Empty Response** | LLM returns 0 output tokens |

### 💰 Multi-Dimensional Cost Attribution
Know exactly how many tokens each step consumed and what it cost, broken down by **model**, **tool**, **task type**, or **service**. Supports 11+ models out of the box:

| Provider | Models |
|---|---|
| Anthropic | Claude Opus 4, Sonnet 4, Haiku 3.5 |
| OpenAI | GPT-4o, GPT-4o-mini, o1, o1-mini |
| Google | Gemini 1.5 Pro, Gemini 1.5 Flash |
| DeepSeek | DeepSeek V3, DeepSeek R1 |

### 🌐 REST API + Storage
FastAPI server with async SQLite storage. Ingest traces, query history, get causal analysis — all via API.

## Tech Stack

| Component | Technology | Purpose |
|---|---|---|
| **Language** | Python 3.10+ | Async-first with `asyncio`, `contextvars` |
| **Web Framework** | FastAPI ≥0.110 | Async REST API with auto-generated OpenAPI docs |
| **ASGI Server** | Uvicorn ≥0.27 | High-performance async server |
| **Database** | SQLite via aiosqlite ≥0.20 | Zero-config async storage |
| **Validation** | Pydantic ≥2.0 | Request/response schema validation |
| **Telemetry** | OpenTelemetry (optional) | OTLP export, GenAI semantic conventions |
| **Testing** | pytest ≥8.0 + pytest-asyncio | 46 tests, async-native |
| **HTTP Client** | httpx ≥0.27 | Async test client for FastAPI |

## Quick Start

### Installation

```bash
# From source (recommended for now):
git clone https://github.com/niceyusen/flowlens.git
cd flowlens
pip install -e ".[dev]"

# With OpenTelemetry export support:
pip install -e ".[dev,otlp]"
```

### 1. Instrument Your Agent (3 lines of code)

```python
from flowlens import FlowLens, trace_agent, trace_llm, trace_tool

# Initialize — pick an exporter
lens = FlowLens(service_name="my-agent", export_to="console", verbose=True)

@trace_agent(name="research_bot")
async def run_agent(task: str):
    plan = await think(task)
    result = await execute(plan)
    return result

@trace_llm(model="claude-sonnet-4-20250514")
async def think(task: str):
    # Works with any LLM client — Anthropic, OpenAI, etc.
    return await client.messages.create(
        model="claude-sonnet-4-20250514",
        messages=[{"role": "user", "content": task}]
    )

@trace_tool(name="web_search")
async def search(query: str):
    return await search_api.query(query)
```

### 2. Run Your Agent — See Traces Immediately

```
[FlowLens] Trace a1b2c3d4 | 8 spans | 1847ms | 2967 tokens | $0.0190 | ERROR
  🤖 research_bot (1847ms)
  ├─ 🧠 plan_research (312ms) [856 tok]
  ├─ 🔧 web_search (2003ms) ❌ timeout
  ├─ 🔧 fetch_page (5ms) ❌ no input from search
  ├─ 🧠 decide_retry (201ms) [445 tok]
  ├─ 🔧 web_search (150ms) ✓
  ├─ 🔧 fetch_page (89ms) ✓
  └─ 🧠 synthesize (278ms) [1666 tok]
```

### 3. Analyze — Find Root Causes Automatically

```python
from flowlens.analysis.dag_builder import build_causal_dag
from flowlens.analysis.patterns import detect_patterns

dag = build_causal_dag(trace)
patterns = detect_patterns(trace, dag)

print(dag.root_causes)                  # ['web_search_span_id']
print(dag.cascade_depth)                # 1
print(patterns[0].pattern_type)         # PatternType.TIMEOUT_CASCADE
print(patterns[0].details["timeout"])   # 'web_search'
```

### 4. Run the API Server

```bash
uvicorn flowlens.server.app:create_app --factory --port 8585
```

**API Endpoints:**

```
POST /v1/traces/ingest          Receive trace data
POST /v1/traces/import          Import JSONL trace file
GET  /v1/traces                 List traces (paginated, filterable)
GET  /v1/traces/{id}            Full trace with all spans
GET  /v1/traces/{id}/dag        Causal DAG analysis
GET  /v1/cost/breakdown         Cost attribution (group by service/kind/name)
GET  /v1/stats                  Global statistics
GET  /health                    Health check
```

## Run the Demo

```bash
python -m examples.demo_agent
```

This runs a research agent that **intentionally fails** — a search timeout cascades into a fetch failure, triggers a retry, and eventually succeeds. The demo then prints a full causal analysis report showing root causes, cascaded errors, and detected patterns.

<details>
<summary>📋 Sample Demo Output</summary>

```
════════════════════════════════════════════════════════════════
  FlowLens — Causal Analysis Report
════════════════════════════════════════════════════════════════

Trace: f7a1...c3d4 | research_agent | 8 spans | 1847ms

Root Causes (1):
  ✗ web_search [TOOL] — "Connection timeout after 2000ms"

Cascaded Errors (1):
  ↳ fetch_page [TOOL] — "Invalid input: empty URL from search"
    caused by: web_search (timeout → no output → fetch fails)

Detected Patterns:
  ⚠ TIMEOUT_CASCADE (severity: high)
    web_search timeout caused 1 downstream failure

Cost: 2967 tokens | $0.019
  plan_research:  856 tok ($0.005)
  decide_retry:   445 tok ($0.003)
  synthesize:    1666 tok ($0.011)
```

</details>

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Your Agent Code                      │
│   @trace_agent  ·  @trace_llm  ·  @trace_tool           │
└──────────────┬──────────────────────────────┬────────────┘
               │                              │
       ┌───────▼───────┐             ┌────────▼────────┐
       │   SDK Layer    │             │  Analysis Layer  │
       │               │             │                  │
       │ · TraceContext │             │ · DAG Builder    │
       │ · SpanContext  │             │ · Pattern Detect │
       │ · Exporters    │             │ · Root Cause ID  │
       │   (Console,    │             │ · Cost Engine    │
       │    JSONL,      │             └────────▲────────┘
       │    HTTP,       │                      │
       │    Callback)   │             ┌────────┴────────┐
       └───────┬───────┘             │  Server Layer    │
               │                      │                  │
               │                      │ · FastAPI REST   │
               └──────────►           │ · SQLite Store   │
                   export             │ · Query + Filter │
                                      └─────────────────┘
```

**SDK** (`flowlens/sdk/`) — Zero-intrusion tracing via Python decorators. Uses `contextvars.ContextVar` for async-safe parent-child span linking. Four exporters: Console (colored), JSONL (file), HTTP (to server), Callback (for testing).

**Analysis** (`flowlens/analysis/`) — Causal DAG engine that builds directed acyclic graphs from trace spans. Classifies errors as ROOT_CAUSE, CASCADED, or INDEPENDENT. Five pattern detectors run over the DAG to surface anti-patterns.

**Server** (`flowlens/server/`) — FastAPI application with async SQLite storage. Full CRUD for traces, plus causal DAG analysis and multi-dimensional cost breakdowns via REST API.

## How It Compares

|  | Langfuse | LangSmith | Opik | **FlowLens** |
|---|:---:|:---:|:---:|:---:|
| Open Source | ✅ | ❌ | ✅ | ✅ |
| Framework Agnostic | ✅ | ❌ | ✅ | ✅ |
| **Causal DAG Analysis** | ❌ | ❌ | ❌ | ✅ |
| **Error Cascade Detection** | ❌ | ❌ | ❌ | ✅ |
| **Anti-Pattern Detection** | ❌ | ❌ | ❌ | ✅ |
| Cost Attribution | Basic | Basic | Basic | **Multi-dim** |
| Zero-Config Storage | ❌ | ❌ | ✅ | ✅ |
| OTEL GenAI Conventions | ❌ | ❌ | ❌ | ✅ |
| Self-Hosted | Docker | ❌ | Docker | **pip install** |

## Project Structure

```
flowlens/
├── flowlens/
│   ├── __init__.py              # Public API exports
│   ├── sdk/
│   │   ├── models.py            # Span, Trace, TokenUsage, cost pricing
│   │   ├── context.py           # Async-safe context (contextvars)
│   │   ├── tracer.py            # FlowLens singleton, trace lifecycle
│   │   ├── decorators.py        # @trace_agent, @trace_llm, @trace_tool
│   │   └── exporters.py         # Console, JSONL, HTTP, Callback exporters
│   ├── analysis/
│   │   ├── models.py            # CausalDAG, CausalNode, CausalEdge, DetectedPattern
│   │   ├── dag_builder.py       # build_causal_dag() — core algorithm
│   │   └── patterns.py          # 5 pattern detectors
│   └── server/
│       ├── app.py               # FastAPI application (8 endpoints)
│       └── storage.py           # Async SQLite storage (TraceStore)
├── tests/
│   ├── test_models.py           # 15 tests — Span, Trace, cost estimation
│   ├── test_decorators.py       #  8 tests — decorators, nested spans
│   ├── test_dag.py              # 10 tests — DAG builder, pattern detection
│   └── test_server.py           # 13 tests — storage CRUD, API endpoints
├── examples/
│   ├── demo_agent.py            # Full demo with intentional failures
│   └── demo_dashboard.html      # Interactive trace visualization
├── docs/
│   └── flowlens-handbook.md     # Architecture & design decisions
├── pyproject.toml               # Project config, dependencies
├── LICENSE                      # MIT
└── README.md
```

**~3,000 lines of Python** · **46 tests** · **0 external runtime dependencies beyond FastAPI**

## Run Tests

```bash
# All tests
pytest tests/ -v

# By module
pytest tests/test_models.py -v       # Data models & cost estimation
pytest tests/test_decorators.py -v   # SDK decorators
pytest tests/test_dag.py -v          # Causal DAG & pattern detection
pytest tests/test_server.py -v       # API server & storage
```

## Roadmap

- [ ] **Web Dashboard** — Real-time trace viewer with interactive DAG visualization
- [ ] **OpenTelemetry OTLP Export** — Send traces to Jaeger, Grafana Tempo, etc.
- [ ] **LangChain / CrewAI Auto-Instrumentation** — Zero-code tracing for popular frameworks
- [ ] **Streaming Support** — Trace streamed LLM responses token-by-token
- [ ] **Alerting** — Webhook alerts on detected anti-patterns
- [ ] **Multi-Trace Correlation** — Find systemic patterns across hundreds of traces

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

```bash
# Setup dev environment
git clone https://github.com/niceyusen/flowlens.git
cd flowlens
pip install -e ".[dev]"

# Run tests before submitting
pytest tests/ -v
```

## License

[MIT](LICENSE) — Copyright (c) 2026 Yusen
