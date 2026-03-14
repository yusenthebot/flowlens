"""Tests for Causal DAG builder and pattern detection."""
from flowlens.sdk.models import Span, SpanKind, SpanStatus, Trace
from flowlens.analysis.dag_builder import build_causal_dag
from flowlens.analysis.models import ErrorRole, PatternType
from flowlens.analysis.patterns import detect_patterns


def _make_trace(*spans: Span) -> Trace:
    trace = Trace(trace_id="test-trace-001", service_name="test")
    for s in spans:
        s.trace_id = trace.trace_id
    trace.spans = list(spans)
    return trace


class TestDAGBuilder:
    def test_no_errors_empty_dag(self):
        s1 = Span(span_id="s1", name="a", kind=SpanKind.TOOL)
        s1.finish()
        s2 = Span(span_id="s2", name="b", kind=SpanKind.TOOL, parent_span_id="s1")
        s2.finish()
        trace = _make_trace(s1, s2)

        dag = build_causal_dag(trace)
        assert not dag.has_errors
        assert dag.root_causes == []
        assert dag.edges == []

    def test_single_error_is_root_cause(self):
        s1 = Span(span_id="s1", name="agent", kind=SpanKind.AGENT)
        s1.finish()
        s2 = Span(span_id="s2", name="search", kind=SpanKind.TOOL, parent_span_id="s1")
        s2.finish(error="timeout")
        trace = _make_trace(s1, s2)

        dag = build_causal_dag(trace)
        assert dag.has_errors
        assert "s2" in dag.root_causes
        node_map = {n.span_id: n for n in dag.nodes}
        assert node_map["s2"].error_role == ErrorRole.ROOT_CAUSE

    def test_cascaded_error(self):
        """parent error → child error = cascade"""
        s1 = Span(span_id="s1", name="agent", kind=SpanKind.AGENT, start_time=1.0)
        s1.finish(error="child failed")
        s1.end_time = 3.0

        s2 = Span(
            span_id="s2", name="search", kind=SpanKind.TOOL,
            parent_span_id="s1", start_time=1.1,
        )
        s2.finish(error="timeout")
        s2.end_time = 2.0

        s3 = Span(
            span_id="s3", name="fetch", kind=SpanKind.TOOL,
            parent_span_id="s1", start_time=2.1,
        )
        s3.finish(error="no input from search")
        s3.end_time = 2.5

        trace = _make_trace(s1, s2, s3)
        dag = build_causal_dag(trace)

        # s1 has no error parent → root cause
        assert "s1" in dag.root_causes
        node_map = {n.span_id: n for n in dag.nodes}
        # s2 and s3 are children of error parent s1 → cascaded
        assert node_map["s2"].error_role == ErrorRole.CASCADED
        assert node_map["s3"].error_role == ErrorRole.CASCADED
        # caused_by edges from s1 → s2 and s1 → s3
        edge_pairs = [(e.source_id, e.target_id) for e in dag.edges]
        assert ("s1", "s2") in edge_pairs
        assert ("s1", "s3") in edge_pairs

    def test_cascade_depth(self):
        s1 = Span(span_id="s1", name="a", kind=SpanKind.AGENT, start_time=1.0)
        s1.finish(error="e")

        s2 = Span(span_id="s2", name="b", kind=SpanKind.TOOL, parent_span_id="s1", start_time=1.1)
        s2.finish(error="e")

        s3 = Span(span_id="s3", name="c", kind=SpanKind.TOOL, parent_span_id="s2", start_time=1.2)
        s3.finish(error="e")

        trace = _make_trace(s1, s2, s3)
        dag = build_causal_dag(trace)
        # s1 is root, s2 cascaded from s1, s3 cascaded from s2
        assert dag.cascade_depth >= 1

    def test_empty_trace(self):
        trace = Trace(trace_id="empty")
        dag = build_causal_dag(trace)
        assert not dag.has_errors
        assert dag.nodes == []


class TestPatternDetection:
    def test_detect_retry_storm(self):
        """同名 tool 调用 >= 5 次 = retry_storm"""
        spans = []
        for i in range(6):
            s = Span(
                span_id=f"s{i}", name="flaky_api",
                kind=SpanKind.TOOL, start_time=float(i),
            )
            s.finish(error="timeout" if i < 5 else None)
            spans.append(s)

        trace = _make_trace(*spans)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)

        retry_patterns = [p for p in patterns if p.pattern_type == PatternType.RETRY_STORM]
        assert len(retry_patterns) == 1
        assert retry_patterns[0].details["call_count"] == 6

    def test_detect_infinite_loop(self):
        """A → B → A → B → A → B = loop of [A,B] x3"""
        names = ["tool_a", "tool_b"] * 3
        spans = []
        for i, name in enumerate(names):
            s = Span(
                span_id=f"s{i}", name=name,
                kind=SpanKind.TOOL, start_time=float(i),
            )
            s.finish()
            spans.append(s)

        trace = _make_trace(*spans)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)

        loop_patterns = [p for p in patterns if p.pattern_type == PatternType.INFINITE_LOOP]
        assert len(loop_patterns) == 1
        assert loop_patterns[0].details["cycle"] == ["tool_a", "tool_b"]

    def test_detect_context_overflow(self):
        """Token usage > 90% of context limit"""
        s = Span(
            span_id="s1", name="big_llm",
            kind=SpanKind.LLM,
            attributes={"gen_ai.request.model": "claude-sonnet-4-20250514"},
        )
        s.set_token_usage(input_tokens=180_000, output_tokens=5_000, model="claude-sonnet-4-20250514")
        s.finish()

        trace = _make_trace(s)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)

        overflow = [p for p in patterns if p.pattern_type == PatternType.CONTEXT_OVERFLOW]
        assert len(overflow) == 1
        assert overflow[0].details["usage_ratio"] > 0.9

    def test_detect_empty_response(self):
        s = Span(span_id="s1", name="llm", kind=SpanKind.LLM)
        s.set_token_usage(input_tokens=1000, output_tokens=0, model="")
        s.finish()

        trace = _make_trace(s)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)

        empty = [p for p in patterns if p.pattern_type == PatternType.EMPTY_RESPONSE]
        assert len(empty) == 1

    def test_no_patterns_on_clean_trace(self):
        s1 = Span(span_id="s1", name="tool", kind=SpanKind.TOOL)
        s1.finish()
        s2 = Span(span_id="s2", name="llm", kind=SpanKind.LLM)
        s2.set_token_usage(100, 50, "")
        s2.finish()

        trace = _make_trace(s1, s2)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)
        assert len(patterns) == 0
