<p align="center">
  <h1 align="center">FlowLens</h1>
  <p align="center"><strong>Agent Observability Platform — Chrome DevTools for LLM Agents</strong></p>
</p>

<p align="center">
  <a href="https://pypi.org/project/flowlens/"><img src="https://img.shields.io/pypi/v/flowlens.svg" alt="PyPI version"></a>
  <a href="https://pypi.org/project/flowlens/"><img src="https://img.shields.io/pypi/dm/flowlens.svg" alt="PyPI downloads"></a>
  <a href="https://github.com/niceyusen/flowlens/actions"><img src="https://img.shields.io/github/actions/workflow/status/niceyusen/flowlens/ci.yml?branch=main&label=CI" alt="CI Status"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-blue.svg" alt="Python 3.10+"></a>
  <a href="https://github.com/niceyusen/flowlens/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
  <a href="https://opentelemetry.io/"><img src="https://img.shields.io/badge/OpenTelemetry-compatible-blueviolet.svg" alt="OTEL Compatible"></a>
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

## Dashboard

Start the server and visit `http://localhost:8585` to see your traces in real time:

```bash
flowlens-server
# or: uvicorn flowlens.server.app:create_app --factory --port 8585
```

<p align="center">
  <img src="examples/dashboard_full.png" alt="FlowLens Dashboard" width="800">
</p>

<details>
<summary>Trace Overview and Execution Timeline</summary>
<p align="center">
  <img src="examples/screenshot_overview.png" alt="Trace Overview" width="700">
</p>
</details>

<details>
<summary>Causal Error DAG</summary>
<p align="center">
  <img src="examples/screenshot_dag.png" alt="Causal DAG" width="700">
</p>
</details>

---

## Key Features

### Causal DAG Analysis

Not just "what failed" but "why it failed and how the error spread." FlowLens builds directed acyclic graphs showing error propagation paths, distinguishing **root causes** from **cascaded failures**.

### Zero-Intrusion Tracing

Five decorators instrument your code without changing any business logic. Framework-agnostic — works with **any** Python agent: LangChain, CrewAI, AutoGen, or fully custom.

```python
@trace_agent(name="my_bot")       # Wraps agent entry point — creates trace
@trace_llm(model="claude-4")      # Wraps LLM calls, extracts tokens + cost
@trace_tool(name="search")        # Wraps tool calls, captures params + results
@trace_chain(name="pipeline")     # Wraps multi-step workflows
@trace_retrieval(name="rag")      # Wraps RAG retrieval steps
```

### Auto-Instrumentation

Drop a single call into your startup code and FlowLens instruments your entire application automatically — no decorators required:

```python
from flowlens import FlowLens
from flowlens.sdk.auto_instrument import auto_instrument

lens = FlowLens(service_name="my-agent", export_to="http")
auto_instrument(lens)  # patches Anthropic, OpenAI, LangChain automatically
```

See the [Auto-Instrumentation section](#auto-instrumentation) for full details.

### Streaming Support

Trace token-by-token streamed LLM responses with accurate token counts and timing:

```python
@trace_llm(model="claude-sonnet-4-20250514", streaming=True)
async def stream_response(messages):
    async with client.messages.stream(...) as stream:
        async for text in stream.text_stream:
            yield text
```

### WebSocket Real-Time Streaming

Connect to the WebSocket endpoint to receive trace events as they happen — power your own dashboards or alerting pipelines:

```javascript
const ws = new WebSocket("ws://localhost:8585/ws/traces");
ws.onmessage = (event) => {
  const trace = JSON.parse(event.data);
  console.log("New trace:", trace.trace_id, trace.has_errors);
};
```

### Pattern Detection

Automatically detects 5 anti-patterns in agent execution:

| Pattern | Description |
|---|---|
| **Retry Storm** | Same tool called 5+ times (flaky API, bad retry logic) |
| **Infinite Loop** | Repeating tool sequences (A→B→A→B→A→B) |
| **Context Overflow** | Token usage >90% of model's context window |
| **Timeout Cascade** | Timeout causing downstream failures |
| **Empty Response** | LLM returns 0 output tokens |

### Multi-Dimensional Cost Attribution

Know exactly how many tokens each step consumed and what it cost, broken down by **model**, **tool**, **task type**, or **service**. Supports 16+ models out of the box:

| Provider | Models |
|---|---|
| Anthropic | Claude Opus 4, Sonnet 4, Haiku 3.5 |
| OpenAI | GPT-4o, GPT-4o-mini, GPT-4.1, GPT-4.1-mini, o1, o1-mini |
| Google | Gemini 2.5 Pro, Gemini 2.5 Flash |
| DeepSeek | DeepSeek V3, DeepSeek R1 |
| Meta | Llama 3.1 70B, 405B |
| Mistral | Mistral Large |

### REST API + Real-Time Storage

FastAPI server with async SQLite storage. 15+ endpoints cover everything from ingestion to causal analysis, error search, cost trends, and live WebSocket streaming.

---

## Quick Start

### Installation

```bash
# From PyPI (recommended):
pip install flowlens

# From source:
git clone https://github.com/niceyusen/flowlens.git
cd flowlens
pip install -e ".[dev]"

# With OpenTelemetry OTLP export:
pip install flowlens[otlp]
```

### Step 1 — Instrument Your Agent

Add three decorators. No other changes needed:

```python
from flowlens import FlowLens, trace_agent, trace_llm, trace_tool

# Initialize once at startup
lens = FlowLens(service_name="my-agent", export_to="console", verbose=True)

@trace_agent(name="research_bot")
async def run_agent(task: str):
    plan = await think(task)
    result = await execute(plan)
    return result

@trace_llm(model="claude-sonnet-4-20250514")
async def think(task: str):
    return await client.messages.create(
        model="claude-sonnet-4-20250514",
        messages=[{"role": "user", "content": task}]
    )

@trace_tool(name="web_search")
async def search(query: str):
    return await search_api.query(query)
```

### Step 2 — Run Your Agent

```bash
python my_agent.py
```

Console output appears immediately:

```
[FlowLens] Trace a1b2c3d4 | 8 spans | 1847ms | 2967 tokens | $0.0190 | ERROR
  agent research_bot (1847ms)
  ├─ llm plan_research (312ms) [856 tok]
  ├─ tool web_search (2003ms) ERROR timeout
  ├─ tool fetch_page (5ms) ERROR no input from search
  ├─ llm decide_retry (201ms) [445 tok]
  ├─ tool web_search (150ms) OK
  ├─ tool fetch_page (89ms) OK
  └─ llm synthesize (278ms) [1666 tok]
```

### Step 3 — Start the Dashboard

```bash
flowlens-server
```

Open `http://localhost:8585` in your browser. Every trace your agent produces appears instantly in the dashboard with full span trees, cost breakdowns, and causal DAG visualizations.

To send traces to the server instead of console, switch the exporter:

```python
lens = FlowLens(
    service_name="my-agent",
    export_to="http",
    endpoint="http://localhost:8585/v1/traces/ingest",
)
```

### Step 4 — Analyze Root Causes

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

---

## Auto-Instrumentation

Auto-instrumentation patches supported LLM clients at import time — you get tracing without adding a single decorator to your code.

```python
from flowlens import FlowLens
from flowlens.sdk.auto_instrument import auto_instrument

lens = FlowLens(service_name="my-agent", export_to="http")

# Instrument everything automatically
auto_instrument(lens)

# Your existing code — completely unchanged
import anthropic
client = anthropic.Anthropic()
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Explain quantum computing"}]
)
# A trace was created and exported automatically
```

**Supported frameworks for auto-instrumentation:**

| Framework | What is traced |
|---|---|
| `anthropic` | All `messages.create` and `messages.stream` calls |
| `openai` | All `chat.completions.create` calls |
| `langchain` | LLM calls, tool invocations, chain executions |

**Selective instrumentation:**

```python
# Only instrument Anthropic
auto_instrument(lens, patch=["anthropic"])

# Only instrument OpenAI
auto_instrument(lens, patch=["openai"])

# All supported frameworks (default)
auto_instrument(lens)
```

---

## Streaming Support

FlowLens traces streamed LLM responses accurately — token counts are accumulated as chunks arrive, and timing captures the full streaming window.

```python
from flowlens import FlowLens, trace_agent, trace_llm

lens = FlowLens(service_name="streaming-bot", export_to="http")

@trace_agent(name="stream_bot")
async def run(prompt: str):
    async for chunk in generate(prompt):
        print(chunk, end="", flush=True)

@trace_llm(model="claude-sonnet-4-20250514", streaming=True)
async def generate(prompt: str):
    async with client.messages.stream(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        async for text in stream.text_stream:
            yield text
```

The resulting span captures:
- `streaming: true` attribute
- Accurate `input_tokens` and `output_tokens` from the final stream message
- Full wall-clock duration from first token to last

---

## WebSocket Real-Time Streaming

Subscribe to live trace events over WebSocket. Every time a trace completes and is ingested by the server, it is broadcast to all connected clients.

**Connection:**

```
ws://localhost:8585/ws/traces
```

**Message format** — each message is a complete trace object serialized as JSON:

```json
{
  "trace_id": "a1b2c3d4",
  "service_name": "my-agent",
  "duration_ms": 1847,
  "total_tokens": 2967,
  "total_cost_usd": 0.019,
  "has_errors": true,
  "error_count": 2,
  "span_count": 8,
  "spans": [...]
}
```

**Python client example:**

```python
import asyncio
import websockets
import json

async def watch_traces():
    async with websockets.connect("ws://localhost:8585/ws/traces") as ws:
        async for message in ws:
            trace = json.loads(message)
            if trace["has_errors"]:
                print(f"ERROR trace {trace['trace_id']}: {trace['error_count']} errors")
                # Trigger alert, Slack notification, etc.

asyncio.run(watch_traces())
```

**JavaScript / browser client:**

```javascript
const ws = new WebSocket("ws://localhost:8585/ws/traces");

ws.onopen = () => console.log("Connected to FlowLens");

ws.onmessage = (event) => {
  const trace = JSON.parse(event.data);
  updateDashboard(trace);  // your custom dashboard logic
};

ws.onerror = (err) => console.error("WebSocket error:", err);
```

---

## Docker Deployment

### Single Container

```bash
# Pull and run
docker run -d \
  --name flowlens \
  -p 8585:8585 \
  -v flowlens-data:/data \
  niceyusen/flowlens:latest

# Visit the dashboard
open http://localhost:8585
```

### Docker Compose (Recommended)

Create a `docker-compose.yml`:

```yaml
version: "3.9"

services:
  flowlens:
    image: niceyusen/flowlens:latest
    ports:
      - "8585:8585"
    volumes:
      - flowlens-data:/data
    environment:
      - FLOWLENS_DB_PATH=/data/flowlens.db
      - FLOWLENS_LOG_LEVEL=INFO
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8585/health"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  flowlens-data:
```

```bash
docker-compose up -d
docker-compose logs -f flowlens
```

### Build from Source

```bash
git clone https://github.com/niceyusen/flowlens.git
cd flowlens

# Build image
docker build -t flowlens:local .

# Run
docker run -d -p 8585:8585 flowlens:local
```

### Configuring Agents to Send to Docker

```python
lens = FlowLens(
    service_name="my-agent",
    export_to="http",
    endpoint="http://localhost:8585/v1/traces/ingest",  # or your Docker host IP
)
```

---

## API Endpoints

The FlowLens server exposes a REST API at `http://localhost:8585`. Full OpenAPI documentation is available at `http://localhost:8585/docs`.

**Traces:**

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/traces/ingest` | Ingest a single trace from SDK |
| `POST` | `/v1/traces/import` | Bulk import from JSONL file |
| `GET` | `/v1/traces` | List traces (paginated, filterable) |
| `GET` | `/v1/traces/{id}` | Full trace with all spans |
| `GET` | `/v1/traces/{id}/dag` | Causal DAG analysis + patterns |
| `DELETE` | `/v1/traces/{id}` | Delete a trace |
| `GET` | `/v1/traces/errors` | List only error traces |
| `GET` | `/v1/traces/search` | Full-text search across traces |
| `POST` | `/v1/traces/cleanup` | Delete traces older than N days |

**Cost and Patterns:**

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/cost/breakdown` | Cost attribution (group by service/kind/name) |
| `GET` | `/v1/cost/trends` | Cost over time (daily/weekly aggregation) |
| `GET` | `/v1/patterns/summary` | Aggregated anti-pattern statistics |
| `GET` | `/v1/stats` | Global aggregate statistics |

**Real-Time:**

| Method | Path | Description |
|---|---|---|
| `WS` | `/ws/traces` | WebSocket stream of live trace events |
| `GET` | `/health` | Server health check |

See [docs/api-reference.md](docs/api-reference.md) for complete request/response documentation.

---

## Run the Demo

```bash
python -m examples.demo_agent
```

This runs a research agent that **intentionally fails** — a search timeout cascades into a fetch failure, triggers a retry, and eventually succeeds. The demo prints a full causal analysis report showing root causes, cascaded errors, and detected patterns.

<details>
<summary>Sample Demo Output</summary>

```
════════════════════════════════════════════════════════════════
  FlowLens — Causal Analysis Report
════════════════════════════════════════════════════════════════

Trace: f7a1...c3d4 | research_agent | 8 spans | 1847ms

Root Causes (1):
  x web_search [TOOL] — "Connection timeout after 2000ms"

Cascaded Errors (1):
  -> fetch_page [TOOL] — "Invalid input: empty URL from search"
    caused by: web_search (timeout -> no output -> fetch fails)

Detected Patterns:
  ! TIMEOUT_CASCADE (severity: high)
    web_search timeout caused 1 downstream failure

Cost: 2967 tokens | $0.019
  plan_research:  856 tok ($0.005)
  decide_retry:   445 tok ($0.003)
  synthesize:    1666 tok ($0.011)
```

</details>

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Your Agent Code                      │
│   @trace_agent  ·  @trace_llm  ·  @trace_tool           │
│   auto_instrument()  ·  @trace_chain  ·  @trace_retrieval│
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
       │ · Auto-Instr.  │             │  Server Layer    │
       └───────┬───────┘             │                  │
               │                     │ · FastAPI REST   │
               │                     │ · WebSocket      │
               └──────────►          │ · SQLite Store   │
                   export            │ · Dashboard      │
                                     └─────────────────┘
```

**SDK** (`flowlens/sdk/`) — Zero-intrusion tracing via Python decorators. Uses `contextvars.ContextVar` for async-safe parent-child span linking. Four exporters: Console (colored), JSONL (file), HTTP (to server), Callback (for testing). Auto-instrumentation patches supported LLM clients at import time.

**Analysis** (`flowlens/analysis/`) — Causal DAG engine that builds directed acyclic graphs from trace spans. Classifies errors as ROOT_CAUSE, CASCADED, or INDEPENDENT. Five pattern detectors run over the DAG to surface anti-patterns.

**Server** (`flowlens/server/`) — FastAPI application with async SQLite storage. Full CRUD for traces, causal DAG analysis, multi-dimensional cost breakdowns, and real-time WebSocket broadcasting.

---

## How It Compares

|  | Langfuse | LangSmith | Opik | **FlowLens** |
|---|:---:|:---:|:---:|:---:|
| Open Source | Yes | No | Yes | **Yes** |
| Framework Agnostic | Yes | No | Yes | **Yes** |
| **Causal DAG Analysis** | No | No | No | **Yes** |
| **Error Cascade Detection** | No | No | No | **Yes** |
| **Anti-Pattern Detection** | No | No | No | **Yes** |
| **Auto-Instrumentation** | Partial | Yes | No | **Yes** |
| **Streaming Trace Support** | No | Partial | No | **Yes** |
| **WebSocket Live Feed** | No | No | No | **Yes** |
| Cost Attribution | Basic | Basic | Basic | **Multi-dim** |
| Zero-Config Storage | No | No | Yes | **Yes** |
| OTEL GenAI Conventions | No | No | No | **Yes** |
| Self-Hosted | Docker | No | Docker | **pip + Docker** |

---

## Tech Stack

| Component | Technology | Purpose |
|---|---|---|
| **Language** | Python 3.10+ | Async-first with `asyncio`, `contextvars` |
| **Web Framework** | FastAPI >=0.110 | Async REST API with auto-generated OpenAPI docs |
| **ASGI Server** | Uvicorn >=0.27 | High-performance async server + WebSocket support |
| **Database** | SQLite via aiosqlite >=0.20 | Zero-config async storage |
| **Validation** | Pydantic >=2.0 | Request/response schema validation |
| **Telemetry** | OpenTelemetry (optional) | OTLP export, GenAI semantic conventions |
| **Testing** | pytest >=8.0 + pytest-asyncio | 46 tests, async-native |
| **HTTP Client** | httpx >=0.27 | Async test client for FastAPI |

---

## Project Structure

```
flowlens/
├── flowlens/
│   ├── __init__.py              # Public API exports
│   ├── sdk/
│   │   ├── models.py            # Span, Trace, TokenUsage, cost pricing
│   │   ├── context.py           # Async-safe context (contextvars)
│   │   ├── tracer.py            # FlowLens singleton, trace lifecycle
│   │   ├── decorators.py        # @trace_agent, @trace_llm, @trace_tool, @trace_chain, @trace_retrieval
│   │   ├── auto_instrument.py   # Zero-code auto-instrumentation
│   │   └── exporters.py         # Console, JSONL, HTTP, Callback exporters
│   ├── analysis/
│   │   ├── models.py            # CausalDAG, CausalNode, CausalEdge, DetectedPattern
│   │   ├── dag_builder.py       # build_causal_dag() — core algorithm
│   │   └── patterns.py          # 5 pattern detectors
│   └── server/
│       ├── app.py               # FastAPI application (15+ endpoints, WebSocket)
│       └── storage.py           # Async SQLite storage (TraceStore)
├── tests/
│   ├── test_models.py           # Data models & cost estimation
│   ├── test_decorators.py       # Decorators, nested spans
│   ├── test_dag.py              # DAG builder, pattern detection
│   └── test_server.py           # Storage CRUD, API endpoints
├── examples/
│   ├── demo_agent.py            # Full demo with intentional failures
│   └── demo_dashboard.html      # Interactive trace visualization
├── docs/
│   ├── quickstart.md            # Step-by-step getting started guide
│   ├── api-reference.md         # Complete API reference
│   └── architecture.md          # Internals and design decisions
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml               # Project config, dependencies
├── LICENSE                      # MIT
└── README.md
```

**~4,000 lines of Python** · **46 tests** · **0 external runtime dependencies beyond FastAPI**

---

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

---

## Roadmap

- [x] **Causal DAG Analysis** — Root cause identification with cascade depth
- [x] **5 Anti-Pattern Detectors** — Retry storm, infinite loop, context overflow, timeout cascade, empty response
- [x] **Multi-Dimensional Cost Attribution** — 16+ models, group by service/kind/name
- [x] **REST API Server** — FastAPI with async SQLite, 15+ endpoints
- [x] **Auto-Instrumentation** — Zero-code tracing for Anthropic, OpenAI, LangChain
- [x] **Streaming Support** — Trace token-by-token streamed responses
- [x] **WebSocket Live Feed** — Real-time trace broadcast to connected clients
- [x] **Docker Deployment** — Single container and Compose support
- [ ] **Multi-Trace Correlation** — Find systemic patterns across hundreds of traces
- [ ] **Alerting** — Webhook alerts triggered by detected anti-patterns
- [ ] **OTLP Export** — Send traces to Jaeger, Grafana Tempo, etc.
- [ ] **CrewAI / AutoGen Auto-Instrumentation** — Extend framework coverage

---

## Contributing

Contributions are welcome. Please feel free to submit a Pull Request. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

```bash
git clone https://github.com/niceyusen/flowlens.git
cd flowlens
pip install -e ".[dev]"
pytest tests/ -v  # All tests must pass before submitting
```

---

## License

[MIT](LICENSE) — Copyright (c) 2026 Yusen
