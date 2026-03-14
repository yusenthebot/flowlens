#!/usr/bin/env python3
"""
FlowLens Server Demo — Tutorial Walkthrough
============================================
This script starts the FlowLens FastAPI server in a background thread,
ingests sample traces via the HTTP API, queries them, and demonstrates
real-time WebSocket streaming — all in a single self-contained script.

Run with:
    python examples/server_demo.py

Requirements (server mode only):
    pip install fastapi uvicorn

The script will automatically skip the server sections if fastapi/uvicorn
are not installed and fall back to a pure-SDK demo instead.

curl equivalents are shown as comments so you can replay every step
from a separate terminal window.

Server endpoints demonstrated:
  POST   /v1/traces/ingest        — ingest a trace
  GET    /v1/traces               — list all traces
  GET    /v1/traces/{id}          — trace detail
  GET    /v1/traces/{id}/dag      — causal DAG
  GET    /v1/stats                — global stats
  GET    /health                  — health check
  WS     /ws/traces               — real-time trace stream
"""

import asyncio
import json
import os
import socket
import sys
import threading
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flowlens import FlowLens

# ───────────────────────────────────────────────────────────────────────────
# ANSI helpers
# ───────────────────────────────────────────────────────────────────────────

RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
GREEN   = "\033[92m"
YELLOW  = "\033[93m"
BLUE    = "\033[94m"
CYAN    = "\033[96m"
RED     = "\033[91m"
WHITE   = "\033[97m"
MAGENTA = "\033[95m"


def c(text: str, *codes: str) -> str:
    return "".join(codes) + str(text) + RESET


def banner(title: str) -> None:
    width = 72
    pad = max(0, (width - len(title) - 4)) // 2
    print()
    print(c("╔" + "═" * (width - 2) + "╗", CYAN, BOLD))
    print(c(f"║{' ' * pad}  {title}  {' ' * pad}║", CYAN, BOLD))
    print(c("╚" + "═" * (width - 2) + "╝", CYAN, BOLD))
    print()


def section(title: str) -> None:
    print()
    print(c(f"  ── {title} " + "─" * max(0, 58 - len(title)), CYAN))
    print()


def step(num: int, title: str) -> None:
    print(c(f"\n  [{num}] {title}", WHITE, BOLD))
    print(c("  " + "─" * 60, DIM))
    print()


def curl(method: str, path: str, host: str = "localhost:8585", body: str = "") -> None:
    """Print a curl equivalent comment for educational purposes."""
    if body:
        cmd = f"curl -s -X {method} http://{host}{path} \\\n       -H 'Content-Type: application/json' \\\n       -d '{body[:100]}...'"
    else:
        cmd = f"curl -s http://{host}{path}"
    print(c("  # curl equivalent:", DIM))
    print(c(f"  # {cmd}", DIM))
    print()


def ok(text: str) -> None:
    print(c(f"  ✓ {text}", GREEN))


def info(text: str) -> None:
    print(c(f"  → {text}", BLUE))


def warn(text: str) -> None:
    print(c(f"  ! {text}", YELLOW))


def _pretty_json(data: dict, indent: int = 4, max_lines: int = 20) -> None:
    lines = json.dumps(data, indent=indent).split("\n")
    for line in lines[:max_lines]:
        # Colour keys cyan, string values green, numbers yellow
        if '":' in line:
            key_end = line.index('":') + 2
            key_part = c(line[:key_end], CYAN)
            rest = line[key_end:]
            if '"' in rest:
                print(f"    {key_part}{c(rest, GREEN)}")
            else:
                print(f"    {key_part}{c(rest, YELLOW)}")
        else:
            print(f"    {c(line, DIM)}")
    if len(lines) > max_lines:
        print(f"    {c('... (truncated)', DIM)}")


# ───────────────────────────────────────────────────────────────────────────
# Find a free port
# ───────────────────────────────────────────────────────────────────────────

def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


# ───────────────────────────────────────────────────────────────────────────
# Sample trace payloads
# ───────────────────────────────────────────────────────────────────────────

def _make_sample_payload(
    scenario: str = "healthy",
    has_error: bool = False,
    token_count: int = 1500,
) -> dict:
    """Generate a realistic trace ingest payload."""
    now = time.time()
    trace_id = uuid.uuid4().hex
    agent_span_id = uuid.uuid4().hex[:16]
    llm_span_id = uuid.uuid4().hex[:16]
    tool_span_id = uuid.uuid4().hex[:16]

    spans = [
        {
            "span_id": agent_span_id,
            "trace_id": trace_id,
            "parent_span_id": None,
            "name": "research_agent",
            "kind": "agent",
            "status": "error" if has_error else "ok",
            "start_time": now,
            "end_time": now + 0.35,
            "duration_ms": 350,
            "attributes": {"scenario": scenario},
            "events": [],
            "error": {"message": "web_search timed out after 30s", "type": "TimeoutError"} if has_error else None,
        },
        {
            "span_id": llm_span_id,
            "trace_id": trace_id,
            "parent_span_id": agent_span_id,
            "name": "research_planner",
            "kind": "llm",
            "status": "ok",
            "start_time": now + 0.01,
            "end_time": now + 0.09,
            "duration_ms": 80,
            "attributes": {
                "gen_ai.request.model": "claude-sonnet-4-20250514",
                "gen_ai.usage.input_tokens": token_count // 2,
                "gen_ai.usage.output_tokens": token_count // 4,
            },
            "events": [],
            "token_usage": {
                "input_tokens": token_count // 2,
                "output_tokens": token_count // 4,
                "total_tokens": token_count // 2 + token_count // 4,
                "input_cost_usd": (token_count // 2) / 1_000_000 * 3.0,
                "output_cost_usd": (token_count // 4) / 1_000_000 * 15.0,
                "total_cost_usd": (token_count // 2) / 1_000_000 * 3.0 + (token_count // 4) / 1_000_000 * 15.0,
            },
        },
        {
            "span_id": tool_span_id,
            "trace_id": trace_id,
            "parent_span_id": agent_span_id,
            "name": "web_search",
            "kind": "tool",
            "status": "error" if has_error else "ok",
            "start_time": now + 0.09,
            "end_time": now + 0.30,
            "duration_ms": 30_000 if has_error else 210,
            "attributes": {"tool.input.query": "agentic AI 2026"},
            "events": [],
            "error": {"message": "web_search timed out after 30s", "type": "TimeoutError"} if has_error else None,
        },
    ]

    total_tokens = token_count // 2 + token_count // 4
    total_cost = total_tokens / 1_000_000 * 9.0  # rough midpoint

    return {
        "trace_id": trace_id,
        "service_name": "server-demo",
        "start_time": now,
        "end_time": now + 0.35,
        "duration_ms": 350,
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 6),
        "has_errors": has_error,
        "error_count": 2 if has_error else 0,
        "span_count": len(spans),
        "metadata": {"scenario": scenario},
        "spans": spans,
    }


# ───────────────────────────────────────────────────────────────────────────
# Server management (optional, requires fastapi + uvicorn)
# ───────────────────────────────────────────────────────────────────────────

_server_thread: threading.Thread | None = None
_server_port: int = 0


def _start_server(port: int) -> bool:
    """Start the FlowLens server in a background thread. Returns True if started."""
    global _server_thread, _server_port

    try:
        import uvicorn

        from flowlens.server.app import create_app
    except ImportError as exc:
        warn(f"Cannot start server: {exc}")
        warn("Install with: pip install fastapi uvicorn")
        return False

    app = create_app(db_path=":memory:")  # in-memory SQLite for demo
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    _server_port = port

    def _run() -> None:
        asyncio.run(server.serve())

    _server_thread = threading.Thread(target=_run, daemon=True)
    _server_thread.start()

    # Wait for the server to be ready
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            import urllib.request
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5)
            return True
        except Exception:
            time.sleep(0.1)

    warn("Server did not become ready in time")
    return False


# ───────────────────────────────────────────────────────────────────────────
# HTTP helper
# ───────────────────────────────────────────────────────────────────────────

def _http_get(url: str) -> dict:
    import urllib.request
    with urllib.request.urlopen(url, timeout=5) as resp:
        return json.loads(resp.read())


def _http_post(url: str, data: dict) -> dict:
    import urllib.request
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


# ───────────────────────────────────────────────────────────────────────────
# Demo sections
# ───────────────────────────────────────────────────────────────────────────

def demo_health(base: str) -> None:
    step(1, "Health Check")
    curl("GET", "/health", host=base.replace("http://", ""))
    result = _http_get(f"{base}/health")
    ok(f"Server is alive: {result}")


def demo_ingest(base: str) -> list[str]:
    step(2, "Ingesting Sample Traces")
    info("Sending 5 traces: 3 healthy, 2 with timeout cascade errors")
    print()

    trace_ids: list[str] = []
    scenarios = [
        ("healthy_1",  False, 1200),
        ("healthy_2",  False, 1600),
        ("healthy_3",  False, 1400),
        ("timeout_1",  True,  950),
        ("timeout_2",  True,  1100),
    ]

    for scenario, has_error, tokens in scenarios:
        payload = _make_sample_payload(scenario, has_error, tokens)
        trace_ids.append(payload["trace_id"])

        # Show the curl equivalent on first trace only
        if scenario == "healthy_1":
            curl("POST", "/v1/traces/ingest", host=base.replace("http://", ""),
                 body=json.dumps({k: v for k, v in payload.items() if k != "spans"})[:120])

        result = _http_post(f"{base}/v1/traces/ingest", payload)
        color = YELLOW if has_error else GREEN
        ok(f"{scenario:<20}  {c('ingested', color)}  trace_id={payload['trace_id'][:16]}...")
        time.sleep(0.05)

    return trace_ids


def demo_list_traces(base: str) -> None:
    step(3, "Listing All Traces")
    curl("GET", "/v1/traces?limit=10", host=base.replace("http://", ""))

    result = _http_get(f"{base}/v1/traces?limit=10")
    total = result.get("total", 0)
    traces = result.get("traces", [])

    ok(f"Found {total} trace(s) in store")
    print()
    print(c("  Trace listing (newest first):", DIM))
    for t in traces:
        status_color = RED if t.get("has_errors") else GREEN
        status = c("ERROR", RED) if t.get("has_errors") else c("OK", GREEN)
        print(
            f"    {c(t['trace_id'][:16] + '...', DIM)}  "
            f"{status}  "
            f"{c(str(t.get('duration_ms', 0))[:6] + 'ms', CYAN)}  "
            f"{c(str(t.get('total_tokens', 0)) + ' tok', YELLOW)}"
        )


def demo_trace_detail(base: str, trace_id: str) -> None:
    step(4, "Fetching Trace Detail")
    curl("GET", f"/v1/traces/{trace_id}", host=base.replace("http://", ""))

    result = _http_get(f"{base}/v1/traces/{trace_id}")
    ok(f"Trace detail for {trace_id[:16]}...")
    print()
    _pretty_json({
        "trace_id": result.get("trace_id", "")[:24] + "...",
        "service_name": result.get("service_name"),
        "has_errors": result.get("has_errors"),
        "span_count": result.get("span_count"),
        "total_tokens": result.get("total_tokens"),
        "total_cost_usd": result.get("total_cost_usd"),
        "duration_ms": result.get("duration_ms"),
    })


def demo_dag(base: str, trace_id: str) -> None:
    step(5, "Fetching Causal DAG for an Error Trace")
    curl("GET", f"/v1/traces/{trace_id}/dag", host=base.replace("http://", ""))

    try:
        result = _http_get(f"{base}/v1/traces/{trace_id}/dag")
        ok("Causal DAG computed")
        print()

        root_causes = result.get("root_causes", [])
        nodes = result.get("nodes", [])
        edges = result.get("edges", [])

        print(f"  {c('Nodes:', DIM)}   {len(nodes)}")
        print(f"  {c('Edges:', DIM)}   {len(edges)}")
        print(f"  {c('Root causes:', DIM)} {len(root_causes)}")
        print()

        node_map = {n["span_id"]: n for n in nodes}
        for rc_id in root_causes:
            rc = node_map.get(rc_id, {})
            print(f"  {c('● ROOT CAUSE:', RED, BOLD)}  {c(rc.get('name', rc_id), RED)}")
            if rc.get("error_message"):
                print(f"    {c(rc['error_message'][:80], DIM)}")

        for edge in edges:
            src = node_map.get(edge.get("source_id", ""), {}).get("name", "?")
            tgt = node_map.get(edge.get("target_id", ""), {}).get("name", "?")
            rel = edge.get("relation", "")
            print(f"  {c(src, YELLOW)}  {c('──[' + rel + ']──▶', DIM)}  {c(tgt, YELLOW)}")

    except Exception as exc:
        warn(f"DAG endpoint error: {exc}")


def demo_stats(base: str) -> None:
    step(6, "Global Statistics")
    curl("GET", "/v1/stats", host=base.replace("http://", ""))

    result = _http_get(f"{base}/v1/stats")
    ok("Statistics retrieved")
    print()
    fields = [
        ("total_traces",   CYAN),
        ("total_spans",    CYAN),
        ("total_tokens",   YELLOW),
        ("total_cost",     YELLOW),
        ("error_traces",   RED),
        ("avg_duration_ms", CYAN),
    ]
    for field, color in fields:
        val = result.get(field, "N/A")
        if isinstance(val, float):
            val = f"{val:.4f}"
        print(f"  {c(field + ':', DIM):<30}  {c(str(val), color)}")


async def demo_websocket(base: str) -> None:
    step(7, "Real-Time WebSocket Stream")
    ws_url = base.replace("http://", "ws://") + "/ws/traces"
    info(f"Connecting to: {ws_url}")
    print()
    print(c("  # Python equivalent:", DIM))
    print(c("  # import websockets", DIM))
    print(c(f"  # async with websockets.connect('{ws_url}') as ws:", DIM))
    print(c("  #     async for msg in ws:", DIM))
    print(c("  #         trace = json.loads(msg)", DIM))
    print(c("  #         print(trace['trace_id'])", DIM))
    print()

    try:
        import websockets  # type: ignore

        received: list[dict] = []
        ingest_done = asyncio.Event()

        async def listener() -> None:
            try:
                async with websockets.connect(ws_url, ping_timeout=3) as ws:
                    ok("WebSocket connected — waiting for live traces...")
                    ingest_done.clear()
                    while not ingest_done.is_set() or received == []:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                            msg = json.loads(raw)
                            received.append(msg)
                            tid = msg.get("trace_id", "")[:16]
                            has_err = msg.get("has_errors", False)
                            status = c("ERROR", RED) if has_err else c("OK", GREEN)
                            print(f"  {c('[WS]', MAGENTA, BOLD)}  {c(tid + '...', DIM)}  {status}")
                        except asyncio.TimeoutError:
                            break
            except Exception as exc:
                warn(f"WebSocket error: {exc}")

        async def ingestor() -> None:
            await asyncio.sleep(0.3)  # let listener connect first
            payload = _make_sample_payload("ws_demo", has_error=False, token_count=800)
            _http_post(f"{base}/v1/traces/ingest", payload)
            payload2 = _make_sample_payload("ws_demo_error", has_error=True, token_count=600)
            _http_post(f"{base}/v1/traces/ingest", payload2)
            await asyncio.sleep(0.5)
            ingest_done.set()

        await asyncio.gather(listener(), ingestor())

        if received:
            ok(f"Received {len(received)} live trace event(s) via WebSocket")
        else:
            warn("No WebSocket events received (may need 'pip install websockets')")

    except ImportError:
        warn("websockets library not installed — skipping live WebSocket demo")
        warn("Install with: pip install websockets")
        info("The server's /ws/traces endpoint is still fully functional")


def demo_error_list(base: str) -> None:
    step(8, "Error-Only Trace Listing")
    curl("GET", "/v1/traces/errors?limit=5", host=base.replace("http://", ""))

    result = _http_get(f"{base}/v1/traces/errors?limit=5")
    traces = result.get("traces", [])
    ok(f"Found {len(traces)} error trace(s)")
    for t in traces:
        print(
            f"    {c(t['trace_id'][:16] + '...', DIM)}  "
            f"{c('ERROR', RED)}  "
            f"{c(str(t.get('error_count', 0)) + ' error span(s)', RED)}"
        )


def print_curl_cheatsheet(base: str) -> None:
    section("curl Cheatsheet — replay from any terminal")
    host = base.replace("http://", "")
    commands = [
        ("Health check",       f"curl {base}/health"),
        ("List traces",        f"curl '{base}/v1/traces?limit=20&offset=0'"),
        ("List error traces",  f"curl '{base}/v1/traces/errors?limit=10'"),
        ("Trace detail",       f"curl '{base}/v1/traces/<trace_id>'"),
        ("Causal DAG",         f"curl '{base}/v1/traces/<trace_id>/dag'"),
        ("Statistics",         f"curl '{base}/v1/stats'"),
        ("Pattern summary",    f"curl '{base}/v1/patterns/summary'"),
        ("Cost breakdown",     f"curl '{base}/v1/cost/breakdown'"),
        ("Cost trends",        f"curl '{base}/v1/cost/trends?period=daily'"),
        ("Ingest trace",       f"curl -X POST '{base}/v1/traces/ingest' -H 'Content-Type: application/json' -d @trace.json"),
        ("WebSocket stream",   f"# Connect: ws://{host}/ws/traces"),
        ("API docs (Swagger)", f"{base}/docs"),
        ("OpenAPI JSON",       f"{base}/openapi.json"),
    ]
    for label, cmd in commands:
        print(f"  {c(label + ':', DIM):<28}  {c(cmd, CYAN)}")
    print()


# ───────────────────────────────────────────────────────────────────────────
# Pure-SDK fallback (no server required)
# ───────────────────────────────────────────────────────────────────────────

async def demo_sdk_only() -> None:
    """Run a short SDK demo when the server cannot be started."""
    from flowlens import trace_agent, trace_llm, trace_tool
    from flowlens.sdk.models import Trace

    section("SDK-Only Demo (server not available)")
    info("Demonstrating the FlowLens SDK without the server")
    print()

    traces: list[Trace] = []

    def capture(t: Trace) -> None:
        traces.append(t)

    lens = FlowLens(
        service_name="server-demo-sdk",
        export_to="console",
        verbose=False,
        on_trace_complete=capture,
    )

    class _FakeResp:
        def __init__(self):
            self.content = [type("B", (), {"text": "Hello from mocked LLM"})()]
            self.usage = type("U", (), {"input_tokens": 500, "output_tokens": 120})()
            self.stop_reason = "end_turn"

    @trace_agent(name="sdk_demo_agent")
    async def run_agent(task: str) -> dict:
        @trace_llm(model="claude-haiku-4-20250514", name="planner")
        async def plan(t: str) -> _FakeResp:
            await asyncio.sleep(0.05)
            return _FakeResp()

        @trace_tool(name="lookup")
        async def lookup(q: str) -> dict:
            await asyncio.sleep(0.03)
            return {"result": f"Found: {q}"}

        plan_result = await plan(task)
        lookup_result = await lookup(task)
        return {"plan": plan_result.content[0].text, "lookup": lookup_result}

    result = await run_agent("latest AI research 2026")
    lens.shutdown()

    ok(f"Agent completed: {result}")
    if traces:
        t = traces[0]
        print()
        print(f"  Spans     : {len(t.spans)}")
        print(f"  Tokens    : {t.total_tokens}")
        print(f"  Cost      : ${t.total_cost_usd:.5f}")
        print(f"  Errors    : {t.error_count}")
    print()
    info("To use the full server demo, install: pip install fastapi uvicorn")


# ───────────────────────────────────────────────────────────────────────────
# Main
# ───────────────────────────────────────────────────────────────────────────

async def main() -> None:
    banner("FlowLens Server Demo — Tutorial Walkthrough")

    section("Starting FlowLens Server")
    port = _find_free_port()
    base = f"http://127.0.0.1:{port}"
    info(f"Attempting to start server on {c(base, CYAN)}...")

    started = _start_server(port)

    if not started:
        warn("Server could not be started — falling back to SDK-only demo")
        await demo_sdk_only()
        return

    ok(f"Server running at {c(base, CYAN, BOLD)}")
    info("In-memory SQLite database — data exists only for this session")
    print()
    info(f"Swagger UI: {c(base + '/docs', CYAN)}")
    info(f"OpenAPI JSON: {c(base + '/openapi.json', CYAN)}")

    # ── Walkthrough ────────────────────────────────────────────────────────
    demo_health(base)
    trace_ids = demo_ingest(base)
    demo_list_traces(base)

    # Show detail + DAG for first error trace (index 3)
    if len(trace_ids) >= 4:
        error_trace_id = trace_ids[3]  # timeout_1
        demo_trace_detail(base, error_trace_id)
        demo_dag(base, error_trace_id)

    demo_error_list(base)
    demo_stats(base)
    await demo_websocket(base)

    # ── curl cheatsheet ────────────────────────────────────────────────────
    print_curl_cheatsheet(base)

    section("SDK + HTTP Exporter Integration")
    print(c("  To send traces directly from your agent to the server:", WHITE, BOLD))
    print()
    code = [
        "from flowlens import FlowLens, trace_agent",
        "",
        "# Point the SDK at your running FlowLens server",
        "lens = FlowLens(",
        "    service_name='my-agent',",
        "    export_to='http',",
        f"    endpoint='{base}/v1/traces/ingest',",
        ")",
        "",
        "@trace_agent(name='my_bot')",
        "async def run(task: str) -> str:",
        "    ...  # your agent code here",
        "",
        "# Every @trace_agent call now POSTs its trace to the server.",
        "# No other code changes needed.",
    ]
    for line in code:
        print(f"  {c(line, CYAN)}")

    print()
    print(c("═" * 72, CYAN))
    print(c("  Server demo complete. Server remains running until you press Ctrl+C.", WHITE))
    print(c("═" * 72, CYAN))
    print()

    # Keep server alive briefly so the user can browse the API
    try:
        info(f"Browse the API at {c(base + '/docs', CYAN, BOLD)} (Ctrl+C to quit)")
        await asyncio.sleep(30)
    except KeyboardInterrupt:
        info("Shutting down...")


if __name__ == "__main__":
    asyncio.run(main())
