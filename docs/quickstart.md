# FlowLens Quickstart Guide

Get from zero to full agent observability in under five minutes.

## Table of Contents

- [Installation](#installation)
- [Basic Usage with Decorators](#basic-usage-with-decorators)
- [Auto-Instrumentation](#auto-instrumentation)
- [Viewing Traces in the Dashboard](#viewing-traces-in-the-dashboard)
- [Docker Deployment](#docker-deployment)
- [Next Steps](#next-steps)

---

## Installation

### Option 1: pip (Recommended)

```bash
pip install flowlens
```

Requirements: Python 3.10+. No other runtime dependencies beyond FastAPI and Uvicorn.

To enable OpenTelemetry OTLP export (optional):

```bash
pip install flowlens[otlp]
```

### Option 2: From Source

```bash
git clone https://github.com/niceyusen/flowlens.git
cd flowlens
pip install -e ".[dev]"
```

### Option 3: Docker

```bash
docker pull niceyusen/flowlens:latest
docker run -d -p 8585:8585 niceyusen/flowlens:latest
```

Verify the install:

```bash
python -c "import flowlens; print(flowlens.__version__)"
# 0.1.0
```

---

## Basic Usage with Decorators

### Step 1: Initialize FlowLens

Create a `FlowLens` instance once at application startup. It registers itself as a global singleton that all decorators pick up automatically.

```python
from flowlens import FlowLens

lens = FlowLens(
    service_name="my-agent",  # Appears in all traces
    export_to="console",      # Print to stdout during development
    verbose=True,
)
```

Available exporters:

| `export_to` | Description |
|---|---|
| `"console"` | Colored tree output to stdout (best for development) |
| `"jsonl"` | Write one JSON object per line to `./traces/*.jsonl` |
| `"http"` | POST to the FlowLens server at `endpoint` |
| `"callback"` | User-provided Python function (useful in tests) |

### Step 2: Add Decorators

Decorate your agent's entry point, LLM calls, and tool calls:

```python
from flowlens import FlowLens, trace_agent, trace_llm, trace_tool
import anthropic

lens = FlowLens(service_name="research-bot", export_to="console", verbose=True)
client = anthropic.Anthropic()

@trace_agent(name="research_bot")
async def run_agent(task: str) -> str:
    """Agent entry point — creates a new trace automatically."""
    plan = await think(task)
    results = await search(plan)
    answer = await summarize(results)
    return answer

@trace_llm(model="claude-sonnet-4-20250514")
async def think(task: str) -> str:
    """LLM call — token usage and cost recorded automatically."""
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": f"Plan research for: {task}"}]
    )
    return response.content[0].text

@trace_tool(name="web_search")
async def search(query: str) -> list[str]:
    """Tool call — input parameters and result summary recorded automatically."""
    # Your search implementation here
    return ["result 1", "result 2"]

@trace_llm(model="claude-sonnet-4-20250514")
async def summarize(results: list[str]) -> str:
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=512,
        messages=[{"role": "user", "content": f"Summarize: {results}"}]
    )
    return response.content[0].text
```

### Step 3: Run Your Agent

```python
import asyncio

asyncio.run(run_agent("What is quantum computing?"))
```

You will see output like this in your terminal:

```
[FlowLens] Trace a1b2c3d4 | 4 spans | 2341ms | 1850 tokens | $0.0128 | OK
  agent research_bot (2341ms)
  ├─ llm think (892ms) [856 tok]
  ├─ tool web_search (12ms)
  └─ llm summarize (1437ms) [994 tok]
```

### Decorating Sync Functions

All decorators work on synchronous functions too:

```python
@trace_agent(name="sync_bot")
def run_sync(task: str) -> str:
    return process(task)

@trace_tool(name="db_query")
def fetch_from_db(query: str) -> dict:
    return db.execute(query)
```

### Handling Errors

Decorators record errors automatically and re-raise them. Your exception handling is never suppressed:

```python
@trace_tool(name="flaky_api")
async def call_api(url: str) -> dict:
    # If this raises, the span is marked ERROR with the exception message
    # The exception propagates normally to your calling code
    return await http.get(url)
```

When an error occurs, FlowLens runs causal analysis to identify root causes:

```
[FlowLens] Trace b2c3d4e5 | 4 spans | 5012ms | 856 tokens | $0.0050 | ERROR
  agent research_bot (5012ms) ERROR
  ├─ llm think (892ms) [856 tok]
  ├─ tool web_search (2003ms) ERROR Connection timeout after 2000ms
  └─ tool summarize (5ms) ERROR No search results available
```

### Adding Metadata and Checkpoints

Attach custom metadata to traces and add named checkpoints within spans:

```python
@trace_agent(name="research_bot", metadata={"user_id": "u123", "session": "s456"})
async def run_agent(task: str):
    lens.checkpoint("started", task_length=len(task))
    result = await execute(task)
    lens.checkpoint("completed", result_length=len(result))
    return result
```

### Sampling

In high-traffic environments, sample a fraction of traces:

```python
lens = FlowLens(
    service_name="my-agent",
    export_to="http",
    sample_rate=0.1,  # Export 10% of traces
)
```

### Using All Five Decorators

```python
from flowlens import trace_agent, trace_llm, trace_tool, trace_chain, trace_retrieval

@trace_agent(name="rag_bot")
async def run(query: str):
    return await full_pipeline(query)

@trace_chain(name="rag_pipeline")
async def full_pipeline(query: str):
    docs = await retrieve(query)
    answer = await generate(query, docs)
    return answer

@trace_retrieval(name="vector_search")
async def retrieve(query: str) -> list[dict]:
    # retrieval.result_count is recorded automatically
    return await vector_db.similarity_search(query, k=5)

@trace_llm(model="claude-sonnet-4-20250514")
async def generate(query: str, docs: list[dict]) -> str:
    return await llm.generate(query, context=docs)
```

---

## Auto-Instrumentation

If you want tracing without adding decorators to every function, use auto-instrumentation. It patches supported LLM client libraries at the module level.

### Basic Auto-Instrumentation

```python
from flowlens import FlowLens
from flowlens.sdk.auto_instrument import auto_instrument

# Initialize FlowLens first
lens = FlowLens(service_name="my-agent", export_to="http")

# Patch supported libraries
auto_instrument(lens)

# From this point forward, all LLM calls are traced automatically
# — no decorators needed on individual functions
```

### What Gets Traced Automatically

```python
import anthropic
import openai

# These calls are now automatically traced:
anthropic_client = anthropic.Anthropic()
response = anthropic_client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello"}]
)
# ^ FlowLens created a span, recorded tokens, estimated cost

openai_client = openai.OpenAI()
response = openai_client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}]
)
# ^ Same — automatic span with token counts
```

### Selective Patching

Patch only the libraries you use:

```python
# Only Anthropic
auto_instrument(lens, patch=["anthropic"])

# Anthropic and OpenAI
auto_instrument(lens, patch=["anthropic", "openai"])

# All supported (default)
auto_instrument(lens)
```

### Mixing Auto-Instrumentation with Decorators

You can use both together. Decorators give you explicit control; auto-instrumentation fills in the gaps:

```python
auto_instrument(lens)  # Traces all LLM calls automatically

@trace_agent(name="my_bot")
async def run(task: str):
    # This creates the trace root span (agent-level context)
    # All LLM calls inside are traced by auto-instrumentation
    result = await execute(task)
    return result
```

---

## Viewing Traces in the Dashboard

### Start the Server

```bash
# Option 1: Using the entry point (after pip install)
flowlens-server

# Option 2: Using uvicorn directly
uvicorn flowlens.server.app:create_app --factory --port 8585

# Option 3: Custom database path
uvicorn flowlens.server.app:create_app --factory --port 8585 \
  --env FLOWLENS_DB_PATH=/var/data/flowlens.db
```

The server starts at `http://localhost:8585`. Visit it in your browser to see the dashboard.

### Send Traces to the Server

Change your exporter from `"console"` to `"http"`:

```python
lens = FlowLens(
    service_name="my-agent",
    export_to="http",
    endpoint="http://localhost:8585/v1/traces/ingest",
)
```

Now run your agent — traces appear in the dashboard in real time.

### Import Existing Traces

If you have traces saved as JSONL files, import them:

```bash
curl -X POST "http://localhost:8585/v1/traces/import?file_path=/path/to/traces.jsonl"
```

### Explore the Dashboard

The dashboard provides:

- **Trace list** — all recent traces, sorted by time, filterable by service and error status
- **Span tree** — hierarchical view of every operation in a trace, with durations and status
- **Causal DAG** — interactive graph showing which error caused which downstream failure
- **Cost breakdown** — token usage and USD cost per service, span type, or operation name
- **Live WebSocket feed** — new traces appear automatically without page refresh

### Query the API Directly

The REST API is available at `http://localhost:8585`. Interactive docs at `http://localhost:8585/docs`.

```bash
# List recent traces
curl "http://localhost:8585/v1/traces?limit=10"

# Get causal analysis for a specific trace
curl "http://localhost:8585/v1/traces/a1b2c3d4/dag" | jq '.'

# Cost breakdown by service
curl "http://localhost:8585/v1/cost/breakdown?group_by=service_name"

# Global statistics
curl "http://localhost:8585/v1/stats"
```

### Real-Time WebSocket Feed

Connect to the live trace stream for custom dashboards or alerting:

```python
import asyncio
import websockets
import json

async def watch():
    async with websockets.connect("ws://localhost:8585/ws/traces") as ws:
        async for message in ws:
            trace = json.loads(message)
            status = "ERROR" if trace["has_errors"] else "OK"
            print(f"[{status}] {trace['service_name']} — {trace['duration_ms']:.0f}ms")

asyncio.run(watch())
```

---

## Docker Deployment

Docker is the recommended way to run the FlowLens server in production.

### Quick Start

```bash
docker run -d \
  --name flowlens \
  -p 8585:8585 \
  -v flowlens-data:/data \
  niceyusen/flowlens:latest
```

Visit `http://localhost:8585` to confirm the server is running.

### Docker Compose

Create `docker-compose.yml`:

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
# Start in background
docker-compose up -d

# View logs
docker-compose logs -f flowlens

# Stop
docker-compose down
```

### Build from Source

```bash
git clone https://github.com/niceyusen/flowlens.git
cd flowlens
docker build -t flowlens:local .
docker run -d -p 8585:8585 -v flowlens-data:/data flowlens:local
```

### Connect Your Agents to the Docker Server

From any machine that can reach the Docker host:

```python
lens = FlowLens(
    service_name="my-agent",
    export_to="http",
    endpoint="http://<docker-host-ip>:8585/v1/traces/ingest",
)
```

For local development with Docker Desktop on Mac or Windows, use `host.docker.internal` as the hostname if your agent runs inside another container:

```python
endpoint="http://host.docker.internal:8585/v1/traces/ingest"
```

### Data Persistence

The SQLite database is stored at `/data/flowlens.db` inside the container. The volume mount (`-v flowlens-data:/data`) ensures data survives container restarts and updates.

To back up your data:

```bash
docker cp flowlens:/data/flowlens.db ./flowlens-backup.db
```

To restore:

```bash
docker cp ./flowlens-backup.db flowlens:/data/flowlens.db
docker-compose restart flowlens
```

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `FLOWLENS_DB_PATH` | `/data/flowlens.db` | SQLite database file path |
| `FLOWLENS_LOG_LEVEL` | `INFO` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `FLOWLENS_PORT` | `8585` | Server port |
| `FLOWLENS_WORKERS` | `1` | Number of Uvicorn workers |

---

## Next Steps

### Run the Demo

See a complete example with intentional failures and causal analysis:

```bash
python -m examples.demo_agent
```

### Read the Full API Reference

Every endpoint, parameter, and response schema is documented in [docs/api-reference.md](api-reference.md).

### Understand the Internals

The complete architectural guide — causal DAG algorithm, pattern detection logic, WebSocket design — is in [docs/architecture.md](architecture.md).

### Instrument a Real Agent

Here is a minimal template for any agent:

```python
import asyncio
from flowlens import FlowLens, trace_agent, trace_llm, trace_tool

# 1. Initialize once
lens = FlowLens(
    service_name="your-agent-name",
    export_to="http",
    endpoint="http://localhost:8585/v1/traces/ingest",
)

# 2. Decorate your functions
@trace_agent(name="your_agent")
async def run(task: str):
    ...

@trace_llm(model="your-model-name")
async def call_llm(messages: list):
    ...

@trace_tool(name="your_tool")
async def use_tool(input: str):
    ...

# 3. Run normally
asyncio.run(run("your task here"))
```

### Get Help

- GitHub Issues: https://github.com/niceyusen/flowlens/issues
- Contributing: [CONTRIBUTING.md](../CONTRIBUTING.md)
