# FlowLens API Reference

Complete documentation of all public APIs in FlowLens SDK, Analysis, and Server modules.

## Table of Contents

- [FlowLens Core Class](#flowlens-core-class)
- [Decorators](#decorators)
- [Data Models](#data-models)
- [Analysis Functions](#analysis-functions)
- [Server API Endpoints](#server-api-endpoints)

---

## FlowLens Core Class

The main entry point for instrumentation.

### `FlowLens(service_name, export_to, output_dir, endpoint, verbose, metadata)`

Initialize a FlowLens tracer instance. Creates a singleton that decorators reference.

**Parameters:**

- `service_name` (str, default: `"flowlens"`): Human-readable service name appearing in traces
- `export_to` (str, default: `"console"`): Exporter type — one of:
  - `"console"`: Colored output to stdout (recommended for dev)
  - `"jsonl"`: Write JSONL files to disk
  - `"http"`: Send to remote server
  - `"callback"`: User-provided callback function
- `output_dir` (str, default: `"./traces"`): Directory for JSONL exporter (if used)
- `endpoint` (str, default: `"http://localhost:8585/v1/traces/ingest"`): HTTP endpoint for HTTP exporter
- `verbose` (bool, default: `False`): Print debug info during export
- `metadata` (dict, optional): Default metadata added to every trace (e.g., `{"env": "prod"}`)

**Example:**

```python
from flowlens import FlowLens

lens = FlowLens(
    service_name="my-agent",
    export_to="console",
    verbose=True,
    metadata={"env": "development", "version": "1.0"}
)
```

### `FlowLens.get_instance()`

Retrieve the global FlowLens singleton instance.

**Returns:** `Optional[FlowLens]` — The singleton if initialized, None otherwise

**Example:**

```python
lens = FlowLens.get_instance()
if lens:
    trace = lens.start_trace()
```

### `FlowLens.start_trace(metadata)`

Create and activate a new trace context.

**Parameters:**

- `metadata` (dict, optional): Trace-specific metadata, merged with instance metadata

**Returns:** `Trace` object

**Example:**

```python
trace = lens.start_trace(metadata={"task_id": "research-001"})
```

### `FlowLens.end_trace(trace)`

Finish a trace and export it via the configured exporter.

**Parameters:**

- `trace` (Trace): The trace object to export

**Example:**

```python
lens.end_trace(trace)  # Exports immediately
```

### `FlowLens.start_span(name, kind, attributes)`

Create a span within the current trace context. Automatically links to parent span if nested.

**Parameters:**

- `name` (str): Span name (e.g., `"web_search"`, `"llm_call"`)
- `kind` (SpanKind, default: `SpanKind.CUSTOM`): Span category:
  - `SpanKind.AGENT`: Agent main loop
  - `SpanKind.LLM`: Language model call
  - `SpanKind.TOOL`: Tool/API invocation
  - `SpanKind.CHAIN`: Multi-step workflow
  - `SpanKind.RETRIEVAL`: RAG retrieval
  - `SpanKind.CUSTOM`: User-defined
- `attributes` (dict, optional): Key-value metadata attached to span

**Returns:** `Span` object (not yet started — call `span.finish()` when done)

**Example:**

```python
span = lens.start_span(
    "db_query",
    kind=SpanKind.TOOL,
    attributes={"db": "postgres", "query_type": "select"}
)
# ... do work ...
span.finish(status=SpanStatus.OK)
```

### `FlowLens.checkpoint(name, **attrs)`

Add a named checkpoint event to the current span.

**Parameters:**

- `name` (str): Checkpoint identifier
- `**attrs`: Arbitrary keyword arguments logged with the checkpoint

**Example:**

```python
lens.checkpoint("retrieval_done", docs_count=42)
```

### `FlowLens.shutdown()`

Gracefully shut down FlowLens. Exports any pending traces and closes resources.

**Example:**

```python
lens.shutdown()  # Call at program exit
```

---

## Decorators

Zero-intrusion decorators that wrap your functions. Support both async and sync functions.

### `@trace_agent(name, metadata, **attrs)`

Wrap an agent's main entry point. Creates a trace with a root AGENT span.

**Parameters:**

- `name` (str, default: `"agent"`): Root span name
- `metadata` (dict, optional): Trace metadata
- `**attrs`: Additional span attributes

**Returns:** Decorated function

**Example:**

```python
from flowlens import trace_agent

@trace_agent(name="research_bot")
async def run_agent(task: str) -> str:
    result = await search(task)
    return f"Done: {result}"

# Sync version also supported:
@trace_agent(name="sync_bot")
def run_sync_agent(task: str) -> str:
    return task.upper()
```

### `@trace_llm(model, name, **attrs)`

Wrap LLM calls. Automatically extracts token usage and estimates cost.

**Parameters:**

- `model` (str, default: `""`): Model identifier (e.g., `"claude-sonnet-4-20250514"`, `"gpt-4o"`)
- `name` (str, optional): Span name (defaults to function name)
- `**attrs`: Additional attributes

**Returns:** Decorated function

**Supported Models & Pricing:**

- Claude: Opus 4, Sonnet 4, Haiku 4 (3.5)
- OpenAI: GPT-4o, GPT-4o-mini, GPT-4.1, GPT-4.1-mini
- Google: Gemini 2.5 Pro, Gemini 2.5 Flash
- DeepSeek: V3, R1
- Llama: 3.1 (70B, 405B)
- Mistral: Large
- Command: R+

**Example:**

```python
from flowlens import trace_llm

@trace_llm(model="claude-sonnet-4-20250514", name="think")
async def call_claude(messages: list) -> str:
    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        messages=messages
    )
    return response.content[0].text
```

Token usage is automatically extracted from Anthropic SDK (`.usage.input_tokens`) or OpenAI SDK (`["usage"]["prompt_tokens"]`).

### `@trace_tool(name)`

Wrap tool/API calls. Automatically captures parameters and results.

**Parameters:**

- `name` (str, optional): Tool name (defaults to function name)

**Returns:** Decorated function

**Example:**

```python
from flowlens import trace_tool

@trace_tool(name="web_search")
async def search(query: str, limit: int = 10) -> dict:
    results = await search_api.query(query, limit)
    return results

# Parameters captured as span attributes:
# - tool.input.query = "hello"
# - tool.input.limit = 10
# - tool.output_summary = "<dict summary>"
```

---

## Data Models

Core data structures passed through the SDK.

### `Span`

Represents a single operation.

**Attributes:**

- `span_id` (str): Unique identifier (auto-generated)
- `trace_id` (str): Parent trace identifier
- `parent_span_id` (Optional[str]): Parent span for nesting
- `name` (str): Operation name
- `kind` (SpanKind): Category (AGENT, LLM, TOOL, etc.)
- `status` (SpanStatus): OK, ERROR, or UNSET
- `start_time` (float): Unix timestamp (seconds)
- `end_time` (float): Unix timestamp (seconds)
- `duration_ms` (float, read-only): Computed duration
- `attributes` (dict): Custom metadata
- `events` (list[SpanEvent]): Checkpoint events within span
- `token_usage` (Optional[TokenUsage]): Token counts (LLM spans only)
- `error_message` (Optional[str]): Error description if status=ERROR
- `error_type` (Optional[str]): Exception class name

**Methods:**

```python
span = Span(name="my_op", kind=SpanKind.TOOL)

# Finish the span
span.finish(status=SpanStatus.OK, error=None)

# Add a checkpoint event
span.add_event("step_complete", step=1, data="sample")

# Set token usage (for LLM spans)
span.set_token_usage(
    input_tokens=1000,
    output_tokens=500,
    model="claude-sonnet-4-20250514"
)

# Serialize to dict
span_dict = span.to_dict()
```

### `Trace`

A complete execution trace containing multiple spans.

**Attributes:**

- `trace_id` (str): Unique identifier (auto-generated)
- `service_name` (str): Service name
- `root_span_id` (Optional[str]): Top-level span
- `spans` (list[Span]): All spans in execution order
- `start_time` (float): Trace start time
- `end_time` (float): Trace end time
- `duration_ms` (float, read-only): Total duration
- `total_tokens` (int, read-only): Sum of all token usage
- `total_cost_usd` (float, read-only): Estimated cost
- `has_errors` (bool, read-only): True if any span errored
- `error_count` (int, read-only): Number of error spans
- `error_rate` (float, read-only): Fraction of spans that errored
- `metadata` (dict): Custom metadata

**Methods:**

```python
trace = Trace(service_name="my-agent")

# Finish the trace
trace.finish()

# Serialize to dict
trace_dict = trace.to_dict()
```

### `TokenUsage`

Token usage and cost for an LLM call.

**Attributes:**

- `input_tokens` (int): Input token count
- `output_tokens` (int): Output token count
- `total_tokens` (int): Sum
- `input_cost_usd` (float): Input cost
- `output_cost_usd` (float): Output cost
- `total_cost_usd` (float): Total cost

**Example:**

```python
usage = TokenUsage(
    input_tokens=1000,
    output_tokens=500,
    total_tokens=1500,
    input_cost_usd=0.003,
    output_cost_usd=0.005,
    total_cost_usd=0.008
)
```

### `SpanKind` (Enum)

Span category enumeration.

- `AGENT`: Agent main loop
- `LLM`: Language model call
- `TOOL`: Tool/API execution
- `CHAIN`: Multi-step workflow
- `RETRIEVAL`: RAG retrieval
- `CUSTOM`: User-defined

### `SpanStatus` (Enum)

Span execution status.

- `OK`: Completed successfully
- `ERROR`: Threw an exception
- `UNSET`: Not yet finished

---

## Analysis Functions

Post-trace analysis to understand failures and detect patterns.

### `build_causal_dag(trace) -> CausalDAG`

Build a directed acyclic graph showing error propagation.

**Parameters:**

- `trace` (Trace): Completed trace with spans

**Returns:** `CausalDAG` object containing nodes, edges, and root causes

**Algorithm:**

1. Build parent-child tree from span relationships
2. Identify error spans
3. Classify each error as ROOT_CAUSE, CASCADED, or INDEPENDENT
4. Build edges showing error propagation

**Example:**

```python
from flowlens.analysis.dag_builder import build_causal_dag

dag = build_causal_dag(trace)

print(f"Root causes: {dag.root_causes}")        # ["span_id_1", "span_id_2"]
print(f"Cascade depth: {dag.cascade_depth}")    # 2
print(f"Has errors: {dag.has_errors}")          # True

# Iterate nodes
for node in dag.nodes:
    print(f"{node.name} [{node.kind}] - {node.status}")
    if node.error_role == ErrorRole.ROOT_CAUSE:
        print(f"  Root cause: {node.error_message}")
```

### `detect_patterns(trace, dag) -> list[DetectedPattern]`

Run all pattern detectors and return detected anti-patterns.

**Parameters:**

- `trace` (Trace): Execution trace
- `dag` (CausalDAG): Pre-built DAG (patterns are written to `dag.patterns`)

**Returns:** List of `DetectedPattern` objects

**Detectors:**

| Pattern | Description | Threshold |
|---------|-------------|-----------|
| RETRY_STORM | Same tool called ≥5 times | >= 5 calls |
| INFINITE_LOOP | Repeating tool sequence | >= 3 repetitions |
| CONTEXT_OVERFLOW | Token usage ≥90% of model limit | >= 0.9 ratio |
| TIMEOUT_CASCADE | Timeout causing downstream failures | Any timeout |
| EMPTY_RESPONSE | LLM returns 0 output tokens | 0 output tokens |

**Example:**

```python
from flowlens.analysis.patterns import detect_patterns

patterns = detect_patterns(trace, dag)

for pattern in patterns:
    print(f"[{pattern.severity}] {pattern.pattern_type.value}")
    print(f"  {pattern.description}")
    print(f"  Involved: {pattern.involved_spans}")
    print(f"  Details: {pattern.details}")
```

### `CausalDAG` Data Structure

Result of DAG analysis.

**Attributes:**

- `trace_id` (str): Source trace ID
- `nodes` (list[CausalNode]): Span nodes in graph
- `edges` (list[CausalEdge]): Error propagation edges
- `patterns` (list[DetectedPattern]): Detected patterns
- `root_causes` (list[str]): Root cause span IDs
- `has_errors` (bool, read-only): True if any root causes
- `cascade_depth` (int, read-only): Max error cascade depth

**Example:**

```python
dag.to_dict()  # Serialize to JSON-compatible dict
```

---

## Server API Endpoints

RESTful API for ingesting, querying, and analyzing traces.

### Base URL

Default: `http://localhost:8585`

### Health Check

**GET /health**

Check server status.

**Response:**

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

**curl:**

```bash
curl http://localhost:8585/health
```

### Ingest Trace

**POST /v1/traces/ingest**

Receive a single trace from SDK.

**Request Body:**

```json
{
  "trace_id": "abc123",
  "service_name": "my-agent",
  "start_time": 1000.0,
  "end_time": 1005.0,
  "duration_ms": 5000,
  "total_tokens": 2000,
  "total_cost_usd": 0.012,
  "has_errors": false,
  "error_count": 0,
  "metadata": {"env": "prod"},
  "spans": [
    {
      "span_id": "s1",
      "trace_id": "abc123",
      "parent_span_id": null,
      "name": "agent_run",
      "kind": "agent",
      "status": "ok",
      "start_time": 1000.0,
      "end_time": 1005.0,
      "duration_ms": 5000,
      "attributes": {},
      "events": [],
      "token_usage": {
        "input_tokens": 1000,
        "output_tokens": 1000,
        "total_cost_usd": 0.012
      }
    }
  ]
}
```

**Response:**

```json
{
  "status": "ok",
  "trace_id": "abc123"
}
```

**curl:**

```bash
curl -X POST http://localhost:8585/v1/traces/ingest \
  -H "Content-Type: application/json" \
  -d @trace.json
```

### Import JSONL File

**POST /v1/traces/import**

Bulk import traces from JSONL file.

**Query Parameters:**

- `file_path` (str, required): Absolute path to JSONL file

**Response:**

```json
{
  "imported": 100,
  "errors": 2
}
```

**curl:**

```bash
curl -X POST "http://localhost:8585/v1/traces/import?file_path=/traces/export.jsonl"
```

### List Traces

**GET /v1/traces**

Query traces with pagination and filtering.

**Query Parameters:**

- `limit` (int, default: 50, max: 200): Traces per page
- `offset` (int, default: 0): Pagination offset
- `service` (str, optional): Filter by service name
- `errors_only` (bool, default: false): Only traces with errors

**Response:**

```json
{
  "traces": [
    {
      "trace_id": "abc123",
      "service_name": "my-agent",
      "start_time": 1000.0,
      "duration_ms": 5000,
      "span_count": 3,
      "total_tokens": 2000,
      "total_cost_usd": 0.012,
      "has_errors": false,
      "error_count": 0
    }
  ],
  "total": 150,
  "limit": 50,
  "offset": 0
}
```

**curl:**

```bash
# Get first 50 traces
curl "http://localhost:8585/v1/traces?limit=50&offset=0"

# Filter by service
curl "http://localhost:8585/v1/traces?service=my-agent&limit=20"

# Only errors
curl "http://localhost:8585/v1/traces?errors_only=true"
```

### Get Trace

**GET /v1/traces/{trace_id}**

Retrieve complete trace with all spans.

**Path Parameters:**

- `trace_id` (str): Trace identifier

**Response:**

```json
{
  "trace_id": "abc123",
  "service_name": "my-agent",
  "start_time": 1000.0,
  "end_time": 1005.0,
  "duration_ms": 5000,
  "span_count": 3,
  "total_tokens": 2000,
  "total_cost_usd": 0.012,
  "has_errors": false,
  "error_count": 0,
  "spans": [...]
}
```

**curl:**

```bash
curl http://localhost:8585/v1/traces/abc123
```

### Get Causal DAG

**GET /v1/traces/{trace_id}/dag**

Retrieve causal DAG analysis with detected patterns.

**Path Parameters:**

- `trace_id` (str): Trace identifier

**Response:**

```json
{
  "trace_id": "abc123",
  "nodes": [
    {
      "span_id": "s1",
      "name": "agent_run",
      "kind": "agent",
      "status": "ok",
      "error_role": "independent",
      "duration_ms": 5000,
      "token_count": 2000
    }
  ],
  "edges": [],
  "patterns": [],
  "root_causes": [],
  "cascade_depth": 0,
  "has_errors": false
}
```

**curl:**

```bash
curl http://localhost:8585/v1/traces/abc123/dag | jq '.'
```

### Cost Breakdown

**GET /v1/cost/breakdown**

Multi-dimensional cost attribution.

**Query Parameters:**

- `group_by` (str, default: "service_name"): Grouping dimension
  - `"service_name"`: By service
  - `"kind"`: By span type (agent, llm, tool)
  - `"name"`: By span name

**Response:**

```json
[
  {
    "dimension": "my-agent",
    "total_cost_usd": 0.50,
    "total_tokens": 50000,
    "span_count": 100
  },
  {
    "dimension": "other-agent",
    "total_cost_usd": 0.30,
    "total_tokens": 30000,
    "span_count": 60
  }
]
```

**curl:**

```bash
# Cost by service
curl "http://localhost:8585/v1/cost/breakdown?group_by=service_name"

# Cost by span type
curl "http://localhost:8585/v1/cost/breakdown?group_by=kind"

# Cost by operation
curl "http://localhost:8585/v1/cost/breakdown?group_by=name"
```

### Global Statistics

**GET /v1/stats**

Aggregate statistics across all traces.

**Response:**

```json
{
  "total_traces": 1000,
  "total_spans": 5000,
  "total_tokens": 500000,
  "total_cost": 2.50,
  "error_traces": 150,
  "avg_duration_ms": 3500.0
}
```

**curl:**

```bash
curl http://localhost:8585/v1/stats | jq '.'
```

---

## Complete Example

End-to-end usage of SDK → Server:

```python
# Step 1: Instrument code
from flowlens import FlowLens, trace_agent, trace_llm, trace_tool

lens = FlowLens(service_name="research-bot", export_to="http", endpoint="http://localhost:8585/v1/traces/ingest")

@trace_agent(name="researcher")
async def run(task: str):
    plan = await think(task)
    result = await search(plan)
    return result

@trace_llm(model="claude-sonnet-4-20250514")
async def think(task: str):
    return await llm_client.messages.create(
        model="claude-sonnet-4-20250514",
        messages=[{"role": "user", "content": task}]
    )

@trace_tool(name="search")
async def search(query: str):
    return await search_api.query(query)

# Step 2: Run agent
await run("What is AI safety?")

# Step 3: Query via API
import httpx

async with httpx.AsyncClient() as client:
    # Get all traces for this service
    r = await client.get("http://localhost:8585/v1/traces?service=research-bot")
    traces = r.json()["traces"]

    # Analyze the first trace
    trace_id = traces[0]["trace_id"]
    r = await client.get(f"http://localhost:8585/v1/traces/{trace_id}/dag")
    dag = r.json()
    print(f"Root causes: {dag['root_causes']}")
    print(f"Patterns: {dag['patterns']}")
```
