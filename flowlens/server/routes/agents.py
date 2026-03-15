"""
Agent observability route handlers.

Endpoints:
- GET /v1/agents/summary
- GET /v1/agents/activity
- GET /v1/agents/profiles
- GET /v1/agents/relationships
- GET /v1/agents/network
- GET /v1/agents/{agent_name}/timeline
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from ..storage import TraceStore
from ..utils import _AGENT_PROFILES, _extract_agents_from_trace, _parse_tags

logger = logging.getLogger(__name__)

# TTL for the route-level summary cache (seconds)
_AGENTS_CACHE_TTL = 30.0


def create_agents_router(store: TraceStore) -> APIRouter:
    """Create and return the agents router."""
    router = APIRouter()

    # Per-router-instance TTL cache (dict + timestamp, no external deps).
    # Instance-scoped so each test/server gets isolated cache state.
    _cache: dict[str, tuple[float, Any]] = {}
    _cache_lock = threading.Lock()

    def _cache_get(key: str) -> Any:
        with _cache_lock:
            entry = _cache.get(key)
            if entry is None:
                return None
            ts, value = entry
            if time.time() - ts > _AGENTS_CACHE_TTL:
                del _cache[key]
                return None
            return value

    def _cache_set(key: str, value: Any) -> None:
        with _cache_lock:
            _cache[key] = (time.time(), value)

    def _make_agent_bucket(agent_name: str) -> dict[str, Any]:
        """Create a fresh per-agent stats accumulator."""
        return {
            "agent": agent_name,
            "trace_count": 0,
            "error_count": 0,
            "total_duration_ms": 0.0,
            "total_cost_usd": 0.0,
            "total_spans": 0,
            # models_used: {model_name: {"calls": int, "cost": float}}
            "models_used": {},
            # tool_counts: {tool_name: count}
            "tool_counts": {},
        }

    def _accumulate_trace_into_bucket(
        bucket: dict[str, Any],
        trace: dict[str, Any],
        spans: list[dict[str, Any]],
    ) -> None:
        """Accumulate trace-level + span-level metrics into a bucket."""
        bucket["trace_count"] += 1
        if trace.get("has_errors"):
            bucket["error_count"] += 1
        bucket["total_duration_ms"] += trace.get("duration_ms") or 0.0
        bucket["total_cost_usd"] += trace.get("total_cost_usd") or 0.0
        bucket["total_spans"] += trace.get("span_count") or 0

        # Aggregate per-span model usage and tool counts
        for span in spans:
            attrs = span.get("attributes") or {}
            span_name: str = span.get("name") or ""
            # Determine tool name (strip "agent/" prefix)
            tool_name = span_name.split("/")[-1] if "/" in span_name else span_name
            if tool_name:
                bucket["tool_counts"][tool_name] = bucket["tool_counts"].get(tool_name, 0) + 1

            # Model usage: look for gen_ai.request.model attribute
            model = attrs.get("gen_ai.request.model") or attrs.get("llm.model") or ""
            if model:
                span_cost = 0.0
                tok = span.get("token_usage") or {}
                if isinstance(tok, dict):
                    span_cost = float(tok.get("total_cost_usd") or 0.0)
                if model not in bucket["models_used"]:
                    bucket["models_used"][model] = {"calls": 0, "cost": 0.0}
                bucket["models_used"][model]["calls"] += 1
                bucket["models_used"][model]["cost"] = round(
                    bucket["models_used"][model]["cost"] + span_cost, 8
                )

    @router.get("/v1/agents/summary")
    async def agents_summary() -> JSONResponse:
        """Aggregate trace statistics grouped by agent name.

        Extracts agent info from trace tags (tags.agent) or span attributes.
        Returns a list of agent summaries with trace count, error rate,
        avg latency, total cost, span count, per-model usage, and top tools.

        Uses batch SQL queries (2 total) instead of N per-trace calls,
        and a 30-second TTL cache to reduce repeated aggregation work.
        """
        cached = _cache_get("agents_summary")
        if cached is not None:
            return JSONResponse(cached)

        t0 = time.perf_counter()

        try:
            traces = store.list_traces(limit=10_000)
        except Exception:
            logger.exception("Failed to list traces for agents summary")
            raise HTTPException(500, "Failed to retrieve traces")

        trace_ids = [t["trace_id"] for t in traces]

        # Single batch query for ALL spans (eliminates N get_trace() calls)
        spans_by_trace = store.get_spans_for_traces(trace_ids)

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug("agents_summary batch fetch: %d traces in %.1f ms", len(trace_ids), elapsed_ms)

        # Group metrics by agent name from tags or span attributes
        agent_stats: dict[str, dict[str, Any]] = {}
        for trace in traces:
            # Try trace-level tags first, then look at spans
            tags = _parse_tags(trace.get("tags") or {})
            agent_name: str = tags.get("agent") or "unknown"

            spans: list[dict[str, Any]] = spans_by_trace.get(trace["trace_id"]) or []

            # If still unknown, check span attributes for agent.name
            if agent_name == "unknown" and spans:
                found = _extract_agents_from_trace(trace, spans)
                found.discard("unknown")
                if found:
                    # Attribute this trace to ALL agents found in spans
                    for a in found:
                        if a not in agent_stats:
                            agent_stats[a] = _make_agent_bucket(a)
                        _accumulate_trace_into_bucket(agent_stats[a], trace, spans)
                    continue

            if agent_name not in agent_stats:
                agent_stats[agent_name] = _make_agent_bucket(agent_name)
            _accumulate_trace_into_bucket(agent_stats[agent_name], trace, spans)

        result = []
        for bucket in agent_stats.values():
            tc = bucket["trace_count"]
            # Build sorted top_tools list
            top_tools = sorted(
                [{"name": t, "count": c} for t, c in bucket["tool_counts"].items()],
                key=lambda x: -x["count"],
            )
            result.append(
                {
                    "agent": bucket["agent"],
                    "trace_count": tc,
                    "error_count": bucket["error_count"],
                    "error_rate": round(bucket["error_count"] / tc, 4) if tc else 0.0,
                    "avg_duration_ms": round(bucket["total_duration_ms"] / tc, 2) if tc else 0.0,
                    "total_cost_usd": round(bucket["total_cost_usd"], 6),
                    "total_spans": bucket["total_spans"],
                    "models_used": bucket["models_used"],
                    "top_tools": top_tools,
                }
            )

        result.sort(key=lambda x: x["trace_count"], reverse=True)
        payload = {"agents": result}
        _cache_set("agents_summary", payload)
        return JSONResponse(payload)

    @router.get("/v1/agents/activity")
    async def agents_activity() -> JSONResponse:
        """Return recent activity for each known agent.

        For each agent, returns:
        - last_seen: timestamp of most recent trace
        - status: "active" if last seen within 5 min, else "idle"
        - recent_tools: list of recent tool names used (from span names)
        - current_task: description from most recent span attributes
        - trace_count_1h: traces in last hour
        """
        now = time.time()
        one_hour_ago = now - 3600.0
        active_threshold = now - 300.0  # 5 minutes

        try:
            recent_traces = store.get_traces_by_time_range(start=one_hour_ago, end=now + 1)
        except Exception:
            logger.exception("Failed to list traces for agents activity")
            raise HTTPException(500, "Failed to retrieve agent activity")

        # Group traces by agent
        agent_buckets: dict[str, dict[str, Any]] = {}
        for trace in recent_traces:
            tags = _parse_tags(trace.get("tags") or {})
            agent_name: str = tags.get("agent") or "unknown"

            if agent_name not in agent_buckets:
                agent_buckets[agent_name] = {
                    "agent": agent_name,
                    "last_seen": 0.0,
                    "trace_count_1h": 0,
                    "all_tool_names": [],
                    "latest_trace_id": None,
                }
            bucket = agent_buckets[agent_name]
            bucket["trace_count_1h"] += 1
            start_time = trace.get("start_time") or 0.0
            if start_time > bucket["last_seen"]:
                bucket["last_seen"] = start_time
                bucket["latest_trace_id"] = trace.get("trace_id")

        # Ensure ALL known agents from _AGENT_PROFILES are included
        for known_agent in _AGENT_PROFILES:
            if known_agent not in agent_buckets:
                agent_buckets[known_agent] = {
                    "agent": known_agent,
                    "last_seen": 0.0,
                    "trace_count_1h": 0,
                    "all_tool_names": [],
                    "latest_trace_id": None,
                }

        # For each agent, fetch the most recent trace's spans to extract tool names
        result = []
        for agent_name, bucket in agent_buckets.items():
            recent_tools: list[str] = []
            current_task: str | None = None

            latest_tid = bucket["latest_trace_id"]
            if latest_tid:
                try:
                    full_trace = store.get_trace(latest_tid)
                    if full_trace:
                        spans = full_trace.get("spans") or []
                        # Collect span names, extract tool name after last "/"
                        tool_names_seen: list[str] = []
                        for span in spans:
                            span_name = span.get("name") or ""
                            # "vr-alpha/Read" -> "Read"; "Read" -> "Read"
                            tool_name = span_name.split("/")[-1] if "/" in span_name else span_name
                            if tool_name and tool_name not in tool_names_seen:
                                tool_names_seen.append(tool_name)
                        recent_tools = tool_names_seen[:5]

                        # current_task: description from the last span's attributes
                        if spans:
                            last_span = spans[-1]
                            attrs = last_span.get("attributes") or {}
                            current_task = attrs.get("description") or attrs.get("task") or None
                except Exception:
                    logger.debug(
                        "Failed to fetch spans for agent %s trace %s", agent_name, latest_tid
                    )

            last_seen = bucket["last_seen"]
            status = "active" if last_seen >= active_threshold else "idle"

            result.append(
                {
                    "agent": agent_name,
                    "last_seen": last_seen if last_seen > 0 else None,
                    "status": status,
                    "recent_tools": recent_tools,
                    "current_task": current_task,
                    "trace_count_1h": bucket["trace_count_1h"],
                }
            )

        # Sort: active first, then by last_seen desc, then alphabetical
        result.sort(
            key=lambda x: (0 if x["status"] == "active" else 1, -(x["last_seen"] or 0), x["agent"])
        )
        return JSONResponse({"agents": result})

    @router.get("/v1/agents/profiles")
    async def agents_profiles() -> JSONResponse:
        """Return profile info for all known agents.

        Merges built-in profiles with dynamically discovered agents from traces.
        """
        # Get all known agent names from traces
        traces = store.list_traces(limit=1000)
        discovered = set()
        for t in traces:
            tags = _parse_tags(t.get("tags") or {})
            agent = tags.get("agent")
            if agent:
                discovered.add(agent)

        result = []
        # Add all built-in profiles
        for agent_name, profile in _AGENT_PROFILES.items():
            result.append(
                {
                    "agent": agent_name,
                    "known": True,
                    **profile,
                }
            )

        # Add any discovered agents not in built-in
        for agent_name in discovered:
            if agent_name not in _AGENT_PROFILES:
                result.append(
                    {
                        "agent": agent_name,
                        "name": agent_name,
                        "role": "Agent",
                        "color": "#9ca3af",
                        "icon": "user",
                        "known": False,
                    }
                )

        return JSONResponse({"agents": result})

    @router.get("/v1/agents/relationships")
    async def agents_relationships() -> JSONResponse:
        """Return agent spawn relationships for visualization.

        Analyzes spans where tool_name contains 'Agent' or 'spawn' to build
        a parent-child graph of which agents spawned which others.

        Span naming conventions recognized:
        - ``subagent/<child>``        — span name emitted by SDK subagent hook
        - ``<parent>/spawn/<child>``  — explicit spawn span with parent prefix
        - ``<parent>/Agent/<input>``  — Agent tool call (subagent_type parsed
                                       from attributes.tool.input or span name)
        """
        try:
            traces = store.list_traces(limit=500)
        except Exception:
            logger.exception("Failed to list traces for agent relationships")
            raise HTTPException(500, "Failed to retrieve traces")

        relationships: dict[str, int] = {}  # "parent->child": count

        for trace_meta in traces:
            # Extract the agent that owns this trace (default "main")
            tags = _parse_tags(trace_meta.get("tags") or {})
            trace_agent: str = tags.get("agent") or "main"

            full = store.get_trace(trace_meta["trace_id"])
            if not full:
                continue

            for span in full.get("spans", []):
                name: str = span.get("name", "")
                name_lower = name.lower()
                attrs: dict[str, Any] = span.get("attributes") or {}

                # Pattern 1: "subagent/<child>" — subagent lifecycle span
                if name_lower.startswith("subagent/"):
                    child = name[len("subagent/") :]
                    if child:
                        key = f"{trace_agent}->{child}"
                        relationships[key] = relationships.get(key, 0) + 1
                    continue

                # Pattern 2: "spawn" anywhere in the name
                if "spawn" in name_lower:
                    parts = [p for p in name.split("/") if p]
                    if len(parts) >= 2:
                        parent = parts[0]
                        child = parts[-1]
                        if parent != child:
                            key = f"{parent}->{child}"
                            relationships[key] = relationships.get(key, 0) + 1
                    continue

                # Pattern 3: "<parent>/Agent/<something>" — Agent tool call
                if "Agent" in name and "/" in name:
                    parts = name.split("/")
                    if len(parts) >= 2:
                        parent = parts[0]
                        # Try to resolve the spawned agent type from attributes
                        tool_input = attrs.get("tool.input") or attrs.get("input") or ""
                        if isinstance(tool_input, dict):
                            child = tool_input.get("subagent_type") or tool_input.get("agent") or ""
                        elif isinstance(tool_input, str):
                            # Simple heuristic: look for subagent_type key in JSON-ish string
                            m = re.search(r'"subagent_type"\s*:\s*"([^"]+)"', tool_input)
                            child = m.group(1) if m else ""
                        else:
                            child = ""
                        if not child:
                            # Fall back to last path component
                            child = parts[-1]
                        if parent and child and parent != child:
                            key = f"{parent}->{child}"
                            relationships[key] = relationships.get(key, 0) + 1

        # Build graph structure — collect agents from relationships
        agents: set[str] = set()
        edges: list[dict[str, Any]] = []
        for rel, count in relationships.items():
            src, tgt = rel.split("->", 1)
            agents.add(src)
            agents.add(tgt)
            edges.append({"source": src, "target": tgt, "count": count})

        # Always include all built-in agents as nodes
        for agent_name in _AGENT_PROFILES:
            agents.add(agent_name)

        # Always include agents discovered from traces
        for trace_meta in traces:
            tags = _parse_tags(trace_meta.get("tags") or {})
            discovered_agent: str = tags.get("agent") or ""
            if discovered_agent:
                agents.add(discovered_agent)

        nodes = [
            {
                "id": a,
                "label": _AGENT_PROFILES.get(a, {}).get("name", a),
            }
            for a in sorted(agents)
        ]
        edges.sort(key=lambda e: (-e["count"], e["source"], e["target"]))
        return JSONResponse({"nodes": nodes, "edges": edges})

    @router.get("/v1/agents/network")
    async def agents_network() -> JSONResponse:
        """Return complete agent network data for 3D visualization.

        Returns nodes with size/status info and edges with type/weight.
        Merges data from summary, activity, profiles, and relationships.
        """
        # Fetch all source data
        summary_resp = await agents_summary()
        summary_data = json.loads(summary_resp.body)

        activity_resp = await agents_activity()
        activity_data = json.loads(activity_resp.body)

        rel_resp = await agents_relationships()
        rel_data = json.loads(rel_resp.body)

        # Index summary and activity by agent name for O(1) lookup
        summary_by_agent: dict[str, dict[str, Any]] = {
            a["agent"]: a for a in summary_data.get("agents", [])
        }
        activity_by_agent: dict[str, dict[str, Any]] = {
            a["agent"]: a for a in activity_data.get("agents", [])
        }

        # Collect the full set of known agents from all sources
        all_agents: set[str] = set(_AGENT_PROFILES.keys())
        all_agents.update(summary_by_agent.keys())
        all_agents.update(activity_by_agent.keys())
        # Also include nodes returned by the relationships endpoint
        for node in rel_data.get("nodes", []):
            all_agents.add(node["id"])

        def _normalize_size(trace_count: int) -> float:
            """Map trace count to a node size in [0.3, 1.0]."""
            if trace_count <= 0:
                return 0.3
            # Soft cap at 100 traces → size 1.0
            return min(1.0, 0.3 + 0.7 * (trace_count / 100.0))

        nodes: list[dict[str, Any]] = []
        for agent in sorted(all_agents):
            profile = _AGENT_PROFILES.get(agent, {})
            summary = summary_by_agent.get(agent, {})
            activity = activity_by_agent.get(agent, {})

            nodes.append(
                {
                    "id": agent,
                    "label": profile.get("name", agent),
                    "role": profile.get("role", "Agent"),
                    "color": profile.get("color", "#9ca3af"),
                    "size": _normalize_size(summary.get("trace_count", 0)),
                    "status": activity.get("status", "idle") if activity else "idle",
                    "trace_count": summary.get("trace_count", 0),
                    "error_rate": summary.get("error_rate", 0),
                    "cost": summary.get("total_cost_usd", 0),
                }
            )

        edges = rel_data.get("edges", [])
        return JSONResponse({"nodes": nodes, "edges": edges})

    @router.get("/v1/agents/{agent_name}/timeline")
    async def agent_timeline(agent_name: str, limit: int = 100) -> JSONResponse:
        """Return chronological tool calls for a specific agent.

        Scans recent traces attributed to the given agent and returns a flat
        list of span events ordered by start_time ascending (oldest first).
        Each event includes the tool name, optional file path (for Read/Edit/
        Write/Glob/Grep tools), optional command (for Bash), optional model
        name (for LLM spans), duration, and status.

        Query parameters:
        - ``limit`` (int, default 100): maximum events to return.
        """
        limit = max(1, min(limit, 500))

        try:
            traces = store.list_traces(limit=500)
        except Exception:
            logger.exception("Failed to list traces for agent timeline: %s", agent_name)
            raise HTTPException(500, "Failed to retrieve traces")

        events: list[dict[str, Any]] = []

        for trace_meta in traces:
            tags = _parse_tags(trace_meta.get("tags") or {})
            trace_agent: str = tags.get("agent") or "unknown"

            # Only look at traces that might belong to this agent
            # (direct tag match, or we'll check spans for attribute match)
            if trace_agent != agent_name and trace_agent != "unknown":
                continue

            full = store.get_trace(trace_meta["trace_id"])
            if not full:
                continue
            spans: list[dict[str, Any]] = full.get("spans") or []

            for span in spans:
                attrs = span.get("attributes") or {}
                span_name: str = span.get("name") or ""

                # Determine which agent this span belongs to
                span_agent = (
                    attrs.get("agent.name")
                    or (span_name.split("/", 1)[0] if "/" in span_name else None)
                    or trace_agent
                )
                if span_agent != agent_name:
                    continue

                # Extract tool name (strip agent prefix)
                tool = span_name.split("/")[-1] if "/" in span_name else span_name

                # Extract file_path from tool.input for file-based tools
                file_path: str | None = None
                command: str | None = None
                model: str | None = None

                tool_input = attrs.get("tool.input") or attrs.get("input") or ""
                if isinstance(tool_input, str) and tool_input:
                    try:
                        tool_input = json.loads(tool_input)
                    except (ValueError, TypeError):
                        pass

                if isinstance(tool_input, dict):
                    # File-based tools: Read, Edit, Write, Glob, Grep
                    file_path = (
                        tool_input.get("file_path")
                        or tool_input.get("path")
                        or tool_input.get("pattern")
                        or None
                    )
                    # Bash: command
                    command = tool_input.get("command") or None
                elif isinstance(tool_input, str) and tool_input:
                    # Some exporters emit the raw file path as a plain string
                    file_path = tool_input if "\n" not in tool_input else None

                # Model for LLM spans
                model = attrs.get("gen_ai.request.model") or attrs.get("llm.model") or None

                event: dict[str, Any] = {
                    "timestamp": span.get("start_time") or 0,
                    "tool": tool,
                    "duration_ms": span.get("duration_ms") or 0,
                    "status": span.get("status") or "ok",
                }
                if file_path:
                    event["file_path"] = file_path
                if command:
                    event["command"] = command
                if model:
                    event["model"] = model

                events.append(event)

        # Sort chronologically (oldest first)
        events.sort(key=lambda e: e["timestamp"])
        events = events[:limit]

        return JSONResponse({"agent": agent_name, "events": events, "total": len(events)})

    return router
