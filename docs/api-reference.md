# FlowLens API Reference

Complete documentation of all public APIs: SDK, Analysis, and Server.

## Table of Contents

- [FlowLens Core Class](#flowlens-core-class)
- [Decorators](#decorators)
- [Auto-Instrumentation](#auto-instrumentation)
- [Data Models](#data-models)
- [Analysis Functions](#analysis-functions)
- [Server API Endpoints](#server-api-endpoints)
  - [Ingest](#post-v1tracesingest)
  - [Import](#post-v1tracesimport)
  - [List Traces](#get-v1traces)
  - [Get Trace](#get-v1tracestrace_id)
  - [Delete Trace](#delete-v1tracestrace_id)
  - [Causal DAG](#get-v1tracestrace_iddag)
  - [Error Traces](#get-v1traceserrors)
  - [Search Traces](#get-v1tracessearch)
  - [Cleanup](#post-v1tracescleanup)
  - [Cost Breakdown](#get-v1costbreakdown)
  - [Cost Trends](#get-v1costtrends)
  - [Pattern Summary](#get-v1patternssummary)
  - [Global Stats](#get-v1stats)
  - [WebSocket](#ws-wstraces)
  - [Health Check](#get-health)

---

## FlowLens Core Class

The main entry point for instrumentation.

### `FlowLens(service_name, export_to, ...)`

Initialize the FlowLens tracer. Creates a global singleton that all decorators reference automatically.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `service_name` | str | `"flowlens"` | Human-readable service name appearing in all traces |
| `export_to` | str | `"console"` | Exporter: `"console"`, `"jsonl"`, `"http"`, or `"callback"` |
| `output_dir` | str | `"./traces"` | Directory for JSONL exporter output |
| `endpoint` | str | `"http://localhost:8585/v1/traces/ingest"` | Target URL for HTTP exporter |
| `verbose` | bool | `False` | Print debug information during export |
| `metadata` | dict | `None` | Default metadata added to every trace |
| `sample_rate` | float | `1.0` | Fraction of traces to export (0.0–1.0) |
| `on_trace_complete` | callable | `None` | Callback invoked when each trace finishes |

**Example:**

```python
from flowlens import FlowLens

lens = FlowLens(
    service_name="my-agent",
    export_to="http",
    endpoint="http://localhost:8585/v1/traces/ingest",
    verbose=True,
    metadata={"env": "production", "version": "2.1"},
    sample_rate=0.5,  # Export 50% of traces
)
```

### `FlowLens.configure(**kwargs) -> FlowLens`

Alternative class-method constructor. Identical parameters to `__init__`.

```python
lens = FlowLens.configure(
    service_name="my-agent",
    export_to="jsonl",
    sample_rate=0.1,
)
```

### `FlowLens.get_instance() -> Optional[FlowLens]`

Retrieve the global singleton. Returns `None` if not yet initialized.

```python
lens = FlowLens.get_instance()
if lens:
    lens.checkpoint("my_step", result_count=42)
```

### `FlowLens.start_trace(metadata) -> Trace`

Manually create a new trace context. Prefer decorators; use this for manual instrumentation.

```python
trace = lens.start_trace(metadata={"task_id": "research-001"})
```

### `FlowLens.end_trace(trace)`

Finish a trace and trigger export. Called automatically by decorators.

```python
lens.end_trace(trace)
```

### `FlowLens.start_span(name, kind, attributes) -> Span`

Create a span within the current trace. Automatically links to the parent span if nested.

```python
span = lens.start_span(
    "db_query",
    kind=SpanKind.TOOL,
    attributes={"db": "postgres", "query": "SELECT ..."}
)
# ... do work ...
span.finish(status=SpanStatus.OK)
```

### `FlowLens.checkpoint(name, **attrs)`

Add a named event checkpoint to the currently active span.

```python
lens.checkpoint("retrieval_done", docs_count=42, latency_ms=120)
```

### `FlowLens.set_exporter(exporter)`

Swap the exporter at runtime. Useful for testing.

```python
from flowlens.sdk.exporters import CallbackExporter

captured = []
lens.set_exporter(CallbackExporter(lambda t: captured.append(t)))
```

### `FlowLens.shutdown()`

Flush pending traces and close resources. Call at program exit.

```python
import atexit
atexit.register(lens.shutdown)
```

---

## Decorators

Zero-intrusion decorators that wrap your functions. All decorators support both `async` and `sync` functions. Exceptions are re-raised after being recorded — no business logic is suppressed.

### `@trace_agent(name, metadata, **attrs)`

Wrap an agent's entry point. Creates a new trace and a root AGENT span. Exports the complete trace when the function returns.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name` | str | `"agent"` | Root span name |
| `metadata` | dict | `None` | Trace-level metadata |
| `**attrs` | any | — | Additional span attributes |

**Example:**

```python
from flowlens import trace_agent

@trace_agent(name="research_bot", metadata={"version": "2"})
async def run_agent(task: str) -> str:
    return await execute(task)

# Sync also supported
@trace_agent(name="sync_bot")
def run_sync(task: str) -> str:
    return task.upper()
```

### `@trace_llm(model, name, streaming, **attrs)`

Wrap LLM calls. Automatically extracts token usage and cost from the response.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `model` | str | `""` | Model identifier (e.g., `"claude-sonnet-4-20250514"`) |
| `name` | str | function name | Span name override |
| `streaming` | bool | `False` | Enable streaming trace mode |
| `**attrs` | any | — | Additional span attributes |

**Token extraction support:**

- Anthropic SDK: `result.usage.input_tokens / output_tokens`
- OpenAI SDK: `result["usage"]["prompt_tokens"] / completion_tokens`
- Google Generative AI: `result.usage_metadata.prompt_token_count`
- LiteLLM: `result.usage.prompt_tokens / completion_tokens`

**Example:**

```python
from flowlens import trace_llm

@trace_llm(model="claude-sonnet-4-20250514")
async def call_claude(messages: list) -> str:
    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        messages=messages
    )
    return response.content[0].text

# Streaming variant
@trace_llm(model="claude-sonnet-4-20250514", streaming=True)
async def stream_claude(messages: list):
    async with client.messages.stream(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=messages,
    ) as stream:
        async for text in stream.text_stream:
            yield text
```

### `@trace_tool(name, **attrs)`

Wrap tool or API calls. Captures input parameters as span attributes and records a result summary.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `name` | str | function name | Tool span name |
| `**attrs` | any | — | Additional span attributes |

**Example:**

```python
from flowlens import trace_tool

@trace_tool(name="web_search")
async def search(query: str, limit: int = 10) -> dict:
    return await search_api.query(query, limit)

# Attributes automatically captured on the span:
# - tool.input.query = "..."
# - tool.input.limit = 10
# - tool.output_summary = "<result summary>"
```

### `@trace_chain(name, **attrs)`

Wrap multi-step workflows or pipeline stages.

```python
from flowlens import trace_chain

@trace_chain(name="research_pipeline")
async def run_pipeline(task: str):
    docs = await retrieve(task)
    summary = await summarize(docs)
    return summary
```

### `@trace_retrieval(name, **attrs)`

Wrap RAG retrieval steps. Automatically records `retrieval.result_count` if the result is a list.

```python
from flowlens import trace_retrieval

@trace_retrieval(name="vector_search")
async def retrieve(query: str) -> list[dict]:
    return await vector_db.similarity_search(query, k=5)

# Attributes automatically captured:
# - retrieval.result_count = 5
# - retrieval.output_summary = "<list summary>"
```

---

## Auto-Instrumentation

Patch supported LLM clients automatically — no decorators required.

### `auto_instrument(lens, patch)`

Instrument supported frameworks by monkey-patching their core call methods.

**Parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `lens` | FlowLens | required | The initialized FlowLens instance |
| `patch` | list[str] | all supported | Frameworks to patch: `"anthropic"`, `"openai"`, `"langchain"` |

**Example:**

```python
from flowlens import FlowLens
from flowlens.sdk.auto_instrument import auto_instrument

lens = FlowLens(service_name="my-agent", export_to="http")
auto_instrument(lens)

# From here, all Anthropic / OpenAI / LangChain calls are traced automatically
```

**Selective patching:**

```python
# Only patch Anthropic
auto_instrument(lens, patch=["anthropic"])

# Patch OpenAI and LangChain only
auto_instrument(lens, patch=["openai", "langchain"])
```

**What gets traced per framework:**

| Framework | Traced calls |
|---|---|
| `anthropic` | `client.messages.create()`, `client.messages.stream()` |
| `openai` | `client.chat.completions.create()` |
| `langchain` | LLM `__call__`, tool `run`, chain `__call__` |

---

## Data Models

### `Span`

Represents a single instrumented operation.

**Attributes:**

| Attribute | Type | Description |
|---|---|---|
| `span_id` | str | Unique identifier (auto-generated) |
| `trace_id` | str | Parent trace identifier |
| `parent_span_id` | Optional[str] | Parent span for nesting (auto-linked) |
| `name` | str | Operation name |
| `kind` | SpanKind | Category: AGENT, LLM, TOOL, CHAIN, RETRIEVAL, CUSTOM |
| `status` | SpanStatus | OK, ERROR, or UNSET |
| `start_time` | float | Unix timestamp (seconds) |
| `end_time` | float | Unix timestamp (seconds) |
| `duration_ms` | float | Computed duration (read-only) |
| `attributes` | dict | Custom metadata key-value pairs |
| `events` | list[SpanEvent] | Named checkpoint events within the span |
| `token_usage` | Optional[TokenUsage] | Token counts and cost (LLM spans only) |
| `error_message` | Optional[str] | Error description if status=ERROR |
| `error_type` | Optional[str] | Exception class name |

**Methods:**

```python
span.finish(status=SpanStatus.OK)
span.add_event("step_complete", step=1, data="sample")
span.set_token_usage(input_tokens=1000, output_tokens=500, model="claude-sonnet-4-20250514")
span_dict = span.to_dict()
```

### `Trace`

A complete execution trace containing all spans.

**Attributes:**

| Attribute | Type | Description |
|---|---|---|
| `trace_id` | str | Unique identifier (auto-generated) |
| `service_name` | str | Service name |
| `root_span_id` | Optional[str] | Top-level span |
| `spans` | list[Span] | All spans in execution order |
| `start_time` | float | Trace start time |
| `end_time` | float | Trace end time |
| `duration_ms` | float | Total duration (read-only) |
| `total_tokens` | int | Sum of all token usage (read-only) |
| `total_cost_usd` | float | Estimated cost (read-only) |
| `has_errors` | bool | True if any span errored (read-only) |
| `error_count` | int | Number of error spans (read-only) |
| `error_rate` | float | Fraction of spans that errored (read-only) |
| `metadata` | dict | Custom metadata |

### `TokenUsage`

Token usage and estimated cost for an LLM span.

```python
usage = TokenUsage(
    input_tokens=1000,
    output_tokens=500,
    total_tokens=1500,
    input_cost_usd=0.003,
    output_cost_usd=0.0075,
    total_cost_usd=0.0105,
)
```

### `SpanKind` (Enum)

- `AGENT` — Agent main loop
- `LLM` — Language model call
- `TOOL` — Tool or API execution
- `CHAIN` — Multi-step workflow
- `RETRIEVAL` — RAG retrieval
- `CUSTOM` — User-defined

### `SpanStatus` (Enum)

- `OK` — Completed successfully
- `ERROR` — Threw an exception
- `UNSET` — Not yet finished

---

## Analysis Functions

### `build_causal_dag(trace) -> CausalDAG`

Build a directed acyclic graph showing error propagation paths.

```python
from flowlens.analysis.dag_builder import build_causal_dag

dag = build_causal_dag(trace)
print(dag.root_causes)     # ["span_id_1"]
print(dag.cascade_depth)   # 2
print(dag.has_errors)      # True

for node in dag.nodes:
    if node.error_role == ErrorRole.ROOT_CAUSE:
        print(f"Root cause: {node.name} — {node.error_message}")
```

### `detect_patterns(trace, dag) -> list[DetectedPattern]`

Run all five pattern detectors and populate `dag.patterns`.

```python
from flowlens.analysis.patterns import detect_patterns

patterns = detect_patterns(trace, dag)

for p in patterns:
    print(f"[{p.severity}] {p.pattern_type.value}: {p.description}")
    print(f"  Spans: {p.involved_spans}")
```

**Pattern thresholds:**

| Pattern | Threshold |
|---|---|
| `RETRY_STORM` | Same tool called 5+ times |
| `INFINITE_LOOP` | Sequence repeats 3+ times |
| `CONTEXT_OVERFLOW` | Token usage >= 90% of model limit |
| `TIMEOUT_CASCADE` | Any timeout with downstream failures |
| `EMPTY_RESPONSE` | LLM returns 0 output tokens |

### `CausalDAG` Data Structure

```python
@dataclass
class CausalDAG:
    trace_id: str
    nodes: list[CausalNode]          # All spans as graph nodes
    edges: list[CausalEdge]          # Error propagation edges
    patterns: list[DetectedPattern]  # Detected anti-patterns
    root_causes: list[str]           # Root cause span IDs
    has_errors: bool                 # True if any root causes exist
    cascade_depth: int               # Maximum error cascade depth

    def to_dict(self) -> dict: ...
```

---

## Server API Endpoints

Base URL: `http://localhost:8585`

Interactive documentation: `http://localhost:8585/docs`

---

### `POST /v1/traces/ingest`

Receive and store a single trace from the SDK HTTP exporter.

**Request body:**

```json
{
  "trace_id": "a1b2c3d4",
  "service_name": "my-agent",
  "start_time": 1700000000.0,
  "end_time": 1700000005.847,
  "duration_ms": 5847,
  "total_tokens": 2967,
  "total_cost_usd": 0.019,
  "has_errors": true,
  "error_count": 2,
  "span_count": 8,
  "metadata": {"env": "prod"},
  "spans": [
    {
      "span_id": "s1",
      "trace_id": "a1b2c3d4",
      "parent_span_id": null,
      "name": "research_bot",
      "kind": "agent",
      "status": "error",
      "start_time": 1700000000.0,
      "end_time": 1700000005.847,
      "duration_ms": 5847,
      "attributes": {},
      "events": [],
      "token_usage": {
        "input_tokens": 1856,
        "output_tokens": 1111,
        "total_cost_usd": 0.019
      }
    }
  ]
}
```

**Response (201):**

```json
{
  "status": "ok",
  "trace_id": "a1b2c3d4"
}
```

```bash
curl -X POST http://localhost:8585/v1/traces/ingest \
  -H "Content-Type: application/json" \
  -d @trace.json
```

---

### `POST /v1/traces/import`

Bulk import traces from a JSONL file on disk. Each line must be a valid trace JSON object.

**Query parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `file_path` | str | yes | Absolute path to the JSONL file |

**Response (201):**

```json
{
  "imported": 100,
  "errors": 2
}
```

```bash
curl -X POST "http://localhost:8585/v1/traces/import?file_path=/data/traces/export.jsonl"
```

---

### `GET /v1/traces`

List traces with pagination and optional filtering.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `limit` | int | 50 | Traces per page (max 200) |
| `offset` | int | 0 | Pagination offset |
| `service` | str | — | Filter by service name (exact match) |
| `errors_only` | bool | false | Return only traces with errors |

**Response (200):**

```json
{
  "traces": [
    {
      "trace_id": "a1b2c3d4",
      "service_name": "my-agent",
      "start_time": 1700000000.0,
      "duration_ms": 5847,
      "span_count": 8,
      "total_tokens": 2967,
      "total_cost_usd": 0.019,
      "has_errors": true,
      "error_count": 2
    }
  ],
  "total": 150,
  "limit": 50,
  "offset": 0
}
```

```bash
# First page
curl "http://localhost:8585/v1/traces?limit=50&offset=0"

# Filter by service
curl "http://localhost:8585/v1/traces?service=my-agent&limit=20"

# Errors only
curl "http://localhost:8585/v1/traces?errors_only=true"

# Second page of errors for a specific service
curl "http://localhost:8585/v1/traces?service=my-agent&errors_only=true&limit=20&offset=20"
```

---

### `GET /v1/traces/{trace_id}`

Retrieve the complete trace including all spans.

**Path parameters:**

| Parameter | Type | Description |
|---|---|---|
| `trace_id` | str | Trace identifier |

**Response (200):**

```json
{
  "trace_id": "a1b2c3d4",
  "service_name": "my-agent",
  "start_time": 1700000000.0,
  "end_time": 1700000005.847,
  "duration_ms": 5847,
  "span_count": 8,
  "total_tokens": 2967,
  "total_cost_usd": 0.019,
  "has_errors": true,
  "error_count": 2,
  "metadata": {"env": "prod"},
  "spans": [...]
}
```

**Error (404):**

```json
{"detail": "Trace not found: a1b2c3d4"}
```

```bash
curl http://localhost:8585/v1/traces/a1b2c3d4
```

---

### `DELETE /v1/traces/{trace_id}`

Permanently delete a trace and all its spans.

**Path parameters:**

| Parameter | Type | Description |
|---|---|---|
| `trace_id` | str | Trace identifier |

**Response (200):**

```json
{
  "status": "deleted",
  "trace_id": "a1b2c3d4"
}
```

**Error (404):**

```json
{"detail": "Trace not found: a1b2c3d4"}
```

```bash
curl -X DELETE http://localhost:8585/v1/traces/a1b2c3d4
```

---

### `GET /v1/traces/{trace_id}/dag`

Retrieve the causal DAG analysis for a trace, including detected patterns.

**Path parameters:**

| Parameter | Type | Description |
|---|---|---|
| `trace_id` | str | Trace identifier |

**Response (200):**

```json
{
  "trace_id": "a1b2c3d4",
  "nodes": [
    {
      "span_id": "s3",
      "name": "web_search",
      "kind": "tool",
      "status": "error",
      "error_role": "root_cause",
      "error_message": "Connection timeout after 2000ms",
      "duration_ms": 2003,
      "token_count": 0
    },
    {
      "span_id": "s4",
      "name": "fetch_page",
      "kind": "tool",
      "status": "error",
      "error_role": "cascaded",
      "error_message": "Invalid input: empty URL",
      "duration_ms": 5,
      "token_count": 0
    }
  ],
  "edges": [
    {
      "source_id": "s3",
      "target_id": "s4",
      "relation": "preceded_by"
    }
  ],
  "patterns": [
    {
      "pattern_type": "timeout_cascade",
      "severity": "critical",
      "description": "'web_search' timeout caused 1 downstream failure",
      "involved_spans": ["s3", "s4"],
      "details": {"timeout": "web_search"}
    }
  ],
  "root_causes": ["s3"],
  "cascade_depth": 1,
  "has_errors": true
}
```

```bash
curl http://localhost:8585/v1/traces/a1b2c3d4/dag | jq '.'
```

---

### `GET /v1/traces/errors`

List traces that contain at least one error span, sorted by most recent first.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `limit` | int | 50 | Traces per page (max 200) |
| `offset` | int | 0 | Pagination offset |
| `service` | str | — | Filter by service name |

**Response (200):**

```json
{
  "traces": [
    {
      "trace_id": "a1b2c3d4",
      "service_name": "my-agent",
      "start_time": 1700000000.0,
      "duration_ms": 5847,
      "span_count": 8,
      "total_tokens": 2967,
      "total_cost_usd": 0.019,
      "has_errors": true,
      "error_count": 2
    }
  ],
  "total": 23,
  "limit": 50,
  "offset": 0
}
```

```bash
# All error traces
curl "http://localhost:8585/v1/traces/errors"

# Error traces for a specific service
curl "http://localhost:8585/v1/traces/errors?service=my-agent"
```

---

### `GET /v1/traces/search`

Full-text search across trace and span content.

**Query parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `q` | str | yes | Search query string |
| `limit` | int | 20 | Results per page (max 100) |
| `offset` | int | 0 | Pagination offset |
| `service` | str | — | Filter by service name |

**Searchable fields:** `trace_id`, `service_name`, span `name`, span `error_message`, span `attributes`

**Response (200):**

```json
{
  "query": "timeout",
  "results": [
    {
      "trace_id": "a1b2c3d4",
      "service_name": "my-agent",
      "matched_spans": ["web_search"],
      "duration_ms": 5847,
      "has_errors": true
    }
  ],
  "total": 7,
  "limit": 20,
  "offset": 0
}
```

```bash
# Search for timeout-related traces
curl "http://localhost:8585/v1/traces/search?q=timeout"

# Search within a specific service
curl "http://localhost:8585/v1/traces/search?q=fetch_page&service=my-agent"
```

---

### `POST /v1/traces/cleanup`

Delete traces older than a specified number of days to manage disk usage.

**Request body:**

```json
{
  "older_than_days": 30
}
```

**Response (200):**

```json
{
  "deleted": 412,
  "older_than_days": 30
}
```

```bash
# Delete traces older than 30 days
curl -X POST http://localhost:8585/v1/traces/cleanup \
  -H "Content-Type: application/json" \
  -d '{"older_than_days": 30}'
```

---

### `GET /v1/cost/breakdown`

Multi-dimensional cost attribution across all stored traces.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `group_by` | str | `"service_name"` | Grouping dimension: `"service_name"`, `"kind"`, `"name"` |

**Response (200):**

```json
[
  {
    "dimension": "research-bot",
    "total_cost_usd": 2.50,
    "total_tokens": 100000,
    "span_count": 200
  },
  {
    "dimension": "qa-bot",
    "total_cost_usd": 1.20,
    "total_tokens": 50000,
    "span_count": 100
  }
]
```

```bash
# Cost by service
curl "http://localhost:8585/v1/cost/breakdown?group_by=service_name"

# Cost by span type (agent, llm, tool)
curl "http://localhost:8585/v1/cost/breakdown?group_by=kind"

# Cost by operation name
curl "http://localhost:8585/v1/cost/breakdown?group_by=name"
```

---

### `GET /v1/cost/trends`

Cost aggregated over time intervals. Useful for monitoring spend trends.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `interval` | str | `"day"` | Aggregation interval: `"hour"`, `"day"`, `"week"` |
| `days` | int | 30 | Number of days of history to return |
| `service` | str | — | Filter by service name |

**Response (200):**

```json
{
  "interval": "day",
  "data": [
    {
      "date": "2026-03-14",
      "total_cost_usd": 0.82,
      "total_tokens": 41000,
      "trace_count": 18
    },
    {
      "date": "2026-03-13",
      "total_cost_usd": 1.15,
      "total_tokens": 57500,
      "trace_count": 25
    }
  ]
}
```

```bash
# Daily cost for last 30 days
curl "http://localhost:8585/v1/cost/trends?interval=day&days=30"

# Weekly cost for a specific service
curl "http://localhost:8585/v1/cost/trends?interval=week&service=research-bot"
```

---

### `GET /v1/patterns/summary`

Aggregated counts and rates for all detected anti-patterns across stored traces.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `service` | str | — | Filter by service name |
| `days` | int | 7 | Lookback window in days |

**Response (200):**

```json
{
  "total_traces_analyzed": 250,
  "period_days": 7,
  "patterns": [
    {
      "pattern_type": "timeout_cascade",
      "count": 12,
      "rate": 0.048,
      "severity_distribution": {
        "critical": 8,
        "warning": 4
      },
      "most_affected_service": "research-bot"
    },
    {
      "pattern_type": "retry_storm",
      "count": 5,
      "rate": 0.02,
      "severity_distribution": {
        "critical": 5,
        "warning": 0
      },
      "most_affected_service": "research-bot"
    }
  ]
}
```

```bash
# Pattern summary for last 7 days
curl "http://localhost:8585/v1/patterns/summary"

# Pattern summary for a specific service, last 30 days
curl "http://localhost:8585/v1/patterns/summary?service=research-bot&days=30"
```

---

### `GET /v1/stats`

Global aggregate statistics across all stored traces.

**Response (200):**

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

```bash
curl http://localhost:8585/v1/stats | jq '.'
```

---

### `WS /ws/traces`

WebSocket endpoint that broadcasts a message for every trace ingested by the server.

**Connection URL:** `ws://localhost:8585/ws/traces`

**Message format:** Each message is a complete trace serialized as JSON (same schema as `GET /v1/traces/{id}`).

**Behavior:**
- Connects immediately; no authentication required
- Receives one message per trace as soon as it is stored
- Connection remains open until closed by client or server restart
- Multiple clients may connect simultaneously

**Python example:**

```python
import asyncio
import websockets
import json

async def stream_traces():
    uri = "ws://localhost:8585/ws/traces"
    async with websockets.connect(uri) as ws:
        print("Connected to FlowLens trace stream")
        async for message in ws:
            trace = json.loads(message)
            print(
                f"[{trace['service_name']}] {trace['trace_id']} "
                f"| {trace['duration_ms']:.0f}ms "
                f"| {'ERROR' if trace['has_errors'] else 'OK'}"
            )

asyncio.run(stream_traces())
```

**JavaScript example:**

```javascript
const ws = new WebSocket("ws://localhost:8585/ws/traces");

ws.onopen = () => {
  console.log("Connected to FlowLens trace stream");
};

ws.onmessage = (event) => {
  const trace = JSON.parse(event.data);
  if (trace.has_errors) {
    showAlert(`Error in ${trace.service_name}: ${trace.error_count} span(s) failed`);
  }
  appendTraceRow(trace);
};

ws.onclose = () => {
  console.log("Disconnected from FlowLens");
  setTimeout(() => reconnect(), 3000);  // auto-reconnect
};
```

---

### `GET /health`

Server health check.

**Response (200):**

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

```bash
curl http://localhost:8585/health
```

---

## Complete End-to-End Example

```python
import asyncio
import httpx
from flowlens import FlowLens, trace_agent, trace_llm, trace_tool

# 1. Initialize SDK to send traces to server
lens = FlowLens(
    service_name="research-bot",
    export_to="http",
    endpoint="http://localhost:8585/v1/traces/ingest",
)

# 2. Instrument your agent
@trace_agent(name="researcher")
async def run(task: str):
    plan = await think(task)
    result = await search(plan)
    return result

@trace_llm(model="claude-sonnet-4-20250514")
async def think(task: str):
    return await llm_client.messages.create(
        model="claude-sonnet-4-20250514",
        messages=[{"role": "user", "content": task}],
    )

@trace_tool(name="search")
async def search(query: str):
    return await search_api.query(query)

# 3. Run the agent
asyncio.run(run("What is AI safety?"))

# 4. Query results via REST API
async def analyze():
    async with httpx.AsyncClient() as client:
        # List recent traces for this service
        r = await client.get(
            "http://localhost:8585/v1/traces",
            params={"service": "research-bot", "limit": 5},
        )
        traces = r.json()["traces"]

        # Analyze the most recent trace
        trace_id = traces[0]["trace_id"]

        r = await client.get(f"http://localhost:8585/v1/traces/{trace_id}/dag")
        dag = r.json()
        print(f"Root causes: {dag['root_causes']}")
        print(f"Patterns: {[p['pattern_type'] for p in dag['patterns']]}")

        # Cost breakdown
        r = await client.get(
            "http://localhost:8585/v1/cost/breakdown",
            params={"group_by": "service_name"},
        )
        print(r.json())

asyncio.run(analyze())
```
