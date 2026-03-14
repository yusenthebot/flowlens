"""Tests for flowlens/sdk/context.py — context propagation, baggage, isolation, nesting, thread safety."""
from __future__ import annotations

import contextvars
import threading

from flowlens.sdk.context import (
    SpanContext,
    TraceContext,
    _baggage,
    get_baggage,
    get_baggage_item,
    get_current_span,
    get_current_trace,
    set_baggage,
    set_baggage_item,
)
from flowlens.sdk.models import Span, SpanKind, Trace

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_span(name: str = "span") -> Span:
    return Span(name=name, kind=SpanKind.CUSTOM)


def _make_trace(name: str = "svc") -> Trace:
    return Trace(service_name=name)


# ---------------------------------------------------------------------------
# Context propagation across spans
# ---------------------------------------------------------------------------

class TestContextPropagation:
    def test_trace_context_sets_and_restores(self):
        trace = _make_trace()
        assert get_current_trace() is None

        with TraceContext(trace) as t:
            assert get_current_trace() is trace
            assert t is trace

        assert get_current_trace() is None

    def test_span_context_sets_and_restores(self):
        span = _make_span("root")
        assert get_current_span() is None

        with SpanContext(span) as s:
            assert get_current_span() is span
            assert s is span

        assert get_current_span() is None

    def test_span_inherits_trace_id_from_context(self):
        trace = _make_trace()
        span = _make_span("child")

        with TraceContext(trace), SpanContext(span):
            assert span.trace_id == trace.trace_id

    def test_child_span_gets_parent_id(self):
        parent = _make_span("parent")
        child = _make_span("child")

        with SpanContext(parent), SpanContext(child):
            assert child.parent_span_id == parent.span_id

        assert parent.parent_span_id is None

    def test_context_not_leaked_after_exception(self):
        trace = _make_trace()
        span = _make_span()

        try:
            with TraceContext(trace), SpanContext(span):
                raise ValueError("boom")
        except ValueError:
            pass

        assert get_current_trace() is None
        assert get_current_span() is None


# ---------------------------------------------------------------------------
# Baggage get / set / delete
# ---------------------------------------------------------------------------

class TestBaggage:
    def setup_method(self):
        # Reset baggage before each test via ContextVar
        _baggage.set({})

    def test_get_set_baggage(self):
        token = set_baggage({"user": "alice", "session": "xyz"})
        assert get_baggage_item("user") == "alice"
        assert get_baggage_item("session") == "xyz"
        _baggage.reset(token)

    def test_get_baggage_returns_copy(self):
        set_baggage({"k": "v"})
        b1 = get_baggage()
        b1["extra"] = "should_not_affect_stored"
        assert get_baggage_item("extra") is None

    def test_set_baggage_item(self):
        set_baggage({"a": "1"})
        set_baggage_item("b", "2")
        assert get_baggage_item("a") == "1"
        assert get_baggage_item("b") == "2"

    def test_get_missing_baggage_item_returns_none(self):
        assert get_baggage_item("nonexistent") is None

    def test_set_baggage_item_overwrites(self):
        set_baggage({"key": "old"})
        set_baggage_item("key", "new")
        assert get_baggage_item("key") == "new"

    def test_baggage_persists_across_nested_spans(self):
        set_baggage({"req_id": "req-42"})
        span = _make_span()
        with SpanContext(span):
            assert get_baggage_item("req_id") == "req-42"


# ---------------------------------------------------------------------------
# Context isolation between traces
# ---------------------------------------------------------------------------

class TestContextIsolation:
    def test_two_traces_are_independent(self):
        trace_a = _make_trace("svc-a")
        trace_b = _make_trace("svc-b")

        results: list[Trace | None] = []

        def run_in_a():
            ctx = contextvars.copy_context()
            def _inner():
                with TraceContext(trace_a):
                    results.append(get_current_trace())
            ctx.run(_inner)

        def run_in_b():
            ctx = contextvars.copy_context()
            def _inner():
                with TraceContext(trace_b):
                    results.append(get_current_trace())
            ctx.run(_inner)

        run_in_a()
        run_in_b()

        assert trace_a in results
        assert trace_b in results

    def test_outer_context_not_affected_by_inner(self):
        outer = _make_trace("outer")
        inner = _make_trace("inner")

        with TraceContext(outer):
            assert get_current_trace() is outer
            inner_ctx = contextvars.copy_context()
            def _run():
                with TraceContext(inner):
                    assert get_current_trace() is inner
            inner_ctx.run(_run)
            # Outer context unchanged
            assert get_current_trace() is outer


# ---------------------------------------------------------------------------
# Nested span context
# ---------------------------------------------------------------------------

class TestNestedSpanContext:
    def test_triple_nesting(self):
        agent = _make_span("agent")
        llm = _make_span("llm")
        tool = _make_span("tool")

        with SpanContext(agent) as a:
            assert get_current_span() is agent
            with SpanContext(llm) as l:
                assert get_current_span() is llm
                assert llm.parent_span_id == agent.span_id
                with SpanContext(tool) as t:
                    assert get_current_span() is tool
                    assert tool.parent_span_id == llm.span_id
                assert get_current_span() is llm
            assert get_current_span() is agent
        assert get_current_span() is None

    def test_sibling_spans_share_parent(self):
        parent = _make_span("parent")
        child1 = _make_span("c1")
        child2 = _make_span("c2")

        with SpanContext(parent):
            with SpanContext(child1):
                pass
            with SpanContext(child2):
                pass

        assert child1.parent_span_id == parent.span_id
        assert child2.parent_span_id == parent.span_id

    def test_span_without_parent_has_none_parent_id(self):
        span = _make_span("solo")
        with SpanContext(span):
            pass
        assert span.parent_span_id is None


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_context_isolated_per_thread(self):
        """Each thread should see its own trace, not another thread's."""
        results: dict[int, Trace | None] = {}
        errors: list[Exception] = []

        def worker(tid: int, trace: Trace) -> None:
            try:
                ctx = contextvars.copy_context()
                def _run():
                    with TraceContext(trace):
                        import time; time.sleep(0.02)
                        results[tid] = get_current_trace()
                ctx.run(_run)
            except Exception as e:
                errors.append(e)

        traces = [_make_trace(f"svc-{i}") for i in range(5)]
        threads = [
            threading.Thread(target=worker, args=(i, traces[i]))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        for i, trace in enumerate(traces):
            assert results[i] is trace

    def test_baggage_isolated_per_thread(self):
        """Baggage set in one thread must not be visible in another."""
        seen: dict[int, str | None] = {}
        errors: list[Exception] = []

        def worker(tid: int, value: str) -> None:
            try:
                ctx = contextvars.copy_context()
                def _run():
                    set_baggage_item("thread_val", value)
                    import time; time.sleep(0.02)
                    seen[tid] = get_baggage_item("thread_val")
                ctx.run(_run)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=(i, f"val-{i}"))
            for i in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        for i in range(4):
            assert seen[i] == f"val-{i}"
