# FlowLens Architecture

Complete technical guide to FlowLens internals, design decisions, and algorithms.

## System Overview

```
┌──────────────────────────────────────────────────────────────┐
│                    Your Agent Code                            │
│   @trace_agent  ·  @trace_llm  ·  @trace_tool                │
└────────────┬─────────────────────────────────┬────────────────┘
             │                                  │
    ┌────────▼────────┐              ┌─────────▼──────────┐
    │   SDK Layer     │              │ Analysis Layer     │
    │                 │              │                    │
    │ • Models        │              │ • DAG Builder      │
    │ • Decorators    │              │ • Pattern Detect   │
    │ • Context Mgmt  │              │ • Root Cause ID    │
    │ • Exporters     │              │ • Cost Engine      │
    │ (Console,       │              └────────┬───────────┘
    │  JSONL,         │                       │
    │  HTTP,          │              ┌────────▼───────┐
    │  Callback)      │              │  Server Layer   │
    └────────┬────────┘              │                 │
             │                       │ • FastAPI REST  │
             └──────────► export     │ • SQLite Store  │
                                     │ • Query Engine  │
                                     └─────────────────┘
```

### Three-Layer Architecture

1. **SDK Layer** (`flowlens/sdk/`): Instrumentation via decorators, context management, data collection
2. **Analysis Layer** (`flowlens/analysis/`): Post-trace processing, causal DAG construction, pattern detection
3. **Server Layer** (`flowlens/server/`): REST API, persistence, querying

---

## Data Flow: Decorator → Export

### 1. Decorator Wraps Function

```python
@trace_agent(name="my_bot")
async def my_agent():
    result = await task()
    return result
```

The decorator (`decorators.py`) becomes:

```
my_agent()
  → async_wrapper()
    → FlowLens.get_instance() [get singleton]
    → lens.start_trace() [create Trace, set current_trace]
    → TraceContext(trace).__enter__() [enter context]
    → lens.start_span(name="my_bot", kind=AGENT) [create Span, append to trace.spans]
    → SpanContext(span).__enter__() [enter context, set current_span]
    → [call original my_agent function]
    → span.finish(status=OK)
    → lens.end_trace(trace)
    → exporter.export(trace) [send to destination]
```

### 2. Context Management (contextvars)

**Why contextvars?**
- Safe for async/await: Each coroutine has its own context
- Parent-child linking: Child spans know their parent automatically
- Zero-intrusion: User code doesn't manage context

**How it works:**

```python
# In context.py
_current_trace = contextvars.ContextVar('flowlens_current_trace', default=None)
_current_span = contextvars.ContextVar('flowlens_current_span', default=None)

class TraceContext:
    def __enter__(self):
        # Stack the trace on enter
        self._token = set_current_trace(self.trace)

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Pop the trace on exit (restore previous)
        _current_trace.reset(self._token)

class SpanContext:
    def __enter__(self):
        # Auto-detect parent from context
        parent = get_current_span()
        if parent:
            self.span.parent_span_id = parent.span_id

        # Stack this span
        self._token = set_current_span(self.span)
```

**Example: Nested Trace Execution**

```
Main async context:
  TraceContext(trace1)
    │
    ├─ SpanContext(agent_span)
    │   └─ current_span = agent_span
    │
    └─ SpanContext(llm_span)
        └─ current_span = llm_span
           parent_span_id = agent_span.span_id [auto-detected]
```

Each async task (task, coroutine) inherits contextvars from its parent task, enabling automatic parent-child linking across async boundaries.

### 3. Span Structure

```python
@dataclass
class Span:
    # Identity
    span_id: str              # UUID[:16]
    trace_id: str             # Set by TraceContext
    parent_span_id: Optional  # Set by SpanContext

    # Metadata
    name: str                 # e.g., "web_search"
    kind: SpanKind            # AGENT, LLM, TOOL, etc.
    status: SpanStatus        # OK, ERROR, UNSET

    # Timing
    start_time: float         # Unix timestamp
    end_time: float           # Set on finish()

    # Data
    attributes: dict          # Custom metadata
    events: list[SpanEvent]   # Checkpoints
    token_usage: TokenUsage   # For LLM spans
    error_message: Optional   # If status=ERROR
```

**Lifetime:**

1. Created: `lens.start_span(...)` at function entry
2. Modified: `span.add_event(...)`, `span.set_token_usage(...)`
3. Finished: `span.finish(status, error)` at function exit
4. Exported: Span appended to trace, then exported via exporter

### 4. Exporter Interface

```python
class TraceExporter:
    def export(self, trace: Trace) -> None: ...
    def shutdown(self) -> None: ...
```

**Built-in Exporters:**

| Exporter | Purpose | Example |
|----------|---------|---------|
| `ConsoleExporter` | Dev: colored output to stdout | `export_to="console"` |
| `JSONLExporter` | File: one JSON per line | `export_to="jsonl"` |
| `HTTPExporter` | Remote: POST to server | `export_to="http"` |
| `CallbackExporter` | Testing: user-provided function | For unit tests |

**Console Exporter Output:**

```
[FlowLens] Trace a1b2c3d4 | 8 spans | 1847ms | 2967 tokens | $0.0190 | ERROR
  🤖 agent_span (1847ms) [AGENT]
  ├─ 🧠 llm_call (312ms) [LLM] [856 tok]
  └─ 🔧 web_search (2003ms) [TOOL] ❌ timeout
```

---

## Causal DAG Algorithm

The core analysis engine identifies root causes and error propagation patterns.

### Input: Trace with Error Spans

```
Trace:
  Span S1 (agent, OK)
    ├─ Span S2 (llm, OK)
    ├─ Span S3 (tool, ERROR) ← search timeout
    ├─ Span S4 (tool, ERROR) ← fetch failed (cascaded from S3)
    └─ Span S5 (tool, OK)   ← retry succeeded
```

### Algorithm Steps

#### Step 1: Build Index Structures

```python
# Parent-child relationships
parent_of = {
    "S2": "S1",  # S2's parent is S1
    "S3": "S1",
    "S4": "S1",
    "S5": "S1",
}

children_of = {
    "S1": ["S2", "S3", "S4", "S5"],
}

# Execution order (by start_time)
sibling_groups = {
    "S1": ["S2", "S3", "S4", "S5"],  # All under S1, ordered by time
}

# Error set
error_span_ids = {"S3", "S4"}  # Only ERROR status spans
```

#### Step 2: Classify Errors (ROOT_CAUSE vs CASCADED)

For each error span, check:

1. **Has error ancestor?** Walk up parent chain, looking for ERROR status
2. **Has error predecessor?** In sibling order, is there an earlier ERROR?

Classification:

- **ROOT_CAUSE**: No error ancestor AND no error predecessor
- **CASCADED**: Has error ancestor OR error predecessor
- **INDEPENDENT**: Error but no causal relationship to other errors

**Example:**

```
S3 (ERROR): parent=S1 (OK), no earlier ERROR sibling
  → ROOT_CAUSE ✓

S4 (ERROR): parent=S1 (OK), earlier ERROR sibling=S3
  → CASCADED (predecessor=S3) ✓
```

#### Step 3: Build Causal Edges

Two types of edges:

1. **Parent → Child**: Error parent to error child
2. **Sibling → Sibling**: Error to next error in execution order

**Code:**

```python
for span_id in error_span_ids:
    # Parent-child edge
    parent = parent_of.get(span_id)
    if parent and parent in error_span_ids:
        edges.append(CausalEdge(parent, span_id, "caused_by"))

    # Sibling edge
    siblings = sibling_groups[parent_of.get(span_id)]
    idx = siblings.index(span_id)
    if idx > 0 and siblings[idx-1] in error_span_ids:
        edges.append(CausalEdge(siblings[idx-1], span_id, "preceded_by"))
```

#### Step 4: Output CausalDAG

```python
CausalDAG(
    trace_id="t1",
    nodes=[
        CausalNode(span_id="S3", error_role=ROOT_CAUSE, error_message="timeout"),
        CausalNode(span_id="S4", error_role=CASCADED, error_message="invalid input"),
    ],
    edges=[
        CausalEdge(source="S3", target="S4", relation="preceded_by"),
    ],
    root_causes=["S3"],
    cascade_depth=1,
)
```

### Visual Output

```
Trace t1:
  Nodes:
    S1 [AGENT, OK]
    S2 [LLM, OK]
    S3 [TOOL, ERROR] ← ROOT_CAUSE
    S4 [TOOL, ERROR] ← CASCADED
    S5 [TOOL, OK]

  Edges:
    S3 ──preceded_by──> S4

  Root Causes: [S3]
  Cascade Depth: 1
```

---

## Pattern Detection Logic

Five detectors run over trace + DAG to identify anti-patterns.

### 1. Retry Storm

**Definition:** Same tool called ≥5 times, likely due to flaky API or bad retry logic.

**Detection:**

```python
tool_spans = [s for s in trace.spans if s.kind == TOOL]
name_counts = Counter(s.name for s in tool_spans)

for name, count in name_counts.items():
    if count >= 5:
        error_rate = sum(1 for s in tool_spans if s.name == name and s.status == ERROR) / count
        severity = "critical" if error_rate > 0.8 else "warning"
        → DetectedPattern(RETRY_STORM, severity, description=f"Tool '{name}' called {count} times")
```

### 2. Infinite Loop

**Definition:** Repeating sequence of tool calls (e.g., A→B→A→B→A→B, 3+ times).

**Detection:**

```python
tool_sequence = [s.name for s in sorted(trace.spans) if s.kind == TOOL]
# e.g., ["search", "fetch", "search", "fetch", "search", "fetch"]

for cycle_len in (2, 3):  # Try 2-step and 3-step cycles
    for start in range(len(tool_sequence)):
        cycle = tool_sequence[start:start+cycle_len]
        repeat_count = 0

        # Count how many times cycle repeats starting at 'start'
        pos = start
        while pos + cycle_len <= len(tool_sequence):
            if tool_sequence[pos:pos+cycle_len] == cycle:
                repeat_count += 1
                pos += cycle_len
            else:
                break

        if repeat_count >= 3:
            → DetectedPattern(INFINITE_LOOP, "critical", description=f"Cycle {cycle} repeated {repeat_count} times")
```

### 3. Context Overflow

**Definition:** LLM token usage approaching or exceeding model's context window.

**Detection:**

```python
for span in trace.spans:
    if span.kind == LLM and span.token_usage:
        model = span.attributes.get("gen_ai.request.model", "")
        limit = _MODEL_CONTEXT_LIMITS.get(model, DEFAULT_LIMIT)

        usage_ratio = span.token_usage.total_tokens / limit

        if usage_ratio >= 0.9:
            severity = "critical" if usage_ratio >= 1.0 else "warning"
            → DetectedPattern(CONTEXT_OVERFLOW, severity,
                description=f"Token usage {usage_ratio:.0%} of context limit")
```

**Built-in Context Limits:**

| Model | Limit |
|-------|-------|
| Claude Opus/Sonnet/Haiku | 200,000 |
| GPT-4o | 128,000 |
| Gemini 2.5 Pro | 1,000,000 |
| DeepSeek V3/R1 | 64,000 |

### 4. Timeout Cascade

**Definition:** Timeout causing downstream errors (found via DAG traversal).

**Detection:**

```python
timeout_spans = [s for s in trace.spans
                 if s.status == ERROR and "timeout" in s.error_message.lower()]

for ts in timeout_spans:
    cascaded = _find_downstream_errors(ts.span_id, dag)

    if cascaded:
        → DetectedPattern(TIMEOUT_CASCADE, "critical",
            description=f"'{ts.name}' timeout caused {len(cascaded)} downstream failures",
            involved_spans=[ts.span_id] + cascaded)
```

**Helper: Find Downstream Errors**

```python
def _find_downstream_errors(span_id: str, dag: CausalDAG) -> list[str]:
    """BFS to find all error children in DAG"""
    children = {}
    for edge in dag.edges:
        children.setdefault(edge.source_id, []).append(edge.target_id)

    result = []
    queue = children.get(span_id, [])
    visited = set()

    while queue:
        nid = queue.pop(0)
        if nid in visited:
            continue
        visited.add(nid)
        result.append(nid)
        queue.extend(children.get(nid, []))

    return result
```

### 5. Empty Response

**Definition:** LLM returns 0 output tokens (suspicious behavior).

**Detection:**

```python
for span in trace.spans:
    if (span.kind == LLM
        and span.token_usage
        and span.token_usage.output_tokens == 0
        and span.status == OK):
        → DetectedPattern(EMPTY_RESPONSE, "warning",
            description=f"LLM '{span.name}' returned 0 output tokens")
```

---

## Cost Estimation

Token-based cost calculation with 16+ model pricing tables.

### Pricing Table (2026 Rates)

```python
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    # (input_per_1M, output_per_1M)
    "claude-opus-4-20250514": (15.0, 75.0),
    "claude-sonnet-4-20250514": (3.0, 15.0),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
    "gemini-2.5-pro": (1.25, 10.0),
    "deepseek-v3": (0.27, 1.1),
    # ... 10+ more models
}

_DEFAULT_PRICING = (3.0, 15.0)  # Fallback for unknown models
```

### Fuzzy Model Matching

```python
def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> dict:
    pricing = _DEFAULT_PRICING
    model_lower = model.lower()

    # Try exact substring match
    for key in _MODEL_PRICING:
        if key in model_lower or model_lower in key:
            pricing = _MODEL_PRICING[key]
            break

    input_cost = (input_tokens / 1_000_000) * pricing[0]
    output_cost = (output_tokens / 1_000_000) * pricing[1]

    return {
        "input_cost_usd": round(input_cost, 6),
        "output_cost_usd": round(output_cost, 6),
        "total_cost_usd": round(input_cost + output_cost, 6),
    }
```

**Examples:**

```
_estimate_cost("claude-sonnet-4-20250514", 1_000_000, 1_000_000)
→ {"input_cost_usd": 3.0, "output_cost_usd": 15.0, "total_cost_usd": 18.0}

_estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000)
→ {"input_cost_usd": 0.15, "output_cost_usd": 0.6, "total_cost_usd": 0.75}

_estimate_cost("unknown-model-xyz", 1_000_000, 1_000_000)
→ {"input_cost_usd": 3.0, "output_cost_usd": 15.0, "total_cost_usd": 18.0}  # Default
```

---

## Server Storage & Querying

### Database Schema (SQLite)

```sql
-- Main traces table
CREATE TABLE traces (
    trace_id TEXT PRIMARY KEY,
    service_name TEXT,
    start_time REAL,
    end_time REAL,
    duration_ms REAL,
    total_tokens INTEGER,
    total_cost_usd REAL,
    has_errors BOOLEAN,
    error_count INTEGER,
    span_count INTEGER,
    metadata TEXT,  -- JSON
    spans_json TEXT, -- JSON array of spans
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for fast queries
CREATE INDEX idx_service ON traces(service_name);
CREATE INDEX idx_has_errors ON traces(has_errors);
CREATE INDEX idx_created ON traces(created_at DESC);
```

### Query Operations

```python
class TraceStore:
    def save_trace(self, trace_data: dict) -> None:
        """Insert or upsert trace"""

    def get_trace(self, trace_id: str) -> Optional[dict]:
        """Fetch single trace with all spans"""

    def list_traces(self, limit=50, offset=0, service_name=None, has_errors=None) -> list[dict]:
        """Paginated query with filtering"""

    def get_cost_breakdown(self, group_by: str = "service_name") -> list[dict]:
        """Aggregate cost by dimension"""

    def get_stats(self) -> dict:
        """Aggregate statistics"""
```

### Example: Cost Breakdown Query

```sql
SELECT
    service_name as dimension,
    SUM(total_cost_usd) as total_cost_usd,
    SUM(total_tokens) as total_tokens,
    COUNT(*) as span_count
FROM traces
GROUP BY service_name
ORDER BY total_cost_usd DESC;
```

**Result:**

```
[
  {"dimension": "research-bot", "total_cost_usd": 2.50, "total_tokens": 100000, "span_count": 200},
  {"dimension": "qa-bot", "total_cost_usd": 1.20, "total_tokens": 50000, "span_count": 100},
]
```

---

## Performance Characteristics

### Tracing Overhead

- **Per-span**: ~0.1ms (context operations + list append)
- **Per-trace**: ~1ms (exporter serialization)
- **Concurrent**: Linear with span count, no locks (async-safe)

### Memory

- **Trace**: ~50 KB per 100 spans (JSON serialization)
- **Context stack**: ~100 bytes per ContextVar (constant, not per-span)
- **DAG analysis**: O(n) where n = span count

### Database

- **Insert**: ~10ms per trace (SQLite)
- **Query**: ~50ms per 1000 traces (indexed)
- **Disk**: ~100 KB per 10 traces

---

## Design Decisions

### Why contextvars?

✅ Async-safe (each coroutine has isolated context)
✅ Zero-intrusion (automatic parent-child linking)
✅ Standard library (no external deps)

Alternative: Thread-local storage → broken with asyncio

### Why SQLite?

✅ Zero-config (no database server)
✅ ACID (safe concurrent reads)
✅ Good for <1M traces

Limitation: Not suitable for >10M traces (use PostgreSQL)

### Why Pydantic?

✅ Runtime validation (reject malformed traces)
✅ Auto-generated OpenAPI docs
✅ Performance (Rust-compiled validators in v2)

### Why Console + JSONL exporters?

✅ Console: instant feedback during development
✅ JSONL: import/export, human-readable, append-only

---

## Integration Points

### With OpenTelemetry

FlowLens uses OTEL GenAI semantic conventions:

```python
# Automatic OTEL attributes
span.attributes = {
    "gen_ai.system": "anthropic",  # LLM provider
    "gen_ai.request.model": "claude-sonnet-4",
    "gen_ai.usage.input_tokens": 1000,
    "gen_ai.usage.output_tokens": 500,
    "gen_ai.response.model": "claude-sonnet-4",
}
```

Can export to OTEL collectors (Jaeger, Grafana Tempo, etc.) via custom exporter.

### With LangChain / CrewAI / AutoGen

No direct integration yet. Usage pattern:

```python
from flowlens import FlowLens, trace_agent, trace_tool

lens = FlowLens()

@trace_agent
async def run_langchain_agent():
    # LangChain code here
    return agent.run(...)
```

---

## Deployment Architecture

### Single-Process (Development)

```
Client Code → FlowLens SDK → Console/JSONL Exporter → stdout / disk
```

### Multi-Process (Production)

```
Client 1 → FlowLens SDK \
Client 2 → FlowLens SDK  → HTTP Exporter → Server → SQLite → Dashboard
Client 3 → FlowLens SDK /
```

### Scaling

- **Traces/day**: 100K → Single machine (10ms insert)
- **Traces/day**: 1M → Consider PostgreSQL + read replicas
- **Dashboard**: Separate frontend (React/Vue) queries `/v1/traces` API

