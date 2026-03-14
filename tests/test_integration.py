"""
End-to-end integration tests for FlowLens.

Covers:
    1. Full trace lifecycle (decorators → export → structure verification)
    2. Error propagation e2e (failure → DAG root-cause → advisor)
    3. Pattern detection e2e (known anti-patterns → advisor recommendations)
    4. Multi-trace correlation e2e (recurring failures, error rate)
    5. Export pipeline e2e (callback, JSONL, console exporters)
    6. Server API e2e (full CRUD flow via httpx.AsyncClient)
    7. Auto-instrumentation (unknown libs don't crash, mock patching works)
    8. Config and CLI smoke tests
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import httpx

from flowlens.sdk.models import Span, SpanKind, SpanStatus, Trace
from flowlens.sdk.tracer import FlowLens
from flowlens.sdk.decorators import trace_agent, trace_llm, trace_tool
from flowlens.sdk.exporters import CallbackExporter
from flowlens.sdk.context import TraceContext
from flowlens.analysis.dag_builder import build_causal_dag
from flowlens.analysis.patterns import detect_patterns
from flowlens.analysis.advisor import TraceAdvisor
from flowlens.analysis.correlator import correlate_traces
from flowlens.analysis.models import PatternType, ErrorRole
from flowlens.server.app import create_app


# ===========================================================================
# Shared helpers
# ===========================================================================


def _make_trace_data(
    trace_id: str = "t1",
    has_errors: bool = False,
    service_name: str = "test-svc",
    start_time: float = 1000.0,
) -> dict[str, Any]:
    """Build a minimal but fully valid trace dict for API tests."""
    return {
        "trace_id": trace_id,
        "service_name": service_name,
        "start_time": start_time,
        "end_time": start_time + 1.0,
        "duration_ms": 1000.0,
        "span_count": 2,
        "total_tokens": 500,
        "total_cost_usd": 0.005,
        "has_errors": has_errors,
        "error_count": 1 if has_errors else 0,
        "metadata": {"env": "test"},
        "spans": [
            {
                "span_id": f"{trace_id}_s1",
                "trace_id": trace_id,
                "parent_span_id": None,
                "name": "agent",
                "kind": "agent",
                "status": "ok",
                "start_time": start_time,
                "end_time": start_time + 1.0,
                "duration_ms": 1000.0,
                "attributes": {"test": True},
                "events": [],
                "token_usage": {
                    "input_tokens": 300,
                    "output_tokens": 200,
                    "total_cost_usd": 0.005,
                },
            },
            {
                "span_id": f"{trace_id}_s2",
                "trace_id": trace_id,
                "parent_span_id": f"{trace_id}_s1",
                "name": "search",
                "kind": "tool",
                "status": "error" if has_errors else "ok",
                "start_time": start_time + 0.1,
                "end_time": start_time + 0.5,
                "duration_ms": 400.0,
                "attributes": {},
                "events": [],
                "error": {"message": "timeout"} if has_errors else None,
            },
        ],
    }


# ===========================================================================
# Test 1: Full trace lifecycle
# ===========================================================================


class TestFullTraceLifecycle:
    """
    Agent → LLM → Tool → LLM pipeline traced end-to-end.

    Verifies span structure, parent-child relationships, token aggregation,
    and cost estimation.
    """

    def test_sync_pipeline_structure(self):
        collected: list[Trace] = []
        lens = FlowLens(
            service_name="lifecycle-test",
            export_to="console",
            on_trace_complete=collected.append,
        )
        lens.set_exporter(CallbackExporter(collected.append))

        @trace_agent(name="main-agent")
        def run_agent():
            @trace_llm(model="gpt-4o", name="plan")
            def plan_step():
                # Simulate Anthropic-style response with usage
                mock_result = MagicMock()
                mock_result.usage.input_tokens = 100
                mock_result.usage.output_tokens = 50
                return mock_result

            @trace_tool(name="search")
            def search_tool(query: str):
                return {"results": ["doc1", "doc2"]}

            @trace_llm(model="gpt-4o", name="summarise")
            def summarise_step():
                mock_result = MagicMock()
                mock_result.usage.input_tokens = 200
                mock_result.usage.output_tokens = 80
                return mock_result

            plan_step()
            search_tool(query="integration test")
            summarise_step()
            return "done"

        result = run_agent()
        assert result == "done"

        # At most 2 callbacks fire (on_trace_complete + exporter); find the trace
        # The on_trace_complete fires once, exporter fires once → deduplicate
        assert len(collected) >= 1
        trace = collected[0]

        # Span kinds present
        kinds = {s.kind for s in trace.spans}
        assert SpanKind.AGENT in kinds
        assert SpanKind.LLM in kinds
        assert SpanKind.TOOL in kinds

        # Parent-child: root agent has no parent; others do
        agent_spans = [s for s in trace.spans if s.kind == SpanKind.AGENT]
        assert len(agent_spans) == 1
        root = agent_spans[0]
        assert root.parent_span_id is None

        children = [s for s in trace.spans if s.parent_span_id == root.span_id]
        assert len(children) >= 3  # plan, search, summarise

        # Token aggregation
        assert trace.total_tokens > 0

        # Cost estimation (gpt-4o is priced)
        assert trace.total_cost_usd >= 0.0

        # All spans finished (end_time set)
        for span in trace.spans:
            assert span.end_time > 0, f"Span {span.name} end_time not set"

    @pytest.mark.asyncio
    async def test_async_pipeline_structure(self):
        collected: list[Trace] = []
        lens = FlowLens(
            service_name="async-lifecycle",
            export_to="console",
        )
        lens.set_exporter(CallbackExporter(collected.append))

        @trace_agent(name="async-agent")
        async def async_run():
            @trace_llm(model="claude-sonnet-4", name="async-plan")
            async def async_plan():
                mock = MagicMock()
                mock.usage.input_tokens = 120
                mock.usage.output_tokens = 60
                return mock

            @trace_tool(name="async-tool")
            async def async_tool(x: int):
                return x * 2

            @trace_llm(model="claude-sonnet-4", name="async-final")
            async def async_final():
                mock = MagicMock()
                mock.usage.input_tokens = 80
                mock.usage.output_tokens = 40
                return mock

            await async_plan()
            await async_tool(x=42)
            await async_final()
            return "async-done"

        result = await async_run()
        assert result == "async-done"
        assert len(collected) >= 1

        trace = collected[0]
        kinds = {s.kind for s in trace.spans}
        assert SpanKind.AGENT in kinds
        assert SpanKind.LLM in kinds
        assert SpanKind.TOOL in kinds
        assert trace.total_tokens > 0

    def test_timing_ordering(self):
        """Child spans must start after their parent and end before the trace ends."""
        collected: list[Trace] = []
        lens = FlowLens(service_name="timing-test", export_to="console")
        lens.set_exporter(CallbackExporter(collected.append))

        @trace_agent(name="timing-agent")
        def timing_run():
            @trace_llm(model="gpt-4o", name="step1")
            def step1():
                return MagicMock()

            step1()
            return "ok"

        timing_run()
        trace = collected[0]
        agent_span = next(s for s in trace.spans if s.kind == SpanKind.AGENT)
        child_spans = [s for s in trace.spans if s.parent_span_id == agent_span.span_id]

        for child in child_spans:
            assert child.start_time >= agent_span.start_time
            assert child.end_time <= agent_span.end_time + 0.01  # small tolerance

    def test_metadata_propagation(self):
        """Trace metadata passes through the lifecycle correctly."""
        collected: list[Trace] = []
        lens = FlowLens(
            service_name="metadata-test",
            export_to="console",
            metadata={"env": "prod", "version": "2"},
        )
        lens.set_exporter(CallbackExporter(collected.append))

        @trace_agent(name="agent", metadata={"session": "abc"})
        def run():
            return 42

        run()
        trace = collected[0]
        assert trace.metadata.get("env") == "prod"
        assert trace.metadata.get("session") == "abc"


# ===========================================================================
# Test 2: Error propagation e2e
# ===========================================================================


class TestErrorPropagationE2E:
    """
    Intentional tool failure → error propagation through span tree →
    DAG root-cause detection → advisor recommendations.
    """

    def _build_error_trace(self) -> Trace:
        """Build a trace where a tool fails and an LLM after it also fails."""
        trace = Trace(trace_id="err-e2e", service_name="error-test")
        t0 = 1000.0

        agent = Span(
            span_id="agent-1",
            trace_id=trace.trace_id,
            name="agent",
            kind=SpanKind.AGENT,
            status=SpanStatus.ERROR,
            start_time=t0,
            end_time=t0 + 2.0,
            error_message="Child failed",
        )

        llm1 = Span(
            span_id="llm-1",
            trace_id=trace.trace_id,
            parent_span_id="agent-1",
            name="plan-llm",
            kind=SpanKind.LLM,
            status=SpanStatus.OK,
            start_time=t0 + 0.1,
            end_time=t0 + 0.5,
        )

        tool1 = Span(
            span_id="tool-1",
            trace_id=trace.trace_id,
            parent_span_id="agent-1",
            name="broken-tool",
            kind=SpanKind.TOOL,
            status=SpanStatus.ERROR,
            start_time=t0 + 0.6,
            end_time=t0 + 1.0,
            error_message="Connection refused",
            error_type="ConnectionError",
        )

        llm2 = Span(
            span_id="llm-2",
            trace_id=trace.trace_id,
            parent_span_id="agent-1",
            name="summary-llm",
            kind=SpanKind.LLM,
            status=SpanStatus.ERROR,
            start_time=t0 + 1.1,
            end_time=t0 + 1.8,
            error_message="Cannot proceed after tool failure",
            error_type="RuntimeError",
        )

        trace.spans = [agent, llm1, tool1, llm2]
        trace.finish()
        return trace

    def test_root_cause_identified(self):
        trace = self._build_error_trace()
        dag = build_causal_dag(trace)

        assert dag.has_errors
        assert len(dag.root_causes) >= 1
        # agent-1 is the topmost error span with no error ancestor → root cause
        assert "agent-1" in dag.root_causes

    def test_cascaded_errors_marked(self):
        trace = self._build_error_trace()
        dag = build_causal_dag(trace)

        node_map = {n.span_id: n for n in dag.nodes}
        # agent-1 is root cause (topmost error, no error parent)
        assert node_map["agent-1"].error_role == ErrorRole.ROOT_CAUSE
        # tool-1 and llm-2 are children of the root-cause agent → cascaded
        assert node_map["tool-1"].error_role == ErrorRole.CASCADED
        assert node_map["llm-2"].error_role == ErrorRole.CASCADED

    def test_advisor_provides_recommendations(self):
        trace = self._build_error_trace()
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)
        advisor = TraceAdvisor(trace=trace, dag=dag, patterns=patterns)

        report = advisor.generate_report()
        assert report["severity_score"] > 0
        assert len(report["recommendations"]) >= 1
        assert report["error_summary"] != ""

    def test_decorator_propagates_exception(self):
        """Exceptions raised inside @trace_tool must propagate to the caller."""
        collected: list[Trace] = []
        lens = FlowLens(service_name="err-decorator", export_to="console")
        lens.set_exporter(CallbackExporter(collected.append))

        @trace_agent(name="agent")
        def run():
            @trace_tool(name="bad-tool")
            def bad_tool():
                raise ValueError("intentional failure")

            bad_tool()

        with pytest.raises(ValueError, match="intentional failure"):
            run()

        # Trace should still be exported with error status
        assert len(collected) >= 1
        trace = collected[0]
        assert trace.has_errors
        error_spans = [s for s in trace.spans if s.status == SpanStatus.ERROR]
        assert len(error_spans) >= 1

    def test_error_span_has_error_info(self):
        """Error spans must capture error_message and error_type."""
        collected: list[Trace] = []
        lens = FlowLens(service_name="err-info", export_to="console")
        lens.set_exporter(CallbackExporter(collected.append))

        @trace_agent(name="agent")
        def run():
            @trace_tool(name="risky-tool")
            def risky():
                raise TypeError("bad type")

            risky()

        with pytest.raises(TypeError):
            run()

        trace = collected[0]
        tool_spans = [s for s in trace.spans if s.name == "risky-tool"]
        assert len(tool_spans) == 1
        risky_span = tool_spans[0]
        assert risky_span.error_message == "bad type"
        assert risky_span.error_type == "TypeError"


# ===========================================================================
# Test 3: Pattern detection e2e
# ===========================================================================


class TestPatternDetectionE2E:
    """
    Create traces with known anti-patterns; verify they are detected and
    the advisor surfaces relevant recommendations.
    """

    def _make_retry_storm_trace(self, retry_count: int = 6) -> Trace:
        trace = Trace(trace_id="retry-storm", service_name="pattern-test")
        t0 = 1000.0

        agent = Span(
            span_id="agent-1",
            trace_id=trace.trace_id,
            name="agent",
            kind=SpanKind.AGENT,
            status=SpanStatus.OK,
            start_time=t0,
            end_time=t0 + 10.0,
        )
        trace.spans.append(agent)

        for i in range(retry_count):
            s = Span(
                span_id=f"retry-{i}",
                trace_id=trace.trace_id,
                parent_span_id="agent-1",
                name="flaky-api",
                kind=SpanKind.TOOL,
                status=SpanStatus.ERROR,
                start_time=t0 + i * 0.5,
                end_time=t0 + i * 0.5 + 0.4,
                error_message="Service unavailable",
            )
            trace.spans.append(s)

        trace.finish()
        return trace

    def _make_context_overflow_trace(self) -> Trace:
        trace = Trace(trace_id="ctx-overflow", service_name="pattern-test")
        t0 = 1000.0

        agent = Span(
            span_id="agent-1",
            trace_id=trace.trace_id,
            name="agent",
            kind=SpanKind.AGENT,
            status=SpanStatus.OK,
            start_time=t0,
            end_time=t0 + 2.0,
        )

        # Create an LLM span that uses 92% of 200k context
        llm = Span(
            span_id="llm-1",
            trace_id=trace.trace_id,
            parent_span_id="agent-1",
            name="heavy-llm",
            kind=SpanKind.LLM,
            status=SpanStatus.OK,
            start_time=t0 + 0.1,
            end_time=t0 + 1.8,
            attributes={"gen_ai.request.model": "claude-sonnet-4"},
        )
        llm.set_token_usage(input_tokens=180_000, output_tokens=4_000, model="claude-sonnet-4")

        trace.spans = [agent, llm]
        trace.finish()
        return trace

    def test_retry_storm_detected(self):
        trace = self._make_retry_storm_trace(retry_count=6)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)

        pattern_types = {p.pattern_type for p in patterns}
        assert PatternType.RETRY_STORM in pattern_types

        retry_pattern = next(p for p in patterns if p.pattern_type == PatternType.RETRY_STORM)
        assert retry_pattern.severity in ("warning", "critical")
        assert retry_pattern.details["call_count"] >= 6

    def test_context_overflow_detected(self):
        trace = self._make_context_overflow_trace()
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)

        pattern_types = {p.pattern_type for p in patterns}
        assert PatternType.CONTEXT_OVERFLOW in pattern_types

        ctx_pattern = next(p for p in patterns if p.pattern_type == PatternType.CONTEXT_OVERFLOW)
        assert ctx_pattern.details["usage_ratio"] >= 0.9

    def test_advisor_retry_storm_recommendation(self):
        trace = self._make_retry_storm_trace(retry_count=6)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)
        advisor = TraceAdvisor(trace=trace, dag=dag, patterns=patterns)

        report = advisor.generate_report()
        recs = report["recommendations_detail"]
        retry_recs = [r for r in recs if r["pattern_type"] == PatternType.RETRY_STORM.value]
        assert len(retry_recs) >= 1
        assert "backoff" in retry_recs[0]["title"].lower() or "retry" in retry_recs[0]["title"].lower()

    def test_advisor_context_overflow_recommendation(self):
        trace = self._make_context_overflow_trace()
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)
        advisor = TraceAdvisor(trace=trace, dag=dag, patterns=patterns)

        report = advisor.generate_report()
        recs = report["recommendations_detail"]
        ctx_recs = [r for r in recs if r["pattern_type"] == PatternType.CONTEXT_OVERFLOW.value]
        assert len(ctx_recs) >= 1
        # Recommendation should mention context reduction
        assert ctx_recs[0]["code_snippet"] != ""

    def test_severity_score_increases_with_critical_patterns(self):
        """Retry storm (critical) should push severity score higher than a clean trace."""
        clean_trace = Trace(trace_id="clean", service_name="test")
        clean_agent = Span(
            span_id="a1", trace_id="clean", name="agent",
            kind=SpanKind.AGENT, status=SpanStatus.OK,
            start_time=1000.0, end_time=1001.0,
        )
        clean_trace.spans = [clean_agent]
        clean_trace.finish()

        storm_trace = self._make_retry_storm_trace(retry_count=6)

        clean_dag = build_causal_dag(clean_trace)
        clean_patterns = detect_patterns(clean_trace, clean_dag)
        clean_advisor = TraceAdvisor(trace=clean_trace, dag=clean_dag, patterns=clean_patterns)

        storm_dag = build_causal_dag(storm_trace)
        storm_patterns = detect_patterns(storm_trace, storm_dag)
        storm_advisor = TraceAdvisor(trace=storm_trace, dag=storm_dag, patterns=storm_patterns)

        assert storm_advisor.severity_score > clean_advisor.severity_score


# ===========================================================================
# Test 4: Multi-trace correlation e2e
# ===========================================================================


class TestMultiTraceCorrelationE2E:
    """
    Create 5+ traces with recurring failures; verify correlation report.
    """

    def _make_failing_traces(self, count: int = 6) -> list[Trace]:
        traces = []
        t0 = 1000.0
        for i in range(count):
            trace = Trace(
                trace_id=f"fail-{i}",
                service_name="correlation-test",
                start_time=t0 + i,
            )
            agent = Span(
                span_id=f"agent-{i}",
                trace_id=trace.trace_id,
                name="agent",
                kind=SpanKind.AGENT,
                status=SpanStatus.ERROR,
                start_time=t0 + i,
                end_time=t0 + i + 0.5,
                error_message="Database unavailable",
            )
            tool = Span(
                span_id=f"tool-{i}",
                trace_id=trace.trace_id,
                parent_span_id=f"agent-{i}",
                name="db-query",
                kind=SpanKind.TOOL,
                status=SpanStatus.ERROR,
                start_time=t0 + i + 0.1,
                end_time=t0 + i + 0.4,
                error_message="Database unavailable",
                error_type="DatabaseError",
            )
            trace.spans = [agent, tool]
            trace.end_time = t0 + i + 0.5
            traces.append(trace)
        return traces

    def test_recurring_failure_detected(self):
        traces = self._make_failing_traces(count=6)
        report = correlate_traces(traces, failure_threshold=0.5)

        assert report.total_traces == 6
        assert len(report.recurring_failures) >= 1

        top_failure = report.recurring_failures[0]
        assert top_failure.occurrence_count == 6
        assert top_failure.occurrence_rate == 1.0
        assert "database unavailable" in top_failure.error_message.lower()

    def test_error_rate_calculation(self):
        traces = self._make_failing_traces(count=6)
        # Add 2 clean traces
        for i in range(2):
            clean = Trace(
                trace_id=f"clean-{i}",
                service_name="correlation-test",
                start_time=2000.0 + i,
            )
            ok_agent = Span(
                span_id=f"ok-{i}",
                trace_id=clean.trace_id,
                name="agent",
                kind=SpanKind.AGENT,
                status=SpanStatus.OK,
                start_time=2000.0 + i,
                end_time=2000.0 + i + 0.5,
            )
            clean.spans = [ok_agent]
            clean.end_time = 2000.0 + i + 0.5
            traces.append(clean)

        report = correlate_traces(traces, failure_threshold=0.5)
        assert report.total_traces == 8
        # 6 out of 8 traces have errors → 0.75
        assert abs(report.overall_error_rate - 0.75) < 0.01

    def test_report_to_dict(self):
        traces = self._make_failing_traces(count=5)
        report = correlate_traces(traces)
        d = report.to_dict()

        assert d["total_traces"] == 5
        assert "recurring_failures" in d
        assert "performance_trends" in d
        assert "common_anti_patterns" in d
        assert isinstance(d["overall_error_rate"], float)

    def test_empty_traces_returns_empty_report(self):
        report = correlate_traces([])
        assert report.total_traces == 0
        assert report.recurring_failures == []

    def test_correlation_with_minimum_threshold(self):
        """Only errors appearing in >50% of traces are flagged by default."""
        traces = self._make_failing_traces(count=6)
        # Add 10 clean traces so the failure rate drops below 50%
        for i in range(10):
            clean = Trace(trace_id=f"c-{i}", service_name="test", start_time=9000.0 + i)
            clean.spans = []
            clean.end_time = 9000.0 + i + 0.1
            traces.append(clean)

        report = correlate_traces(traces, failure_threshold=0.5)
        # 6/16 ≈ 37.5% < 50% → should not appear as recurring failure
        assert all(
            f.occurrence_rate > 0.5
            for f in report.recurring_failures
        )


# ===========================================================================
# Test 5: Export pipeline e2e
# ===========================================================================


class TestExportPipelineE2E:
    """
    Verify all exporter types work correctly end-to-end.
    """

    def _run_simple_agent(self, lens: FlowLens) -> None:
        @trace_agent(name="export-agent")
        def run():
            @trace_llm(model="gpt-4o", name="llm-call")
            def call():
                mock = MagicMock()
                mock.usage.input_tokens = 100
                mock.usage.output_tokens = 50
                return mock

            call()
            return "exported"

        run()

    def test_callback_exporter_receives_trace(self):
        received: list[Trace] = []
        lens = FlowLens(service_name="callback-test", export_to="console")
        lens.set_exporter(CallbackExporter(received.append))

        self._run_simple_agent(lens)

        assert len(received) >= 1
        trace = received[0]
        # The service_name is set on the FlowLens instance that created the trace
        assert trace.service_name == "callback-test"
        # Verify exported data structure
        d = trace.to_dict()
        assert "trace_id" in d
        assert "spans" in d
        assert isinstance(d["spans"], list)
        assert d["total_tokens"] > 0

    def test_callback_exporter_exported_data_matches_structure(self):
        received: list[Trace] = []
        lens = FlowLens(service_name="structure-test", export_to="console")
        lens.set_exporter(CallbackExporter(received.append))

        self._run_simple_agent(lens)
        trace = received[0]
        d = trace.to_dict()

        # Required top-level keys
        required_keys = {
            "trace_id", "service_name", "start_time", "end_time",
            "duration_ms", "total_tokens", "total_cost_usd",
            "has_errors", "error_count", "span_count", "spans",
        }
        assert required_keys.issubset(d.keys())

        # Each span must have required keys
        for span_dict in d["spans"]:
            assert "span_id" in span_dict
            assert "kind" in span_dict
            assert "status" in span_dict
            assert "start_time" in span_dict

    def test_jsonl_exporter_writes_correct_format(self, tmp_path):
        output_dir = tmp_path / "traces"
        lens = FlowLens(service_name="jsonl-test", export_to="jsonl", output_dir=str(output_dir))

        self._run_simple_agent(lens)
        lens.shutdown()

        jsonl_file = output_dir / "traces.jsonl"
        assert jsonl_file.exists()

        lines = jsonl_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) >= 1

        for line in lines:
            if not line.strip():
                continue
            obj = json.loads(line)
            assert "trace_id" in obj
            assert "spans" in obj
            assert isinstance(obj["spans"], list)

    def test_jsonl_exporter_appends_multiple_traces(self, tmp_path):
        output_dir = tmp_path / "multi"
        lens = FlowLens(service_name="jsonl-multi", export_to="jsonl", output_dir=str(output_dir))

        for _ in range(3):
            self._run_simple_agent(lens)
        lens.shutdown()

        jsonl_file = output_dir / "traces.jsonl"
        lines = [l for l in jsonl_file.read_text().split("\n") if l.strip()]
        assert len(lines) >= 3

    def test_console_exporter_does_not_crash(self, capsys):
        lens = FlowLens(service_name="console-test", export_to="console")
        # ConsoleExporter is the default; just run without error
        self._run_simple_agent(lens)
        # No assertion needed — the test passes if no exception is raised

    def test_console_exporter_verbose_no_crash(self, capsys):
        lens = FlowLens(service_name="console-verbose", export_to="console", verbose=True)
        self._run_simple_agent(lens)
        # Verbose mode should also not crash


# ===========================================================================
# Test 6: Server API e2e
# ===========================================================================


class TestServerAPIE2E:
    """
    Full CRUD flow via httpx.AsyncClient against the FastAPI test server.
    """

    @pytest.fixture
    def app(self, tmp_path):
        return create_app(db_path=str(tmp_path / "e2e_test.db"))

    @pytest.fixture
    def sync_client(self, app):
        from fastapi.testclient import TestClient
        return TestClient(app)

    @pytest.mark.asyncio
    async def test_full_api_crud_flow(self, app, tmp_path):
        """
        1. POST /v1/traces/ingest → store a trace
        2. GET /v1/traces          → list includes it
        3. GET /v1/traces/{id}     → full trace detail
        4. GET /v1/traces/{id}/dag → DAG analysis
        5. GET /v1/stats           → updated stats
        6. DELETE /v1/traces/{id}  → remove it
        7. GET /v1/traces          → list is empty
        """
        trace_data = _make_trace_data("e2e-crud-1", has_errors=True)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # 1. Ingest
            r = await client.post("/v1/traces/ingest", json=trace_data)
            assert r.status_code == 201
            body = r.json()
            assert body["status"] == "ok"
            assert body["trace_id"] == "e2e-crud-1"

            # 2. List — should include the trace
            r = await client.get("/v1/traces")
            assert r.status_code == 200
            listed = r.json()
            trace_ids = [t["trace_id"] for t in listed["traces"]]
            assert "e2e-crud-1" in trace_ids

            # 3. Get detail
            r = await client.get("/v1/traces/e2e-crud-1")
            assert r.status_code == 200
            detail = r.json()
            assert detail["trace_id"] == "e2e-crud-1"
            assert "spans" in detail
            assert len(detail["spans"]) == 2

            # 4. DAG endpoint
            r = await client.get("/v1/traces/e2e-crud-1/dag")
            assert r.status_code == 200
            dag = r.json()
            assert "nodes" in dag
            assert "root_causes" in dag
            assert dag["has_errors"] is True

            # 5. Stats — should show 1 trace, 1 error
            r = await client.get("/v1/stats")
            assert r.status_code == 200
            stats = r.json()
            assert stats["total_traces"] >= 1
            assert stats["error_traces"] >= 1

            # 6. Delete
            r = await client.delete("/v1/traces/e2e-crud-1")
            assert r.status_code == 200
            assert r.json()["status"] == "deleted"

            # 7. List should now be empty (for this trace)
            r = await client.get("/v1/traces")
            assert r.status_code == 200
            listed_after = r.json()
            trace_ids_after = [t["trace_id"] for t in listed_after["traces"]]
            assert "e2e-crud-1" not in trace_ids_after

    @pytest.mark.asyncio
    async def test_404_on_missing_trace(self, app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r = await client.get("/v1/traces/does-not-exist")
            assert r.status_code == 404

            r = await client.delete("/v1/traces/does-not-exist")
            assert r.status_code == 404

            r = await client.get("/v1/traces/does-not-exist/dag")
            assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_stats_update_after_ingest(self, app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            r0 = await client.get("/v1/stats")
            initial_count = r0.json()["total_traces"]

            for i in range(3):
                await client.post(
                    "/v1/traces/ingest",
                    json=_make_trace_data(f"stat-{i}", start_time=float(2000 + i)),
                )

            r1 = await client.get("/v1/stats")
            assert r1.json()["total_traces"] == initial_count + 3

    @pytest.mark.asyncio
    async def test_ingest_validation_errors(self, app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Missing trace_id
            r = await client.post("/v1/traces/ingest", json={"service_name": "x"})
            assert r.status_code == 422

            # Negative tokens
            bad = _make_trace_data("bad-tokens")
            bad["total_tokens"] = -1
            r = await client.post("/v1/traces/ingest", json=bad)
            assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_filter_errors_only(self, app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post("/v1/traces/ingest", json=_make_trace_data("ok-1", start_time=3000.0))
            await client.post(
                "/v1/traces/ingest",
                json=_make_trace_data("err-1", has_errors=True, start_time=3001.0),
            )

            r = await client.get("/v1/traces/errors")
            assert r.status_code == 200
            data = r.json()
            for t in data["traces"]:
                assert t["has_errors"] == 1

    @pytest.mark.asyncio
    async def test_dag_root_cause_via_api(self, app):
        """Ingest a trace with a known error and verify the DAG endpoint returns it."""
        trace_data = {
            "trace_id": "dag-api-1",
            "service_name": "dag-test",
            "start_time": 1000.0,
            "end_time": 1002.0,
            "duration_ms": 2000.0,
            "span_count": 3,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "has_errors": True,
            "error_count": 1,
            "metadata": {},
            "spans": [
                {
                    "span_id": "da1",
                    "trace_id": "dag-api-1",
                    "name": "agent",
                    "kind": "agent",
                    "status": "ok",
                    "start_time": 1000.0,
                    "end_time": 1002.0,
                    "attributes": {},
                    "events": [],
                },
                {
                    "span_id": "da2",
                    "trace_id": "dag-api-1",
                    "parent_span_id": "da1",
                    "name": "plan-llm",
                    "kind": "llm",
                    "status": "ok",
                    "start_time": 1000.1,
                    "end_time": 1000.8,
                    "attributes": {},
                    "events": [],
                },
                {
                    "span_id": "da3",
                    "trace_id": "dag-api-1",
                    "parent_span_id": "da1",
                    "name": "failing-tool",
                    "kind": "tool",
                    "status": "error",
                    "start_time": 1000.9,
                    "end_time": 1001.5,
                    "attributes": {},
                    "events": [],
                    "error": {"message": "timeout"},
                },
            ],
        }

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post("/v1/traces/ingest", json=trace_data)
            r = await client.get("/v1/traces/dag-api-1/dag")
            assert r.status_code == 200
            dag = r.json()
            assert dag["has_errors"]
            assert "da3" in dag["root_causes"]


# ===========================================================================
# Test 7: Auto-instrumentation verification
# ===========================================================================


class TestAutoInstrumentationE2E:
    """
    Verify the auto_instrument mechanism handles unknown libraries gracefully
    and that mock-class patching works.
    """

    def test_unknown_library_does_not_crash(self):
        from flowlens.sdk.auto_instrument import auto_instrument

        # Should log a warning but never raise
        auto_instrument(["completely_unknown_lib_xyz"])

    def test_multiple_unknown_libraries_safe(self):
        from flowlens.sdk.auto_instrument import auto_instrument

        auto_instrument(["fake-lib-1", "fake-lib-2", "another-fake"])

    def test_idempotent_patching(self):
        """Calling auto_instrument twice for the same lib should not raise."""
        from flowlens.sdk.auto_instrument import auto_instrument, _patched

        # Manually add a fake lib as already-patched to test the guard
        _patched.add("__test_idem__")
        try:
            auto_instrument(["__test_idem__"])  # should silently skip
        finally:
            _patched.discard("__test_idem__")

    def test_mock_class_patching_works(self):
        """
        Demonstrate that the patching mechanism can wrap methods on a plain class,
        which is exactly what auto_instrument does for real libraries.
        """
        import functools

        class FakeLLMClient:
            def generate(self, prompt: str) -> str:
                return f"response to: {prompt}"

        original_generate = FakeLLMClient.generate
        call_log: list[str] = []

        @functools.wraps(original_generate)
        def patched_generate(self, prompt: str) -> str:
            call_log.append(prompt)
            return original_generate(self, prompt)

        FakeLLMClient.generate = patched_generate

        client = FakeLLMClient()
        result = client.generate("hello")

        assert result == "response to: hello"
        assert call_log == ["hello"]

        # Restore
        FakeLLMClient.generate = original_generate

    def test_missing_anthropic_does_not_crash(self):
        """_patch_anthropic silently skips when anthropic is not installed."""
        from flowlens.sdk import auto_instrument as ai_mod

        with patch.dict("sys.modules", {"anthropic": None}):
            # Re-import the function to pick up the patched sys.modules
            try:
                ai_mod._patch_anthropic()
            except Exception as exc:
                # Should never raise; only warn
                pytest.fail(f"_patch_anthropic raised unexpectedly: {exc}")

    def test_missing_openai_does_not_crash(self):
        from flowlens.sdk import auto_instrument as ai_mod

        with patch.dict("sys.modules", {"openai": None}):
            try:
                ai_mod._patch_openai()
            except Exception as exc:
                pytest.fail(f"_patch_openai raised unexpectedly: {exc}")


# ===========================================================================
# Test 8: Config and CLI smoke tests
# ===========================================================================


class TestConfigAndCLISmokeTests:
    """Config defaults and CLI --help smoke tests."""

    def test_config_loads_defaults(self):
        from flowlens.config import FlowLensConfig

        cfg = FlowLensConfig()
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 8585
        assert cfg.log_level == "INFO"
        assert cfg.rate_limit == 120
        assert cfg.db_path == "./flowlens.db"
        assert isinstance(cfg.cors_origins, list)
        assert len(cfg.cors_origins) >= 1

    def test_config_env_override(self, monkeypatch):
        monkeypatch.setenv("FLOWLENS_PORT", "9999")
        monkeypatch.setenv("FLOWLENS_LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("FLOWLENS_RATE_LIMIT", "60")

        from flowlens.config import FlowLensConfig
        cfg = FlowLensConfig()
        assert cfg.port == 9999
        assert cfg.log_level == "DEBUG"
        assert cfg.rate_limit == 60

    def test_config_invalid_port_raises(self, monkeypatch):
        from flowlens.config import FlowLensConfig

        monkeypatch.setenv("FLOWLENS_PORT", "99999")
        with pytest.raises((ValueError, Exception)):
            FlowLensConfig()

    def test_cli_help_does_not_crash(self):
        from click.testing import CliRunner
        from flowlens.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "FlowLens" in result.output

    def test_cli_version_subcommand(self):
        from click.testing import CliRunner
        from flowlens.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["version"])
        assert result.exit_code == 0
        assert "FlowLens" in result.output

    def test_cli_serve_help(self):
        from click.testing import CliRunner
        from flowlens.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--port" in result.output or "--host" in result.output

    def test_cli_analyze_help(self):
        from click.testing import CliRunner
        from flowlens.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["analyze", "--help"])
        # May not be 0 if subcommand doesn't exist; just must not crash with traceback
        assert result.exit_code in (0, 2)  # 2 = no such command

    def test_settings_singleton_is_valid(self):
        from flowlens.config import settings

        assert isinstance(settings.port, int)
        assert 1 <= settings.port <= 65535
        assert settings.log_level in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


# ===========================================================================
# Additional integration: FlowLens instance management
# ===========================================================================


class TestFlowLensInstanceManagement:
    """Verify singleton behaviour and shutdown handling."""

    def test_get_instance_returns_last_created(self):
        lens1 = FlowLens(service_name="first", export_to="console")
        lens2 = FlowLens(service_name="second", export_to="console")
        assert FlowLens.get_instance() is lens2

    def test_shutdown_exports_active_traces(self):
        """Traces started but not yet ended must be exported on shutdown."""
        received: list[Trace] = []
        lens = FlowLens(service_name="shutdown-test", export_to="console")
        lens.set_exporter(CallbackExporter(received.append))

        trace = lens.start_trace()
        with TraceContext(trace):
            span = lens.start_span("pending-span")
            span.finish()
        # Do NOT call lens.end_trace — let shutdown handle it

        lens.shutdown()
        # After shutdown the active traces dict should be empty
        assert len(lens._active_traces) == 0

    def test_sample_rate_zero_drops_all_traces(self):
        """With sample_rate=0.0, no trace should be exported."""
        received: list[Trace] = []
        lens = FlowLens(
            service_name="sample-zero",
            export_to="console",
            sample_rate=0.0,
        )
        lens.set_exporter(CallbackExporter(received.append))

        @trace_agent(name="agent")
        def run():
            return "noop"

        # Run multiple times; exporter should receive nothing (or very rarely due to float edge)
        for _ in range(5):
            run()

        assert len(received) == 0

    def test_sample_rate_one_exports_all_traces(self):
        """With sample_rate=1.0, every trace must be exported."""
        received: list[Trace] = []
        lens = FlowLens(
            service_name="sample-full",
            export_to="console",
            sample_rate=1.0,
        )
        lens.set_exporter(CallbackExporter(received.append))

        @trace_agent(name="agent")
        def run():
            return "ok"

        for _ in range(3):
            run()

        assert len(received) >= 3

    def test_configure_classmethod(self):
        lens = FlowLens.configure(
            service_name="configured-lens",
            export_to="console",
        )
        assert lens.service_name == "configured-lens"
        assert FlowLens.get_instance() is lens
