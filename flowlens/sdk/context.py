"""
Trace 上下文管理 — 维护 span 的父子关系和 trace 归属

设计原则：
- 使用 contextvars 实现异步安全的上下文传递
- 支持嵌套 span（agent → llm → tool）
- 零侵入：上下文自动传播，用户无需手动管理
"""

from __future__ import annotations

import contextvars
from typing import Optional

from .models import Span, Trace

# 当前活跃的 trace
_current_trace: contextvars.ContextVar[Optional[Trace]] = contextvars.ContextVar(
    "flowlens_current_trace", default=None
)

# 当前活跃的 span（用于建立 parent-child）
_current_span: contextvars.ContextVar[Optional[Span]] = contextvars.ContextVar(
    "flowlens_current_span", default=None
)

# Baggage — 在整个 trace 中传播的键值对（类似 OpenTelemetry baggage）
_baggage: contextvars.ContextVar[dict[str, str]] = contextvars.ContextVar(
    "flowlens_baggage", default={}
)


def get_current_trace() -> Optional[Trace]:
    """获取当前 trace"""
    return _current_trace.get()


def set_current_trace(trace: Optional[Trace]) -> contextvars.Token:
    """设置当前 trace"""
    return _current_trace.set(trace)


def get_current_span() -> Optional[Span]:
    """获取当前 span"""
    return _current_span.get()


def set_current_span(span: Optional[Span]) -> contextvars.Token:
    """设置当前 span"""
    return _current_span.set(span)


def get_baggage() -> dict[str, str]:
    """获取当前 baggage（跨 trace 传播的上下文）"""
    return _baggage.get().copy()


def set_baggage(baggage: dict[str, str]) -> contextvars.Token:
    """设置当前 baggage"""
    return _baggage.set(baggage.copy())


def get_baggage_item(key: str) -> Optional[str]:
    """获取 baggage 中的单个项目"""
    return _baggage.get().get(key)


def set_baggage_item(key: str, value: str) -> None:
    """设置 baggage 中的单个项目"""
    baggage = _baggage.get().copy()
    baggage[key] = value
    _baggage.set(baggage)


class SpanContext:
    """
    Span 上下文管理器 — 自动处理 parent-child 关系

    用法：
        with SpanContext(span) as s:
            # span 被设为当前 span
            # 任何在此内创建的子 span 自动成为 s 的 child
            ...
        # 退出时恢复之前的 span
    """

    def __init__(self, span: Span):
        self.span = span
        self._trace_token: Optional[contextvars.Token] = None
        self._span_token: Optional[contextvars.Token] = None

    def __enter__(self) -> Span:
        # 自动设置 parent
        parent = get_current_span()
        if parent:
            self.span.parent_span_id = parent.span_id

        # 自动设置 trace_id
        trace = get_current_trace()
        if trace:
            self.span.trace_id = trace.trace_id

        # 入栈
        self._span_token = set_current_span(self.span)
        return self.span

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        # 出栈（恢复上一个 span）
        if self._span_token is not None:
            _current_span.reset(self._span_token)

        return None  # 不吞异常


class TraceContext:
    """
    Trace 上下文管理器

    用法：
        with TraceContext(trace):
            # 所有在此内创建的 span 都属于这个 trace
            ...
    """

    def __init__(self, trace: Trace):
        self.trace = trace
        self._trace_token: Optional[contextvars.Token] = None

    def __enter__(self) -> Trace:
        self._trace_token = set_current_trace(self.trace)
        return self.trace

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._trace_token is not None:
            _current_trace.reset(self._trace_token)
        return None
