"""Tests for flowlens/analysis/dag_builder.py — DAG construction and root cause identification."""

from __future__ import annotations

import time

from flowlens.analysis.dag_builder import (
    build_causal_dag,
    calculate_critical_path,
    get_error_propagation_chain,
)
from flowlens.analysis.models import CausalDAG, ErrorRole
from flowlens.sdk.models import Span, SpanKind, SpanStatus, Trace

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _span(
    name: str,
    kind: SpanKind = SpanKind.CUSTOM,
    status: SpanStatus = SpanStatus.OK,
    parent: Span | None = None,
    trace_id: str = "",
    offset: float = 0.0,
) -> Span:
    s = Span(
        name=name,
        kind=kind,
        status=status,
        trace_id=trace_id,
        start_time=time.time() + offset,
    )
    if parent:
        s.parent_span_id = parent.span_id
    if status == SpanStatus.ERROR:
        s.error_message = f"{name} failed"
    s.end_time = s.start_time + 0.1
    return s


def _trace_with_spans(*spans: Span) -> Trace:
    trace = Trace(service_name="test-svc")
    for s in spans:
        s.trace_id = trace.trace_id
        trace.spans.append(s)
    trace.finish()
    return trace


# ---------------------------------------------------------------------------
# Empty trace
# ---------------------------------------------------------------------------


class TestEmptyTrace:
    def test_empty_trace_returns_empty_dag(self):
        trace = Trace(service_name="empty")
        dag = build_causal_dag(trace)
        assert isinstance(dag, CausalDAG)
        assert dag.nodes == []
        assert dag.edges == []
        assert dag.root_causes == []

    def test_empty_dag_has_no_errors(self):
        trace = Trace(service_name="empty")
        dag = build_causal_dag(trace)
        assert not dag.has_errors


# ---------------------------------------------------------------------------
# Single-node DAG
# ---------------------------------------------------------------------------


class TestSingleNodeDAG:
    def test_single_ok_span(self):
        span = _span("agent", SpanKind.AGENT, SpanStatus.OK)
        trace = _trace_with_spans(span)
        dag = build_causal_dag(trace)

        assert len(dag.nodes) == 1
        assert dag.nodes[0].name == "agent"
        assert dag.nodes[0].status == "ok"
        assert not dag.has_errors
        assert dag.root_causes == []

    def test_single_error_span_is_root_cause(self):
        span = _span("broken", SpanKind.TOOL, SpanStatus.ERROR)
        trace = _trace_with_spans(span)
        dag = build_causal_dag(trace)

        assert len(dag.nodes) == 1
        assert dag.has_errors
        assert len(dag.root_causes) == 1
        assert dag.root_causes[0] == span.span_id

        node = dag.nodes[0]
        assert node.error_role == ErrorRole.ROOT_CAUSE


# ---------------------------------------------------------------------------
# Simple linear DAG (A → B → C, no errors)
# ---------------------------------------------------------------------------


class TestLinearDAG:
    def test_linear_no_errors(self):
        a = _span("a", SpanKind.AGENT, SpanStatus.OK, offset=0.0)
        b = _span("b", SpanKind.LLM, SpanStatus.OK, parent=a, offset=0.1)
        c = _span("c", SpanKind.TOOL, SpanStatus.OK, parent=b, offset=0.2)
        trace = _trace_with_spans(a, b, c)
        dag = build_causal_dag(trace)

        assert len(dag.nodes) == 3
        assert not dag.has_errors
        assert dag.edges == []

    def test_linear_error_at_leaf(self):
        a = _span("a", SpanKind.AGENT, SpanStatus.OK, offset=0.0)
        b = _span("b", SpanKind.LLM, SpanStatus.OK, parent=a, offset=0.1)
        c = _span("c", SpanKind.TOOL, SpanStatus.ERROR, parent=b, offset=0.2)

        trace = _trace_with_spans(a, b, c)
        dag = build_causal_dag(trace)

        assert dag.has_errors
        assert len(dag.root_causes) == 1
        assert dag.root_causes[0] == c.span_id

    def test_linear_error_at_root_propagates(self):
        a = _span("a", SpanKind.AGENT, SpanStatus.ERROR, offset=0.0)
        b = _span("b", SpanKind.LLM, SpanStatus.ERROR, parent=a, offset=0.1)
        c = _span("c", SpanKind.TOOL, SpanStatus.ERROR, parent=b, offset=0.2)

        trace = _trace_with_spans(a, b, c)
        dag = build_causal_dag(trace)

        # Only `a` should be root cause (no error ancestor)
        assert len(dag.root_causes) == 1
        assert dag.root_causes[0] == a.span_id

        node_map = {n.span_id: n for n in dag.nodes}
        assert node_map[b.span_id].error_role == ErrorRole.CASCADED
        assert node_map[c.span_id].error_role == ErrorRole.CASCADED


# ---------------------------------------------------------------------------
# Branching / merging DAG
# ---------------------------------------------------------------------------


class TestBranchingDAG:
    def test_parallel_branches_independent_errors(self):
        root = _span("root", SpanKind.AGENT, SpanStatus.OK, offset=0.0)
        branch_a = _span("branch_a", SpanKind.LLM, SpanStatus.ERROR, parent=root, offset=0.1)
        branch_b = _span("branch_b", SpanKind.TOOL, SpanStatus.ERROR, parent=root, offset=0.2)

        trace = _trace_with_spans(root, branch_a, branch_b)
        dag = build_causal_dag(trace)

        # branch_a comes first in time, so branch_b is preceded by branch_a (an error sibling)
        # Therefore branch_a is the root cause, branch_b is cascaded
        rc_ids = set(dag.root_causes)
        assert branch_a.span_id in rc_ids

    def test_fan_out_one_error_sibling(self):
        root = _span("root", SpanKind.AGENT, SpanStatus.OK, offset=0.0)
        ok_child = _span("ok_child", SpanKind.TOOL, SpanStatus.OK, parent=root, offset=0.1)
        err_child = _span("err_child", SpanKind.TOOL, SpanStatus.ERROR, parent=root, offset=0.2)

        trace = _trace_with_spans(root, ok_child, err_child)
        dag = build_causal_dag(trace)

        # err_child has a preceding sibling (ok_child) that is OK, so it is a root cause
        assert err_child.span_id in dag.root_causes

    def test_causal_edges_parent_to_child(self):
        root = _span("root", SpanKind.AGENT, SpanStatus.ERROR, offset=0.0)
        child = _span("child", SpanKind.LLM, SpanStatus.ERROR, parent=root, offset=0.1)

        trace = _trace_with_spans(root, child)
        dag = build_causal_dag(trace)

        # There should be a "caused_by" edge from root → child
        caused_by_edges = [e for e in dag.edges if e.relation == "caused_by"]
        assert any(
            e.source_id == root.span_id and e.target_id == child.span_id for e in caused_by_edges
        )


# ---------------------------------------------------------------------------
# Circular dependency handling
# ---------------------------------------------------------------------------


class TestCircularDependency:
    def test_no_infinite_loop_with_shared_parent_key(self):
        """Build a trace where two spans share the same parent — no crash expected."""
        root = _span("root", SpanKind.AGENT, SpanStatus.ERROR, offset=0.0)
        c1 = _span("c1", SpanKind.TOOL, SpanStatus.ERROR, parent=root, offset=0.1)
        c2 = _span("c2", SpanKind.TOOL, SpanStatus.ERROR, parent=root, offset=0.2)

        trace = _trace_with_spans(root, c1, c2)
        dag = build_causal_dag(trace)  # must not raise / loop

        assert len(dag.nodes) == 3

    def test_critical_path_does_not_infinite_loop(self):
        root = _span("root", SpanKind.AGENT, SpanStatus.ERROR, offset=0.0)
        c1 = _span("c1", SpanKind.LLM, SpanStatus.ERROR, parent=root, offset=0.1)
        c2 = _span("c2", SpanKind.TOOL, SpanStatus.ERROR, parent=c1, offset=0.2)

        trace = _trace_with_spans(root, c1, c2)
        dag = build_causal_dag(trace)

        path = calculate_critical_path(dag)
        assert isinstance(path, list)
        # Path must not be empty and should start from a root cause
        assert len(path) >= 1

    def test_get_error_propagation_chain_terminates(self):
        root = _span("root", SpanKind.AGENT, SpanStatus.ERROR, offset=0.0)
        c1 = _span("c1", SpanKind.LLM, SpanStatus.ERROR, parent=root, offset=0.1)
        c2 = _span("c2", SpanKind.TOOL, SpanStatus.ERROR, parent=c1, offset=0.2)

        trace = _trace_with_spans(root, c1, c2)
        dag = build_causal_dag(trace)

        chain = get_error_propagation_chain(dag, root.span_id)
        assert isinstance(chain, list)
        assert root.span_id in chain


# ---------------------------------------------------------------------------
# Root cause identification
# ---------------------------------------------------------------------------


class TestRootCauseIdentification:
    def test_multiple_independent_root_causes(self):
        # Two separate error subtrees without shared ancestry
        r1 = _span("r1", SpanKind.TOOL, SpanStatus.ERROR, offset=0.0)
        r2 = _span("r2", SpanKind.TOOL, SpanStatus.ERROR, offset=1.0)

        trace = _trace_with_spans(r1, r2)
        dag = build_causal_dag(trace)

        # r1 comes first — it is a root cause; r2 is also a root cause if r1 does not precede it in same parent
        # Both are at root level (no parent) so both are root causes or r2 is cascaded by r1
        # (r2 has r1 as error predecessor in the __root__ sibling group)
        # Actually r1 precedes r2 so r2 is "preceded_by" an error sibling → cascaded
        assert r1.span_id in dag.root_causes

    def test_ok_spans_are_not_root_causes(self):
        ok_span = _span("ok", SpanKind.TOOL, SpanStatus.OK, offset=0.0)
        err_span = _span("err", SpanKind.LLM, SpanStatus.ERROR, offset=0.1)

        trace = _trace_with_spans(ok_span, err_span)
        dag = build_causal_dag(trace)

        node_map = {n.span_id: n for n in dag.nodes}
        assert node_map[ok_span.span_id].error_role == ErrorRole.INDEPENDENT
        assert node_map[err_span.span_id].error_role in (ErrorRole.ROOT_CAUSE, ErrorRole.CASCADED)

    def test_root_cause_node_has_correct_role(self):
        err = _span("err", SpanKind.TOOL, SpanStatus.ERROR, offset=0.0)
        trace = _trace_with_spans(err)
        dag = build_causal_dag(trace)

        assert len(dag.root_causes) == 1
        node = dag.nodes[0]
        assert node.error_role == ErrorRole.ROOT_CAUSE

    def test_cascade_depth_reflects_chain(self):
        root = _span("root", SpanKind.AGENT, SpanStatus.ERROR, offset=0.0)
        c1 = _span("c1", SpanKind.LLM, SpanStatus.ERROR, parent=root, offset=0.1)
        c2 = _span("c2", SpanKind.TOOL, SpanStatus.ERROR, parent=c1, offset=0.2)

        trace = _trace_with_spans(root, c1, c2)
        dag = build_causal_dag(trace)

        # cascade_depth should reflect the caused_by chain depth
        assert dag.cascade_depth >= 1

    def test_no_edges_when_no_errors(self):
        a = _span("a", SpanKind.AGENT, SpanStatus.OK, offset=0.0)
        b = _span("b", SpanKind.LLM, SpanStatus.OK, parent=a, offset=0.1)
        trace = _trace_with_spans(a, b)
        dag = build_causal_dag(trace)

        assert dag.edges == []

    def test_dag_summary_stats_keys(self):
        root = _span("root", SpanKind.AGENT, SpanStatus.ERROR, offset=0.0)
        trace = _trace_with_spans(root)
        dag = build_causal_dag(trace)

        stats = dag.summary_stats()
        for key in (
            "total_nodes",
            "total_errors",
            "root_cause_count",
            "cascade_depth",
            "patterns_found",
        ):
            assert key in stats

    def test_dag_to_dict_round_trip(self):
        root = _span("root", SpanKind.AGENT, SpanStatus.ERROR, offset=0.0)
        trace = _trace_with_spans(root)
        dag = build_causal_dag(trace)

        d = dag.to_dict()
        assert d["trace_id"] == dag.trace_id
        assert "nodes" in d
        assert "edges" in d
        assert "root_causes" in d
        assert d["has_errors"] is True
