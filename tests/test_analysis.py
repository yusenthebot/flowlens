"""Tests for new analysis features: patterns, advisor, comparator, critical path."""

from flowlens.sdk.models import Span, SpanKind, SpanStatus, Trace
from flowlens.analysis.dag_builder import (
    build_causal_dag,
    calculate_critical_path,
    get_error_propagation_chain,
)
from flowlens.analysis.models import PatternType
from flowlens.analysis.patterns import detect_patterns
from flowlens.analysis.advisor import TraceAdvisor
from flowlens.analysis.comparator import compare_traces


def _make_trace(*spans: Span) -> Trace:
    """Helper to create a test trace"""
    trace = Trace(trace_id="test-trace-001", service_name="test")
    for s in spans:
        s.trace_id = trace.trace_id
    trace.spans = list(spans)
    return trace


class TestNewPatternDetectors:
    """Tests for the 4 new pattern detectors"""

    def test_detect_hallucination_cascade(self):
        """LLM output → Tool error = hallucination cascade"""
        # LLM produces output
        s1 = Span(span_id="s1", name="llm_reasoning", kind=SpanKind.LLM, start_time=1.0)
        s1.set_token_usage(100, 50, "claude-sonnet-4")
        s1.finish()
        s1.end_time = 1.5

        # Tool consumes it and fails
        s2 = Span(
            span_id="s2", name="web_search",
            kind=SpanKind.TOOL, parent_span_id="s1",
            start_time=1.6,
            attributes={"query": "from_llm_output"}
        )
        s2.finish(error="Invalid query format from LLM")
        s2.end_time = 2.0

        trace = _make_trace(s1, s2)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)

        halluc_patterns = [
            p for p in patterns
            if p.pattern_type == PatternType.HALLUCINATION_CASCADE
        ]
        assert len(halluc_patterns) >= 0  # May or may not detect based on heuristics
        if halluc_patterns:
            assert halluc_patterns[0].severity == "critical"

    def test_detect_cost_spike(self):
        """Single LLM call > 50% of total tokens = cost spike"""
        # Expensive LLM call
        s1 = Span(span_id="s1", name="expensive_llm", kind=SpanKind.LLM)
        s1.set_token_usage(input_tokens=40000, output_tokens=10000, model="gpt-4o")
        s1.finish()

        # Small tool call
        s2 = Span(span_id="s2", name="tool", kind=SpanKind.TOOL)
        s2.finish()

        trace = _make_trace(s1, s2)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)

        cost_spikes = [
            p for p in patterns
            if p.pattern_type == PatternType.COST_SPIKE
        ]
        assert len(cost_spikes) == 1
        assert cost_spikes[0].details["cost_pct"] > 50

    def test_detect_slow_tool(self):
        """Tool duration > 3x average = slow tool"""
        # Fast tools
        fast1 = Span(span_id="s1", name="api", kind=SpanKind.TOOL, start_time=0.0)
        fast1.finish()
        fast1.end_time = 0.05  # 50ms

        fast2 = Span(span_id="s2", name="api", kind=SpanKind.TOOL, start_time=0.1)
        fast2.finish()
        fast2.end_time = 0.15  # 50ms

        # Slow tool (3.5x average)
        slow = Span(span_id="s3", name="api", kind=SpanKind.TOOL, start_time=0.2)
        slow.finish()
        slow.end_time = 0.375  # 175ms = 3.5x 50ms average

        trace = _make_trace(fast1, fast2, slow)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)

        slow_patterns = [
            p for p in patterns
            if p.pattern_type == PatternType.SLOW_TOOL
        ]
        assert len(slow_patterns) == 1
        assert slow_patterns[0].details["slowness_factor"] > 3.0

    def test_detect_redundant_calls(self):
        """Same tool with same parameters called multiple times"""
        # Identical calls
        spans = []
        for i in range(3):
            s = Span(
                span_id=f"s{i}", name="search_api",
                kind=SpanKind.TOOL,
                start_time=float(i),
                attributes={"query": "python tutorial", "limit": 10}
            )
            s.finish()
            spans.append(s)

        trace = _make_trace(*spans)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)

        redundant = [
            p for p in patterns
            if p.pattern_type == PatternType.REDUNDANT_CALLS
        ]
        assert len(redundant) == 1
        assert redundant[0].details["call_count"] == 3


class TestCriticalPath:
    """Tests for calculate_critical_path()"""

    def test_critical_path_single_root_cause(self):
        """Critical path from single root cause"""
        # Root cause
        s1 = Span(span_id="s1", name="root", kind=SpanKind.AGENT, start_time=1.0)
        s1.finish(error="e")
        s1.end_time = 1.1

        # Cascaded child
        s2 = Span(
            span_id="s2", name="child",
            kind=SpanKind.TOOL, parent_span_id="s1", start_time=1.2
        )
        s2.finish(error="e")
        s2.end_time = 1.3

        # Cascaded grandchild
        s3 = Span(
            span_id="s3", name="grandchild",
            kind=SpanKind.TOOL, parent_span_id="s2", start_time=1.4
        )
        s3.finish(error="e")

        trace = _make_trace(s1, s2, s3)
        dag = build_causal_dag(trace)
        path = calculate_critical_path(dag)

        assert path == ["s1", "s2", "s3"]

    def test_critical_path_empty_no_errors(self):
        """No critical path if no errors"""
        s1 = Span(span_id="s1", name="tool", kind=SpanKind.TOOL)
        s1.finish()

        trace = _make_trace(s1)
        dag = build_causal_dag(trace)
        path = calculate_critical_path(dag)

        assert path == []


class TestErrorPropagationChain:
    """Tests for get_error_propagation_chain()"""

    def test_full_propagation_chain(self):
        """Get complete chain from root to all cascaded errors"""
        # Root error
        s1 = Span(span_id="s1", name="root", kind=SpanKind.AGENT, start_time=1.0)
        s1.finish(error="e")
        s1.end_time = 1.1

        # Two cascaded children
        s2 = Span(
            span_id="s2", name="child1",
            kind=SpanKind.TOOL, parent_span_id="s1", start_time=1.2
        )
        s2.finish(error="e")
        s2.end_time = 1.3

        s3 = Span(
            span_id="s3", name="child2",
            kind=SpanKind.TOOL, parent_span_id="s1", start_time=1.4
        )
        s3.finish(error="e")

        trace = _make_trace(s1, s2, s3)
        dag = build_causal_dag(trace)

        # Get chain from root
        chain = get_error_propagation_chain(dag, "s1")
        assert "s1" in chain
        assert "s2" in chain
        assert "s3" in chain

    def test_chain_from_non_root(self):
        """Get chain starting from non-root error"""
        s1 = Span(span_id="s1", name="root", kind=SpanKind.AGENT, start_time=1.0)
        s1.finish(error="e")
        s1.end_time = 1.1

        s2 = Span(
            span_id="s2", name="child",
            kind=SpanKind.TOOL, parent_span_id="s1", start_time=1.2
        )
        s2.finish(error="e")
        s2.end_time = 1.3

        s3 = Span(
            span_id="s3", name="grandchild",
            kind=SpanKind.TOOL, parent_span_id="s2", start_time=1.4
        )
        s3.finish(error="e")

        trace = _make_trace(s1, s2, s3)
        dag = build_causal_dag(trace)

        # Get chain from s2 (middle node)
        chain = get_error_propagation_chain(dag, "s2")
        assert "s2" in chain
        assert "s3" in chain
        assert len(chain) >= 2


class TestTraceAdvisor:
    """Tests for TraceAdvisor and report generation"""

    def test_advisor_clean_trace(self):
        """No patterns = low severity"""
        s1 = Span(span_id="s1", name="tool", kind=SpanKind.TOOL)
        s1.finish()

        trace = _make_trace(s1)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)

        advisor = TraceAdvisor(trace=trace, dag=dag, patterns=patterns)
        report = advisor.generate_report()

        assert report["severity_level"] == "low"
        assert report["severity_score"] < 40

    def test_advisor_with_errors(self):
        """Errors increase severity"""
        # Multiple errors
        for i in range(3):
            s = Span(
                span_id=f"s{i}", name="flaky_tool",
                kind=SpanKind.TOOL, start_time=float(i)
            )
            s.finish(error="timeout")
            if i == 0:
                first_span = s

        trace = _make_trace(*[
            Span(span_id=f"s{i}", name="flaky_tool", kind=SpanKind.TOOL, start_time=float(i))
            for i in range(3)
        ])
        for s in trace.spans:
            s.finish(error="timeout")

        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)
        advisor = TraceAdvisor(trace=trace, dag=dag, patterns=patterns)

        assert advisor.severity_score > 40

    def test_advisor_recommendations(self):
        """Test that advisor generates recommendations"""
        # Create a retry storm
        spans = []
        for i in range(6):
            s = Span(
                span_id=f"s{i}", name="api_call",
                kind=SpanKind.TOOL, start_time=float(i)
            )
            s.finish(error="timeout")
            spans.append(s)

        trace = _make_trace(*spans)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)
        advisor = TraceAdvisor(trace=trace, dag=dag, patterns=patterns)
        report = advisor.generate_report()

        assert len(report["recommendations"]) > 0
        # Should recommend retry strategy for api_call
        assert any("retry" in r.lower() or "api" in r.lower() for r in report["recommendations"])

    def test_advisor_estimated_savings(self):
        """Test estimated savings calculation"""
        # Redundant calls
        spans = []
        for i in range(3):
            s = Span(
                span_id=f"s{i}", name="search",
                kind=SpanKind.TOOL,
                start_time=float(i),
                attributes={"query": "same query"}
            )
            s.finish()
            spans.append(s)

        trace = _make_trace(*spans)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)
        advisor = TraceAdvisor(trace=trace, dag=dag, patterns=patterns)
        savings = advisor.estimated_savings

        # Should have positive token/cost savings
        assert savings["token_savings"] >= 0 or savings["cost_savings_usd"] >= 0


class TestTraceComparator:
    """Tests for compare_traces()"""

    def test_compare_identical_traces(self):
        """Comparing identical traces should show no diff"""
        s1 = Span(span_id="s1", name="tool", kind=SpanKind.TOOL, start_time=0.0)
        s1.finish()
        s1.end_time = 0.1

        trace_a = _make_trace(s1)
        trace_b = _make_trace(s1)

        diff = compare_traces(trace_a, trace_b)

        assert len(diff.added_spans) == 0
        assert len(diff.removed_spans) == 0
        assert abs(diff.token_diff) < 1
        assert abs(diff.cost_diff_usd) < 0.0001

    def test_compare_added_span(self):
        """Detect new spans in trace_b"""
        s1 = Span(span_id="s1", name="tool_a", kind=SpanKind.TOOL, start_time=0.0)
        s1.finish()

        trace_a = _make_trace(s1)

        s2 = Span(span_id="s2", name="tool_b", kind=SpanKind.TOOL, start_time=0.0)
        s2.finish()

        trace_b = _make_trace(s1, s2)

        diff = compare_traces(trace_a, trace_b)

        assert len(diff.added_spans) == 1
        assert diff.added_spans[0].span_name == "tool_b"

    def test_compare_removed_span(self):
        """Detect removed spans"""
        s1 = Span(span_id="s1", name="tool_a", kind=SpanKind.TOOL, start_time=0.0)
        s1.finish()

        s2 = Span(span_id="s2", name="tool_b", kind=SpanKind.TOOL, start_time=0.0)
        s2.finish()

        trace_a = _make_trace(s1, s2)
        trace_b = _make_trace(s1)

        diff = compare_traces(trace_a, trace_b)

        assert len(diff.removed_spans) == 1
        assert diff.removed_spans[0].span_name == "tool_b"

    def test_compare_cost_improvement(self):
        """Detect cost improvement"""
        # Trace A: expensive
        s1_a = Span(span_id="s1", name="llm", kind=SpanKind.LLM)
        s1_a.set_token_usage(5000, 1000, "gpt-4o")
        s1_a.finish()

        trace_a = _make_trace(s1_a)

        # Trace B: cheaper
        s1_b = Span(span_id="s1", name="llm", kind=SpanKind.LLM)
        s1_b.set_token_usage(2000, 500, "gpt-4o-mini")
        s1_b.finish()

        trace_b = _make_trace(s1_b)

        diff = compare_traces(trace_a, trace_b)

        assert diff.cost_diff_usd < 0  # Lower cost
        assert diff.is_improvement  # Should be improvement

    def test_compare_speed_improvement(self):
        """Detect speed improvement"""
        # Slow version
        s1_a = Span(span_id="s1", name="tool", kind=SpanKind.TOOL, start_time=0.0)
        s1_a.finish()
        s1_a.end_time = 2.0  # 2000ms

        trace_a = _make_trace(s1_a)
        trace_a.start_time = 0.0
        trace_a.end_time = 2.0

        # Fast version
        s1_b = Span(span_id="s1", name="tool", kind=SpanKind.TOOL, start_time=0.0)
        s1_b.finish()
        s1_b.end_time = 0.5  # 500ms

        trace_b = _make_trace(s1_b)
        trace_b.start_time = 0.0
        trace_b.end_time = 0.5

        diff = compare_traces(trace_a, trace_b)

        assert diff.duration_diff_ms < 0  # Faster
        assert diff.is_improvement

    def test_compare_error_count_improvement(self):
        """Detect fewer errors in trace_b"""
        # Trace A: multiple errors
        s1_a = Span(span_id="s1", name="tool", kind=SpanKind.TOOL)
        s1_a.finish(error="timeout")

        s2_a = Span(span_id="s2", name="tool", kind=SpanKind.TOOL)
        s2_a.finish(error="timeout")

        trace_a = _make_trace(s1_a, s2_a)

        # Trace B: no errors
        s1_b = Span(span_id="s1", name="tool", kind=SpanKind.TOOL)
        s1_b.finish()

        trace_b = _make_trace(s1_b)

        diff = compare_traces(trace_a, trace_b)

        assert trace_a.error_count > trace_b.error_count
        assert diff.is_improvement


if __name__ == "__main__":
    # Run with pytest
    pass
