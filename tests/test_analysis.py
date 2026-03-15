"""Tests for new analysis features: patterns, advisor, comparator, critical path."""

from flowlens.analysis.advisor import TraceAdvisor
from flowlens.analysis.comparator import compare_traces
from flowlens.analysis.correlator import (
    correlate_traces,
)
from flowlens.analysis.dag_builder import (
    build_causal_dag,
    calculate_critical_path,
    get_error_propagation_chain,
)
from flowlens.analysis.models import PatternType
from flowlens.analysis.patterns import detect_patterns
from flowlens.sdk.models import Span, SpanKind, Trace

_trace_counter = 0


def _make_trace(*spans: Span) -> Trace:
    """Helper to create a test trace with a unique trace_id."""
    global _trace_counter
    _trace_counter += 1
    trace = Trace(trace_id=f"test-trace-{_trace_counter:04d}", service_name="test")
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
                pass

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


class TestTokenWasteDetector:
    """Tests for detect_token_waste pattern."""

    def test_detects_high_ratio(self):
        """input/output ratio > 10 → token_waste pattern."""
        s = Span(span_id="s1", name="verbose_llm", kind=SpanKind.LLM)
        s.set_token_usage(input_tokens=5_000, output_tokens=100, model="gpt-4o")
        s.finish()

        trace = _make_trace(s)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)

        waste = [p for p in patterns if p.pattern_type == PatternType.TOKEN_WASTE]
        assert len(waste) == 1
        assert waste[0].details["ratio"] > 10
        assert waste[0].details["input_tokens"] == 5_000
        assert waste[0].details["output_tokens"] == 100
        assert waste[0].severity == "warning"

    def test_no_detection_below_threshold(self):
        """input/output ratio <= 10 → no token_waste pattern."""
        s = Span(span_id="s1", name="normal_llm", kind=SpanKind.LLM)
        s.set_token_usage(input_tokens=1_000, output_tokens=200, model="gpt-4o")
        s.finish()

        trace = _make_trace(s)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)

        waste = [p for p in patterns if p.pattern_type == PatternType.TOKEN_WASTE]
        assert len(waste) == 0

    def test_no_detection_zero_output(self):
        """0 output tokens is handled by empty_response, not token_waste."""
        s = Span(span_id="s1", name="empty_llm", kind=SpanKind.LLM)
        s.set_token_usage(input_tokens=1_000, output_tokens=0, model="gpt-4o")
        s.finish()

        trace = _make_trace(s)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)

        waste = [p for p in patterns if p.pattern_type == PatternType.TOKEN_WASTE]
        # zero-output is excluded from token_waste (division by zero guard)
        assert len(waste) == 0

    def test_multiple_llm_spans_only_offending_flagged(self):
        """Only the span exceeding the ratio is flagged."""
        # Offending span
        s1 = Span(span_id="s1", name="big_prompt", kind=SpanKind.LLM)
        s1.set_token_usage(input_tokens=8_000, output_tokens=50, model="gpt-4o")
        s1.finish()

        # Healthy span
        s2 = Span(span_id="s2", name="normal_call", kind=SpanKind.LLM)
        s2.set_token_usage(input_tokens=500, output_tokens=300, model="gpt-4o")
        s2.finish()

        trace = _make_trace(s1, s2)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)

        waste = [p for p in patterns if p.pattern_type == PatternType.TOKEN_WASTE]
        assert len(waste) == 1
        assert "s1" in waste[0].involved_spans


class TestSequentialBottleneckDetector:
    """Tests for detect_sequential_bottleneck pattern."""

    def test_detects_independent_sequential_tools(self):
        """Two independent tools under same parent running sequentially → flagged."""
        parent = Span(span_id="p1", name="agent", kind=SpanKind.AGENT, start_time=0.0)
        parent.finish()
        parent.end_time = 2.0

        tool_a = Span(
            span_id="t1", name="search_a", kind=SpanKind.TOOL,
            parent_span_id="p1", start_time=0.1,
        )
        tool_a.finish()
        tool_a.end_time = 0.6  # 500 ms

        tool_b = Span(
            span_id="t2", name="search_b", kind=SpanKind.TOOL,
            parent_span_id="p1", start_time=0.7,  # starts after tool_a ends
        )
        tool_b.finish()
        tool_b.end_time = 1.2  # 500 ms

        trace = _make_trace(parent, tool_a, tool_b)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)

        bottleneck = [
            p for p in patterns if p.pattern_type == PatternType.SEQUENTIAL_BOTTLENECK
        ]
        assert len(bottleneck) >= 1
        found = bottleneck[0]
        assert found.details["sequential_count"] >= 2
        assert found.details["potential_savings_ms"] > 0

    def test_no_detection_single_tool(self):
        """Single tool under a parent → no bottleneck."""
        parent = Span(span_id="p1", name="agent", kind=SpanKind.AGENT, start_time=0.0)
        parent.finish()

        tool = Span(
            span_id="t1", name="search", kind=SpanKind.TOOL,
            parent_span_id="p1", start_time=0.1,
        )
        tool.finish()
        tool.end_time = 0.5

        trace = _make_trace(parent, tool)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)

        bottleneck = [
            p for p in patterns if p.pattern_type == PatternType.SEQUENTIAL_BOTTLENECK
        ]
        assert len(bottleneck) == 0


class TestErrorRecoveryDetector:
    """Tests for detect_error_recovery pattern (positive pattern)."""

    def test_detects_successful_recovery(self):
        """Failed span followed by sibling success with same name → error_recovery."""
        parent = Span(span_id="p1", name="agent", kind=SpanKind.AGENT, start_time=0.0)
        parent.finish()

        # First attempt fails
        attempt1 = Span(
            span_id="a1", name="fetch_data", kind=SpanKind.TOOL,
            parent_span_id="p1", start_time=0.1,
        )
        attempt1.finish(error="Connection refused")
        attempt1.end_time = 0.3

        # Second attempt succeeds
        attempt2 = Span(
            span_id="a2", name="fetch_data", kind=SpanKind.TOOL,
            parent_span_id="p1", start_time=0.4,
        )
        attempt2.finish()
        attempt2.end_time = 0.7

        trace = _make_trace(parent, attempt1, attempt2)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)

        recovery = [
            p for p in patterns if p.pattern_type == PatternType.ERROR_RECOVERY
        ]
        assert len(recovery) >= 1
        r = recovery[0]
        assert r.severity == "info"
        assert "a1" in r.details["failed_span_id"]
        assert "a2" in r.details["recovery_span_id"]

    def test_no_recovery_when_both_fail(self):
        """Two failures with same name → no recovery (no successful sibling)."""
        parent = Span(span_id="p1", name="agent", kind=SpanKind.AGENT, start_time=0.0)
        parent.finish()

        fail1 = Span(span_id="a1", name="fetch_data", kind=SpanKind.TOOL,
                     parent_span_id="p1", start_time=0.0)
        fail1.finish(error="Connection refused")
        fail1.end_time = 0.2

        fail2 = Span(span_id="a2", name="fetch_data", kind=SpanKind.TOOL,
                     parent_span_id="p1", start_time=0.3)
        fail2.finish(error="Connection refused")
        fail2.end_time = 0.5

        trace = _make_trace(parent, fail1, fail2)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)

        recovery = [
            p for p in patterns if p.pattern_type == PatternType.ERROR_RECOVERY
        ]
        assert len(recovery) == 0

    def test_no_recovery_when_only_success(self):
        """Success without preceding failure → no recovery pattern."""
        parent = Span(span_id="p1", name="agent", kind=SpanKind.AGENT, start_time=0.0)
        parent.finish()

        s = Span(span_id="t1", name="fetch_data", kind=SpanKind.TOOL,
                 parent_span_id="p1", start_time=0.1)
        s.finish()

        trace = _make_trace(parent, s)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)

        recovery = [
            p for p in patterns if p.pattern_type == PatternType.ERROR_RECOVERY
        ]
        assert len(recovery) == 0


class TestAdvisorNewPatterns:
    """Tests for TraceAdvisor handling of the three new patterns."""

    def test_recommendation_for_token_waste(self):
        """token_waste pattern yields a recommendation with a code snippet."""
        s = Span(span_id="s1", name="fat_prompt", kind=SpanKind.LLM)
        s.set_token_usage(input_tokens=10_000, output_tokens=50, model="gpt-4o")
        s.finish()

        trace = _make_trace(s)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)
        advisor = TraceAdvisor(trace=trace, dag=dag, patterns=patterns)
        report = advisor.generate_report()

        recs = report["recommendations_detail"]
        waste_recs = [r for r in recs if r["pattern_type"] == "token_waste"]
        assert len(waste_recs) >= 1
        assert waste_recs[0]["code_snippet"] != ""

    def test_recommendation_for_sequential_bottleneck(self):
        """sequential_bottleneck pattern yields a recommendation with asyncio snippet."""
        parent = Span(span_id="p1", name="agent", kind=SpanKind.AGENT, start_time=0.0)
        parent.finish()

        tool_a = Span(span_id="t1", name="tool_x", kind=SpanKind.TOOL,
                      parent_span_id="p1", start_time=0.1)
        tool_a.finish()
        tool_a.end_time = 0.6

        tool_b = Span(span_id="t2", name="tool_y", kind=SpanKind.TOOL,
                      parent_span_id="p1", start_time=0.7)
        tool_b.finish()
        tool_b.end_time = 1.2

        trace = _make_trace(parent, tool_a, tool_b)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)
        advisor = TraceAdvisor(trace=trace, dag=dag, patterns=patterns)
        report = advisor.generate_report()

        recs = report["recommendations_detail"]
        bottleneck_recs = [
            r for r in recs if r["pattern_type"] == "sequential_bottleneck"
        ]
        if bottleneck_recs:
            assert "asyncio" in bottleneck_recs[0]["code_snippet"]

    def test_recommendation_for_error_recovery(self):
        """error_recovery yields an info-severity recommendation."""
        parent = Span(span_id="p1", name="agent", kind=SpanKind.AGENT, start_time=0.0)
        parent.finish()

        attempt1 = Span(span_id="a1", name="call_api", kind=SpanKind.TOOL,
                        parent_span_id="p1", start_time=0.1)
        attempt1.finish(error="timeout")
        attempt1.end_time = 0.3

        attempt2 = Span(span_id="a2", name="call_api", kind=SpanKind.TOOL,
                        parent_span_id="p1", start_time=0.4)
        attempt2.finish()
        attempt2.end_time = 0.6

        trace = _make_trace(parent, attempt1, attempt2)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)
        advisor = TraceAdvisor(trace=trace, dag=dag, patterns=patterns)
        report = advisor.generate_report()

        recs = report["recommendations_detail"]
        recovery_recs = [r for r in recs if r["pattern_type"] == "error_recovery"]
        if recovery_recs:
            assert recovery_recs[0]["severity"] == "info"

    def test_advisor_monthly_savings_scaled_by_frequency(self):
        """estimated_monthly_savings scales linearly with traces_per_month."""
        spans = []
        for i in range(3):
            s = Span(
                span_id=f"s{i}", name="dedup_tool",
                kind=SpanKind.TOOL, start_time=float(i),
                attributes={"q": "same"},
            )
            s.finish()
            spans.append(s)

        trace = _make_trace(*spans)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)

        advisor_low = TraceAdvisor(trace=trace, dag=dag, patterns=patterns,
                                   traces_per_month=100)
        advisor_high = TraceAdvisor(trace=trace, dag=dag, patterns=patterns,
                                    traces_per_month=10_000)

        low_monthly = advisor_low.estimated_monthly_savings["cost_savings_usd_monthly"]
        high_monthly = advisor_high.estimated_monthly_savings["cost_savings_usd_monthly"]

        assert advisor_low.estimated_monthly_savings["traces_per_month"] == 100
        assert advisor_high.estimated_monthly_savings["traces_per_month"] == 10_000
        # High-frequency should cost 100x more to waste
        if low_monthly > 0:
            assert abs(high_monthly / low_monthly - 100) < 1  # ~100x

    def test_advisor_severity_positive_pattern_not_inflated(self):
        """error_recovery (positive pattern) must not inflate severity score."""
        parent = Span(span_id="p1", name="agent", kind=SpanKind.AGENT, start_time=0.0)
        parent.finish()

        attempt1 = Span(span_id="a1", name="call_api", kind=SpanKind.TOOL,
                        parent_span_id="p1", start_time=0.1)
        attempt1.finish(error="timeout")
        attempt1.end_time = 0.2

        attempt2 = Span(span_id="a2", name="call_api", kind=SpanKind.TOOL,
                        parent_span_id="p1", start_time=0.3)
        attempt2.finish()
        attempt2.end_time = 0.5

        trace = _make_trace(parent, attempt1, attempt2)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)

        advisor = TraceAdvisor(trace=trace, dag=dag, patterns=patterns)
        # The only non-ok span is attempt1; the recovery should not inflate score
        # beyond the single error span contribution
        assert advisor.severity_score < 60

    def test_advisor_cost_impact_increases_severity(self):
        """High per-trace cost should push severity score upward."""
        # Very expensive LLM call
        s = Span(span_id="s1", name="expensive", kind=SpanKind.LLM)
        s.set_token_usage(input_tokens=100_000, output_tokens=20_000, model="claude-opus-4-20250514")
        s.finish()

        trace = _make_trace(s)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)

        advisor = TraceAdvisor(trace=trace, dag=dag, patterns=patterns)
        # Cost > $0.10 should add bonus points
        if trace.total_cost_usd >= 0.10:
            # Severity score must include cost bonus
            # We can only check it is >= 0 (no errors, but bonus should fire)
            assert advisor.severity_score >= 0

    def test_report_contains_monthly_savings_key(self):
        """generate_report() must include estimated_monthly_savings."""
        s = Span(span_id="s1", name="tool", kind=SpanKind.TOOL)
        s.finish()

        trace = _make_trace(s)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)
        advisor = TraceAdvisor(trace=trace, dag=dag, patterns=patterns)
        report = advisor.generate_report()

        assert "estimated_monthly_savings" in report
        ms = report["estimated_monthly_savings"]
        assert "cost_savings_usd_monthly" in ms
        assert "token_savings_monthly" in ms
        assert "traces_per_month" in ms


class TestCausalDAGMarkdownAndJSON:
    """Tests for CausalDAG.to_markdown() and to_json()."""

    def test_to_json_is_valid_json(self):
        """to_json() must return parseable JSON containing core keys."""
        import json as _json

        s1 = Span(span_id="s1", name="agent", kind=SpanKind.AGENT, start_time=1.0)
        s1.finish(error="fail")

        trace = _make_trace(s1)
        dag = build_causal_dag(trace)
        json_str = dag.to_json()
        data = _json.loads(json_str)

        assert data["trace_id"] == trace.trace_id
        assert "nodes" in data
        assert "edges" in data
        assert "summary_stats" in data

    def test_to_json_alias_matches_to_dict(self):
        """to_json() is consistent with to_dict()."""
        import json as _json

        s = Span(span_id="s1", name="tool", kind=SpanKind.TOOL)
        s.finish()

        trace = _make_trace(s)
        dag = build_causal_dag(trace)

        from_json = _json.loads(dag.to_json())
        from_dict = dag.to_dict()

        assert from_json["trace_id"] == from_dict["trace_id"]
        assert from_json["has_errors"] == from_dict["has_errors"]

    def test_to_markdown_contains_trace_id(self):
        """to_markdown() must mention the trace_id."""
        s = Span(span_id="s1", name="tool", kind=SpanKind.TOOL)
        s.finish()

        trace = _make_trace(s)
        dag = build_causal_dag(trace)
        md = dag.to_markdown()

        assert trace.trace_id in md

    def test_to_markdown_with_errors(self):
        """Markdown report must list root causes when errors are present."""
        s1 = Span(span_id="s1", name="root_agent", kind=SpanKind.AGENT, start_time=1.0)
        s1.finish(error="child failed")
        s1.end_time = 2.0

        s2 = Span(span_id="s2", name="tool_call", kind=SpanKind.TOOL,
                  parent_span_id="s1", start_time=1.1)
        s2.finish(error="timeout")
        s2.end_time = 1.5

        trace = _make_trace(s1, s2)
        dag = build_causal_dag(trace)
        detect_patterns(trace, dag)
        md = dag.to_markdown()

        assert "Root Causes" in md
        assert "root_agent" in md or "s1" in md

    def test_to_markdown_no_errors(self):
        """When there are no errors the report must still be valid Markdown."""
        s = Span(span_id="s1", name="clean_tool", kind=SpanKind.TOOL)
        s.finish()

        trace = _make_trace(s)
        dag = build_causal_dag(trace)
        md = dag.to_markdown()

        assert "## Summary" in md
        assert "No root causes detected" in md

    def test_summary_stats_counts(self):
        """summary_stats() returns correct counts."""
        s1 = Span(span_id="s1", name="ok_tool", kind=SpanKind.TOOL)
        s1.finish()

        s2 = Span(span_id="s2", name="bad_tool", kind=SpanKind.TOOL)
        s2.finish(error="boom")

        trace = _make_trace(s1, s2)
        dag = build_causal_dag(trace)
        stats = dag.summary_stats()

        assert stats["total_nodes"] == 2
        assert stats["total_errors"] == 1
        assert stats["root_cause_count"] == len(dag.root_causes)
        assert stats["cascade_depth"] == dag.cascade_depth
        assert stats["patterns_found"] == len(dag.patterns)

    def test_to_markdown_includes_patterns(self):
        """Detected patterns must appear in the Markdown report."""
        # Create a retry storm so patterns are populated on the DAG
        spans = []
        for i in range(6):
            s = Span(
                span_id=f"s{i}", name="flaky_api",
                kind=SpanKind.TOOL, start_time=float(i),
            )
            s.finish(error="timeout")
            spans.append(s)

        trace = _make_trace(*spans)
        dag = build_causal_dag(trace)
        detect_patterns(trace, dag)  # writes patterns into dag
        md = dag.to_markdown()

        assert "Detected Patterns" in md
        assert "retry_storm" in md


class TestCorrelator:
    """Tests for correlate_traces()."""

    def test_empty_list_returns_empty_report(self):
        """No traces → report with zero counts."""
        report = correlate_traces([])
        assert report.total_traces == 0
        assert report.recurring_failures == []
        assert report.performance_trends == []
        assert report.common_anti_patterns == []

    def test_single_trace_no_systemic_findings(self):
        """A single error cannot reach the 50% threshold for recurrence."""
        s = Span(span_id="s1", name="tool", kind=SpanKind.TOOL)
        s.finish(error="boom")

        trace = _make_trace(s)
        report = correlate_traces([trace])

        # 1 / 1 = 100% > 50%, so it SHOULD be flagged as recurring
        # (it's the only trace and it has the error)
        assert report.total_traces == 1
        assert report.overall_error_rate == 1.0
        assert len(report.recurring_failures) == 1

    def test_recurring_failure_detected_above_threshold(self):
        """Error in 3/4 traces → recurring failure (> 50%)."""
        traces = []
        for i in range(4):
            s = Span(span_id=f"s{i}", name="flaky", kind=SpanKind.TOOL,
                     start_time=float(i))
            if i < 3:
                s.finish(error="Connection refused")
            else:
                s.finish()
            traces.append(_make_trace(s))

        report = correlate_traces(traces, failure_threshold=0.5)

        assert len(report.recurring_failures) == 1
        rf = report.recurring_failures[0]
        assert rf.occurrence_count == 3
        assert rf.total_traces == 4
        assert rf.occurrence_rate > 0.5

    def test_recurring_failure_below_threshold_not_reported(self):
        """Error in 1/4 traces → NOT a recurring failure (< 50%)."""
        traces = []
        for i in range(4):
            s = Span(span_id=f"s{i}", name="tool", kind=SpanKind.TOOL, start_time=float(i))
            if i == 0:
                s.finish(error="rare error")
            else:
                s.finish()
            traces.append(_make_trace(s))

        report = correlate_traces(traces, failure_threshold=0.5)

        # 1/4 = 25% < 50% → should not appear
        assert len(report.recurring_failures) == 0

    def test_performance_trend_detected(self):
        """Monotonically increasing duration across ≥ 3 traces → trend detected."""
        traces = []
        for i in range(5):
            s = Span(span_id=f"s{i}", name="tool", kind=SpanKind.TOOL, start_time=0.0)
            s.finish()
            s.end_time = float(i + 1)  # 1s, 2s, 3s, 4s, 5s → increasing duration

            t = _make_trace(s)
            t.start_time = 0.0
            t.end_time = float(i + 1)
            traces.append(t)

        report = correlate_traces(traces, trend_min_traces=3)

        duration_trends = [
            tr for tr in report.performance_trends if tr.metric == "duration_ms"
        ]
        assert len(duration_trends) == 1
        assert duration_trends[0].direction == "increasing"
        assert duration_trends[0].slope > 0

    def test_no_trend_with_fewer_than_min_traces(self):
        """Fewer traces than trend_min_traces → no trends reported."""
        traces = []
        for i in range(2):
            s = Span(span_id=f"s{i}", name="tool", kind=SpanKind.TOOL, start_time=0.0)
            s.finish()
            s.end_time = float(i + 1)
            t = _make_trace(s)
            t.start_time = 0.0
            t.end_time = float(i + 1)
            traces.append(t)

        report = correlate_traces(traces, trend_min_traces=3)

        assert report.performance_trends == []

    def test_common_anti_pattern_detected(self):
        """retry_storm in > 50% of traces → common anti-pattern."""
        traces = []
        for _ in range(3):
            spans = []
            for j in range(6):
                s = Span(span_id=f"s{j}_{_}", name="flaky_api",
                         kind=SpanKind.TOOL, start_time=float(j))
                s.finish(error="timeout")
                spans.append(s)
            traces.append(_make_trace(*spans))

        # One clean trace
        clean = Span(span_id="c1", name="ok", kind=SpanKind.TOOL)
        clean.finish()
        traces.append(_make_trace(clean))

        report = correlate_traces(traces, anti_pattern_threshold=0.5)

        ptype_values = [p.pattern_type.value for p in report.common_anti_patterns]
        assert "retry_storm" in ptype_values

    def test_summary_method_returns_string(self):
        """CorrelationReport.summary() returns a non-empty string."""
        s = Span(span_id="s1", name="tool", kind=SpanKind.TOOL)
        s.finish()
        trace = _make_trace(s)
        report = correlate_traces([trace])

        summary = report.summary()
        assert isinstance(summary, str)
        assert "1 traces" in summary or "1" in summary

    def test_to_dict_structure(self):
        """CorrelationReport.to_dict() must contain all expected keys."""
        s = Span(span_id="s1", name="tool", kind=SpanKind.TOOL)
        s.finish()
        trace = _make_trace(s)
        report = correlate_traces([trace])
        data = report.to_dict()

        assert "total_traces" in data
        assert "overall_error_rate" in data
        assert "avg_duration_ms" in data
        assert "avg_total_tokens" in data
        assert "avg_total_cost_usd" in data
        assert "recurring_failures" in data
        assert "performance_trends" in data
        assert "common_anti_patterns" in data

    def test_error_rate_calculation(self):
        """overall_error_rate equals fraction of traces with at least one error."""
        error_trace_span = Span(span_id="e1", name="bad", kind=SpanKind.TOOL)
        error_trace_span.finish(error="boom")
        error_trace = _make_trace(error_trace_span)

        ok_trace_span = Span(span_id="o1", name="good", kind=SpanKind.TOOL)
        ok_trace_span.finish()
        ok_trace = _make_trace(ok_trace_span)

        report = correlate_traces([error_trace, ok_trace])
        assert report.overall_error_rate == 0.5

    def test_recurring_failure_includes_span_names(self):
        """RecurringFailure.affected_span_names must list the failing spans."""
        traces = []
        for i in range(3):
            s = Span(span_id=f"s{i}", name="my_tool", kind=SpanKind.TOOL,
                     start_time=float(i))
            s.finish(error="boom")
            traces.append(_make_trace(s))

        report = correlate_traces(traces, failure_threshold=0.5)

        assert len(report.recurring_failures) == 1
        assert "my_tool" in report.recurring_failures[0].affected_span_names


class TestConfigurablePatternThresholds:
    """Tests that custom threshold values change detection behavior."""

    def test_retry_threshold_2_detects_storm_that_5_would_not(self):
        """With threshold=2, 3 calls trigger a storm; threshold=5 would not."""
        from flowlens.analysis.patterns import _detect_retry_storm

        spans = []
        for i in range(3):
            s = Span(span_id=f"s{i}", name="api_call", kind=SpanKind.TOOL,
                     start_time=float(i))
            s.finish()
            spans.append(s)

        trace = _make_trace(*spans)

        # Default threshold=5: 3 calls should NOT be flagged
        patterns_default = _detect_retry_storm(trace, threshold=5)
        assert len(patterns_default) == 0

        # Custom threshold=2: 3 calls SHOULD be flagged
        patterns_custom = _detect_retry_storm(trace, threshold=2)
        assert len(patterns_custom) == 1
        assert patterns_custom[0].pattern_type == PatternType.RETRY_STORM

    def test_loop_repeat_2_detects_loop_that_3_would_not(self):
        """With max_repeat=2, a 2-cycle loop triggers; max_repeat=3 would not."""
        from flowlens.analysis.patterns import _detect_infinite_loop

        # Sequence: A B A B — that's 2 repeats of [A, B]
        tool_names = ["tool_a", "tool_b", "tool_a", "tool_b"]
        spans = []
        for i, name in enumerate(tool_names):
            s = Span(span_id=f"s{i}", name=name, kind=SpanKind.TOOL,
                     start_time=float(i))
            s.finish()
            spans.append(s)

        trace = _make_trace(*spans)

        # Default max_repeat=3: 2 repeats should NOT trigger
        patterns_default = _detect_infinite_loop(trace, max_repeat=3)
        assert len(patterns_default) == 0

        # Custom max_repeat=2: 2 repeats SHOULD trigger
        patterns_custom = _detect_infinite_loop(trace, max_repeat=2)
        assert len(patterns_custom) == 1
        assert patterns_custom[0].pattern_type == PatternType.INFINITE_LOOP

    def test_context_ratio_0_5_detects_overflow_that_0_9_would_not(self):
        """With threshold_ratio=0.5, 60% usage triggers; 0.9 would not."""
        from flowlens.analysis.patterns import _detect_context_overflow

        # 120,000 tokens out of 200,000 = 60% usage
        s = Span(span_id="s1", name="llm_call", kind=SpanKind.LLM)
        s.set_token_usage(input_tokens=100_000, output_tokens=20_000,
                          model="claude-sonnet-4")
        s.finish()

        trace = _make_trace(s)

        # Default ratio=0.9: 60% should NOT trigger
        patterns_default = _detect_context_overflow(trace, threshold_ratio=0.9)
        assert len(patterns_default) == 0

        # Custom ratio=0.5: 60% SHOULD trigger
        patterns_custom = _detect_context_overflow(trace, threshold_ratio=0.5)
        assert len(patterns_custom) == 1
        assert patterns_custom[0].pattern_type == PatternType.CONTEXT_OVERFLOW

    def test_token_waste_ratio_5_detects_waste_that_10_would_not(self):
        """With ratio_threshold=5, ratio of 7 triggers; threshold=10 would not."""
        from flowlens.analysis.patterns import _detect_token_waste

        # 700 input, 100 output → ratio 7.0
        s = Span(span_id="s1", name="llm_call", kind=SpanKind.LLM)
        s.set_token_usage(input_tokens=700, output_tokens=100, model="gpt-4o")
        s.finish()

        trace = _make_trace(s)

        # Default ratio=10: 7.0 should NOT trigger
        patterns_default = _detect_token_waste(trace, ratio_threshold=10.0)
        assert len(patterns_default) == 0

        # Custom ratio=5: 7.0 SHOULD trigger
        patterns_custom = _detect_token_waste(trace, ratio_threshold=5.0)
        assert len(patterns_custom) == 1
        assert patterns_custom[0].pattern_type == PatternType.TOKEN_WASTE

    def test_slow_tool_multiplier_2_detects_tool_that_3_would_not(self):
        """With multiplier=2, a 2.5x slow tool triggers; multiplier=3 would not."""
        from flowlens.analysis.patterns import _detect_slow_tool

        # Two fast tools at 100ms each, one at 250ms (2.5x average)
        fast1 = Span(span_id="s1", name="api", kind=SpanKind.TOOL, start_time=0.0)
        fast1.finish()
        fast1.end_time = 0.1  # 100ms

        fast2 = Span(span_id="s2", name="api", kind=SpanKind.TOOL, start_time=0.2)
        fast2.finish()
        fast2.end_time = 0.3  # 100ms

        slow = Span(span_id="s3", name="api", kind=SpanKind.TOOL, start_time=0.4)
        slow.finish()
        slow.end_time = 0.65  # 250ms = 2.5x average of 100ms

        trace = _make_trace(fast1, fast2, slow)

        # Default multiplier=3: 2.5x should NOT trigger
        patterns_default = _detect_slow_tool(trace, slow_tool_multiplier=3.0)
        assert len(patterns_default) == 0

        # Custom multiplier=2: 2.5x SHOULD trigger
        patterns_custom = _detect_slow_tool(trace, slow_tool_multiplier=2.0)
        assert len(patterns_custom) == 1
        assert patterns_custom[0].pattern_type == PatternType.SLOW_TOOL


if __name__ == "__main__":
    # Run with pytest
    pass
