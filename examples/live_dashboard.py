#!/usr/bin/env python3
"""
FlowLens Example — Live Dashboard
====================================
Generates a rich set of sample traces, saves them to the FlowLens database,
starts the API server, and opens the browser to the live dashboard.

What it does:
  1. Generates 20 realistic sample traces (healthy, error, cost-spike, retry-storm)
  2. Saves each trace to an in-memory SQLite store via the HTTP API
  3. Starts the FlowLens FastAPI server on a free local port (requires uvicorn)
  4. Opens the browser to the dashboard UI
  5. Prints curl commands you can use to explore the API manually

Requirements (for server + browser open):
    pip install fastapi uvicorn

If fastapi/uvicorn are not installed, the script still generates traces and
shows you what the dashboard would contain.

Run with:
    python3 examples/live_dashboard.py
"""

import asyncio
import json
import os
import random
import socket
import sys
import threading
import time
import uuid
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _utils import (
    BOLD,
    BRIGHT_BLUE,
    BRIGHT_CYAN,
    BRIGHT_GREEN,
    BRIGHT_RED,
    BRIGHT_WHITE,
    BRIGHT_YELLOW,
    DIM,
    WHITE,
    c,
    err,
    hbar,
    info,
    note,
    ok,
    print_table,
    section,
    spin,
    warn,
)

# ─────────────────────────────────────────────────────────────────────────────
# Trace payload builder (mirrors the server ingest format)
# ─────────────────────────────────────────────────────────────────────────────

def _make_trace_payload(
    scenario: str,
    service: str = "demo-agent",
    has_error: bool = False,
    input_tokens: int = 900,
    output_tokens: int = 220,
    model: str = "claude-sonnet-4-20250514",
    agent_duration_ms: float = 350.0,
    extra_spans: list | None = None,
) -> dict:
    """Build a complete trace ingest payload."""
    now       = time.time() - random.uniform(0, 3600)  # random time in last hour
    trace_id  = uuid.uuid4().hex
    agent_sid = uuid.uuid4().hex[:16]
    llm_sid   = uuid.uuid4().hex[:16]
    tool_sid  = uuid.uuid4().hex[:16]
    ret_sid   = uuid.uuid4().hex[:16]

    token_total = input_tokens + output_tokens
    cost_usd    = input_tokens / 1_000_000 * 3.0 + output_tokens / 1_000_000 * 15.0

    spans = [
        {
            "span_id": agent_sid, "trace_id": trace_id, "parent_span_id": None,
            "name": "research_agent", "kind": "agent",
            "status": "error" if has_error else "ok",
            "start_time": now, "end_time": now + agent_duration_ms / 1000,
            "duration_ms": agent_duration_ms, "attributes": {"scenario": scenario},
            "events": [],
            "error": {"message": "web_search timed out after 30s", "type": "TimeoutError"}
                     if has_error else None,
        },
        {
            "span_id": llm_sid, "trace_id": trace_id, "parent_span_id": agent_sid,
            "name": "research_planner", "kind": "llm",
            "status": "ok",
            "start_time": now + 0.01, "end_time": now + 0.09,
            "duration_ms": 80,
            "attributes": {
                "gen_ai.request.model": model,
                "gen_ai.usage.input_tokens": input_tokens,
                "gen_ai.usage.output_tokens": output_tokens,
            },
            "events": [],
            "token_usage": {
                "input_tokens": input_tokens, "output_tokens": output_tokens,
                "total_tokens": token_total,
                "input_cost_usd":  round(input_tokens  / 1_000_000 * 3.0,  6),
                "output_cost_usd": round(output_tokens / 1_000_000 * 15.0, 6),
                "total_cost_usd":  round(cost_usd, 6),
            },
        },
        {
            "span_id": ret_sid, "trace_id": trace_id, "parent_span_id": agent_sid,
            "name": "vector_search", "kind": "retrieval",
            "status": "ok",
            "start_time": now + 0.09, "end_time": now + 0.13,
            "duration_ms": 40, "attributes": {"retrieval.top_k": 3}, "events": [],
        },
        {
            "span_id": tool_sid, "trace_id": trace_id, "parent_span_id": agent_sid,
            "name": "web_search", "kind": "tool",
            "status": "error" if has_error else "ok",
            "start_time": now + 0.13,
            "end_time": now + (30.0 if has_error else 0.32),
            "duration_ms": 30_000 if has_error else 190,
            "attributes": {"tool.input.query": f"query for {scenario}"},
            "events": [],
            "error": {"message": "web_search timed out after 30s", "type": "TimeoutError"}
                     if has_error else None,
        },
    ]

    if extra_spans:
        spans.extend(extra_spans)

    return {
        "trace_id": trace_id,
        "service_name": service,
        "start_time": now,
        "end_time": now + agent_duration_ms / 1000,
        "duration_ms": agent_duration_ms,
        "total_tokens": token_total,
        "total_cost_usd": round(cost_usd, 6),
        "has_errors": has_error,
        "error_count": 2 if has_error else 0,
        "span_count": len(spans),
        "metadata": {"scenario": scenario},
        "spans": spans,
    }


def build_sample_traces() -> list[dict]:
    """Generate 20 traces covering all interesting scenarios."""
    traces = []

    # 8 healthy traces (varying token counts, latencies)
    for i in range(8):
        traces.append(_make_trace_payload(
            "healthy", input_tokens=random.randint(600, 1400),
            output_tokens=random.randint(150, 350),
            agent_duration_ms=random.uniform(200, 600),
        ))

    # 4 timeout-cascade error traces
    for i in range(4):
        traces.append(_make_trace_payload(
            "timeout_cascade", has_error=True,
            input_tokens=random.randint(800, 1200), output_tokens=200,
            agent_duration_ms=30_500,
        ))

    # 3 cost-spike traces (massive input tokens)
    for i in range(3):
        traces.append(_make_trace_payload(
            "cost_spike",
            input_tokens=random.randint(80_000, 150_000),
            output_tokens=random.randint(100, 200),
            model="claude-opus-4-20250514",
            agent_duration_ms=random.uniform(400, 800),
        ))

    # 3 retry-storm traces (many tool spans)
    for i in range(3):
        extra = []
        parent_sid = uuid.uuid4().hex[:16]  # reuse agent sid conceptually
        for j in range(6):
            extra.append({
                "span_id": uuid.uuid4().hex[:16],
                "trace_id": "",  # filled in by payload builder
                "parent_span_id": parent_sid,
                "name": "web_search",
                "kind": "tool",
                "status": "error" if j < 5 else "ok",
                "start_time": time.time() + j * 0.05,
                "end_time":   time.time() + j * 0.05 + 0.03,
                "duration_ms": 30,
                "attributes": {}, "events": [],
                "error": {"message": "Connection refused", "type": "ConnectionError"}
                         if j < 5 else None,
            })
        traces.append(_make_trace_payload(
            "retry_storm", input_tokens=900, output_tokens=200,
            agent_duration_ms=random.uniform(600, 1200),
        ))

    # 2 degraded latency traces
    for mult in [2.0, 4.0]:
        traces.append(_make_trace_payload(
            "degraded_latency",
            input_tokens=int(900 * mult), output_tokens=220,
            agent_duration_ms=300 * mult,
        ))

    return traces


# ─────────────────────────────────────────────────────────────────────────────
# Server management
# ─────────────────────────────────────────────────────────────────────────────

def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _start_server(port: int, db_path: str = ":memory:") -> bool:
    """Start the FlowLens API server in a daemon thread. Returns True on success."""
    try:
        import uvicorn

        from flowlens.server.app import create_app
    except ImportError:
        return False

    app = create_app(db_path=db_path)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)

    def _run():
        asyncio.run(server.serve())

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return True


def _wait_for_server(port: int, timeout: float = 8.0) -> bool:
    """Poll until the server accepts connections or timeout expires."""
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.15)
    return False


def _ingest_trace(port: int, payload: dict) -> bool:
    """POST a trace payload to the server. Returns True on success."""
    try:
        import urllib.request
        body = json.dumps(payload).encode()
        req  = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/traces/ingest",
            data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status < 300
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Console-only fallback summary (when uvicorn not available)
# ─────────────────────────────────────────────────────────────────────────────

def print_console_summary(traces: list[dict]) -> None:
    """Print a rich summary of the sample traces when the server isn't available."""
    section("Sample Trace Dataset Summary")

    # Scenario distribution
    scenario_counts: dict[str, int] = {}
    for t in traces:
        s = t["metadata"].get("scenario", "unknown")
        scenario_counts[s] = scenario_counts.get(s, 0) + 1

    max_count = max(scenario_counts.values()) if scenario_counts else 1
    print(c("  Scenario distribution:", BRIGHT_WHITE, BOLD))
    sev_colors = {
        "healthy":          BRIGHT_GREEN,
        "timeout_cascade":  BRIGHT_RED,
        "cost_spike":       BRIGHT_YELLOW,
        "retry_storm":      BRIGHT_YELLOW,
        "degraded_latency": BRIGHT_BLUE,
    }
    for scenario, count in sorted(scenario_counts.items(), key=lambda x: -x[1]):
        col = sev_colors.get(scenario, WHITE)
        bar = hbar(count, max_count, width=20, color=col)
        print(f"    {c(scenario.ljust(20), DIM)}  {bar}  {c(str(count), col)} traces")
    print()

    # Aggregate stats
    error_count  = sum(1 for t in traces if t.get("has_errors"))
    total_tokens = sum(t["total_tokens"] for t in traces)
    total_cost   = sum(t["total_cost_usd"] for t in traces)
    avg_duration = sum(t["duration_ms"] for t in traces) / len(traces) if traces else 0

    print_table(
        ["Metric", "Value"],
        [
            ["Total traces",       c(str(len(traces)), BRIGHT_CYAN)],
            ["Error traces",       c(str(error_count), BRIGHT_RED)],
            ["Error rate",         c(f"{error_count / len(traces) if traces else 0:.0%}", BRIGHT_RED)],
            ["Total tokens",       c(f"{total_tokens:,}", BRIGHT_YELLOW)],
            ["Total cost",         c(f"${total_cost:.4f}", BRIGHT_GREEN)],
            ["Avg cost/trace",     c(f"${total_cost / len(traces) if traces else 0:.5f}", BRIGHT_GREEN)],
            ["Avg duration",       c(f"{avg_duration:.0f} ms", BRIGHT_CYAN)],
        ],
        colors=[DIM, BRIGHT_WHITE],
        title="Aggregate Metrics",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    # Banner
    print(c("\n╔══════════════════════════════════════════════════════════════════════╗", BRIGHT_CYAN, BOLD))
    print(c("║         F L O W L E N S   —   Agent Observability Platform           ║", BRIGHT_CYAN, BOLD))
    print(c("║         Example: Live Dashboard                                      ║", BRIGHT_CYAN, BOLD))
    print(c("║         Generates traces → saves to DB → launches server → browser  ║", BRIGHT_CYAN, BOLD))
    print(c("╚══════════════════════════════════════════════════════════════════════╝", BRIGHT_CYAN, BOLD))
    print()

    # Step 1: Generate traces
    section("Step 1 — Generate Sample Traces")
    info("Building 20 diverse traces (healthy, error, cost-spike, retry-storm, degraded)…")
    sample_traces = build_sample_traces()
    ok(f"Generated {len(sample_traces)} sample traces")

    scenario_counts: dict[str, int] = {}
    for t in sample_traces:
        s = t["metadata"]["scenario"]
        scenario_counts[s] = scenario_counts.get(s, 0) + 1

    sev_colors = {
        "healthy": BRIGHT_GREEN, "timeout_cascade": BRIGHT_RED,
        "cost_spike": BRIGHT_YELLOW, "retry_storm": BRIGHT_YELLOW,
        "degraded_latency": BRIGHT_BLUE,
    }
    for scenario, count in sorted(scenario_counts.items(), key=lambda x: -x[1]):
        col = sev_colors.get(scenario, WHITE)
        bar = hbar(count, max(scenario_counts.values()), width=14, color=col)
        print(f"    {c(scenario.ljust(22), DIM)}  {bar}  {c(str(count), col)}")
    print()

    # Step 2: Try to start the server
    section("Step 2 — Start FlowLens API Server")
    port = _find_free_port()

    try:
        import uvicorn  # noqa: F401
        server_available = True
    except ImportError:
        server_available = False

    if not server_available:
        warn("uvicorn / fastapi not installed — skipping server launch")
        note("Install with: pip install fastapi uvicorn")
        note("Then re-run to get the live dashboard in your browser.")
        print()
        print_console_summary(sample_traces)
        _print_install_hint()
        return

    info(f"Starting FlowLens server on port {c(str(port), BRIGHT_CYAN)}…")
    started = _start_server(port)
    if not started:
        warn("Could not start server.")
        print_console_summary(sample_traces)
        return

    spin("Waiting for server to be ready", seconds=2.0)
    ready = _wait_for_server(port, timeout=8.0)
    if not ready:
        err("Server did not become ready within 8 seconds.")
        print_console_summary(sample_traces)
        return

    ok(f"Server ready at {c(f'http://127.0.0.1:{port}', BRIGHT_CYAN, BOLD)}")

    # Step 3: Ingest traces
    section("Step 3 — Ingest Sample Traces")
    info(f"POSTing {len(sample_traces)} traces to /v1/traces/ingest…")

    success_count = 0
    for i, payload in enumerate(sample_traces):
        if _ingest_trace(port, payload):
            success_count += 1
        # Small progress indication every 5 traces
        if (i + 1) % 5 == 0:
            bar = hbar(i + 1, len(sample_traces), width=20, color=BRIGHT_CYAN)
            sys.stdout.write(f"\r    {bar}  {c(str(i+1)+'/'+str(len(sample_traces)), DIM)}")
            sys.stdout.flush()

    print()  # newline after progress
    ok(f"Ingested {success_count}/{len(sample_traces)} traces successfully")

    # Step 4: Print dashboard URL + API explorer
    section("Step 4 — Dashboard & API Explorer")

    dashboard_url = f"http://127.0.0.1:{port}"
    api_base      = f"http://127.0.0.1:{port}/v1"

    print(c("  Dashboard URLs:", BRIGHT_WHITE, BOLD))
    endpoints = [
        ("Main dashboard",       f"{dashboard_url}/",                              "Visual trace explorer"),
        ("All traces (JSON)",    f"{api_base}/traces",                             "Paginated list"),
        ("Error traces",         f"{api_base}/traces/errors",                      "Only failed traces"),
        ("Global stats",         f"{api_base}/stats",                              "Token/cost/error summary"),
        ("Cost breakdown",       f"{api_base}/cost/breakdown",                     "Cost by model & span"),
        ("Pattern summary",      f"{api_base}/patterns/summary",                   "Fleet-wide pattern stats"),
        ("Health check",         f"{dashboard_url}/health",                        "Server health"),
    ]
    for label, url, desc in endpoints:
        print(f"    {c(label + ':', DIM):<26}  {c(url, BRIGHT_CYAN)}  {c('# ' + desc, DIM)}")
    print()

    print(c("  curl commands:", BRIGHT_WHITE, BOLD))
    curl_examples = [
        ("List traces",    f"curl -s http://127.0.0.1:{port}/v1/traces | python3 -m json.tool"),
        ("Error traces",   f"curl -s http://127.0.0.1:{port}/v1/traces/errors"),
        ("Stats",          f"curl -s http://127.0.0.1:{port}/v1/stats | python3 -m json.tool"),
        ("Cost breakdown", f"curl -s http://127.0.0.1:{port}/v1/cost/breakdown"),
    ]
    for label, cmd in curl_examples:
        print(f"    {c(label + ':', DIM):<16}  {c(cmd, DIM)}")
    print()

    # Step 5: Open browser
    section("Step 5 — Opening Browser")
    info(f"Opening {c(dashboard_url, BRIGHT_CYAN, BOLD)} in your browser…")
    try:
        webbrowser.open(dashboard_url)
        ok("Browser opened")
    except Exception as exc:
        warn(f"Could not open browser automatically: {exc}")
        note(f"Manually open: {dashboard_url}")

    # Keep running with instructions
    section("Server is Running")
    print(c("  Press Ctrl+C to stop the server.\n", BRIGHT_WHITE, BOLD))
    print(f"  {c('Dashboard:', DIM)} {c(dashboard_url, BRIGHT_CYAN, BOLD)}")
    print(f"  {c('API base:  ', DIM)} {c(api_base, BRIGHT_CYAN)}")
    print()
    print_console_summary(sample_traces)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print()
        ok("Server stopped. Goodbye!")
        print()


def _print_install_hint() -> None:
    section("Next Steps")
    print(c("  To launch the live dashboard, install the server dependencies:", DIM))
    print()
    print(f"    {c('pip install fastapi uvicorn', BRIGHT_CYAN)}")
    print()
    print(f"    {c('python3 examples/live_dashboard.py', BRIGHT_CYAN)}")
    print()
    print(c("  Or explore the API directly after starting the server:", DIM))
    print(f"    {c('flowlens server --port 8585', BRIGHT_CYAN)}")
    print()


if __name__ == "__main__":
    main()
