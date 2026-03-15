#!/usr/bin/env python3
"""Seed 50 traces spread across the last 24 hours for realistic trend chart data."""

import json
import os
import random
import time
import urllib.request
import uuid

_PORT = os.environ.get("FLOWLENS_PORT", "8585")
ENDPOINT = f"http://localhost:{_PORT}/v1/traces/ingest"
AGENTS = ["vr-alpha", "vr-beta", "vr-gamma", "vr-lead", "vr-scribe"]
TOOLS = ["Read", "Write", "Edit", "Bash", "Grep", "Glob"]


def main() -> None:
    now = time.time()
    ok = 0
    for i in range(50):
        agent = random.choice(AGENTS)
        hours_ago = random.uniform(0, 23)
        start = now - hours_ago * 3600
        has_error = random.random() < 0.1

        spans = []
        for j in range(random.randint(2, 8)):
            tool = random.choice(TOOLS)
            span_start = start + j * random.uniform(0.5, 3.0)
            dur = random.uniform(50, 5000)
            spans.append({
                "span_id": uuid.uuid4().hex[:16],
                "trace_id": "",
                "name": f"{agent}/{tool}",
                "kind": "tool",
                "status": "error" if (has_error and j == 0) else "ok",
                "start_time": span_start,
                "end_time": span_start + dur / 1000,
                "duration_ms": dur,
                "attributes": {"agent.name": agent, "tool.name": tool},
                "events": [],
            })

        trace_id = uuid.uuid4().hex
        for s in spans:
            s["trace_id"] = trace_id

        trace = {
            "trace_id": trace_id,
            "service_name": "claude-code-agents",
            "start_time": start,
            "end_time": start + max(s["duration_ms"] for s in spans) / 1000,
            "duration_ms": sum(s["duration_ms"] for s in spans),
            "total_tokens": random.randint(1000, 20000),
            "total_cost_usd": round(random.uniform(0.001, 0.5), 4),
            "has_errors": has_error,
            "error_count": 1 if has_error else 0,
            "span_count": len(spans),
            "metadata": {"project": "flowlens"},
            "tags": {"agent": agent, "source": "seed-24h", "project": "flowlens"},
            "spans": spans,
        }

        data = json.dumps(trace).encode()
        req = urllib.request.Request(
            ENDPOINT, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            ok += 1
        except Exception as exc:
            print(f"  trace {i}: {exc}")

    print(f"Seeded {ok}/50 traces across 24 hours")


if __name__ == "__main__":
    main()
