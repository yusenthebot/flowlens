# FlowLens Architecture

Complete technical guide to FlowLens internals, design decisions, and algorithms.

## System Overview

```
┌──────────────────────────────────────────────────────────────┐
│                    Your Agent Code                            │
│   @trace_agent  ·  @trace_llm  ·  @trace_tool                │
│   @trace_chain  ·  @trace_retrieval  ·  auto_instrument()    │
└────────────┬─────────────────────────────┬────────────────────┘
             │                              │
    ┌────────▼────────┐              ┌─────────▼──────────┐
    │   SDK Layer     │              │ Analysis Layer     │
    │                 │              │                    │
    │ • Models        │              │ • DAG Builder      │
    │ • Decorators    │              │ • Pattern Detect   │
    │ • Context Mgmt  │              │ • Root Cause ID    │
    │ • Exporters     │              │ • Cost Engine      │
    │ • Auto-Instr.   │              └────────┬───────────┘
    └────────┬────────┘                       │
             │                      ┌────────▼────────────┐
             └────────► export      │  Server Layer        │
                                    │                      │
                                    │ • FastAPI REST API   │
                                    │ • 6 Route Modules    │
                                    │ • Validation         │
                                    │ • WebSocket Hub      │
                                    │ • SQLite Store       │
                                    │ • Rate Limiting      │
                                    │ • Dashboard Serving  │
                                    └──────────────────────┘
```

### Three-Layer Architecture

1. **SDK Layer** (`flowlens/sdk/`): Instrumentation via decorators and auto-patching, context propagation, data collection, and export.
2. **Analysis Layer** (`flowlens/analysis/`): Post-trace processing — causal DAG construction, error classification, pattern detection, cost estimation.
3. **Server Layer** (`flowlens/server/`): FastAPI REST API with 6 modular route modules, trace ingest validation, WebSocket broadcasting, SQLite persistence, and static dashboard serving.

---

## Server Architecture (Modularized)

### Route Module Structure

The server layer has been refactored from a monolithic app.py (2003 lines) into focused, single-responsibility route modules:

```
flowlens/server/
├── app.py              # Main FastAPI app setup (401 lines)
├── utils.py            # Shared utilities, security helpers, AGENT_PROFILES
├── validation.py       # Trace ingest validation
├── routes/
│   ├── traces.py       # Trace lifecycle: ingest, query, delete, search (15 endpoints)
│   ├── cost.py         # Cost breakdown, trends, forecasting (5 endpoints)
│   ├── agents.py       # Agent profiles, activity, relationships, network (5 endpoints)
│   ├── stats.py        # Statistics, trends, summary, feedback (9 endpoints)
│   ├── alerts.py       # Alert rules, budget alerts (5 endpoints)
│   └── system.py       # Health, version, utility endpoints (5 endpoints)
├── storage.py          # SQLite schema, queries, storage layer
├── dashboard.html      # Static dashboard (750 lines)
└── static/             # CSS/JS modules
    ├── dashboard.css   # Dashboard styling
    ├── dashboard.js    # Main logic
    ├── charts.js       # Chart rendering
    ├── network.js      # SVG network visualization
    └── websocket.js    # WebSocket client
```

### Module Responsibilities

| Module | Endpoints | Purpose |
|--------|-----------|---------|
| `traces.py` | 15 | Trace ingest, retrieval, DAG analysis, search, import/export |
| `cost.py` | 5 | Cost breakdown, trend analysis, monthly forecasting |
| `agents.py` | 5 | Agent profiles, activity streams, relationships, topology |
| `stats.py` | 9 | Statistics, trends, per-agent breakdown, feedback |
| `alerts.py` | 5 | Alert rules, budget tracking, cost spike detection |
| `system.py` | 5 | Health checks, version info, utility endpoints |

### Shared Components

- **utils.py**: Security helpers, rate limiting decorators, AGENT_PROFILES configuration
- **validation.py**: Trace ingest validation (cycles, orphans, sizes, payloads)
- **storage.py**: SQLite schema, query methods, full-text search
- **WebSocket ConnectionManager**: Real-time broadcast hub for traces and alerts

---

## Data Flow: Decorator to Export

### 1. Decorator Wraps Function

```python
@trace_agent(name="my_bot")
async def my_agent():
    result = await task()
    return result
```

The decorator (`decorators.py`) executes as:

```
my_agent()
  → async_wrapper()
    → FlowLens.get_instance()          [get singleton]
    → lens.start_trace()               [create Trace, register in _active_traces]
    → TraceContext(trace).__enter__()  [set context var]
    → lens.start_span("my_bot", AGENT) [create Span, append to trace.spans]
    → SpanContext(span).__enter__()    [set context var, auto-link parent]
    → [call original my_agent()]
    → span.finish(status=OK)
    → lens.end_trace(trace)            [sample, callback, export]
    → exporter.export(trace)           [send to destination]
```

### 2. Context Management (contextvars)

**Why `contextvars`?**

- Each coroutine has its own context — safe for concurrent `asyncio` tasks
- Parent-child linking happens automatically — user code never manages context
- Standard library — zero external dependencies

**Implementation:**

```python
# context.py
_current_trace = contextvars.ContextVar('flowlens_current_trace', default=None)
_current_span = contextvars.ContextVar('flowlens_current_span', default=None)

class TraceContext:
    def __enter__(self):
        self._token = _current_trace.set(self.trace)

    def __exit__(self, *_):
        _current_trace.reset(self._token)  # Restore previous value

class SpanContext:
    def __enter__(self):
        # Auto-detect parent from context
        parent = get_current_span()
        if parent:
            self.span.parent_span_id = parent.span_id
        self._token = _current_span.set(self.span)

    def __exit__(self, *_):
        _current_span.reset(self._token)
```

**Nested trace execution:**

```
Async task A:
  TraceContext(trace1)                   ← current_trace = trace1
    SpanContext(agent_span)              ← current_span = agent_span
      SpanContext(llm_span)             ← current_span = llm_span
        parent_span_id = agent_span.id  ← auto-linked
      SpanContext(tool_span)            ← current_span = tool_span
        parent_span_id = agent_span.id  ← auto-linked
```

Async tasks inherit their parent's context variables at creation time. Concurrent tasks (e.g., `asyncio.gather`) each get independent copies of the context, preventing cross-contamination.

### 3. Span Lifecycle

```python
@dataclass
class Span:
    span_id: str              # UUID[:16] — auto-generated
    trace_id: str             # Set when span is added to trace
    parent_span_id: Optional  # Set by SpanContext.__enter__
    name: str
    kind: SpanKind
    status: SpanStatus        # UNSET until finish() is called
    start_time: float         # Set at construction time
    end_time: float           # Set by finish()
    attributes: dict
    events: list[SpanEvent]
    token_usage: TokenUsage   # LLM spans only
    error_message: Optional[str]
```

Lifecycle:

1. Created by `lens.start_span(...)` at function entry
2. Modified by `span.add_event(...)`, `span.set_token_usage(...)`
3. Finished by `span.finish(status, error)` at function exit (finally block)
4. Exported when `lens.end_trace(trace)` is called

### 4. Exporter Interface

```python
class TraceExporter:
    def export(self, trace: Trace) -> None: ...
    def shutdown(self) -> None: ...
```

| Exporter | Use case | Config |
|---|---|---|
| `ConsoleExporter` | Development: colored tree output to stdout | `export_to="console"` |
| `JSONLExporter` | File storage: one JSON object per line | `export_to="jsonl"` |
| `HTTPExporter` | Remote server: POST to ingest endpoint | `export_to="http"` |
| `CallbackExporter` | Testing: user-provided Python callable | Manual construction |

**Console exporter output format:**

```
[FlowLens] Trace a1b2c3d4 | 8 spans | 1847ms | 2967 tokens | $0.0190 | ERROR
  agent research_bot (1847ms)
  ├─ llm plan_research (312ms) [856 tok]
  └─ tool web_search (2003ms) ERROR timeout
```

---

## Auto-Instrumentation Architecture

Auto-instrumentation (`flowlens/sdk/auto_instrument.py`) works by monkey-patching the core call methods of supported LLM client libraries at runtime.

### Patching Strategy

```
auto_instrument(lens)
  → _patch_anthropic(lens)
      → original_create = anthropic.Anthropic.messages.create
      → anthropic.Anthropic.messages.create = _wrapped_create
      → _wrapped_create():
          span = lens.start_span("anthropic.messages.create", kind=LLM)
          result = original_create(...)
          _extract_llm_usage(span, result, model)
          span.finish(OK)
          return result

  → _patch_openai(lens)
      → original = openai.OpenAI.chat.completions.create
      → openai.OpenAI.chat.completions.create = _wrapped(...)

  → _patch_langchain(lens)
      → patches BaseLLM.__call__, BaseTool.run, Chain.__call__
```

### Streaming Patch

For streaming calls, the patch wraps the async generator to accumulate token counts as chunks arrive:

```
_patched_stream(messages)
  → span = lens.start_span("anthropic.messages.stream", kind=LLM)
  → async with original_stream(messages) as stream:
      async for text in stream.text_stream:
          yield text             ← pass-through, no buffering
  → # After stream completes:
      _extract_llm_usage(span, stream.get_final_message(), model)
      span.finish(OK)
```

Token counts come from the final message object (Anthropic) or the `usage` chunk (OpenAI SSE), not from counting characters — ensuring accuracy.

### Safe Patching

Each patch stores the original method and restores it on `lens.shutdown()`, making auto-instrumentation safe for testing environments where you want to swap configurations between test runs.

---

## Causal DAG Algorithm

The core analysis engine identifies root causes and maps error propagation.

### Input

```
Trace:
  Span S1 (agent, OK)
    ├─ Span S2 (llm, OK)
    ├─ Span S3 (tool, ERROR) ← search timeout
    ├─ Span S4 (tool, ERROR) ← fetch failed (cascaded from S3)
    └─ Span S5 (tool, OK)   ← retry succeeded
```

### Algorithm Steps

**Step 1: Build index structures**

```python
parent_of = {"S2": "S1", "S3": "S1", "S4": "S1", "S5": "S1"}
children_of = {"S1": ["S2", "S3", "S4", "S5"]}
sibling_groups = {"S1": ["S2", "S3", "S4", "S5"]}  # Ordered by start_time
error_span_ids = {"S3", "S4"}
```

**Step 2: Classify each error span**

For each error span, check:
1. Does it have an error ancestor? (walk up parent chain)
2. Does it have an error predecessor? (earlier sibling in execution order with ERROR status)

Classification rules:
- `ROOT_CAUSE`: No error ancestor AND no error predecessor
- `CASCADED`: Has error ancestor OR error predecessor
- `INDEPENDENT`: Error with no relationship to other errors

```
S3 (ERROR): parent=S1 (OK), no earlier ERROR sibling → ROOT_CAUSE
S4 (ERROR): parent=S1 (OK), earlier ERROR sibling=S3 → CASCADED
```

**Step 3: Build causal edges**

```python
# Edge types:
# 1. Parent → child (error parent → error child)
# 2. Sibling → sibling (earlier error → next error in time order)

for span_id in error_span_ids:
    parent = parent_of.get(span_id)
    if parent and parent in error_span_ids:
        edges.append(CausalEdge(parent, span_id, "caused_by"))

    siblings = sibling_groups.get(parent_of.get(span_id), [])
    idx = siblings.index(span_id)
    if idx > 0 and siblings[idx - 1] in error_span_ids:
        edges.append(CausalEdge(siblings[idx - 1], span_id, "preceded_by"))
```

**Step 4: Compute cascade depth**

BFS from each root cause following edges, recording the maximum depth reached.

**Output:**

```python
CausalDAG(
    trace_id="t1",
    nodes=[
        CausalNode(span_id="S3", error_role=ROOT_CAUSE),
        CausalNode(span_id="S4", error_role=CASCADED),
    ],
    edges=[CausalEdge("S3", "S4", "preceded_by")],
    root_causes=["S3"],
    cascade_depth=1,
)
```

---

## Pattern Detection Logic

Five detectors run sequentially after `build_causal_dag()` completes.

### 1. Retry Storm

**Trigger:** Same tool name appears 5+ times in the trace.

```python
tool_counts = Counter(s.name for s in spans if s.kind == TOOL)
for name, count in tool_counts.items():
    if count >= 5:
        error_rate = errors_with_name / count
        severity = "critical" if error_rate > 0.8 else "warning"
        yield DetectedPattern(RETRY_STORM, severity, ...)
```

### 2. Infinite Loop

**Trigger:** A sequence of 2 or 3 tool names repeats 3+ consecutive times.

```python
tool_sequence = [s.name for s in sorted_tool_spans]
# e.g., ["search", "fetch", "search", "fetch", "search", "fetch"]

for cycle_len in (2, 3):
    for start in range(len(tool_sequence)):
        cycle = tool_sequence[start:start + cycle_len]
        repeat_count = count_consecutive_repetitions(tool_sequence, start, cycle)
        if repeat_count >= 3:
            yield DetectedPattern(INFINITE_LOOP, "critical", ...)
```

### 3. Context Overflow

**Trigger:** Token usage >= 90% of the model's context window.

```python
MODEL_LIMITS = {
    "claude-*": 200_000,
    "gpt-4o": 128_000,
    "gemini-2.5-pro": 1_000_000,
    "deepseek-*": 64_000,
}

for span in llm_spans:
    limit = lookup_model_limit(span.attributes["gen_ai.request.model"])
    ratio = span.token_usage.total_tokens / limit
    if ratio >= 0.9:
        severity = "critical" if ratio >= 1.0 else "warning"
        yield DetectedPattern(CONTEXT_OVERFLOW, severity, ...)
```

### 4. Timeout Cascade

**Trigger:** A span with "timeout" in its error message has downstream error spans in the DAG.

```python
timeout_spans = [s for s in spans if "timeout" in (s.error_message or "").lower()]
for ts in timeout_spans:
    downstream = bfs_error_descendants(ts.span_id, dag)
    if downstream:
        yield DetectedPattern(TIMEOUT_CASCADE, "critical", ...)
```

### 5. Empty Response

**Trigger:** An LLM span completes successfully (status=OK) but reports 0 output tokens.

```python
for span in llm_spans:
    if span.status == OK and span.token_usage and span.token_usage.output_tokens == 0:
        yield DetectedPattern(EMPTY_RESPONSE, "warning", ...)
```

---

## Cost Estimation

### Pricing Table

```python
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Format: (input_per_1M_tokens, output_per_1M_tokens) in USD
    "claude-opus-4-20250514":    (15.0, 75.0),
    "claude-sonnet-4-20250514":  (3.0,  15.0),
    "claude-haiku-3-5-20251022": (0.8,  4.0),
    "gpt-4o":                    (2.5,  10.0),
    "gpt-4o-mini":               (0.15, 0.6),
    "gpt-4.1":                   (2.0,  8.0),
    "gemini-2.5-pro":            (1.25, 10.0),
    "gemini-2.5-flash":          (0.075, 0.3),
    "deepseek-v3":               (0.27, 1.1),
    "deepseek-r1":               (0.55, 2.19),
    # ... 6+ more models
}

_DEFAULT_PRICING = (3.0, 15.0)  # Fallback for unknown models
```

### Fuzzy Model Matching

The cost estimator uses substring matching to handle model version strings gracefully:

```python
def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> dict:
    model_lower = model.lower()
    pricing = _DEFAULT_PRICING

    for key in _MODEL_PRICING:
        if key in model_lower or model_lower in key:
            pricing = _MODEL_PRICING[key]
            break

    input_cost = (input_tokens / 1_000_000) * pricing[0]
    output_cost = (output_tokens / 1_000_000) * pricing[1]
    return {"total_cost_usd": round(input_cost + output_cost, 6), ...}
```

---

## Trace Ingest Validation

The validation.py module validates incoming traces for data integrity before persistence.

### Validation Checks

1. **Cycle detection**: Detects self-references and bidirectional parent-child relationships
2. **Orphan references**: Detects spans referencing non-existent parent spans
3. **Span count limits**: Enforces maximum span count per trace
4. **Payload size limits**: Enforces maximum total payload size

### Validation Levels

```python
# strict: Reject invalid traces (early failure)
# warning: Log warnings but allow persistence (observability)
# informational: Log info only, allow all traces (permissive)

ValidationLevel = Enum("STRICT", "WARNING", "INFORMATIONAL")
```

### Example Usage

```python
validator = TraceValidator(level=ValidationLevel.WARNING)
errors = validator.validate(trace_dict)
if errors:
    logger.warning(f"Validation issues: {errors}")
```

---

## Server Storage and Querying

### Database Schema (SQLite)

```sql
CREATE TABLE traces (
    trace_id    TEXT PRIMARY KEY,
    service_name TEXT,
    start_time  REAL,
    end_time    REAL,
    duration_ms REAL,
    total_tokens INTEGER,
    total_cost_usd REAL,
    has_errors  BOOLEAN,
    error_count INTEGER,
    span_count  INTEGER,
    metadata    TEXT,     -- JSON blob
    spans_json  TEXT,     -- JSON array of all spans
    session_id  TEXT,     -- For session timeline grouping
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_service   ON traces(service_name);
CREATE INDEX idx_errors    ON traces(has_errors);
CREATE INDEX idx_created   ON traces(created_at DESC);
CREATE INDEX idx_cost      ON traces(total_cost_usd DESC);
CREATE INDEX idx_session   ON traces(session_id);

CREATE VIRTUAL TABLE spans_fts USING fts5(
    span_id, trace_id, name, kind, attributes
);
```

### Query Operations

```python
class TraceStore:
    def save_trace(self, trace_data: dict) -> None: ...
    def get_trace(self, trace_id: str) -> Optional[dict]: ...
    def delete_trace(self, trace_id: str) -> bool: ...
    def list_traces(self, limit, offset, service_name, has_errors) -> list[dict]: ...
    def search_traces(self, query: str, limit, offset, service_name) -> list[dict]: ...
    def get_error_traces(self, limit, offset, service_name) -> list[dict]: ...
    def cleanup_old_traces(self, older_than_days: int) -> int: ...
    def get_cost_breakdown(self, group_by: str) -> list[dict]: ...
    def get_cost_trends(self, interval: str, days: int, service_name) -> dict: ...
    def get_pattern_summary(self, days: int, service_name) -> dict: ...
    def get_stats(self) -> dict: ...
    def get_recent_feedback(self, limit: int) -> list[dict]: ...
```

### Full-Text Search Implementation

Search uses SQLite's FTS5 MATCH with LIKE fallback:

```sql
SELECT trace_id, service_name, duration_ms, has_errors, spans_json
FROM spans_fts
WHERE spans_fts MATCH :query
LIMIT :limit OFFSET :offset;

-- Fallback to LIKE:
SELECT trace_id, service_name, duration_ms, has_errors, spans_json
FROM traces
WHERE spans_json LIKE '%:query:%'
ORDER BY created_at DESC
LIMIT :limit OFFSET :offset;
```

Post-query, the server inspects `spans_json` to identify which span names matched.

### Cost Trends Query with Forecasting

```sql
SELECT
    strftime('%Y-%m-%d', datetime(created_at)) as date,
    SUM(total_cost_usd) as total_cost_usd,
    SUM(total_tokens) as total_tokens,
    COUNT(*) as trace_count
FROM traces
WHERE created_at >= datetime('now', '-:days days')
  AND (:service IS NULL OR service_name = :service)
GROUP BY date
ORDER BY date DESC;
```

Forecasting applies linear regression to daily costs, computing 95% confidence intervals for month-ahead projection.

---

## WebSocket Connection Management

The WebSocket hub (`/ws/traces`) maintains a set of connected clients and broadcasts to all of them whenever a trace is ingested.

### Architecture

```
                ┌─────────────────────────────────────┐
                │          WebSocket Hub               │
                │                                      │
Ingest POST ───►│  broadcast(trace_json)               │
                │      │                               │
                │      ├──► client_1.send_text(...)    │
                │      ├──► client_2.send_text(...)    │
                │      └──► client_N.send_text(...)    │
                │                                      │
                │  Connected set: {ws_1, ws_2, ...}    │
                └─────────────────────────────────────┘
```

### Connection Lifecycle

```python
class ConnectionManager:
    def __init__(self):
        self.active_connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active_connections.add(ws)

    def disconnect(self, ws: WebSocket):
        self.active_connections.discard(ws)

    async def broadcast(self, message: str):
        dead = set()
        for ws in self.active_connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        self.active_connections -= dead  # Remove stale connections
```

### Integration with Ingest

After `store.save_trace(data)` succeeds in the `/v1/traces/ingest` handler, the server calls `manager.broadcast(json.dumps(data))`. This happens in the same request handler, so WebSocket delivery is synchronous with storage — clients always receive a trace that is already queryable via REST.

### Concurrency Model

The WebSocket hub is a single in-process object shared across all FastAPI route handlers. Because FastAPI runs on a single-threaded async event loop (Uvicorn), the `active_connections` set is accessed only from coroutines on the same event loop — no locking is required.

If you scale to multiple Uvicorn worker processes, add a Redis Pub/Sub layer between the ingest handler and the WebSocket hub.

---

## Rate Limiting Design

Rate limiting protects the ingest endpoint from trace floods in production.

### Implementation

FlowLens uses a token-bucket algorithm per source IP, enforced via a FastAPI middleware:

```python
class RateLimiter:
    def __init__(self, rate: int = 100, per: float = 1.0):
        self.rate = rate            # Max requests per window
        self.per = per              # Window size in seconds
        self._buckets: dict[str, list[float]] = {}  # IP → list of timestamps

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        window_start = now - self.per
        timestamps = self._buckets.get(key, [])

        # Remove timestamps outside window
        timestamps = [t for t in timestamps if t > window_start]
        if len(timestamps) >= self.rate:
            return False
        timestamps.append(now)
        self._buckets[key] = timestamps
        return True
```

**Default limits:**

| Endpoint | Limit |
|---|---|
| `POST /v1/traces/ingest` | 200 requests/second per IP |
| `GET /v1/traces/*` | 100 requests/second per IP |
| `WS /ws/traces` | 10 concurrent connections per IP |

**Response when rate limit exceeded (429):**

```json
{
  "detail": "Rate limit exceeded. Retry after 1 second.",
  "retry_after": 1
}
```

---

## Dashboard Serving

The FlowLens server serves the interactive dashboard as a static HTML file from the `flowlens/server/` directory, accessible at `http://localhost:8585`.

### Static File Mounting

```python
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Mount static assets
app.mount("/static", StaticFiles(directory="flowlens/server/static"), name="static")

@app.get("/")
async def serve_dashboard():
    return FileResponse("flowlens/server/dashboard.html")
```

### Dashboard Architecture (Modularized)

The dashboard (`dashboard.html`) is a self-contained single-page application split into modular files:

1. **dashboard.html** (750 lines) — Main HTML structure with tab navigation and content containers
2. **dashboard.css** — All styling (theme, layout, components)
3. **dashboard.js** — Core logic (tab switching, API calls, event handling)
4. **charts.js** — Chart rendering (Chart.js integration)
5. **network.js** — SVG agent network visualization (particles, glow, interactions)
6. **websocket.js** — WebSocket client for real-time updates

**Workflow:**

1. Polls `GET /v1/traces` on page load to populate the trace list
2. Opens a WebSocket to `/ws/traces` for real-time updates
3. Renders span trees using a recursive HTML/CSS tree structure
4. Renders the causal DAG using SVG visualization
5. Displays cost breakdowns via `GET /v1/cost/breakdown`
6. Shows agent relationships via `GET /v1/agents/network`

No JavaScript bundler or build step is required — the dashboard is modular HTML/CSS/JS files using vanilla JS and native Web APIs.

---

## Performance Characteristics

### SDK Overhead

| Operation | Cost |
|---|---|
| Per-span context operations | ~0.1ms |
| Per-trace export (console/JSONL) | ~1ms |
| Per-trace export (HTTP) | ~5ms network round-trip |
| Concurrent traces | Linear with span count, no locks needed |

### Memory

| Object | Size |
|---|---|
| Per trace (100 spans) | ~50 KB (JSON serialization) |
| Context variable | ~100 bytes (constant, not per-span) |
| WebSocket connection | ~4 KB per active connection |

### Database

| Operation | Latency |
|---|---|
| Insert trace | ~10ms (SQLite WAL mode) |
| Query 1,000 traces (indexed) | ~50ms |
| Full-text search (FTS5) | ~100ms per 10,000 traces |
| Cost breakdown aggregate | ~30ms per 10,000 traces |

### Dashboard

| Metric | Value |
|---|---|
| Initial load time | ~1-2 seconds (SVG rendering 60-70% faster than WebGL) |
| Page rendering | <500ms (vanilla JS, no framework overhead) |
| Real-time WebSocket latency | <100ms (broadcast on ingest) |

---

## Design Decisions

### Why `contextvars` instead of thread-local storage?

Thread-local storage (`threading.local`) breaks with `asyncio` because many coroutines share the same OS thread. `contextvars.ContextVar` gives each coroutine (and each async task spawned from it) an isolated copy of the variable, enabling correct parent-child span linking without any manual plumbing.

### Why SQLite instead of PostgreSQL?

SQLite requires zero configuration — `pip install flowlens` and run. This is critical for a developer tool where the first-run experience matters. SQLite handles ~100K traces/day on a single machine comfortably. When you need more, swap `TraceStore` for a PostgreSQL-backed implementation; the interface contract does not change.

### Why modularized route modules?

Single 2003-line app.py became a maintenance burden: merge conflicts, hard to test individual endpoints, difficult for parallel development. Six focused modules (traces, cost, agents, stats, alerts, system) each with single responsibility: easier to navigate, test, and extend. Shared utils.py and validation.py reduce duplication.

### Why SVG over Three.js by default?

SVG animated paths render 60-70% faster than Three.js WebGL for agent network visualization. For users who want advanced 3D interactivity, Three.js is lazy-loaded as an upgrade path. Tradeoff: simpler, faster default experience; power-user escape hatch available.

### Why broadcast on ingest rather than polling?

Polling introduces 1–30 second latency depending on the interval. WebSocket broadcast delivers traces to the dashboard in under 100ms after ingest, making the dashboard feel genuinely live during debugging sessions. The implementation cost is a single `asyncio` broadcast call per ingest request.

### Why validation.py separate from storage.py?

Separation of concerns: storage.py handles persistence, validation.py handles integrity checking. Enables gradual validation adoption (strict/warning/informational levels) and makes validation logic testable independently.

---

## Deployment Architecture

### Single-Process (Development)

```
Agent Code → FlowLens SDK → Console/JSONL Exporter → stdout / disk
```

### Multi-Service (Production)

```
Service A → FlowLens SDK \
Service B → FlowLens SDK  ──► HTTP Exporter ──► FlowLens Server ──► SQLite
Service C → FlowLens SDK /                             │
                                               WebSocket Hub
                                                       │
                                              Dashboard / Alerts
```

### Docker (Recommended for Production)

```
             ┌─────────────────────────────────┐
             │  Docker Container: flowlens      │
             │                                 │
Agent ───────┤► POST /v1/traces/ingest         │
             │         │                       │
             │     SQLite DB (/data/flowlens.db)│
             │         │                       │
Browser ─────┤◄ GET / (Dashboard)              │
             │         │                       │
WS Client ───┤◄► WS /ws/traces                 │
             └─────────────────────────────────┘
```

### Scaling

- **Up to 100K traces/day**: Single container, default SQLite
- **100K–1M traces/day**: Multiple Uvicorn workers + Redis Pub/Sub for WebSocket broadcast
- **Beyond 1M traces/day**: Replace SQLite with PostgreSQL, consider ClickHouse for analytics queries
