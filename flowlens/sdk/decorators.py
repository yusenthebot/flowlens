"""
FlowLens 装饰器 — 零侵入采集 Agent 执行 trace

三个核心装饰器：
- @trace_agent: 装饰 Agent 主循环，创建 trace + root span
- @trace_llm: 装饰 LLM 调用，记录 token 用量和成本
- @trace_tool: 装饰 Tool/Skill 执行，记录参数和结果

设计原则：
- 装饰器只做采集，不改变原函数行为
- 异常透传：装饰器不吞异常，但会记录错误
- 异步优先：支持 async 和 sync 函数
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
from typing import Any, Callable, Optional

from .models import Span, SpanKind, SpanStatus
from .context import SpanContext, TraceContext, get_current_trace
from .tracer import FlowLens

logger = logging.getLogger(__name__)


def trace_agent(
    name: str = "agent",
    metadata: Optional[dict] = None,
) -> Callable:
    """
    装饰 Agent 主循环

    - 创建新的 trace
    - 创建 root span (kind=AGENT)
    - 自动 export trace 当函数结束
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            lens = FlowLens.get_instance()
            if not lens:
                return await func(*args, **kwargs)

            trace = lens.start_trace(metadata=metadata)

            with TraceContext(trace):
                span = lens.start_span(name, kind=SpanKind.AGENT)

                with SpanContext(span):
                    try:
                        result = await func(*args, **kwargs)
                        span.finish(status=SpanStatus.OK)
                        return result
                    except Exception as e:
                        span.finish(
                            status=SpanStatus.ERROR,
                            error=str(e),
                        )
                        span.error_type = type(e).__name__
                        raise
                    finally:
                        lens.end_trace(trace)

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            lens = FlowLens.get_instance()
            if not lens:
                return func(*args, **kwargs)

            trace = lens.start_trace(metadata=metadata)

            with TraceContext(trace):
                span = lens.start_span(name, kind=SpanKind.AGENT)

                with SpanContext(span):
                    try:
                        result = func(*args, **kwargs)
                        span.finish(status=SpanStatus.OK)
                        return result
                    except Exception as e:
                        span.finish(
                            status=SpanStatus.ERROR,
                            error=str(e),
                        )
                        span.error_type = type(e).__name__
                        raise
                    finally:
                        lens.end_trace(trace)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def trace_llm(
    model: str = "",
    name: Optional[str] = None,
) -> Callable:
    """
    装饰 LLM 调用

    - 创建 span (kind=LLM)
    - 自动提取 token 用量（从返回值中推断）
    - 记录 model 名称
    """

    def decorator(func: Callable) -> Callable:
        span_name = name or func.__name__

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            lens = FlowLens.get_instance()
            if not lens:
                return await func(*args, **kwargs)

            span = lens.start_span(
                span_name,
                kind=SpanKind.LLM,
                attributes={
                    "gen_ai.system": "anthropic" if "claude" in model.lower() else "openai",
                    "gen_ai.request.model": model,
                },
            )

            with SpanContext(span):
                try:
                    result = await func(*args, **kwargs)
                    _extract_llm_usage(span, result, model)
                    span.finish(status=SpanStatus.OK)
                    return result
                except Exception as e:
                    span.finish(status=SpanStatus.ERROR, error=str(e))
                    span.error_type = type(e).__name__
                    raise

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            lens = FlowLens.get_instance()
            if not lens:
                return func(*args, **kwargs)

            span = lens.start_span(
                span_name,
                kind=SpanKind.LLM,
                attributes={
                    "gen_ai.system": "anthropic" if "claude" in model.lower() else "openai",
                    "gen_ai.request.model": model,
                },
            )

            with SpanContext(span):
                try:
                    result = func(*args, **kwargs)
                    _extract_llm_usage(span, result, model)
                    span.finish(status=SpanStatus.OK)
                    return result
                except Exception as e:
                    span.finish(status=SpanStatus.ERROR, error=str(e))
                    span.error_type = type(e).__name__
                    raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def trace_tool(
    name: Optional[str] = None,
) -> Callable:
    """
    装饰 Tool / Skill 执行

    - 创建 span (kind=TOOL)
    - 记录参数和返回值摘要
    """

    def decorator(func: Callable) -> Callable:
        span_name = name or func.__name__

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            lens = FlowLens.get_instance()
            if not lens:
                return await func(*args, **kwargs)

            # 记录输入参数
            attrs = _capture_params(func, args, kwargs)
            span = lens.start_span(
                span_name,
                kind=SpanKind.TOOL,
                attributes=attrs,
            )

            with SpanContext(span):
                try:
                    result = await func(*args, **kwargs)
                    span.attributes["tool.output_summary"] = _summarize(result)
                    span.finish(status=SpanStatus.OK)
                    return result
                except Exception as e:
                    span.finish(status=SpanStatus.ERROR, error=str(e))
                    span.error_type = type(e).__name__
                    raise

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            lens = FlowLens.get_instance()
            if not lens:
                return func(*args, **kwargs)

            attrs = _capture_params(func, args, kwargs)
            span = lens.start_span(
                span_name,
                kind=SpanKind.TOOL,
                attributes=attrs,
            )

            with SpanContext(span):
                try:
                    result = func(*args, **kwargs)
                    span.attributes["tool.output_summary"] = _summarize(result)
                    span.finish(status=SpanStatus.OK)
                    return result
                except Exception as e:
                    span.finish(status=SpanStatus.ERROR, error=str(e))
                    span.error_type = type(e).__name__
                    raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# ===== Helper functions =====


def _extract_llm_usage(span: Span, result: Any, model: str) -> None:
    """从 LLM 响应中提取 token 用量"""
    input_tokens = 0
    output_tokens = 0

    # Anthropic SDK 格式
    if hasattr(result, "usage"):
        usage = result.usage
        input_tokens = getattr(usage, "input_tokens", 0)
        output_tokens = getattr(usage, "output_tokens", 0)
    # OpenAI SDK 格式
    elif isinstance(result, dict) and "usage" in result:
        usage = result["usage"]
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

    if input_tokens or output_tokens:
        span.set_token_usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
        )
        span.attributes["gen_ai.usage.input_tokens"] = input_tokens
        span.attributes["gen_ai.usage.output_tokens"] = output_tokens
        span.attributes["gen_ai.response.model"] = model


def _capture_params(func: Callable, args: tuple, kwargs: dict) -> dict[str, Any]:
    """捕获函数参数（用于 tool span）"""
    attrs: dict[str, Any] = {}
    try:
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())
        for i, arg in enumerate(args):
            if i < len(params):
                key = params[i]
                attrs[f"tool.input.{key}"] = _summarize(arg)
        for key, val in kwargs.items():
            attrs[f"tool.input.{key}"] = _summarize(val)
    except (ValueError, TypeError):
        pass
    return attrs


def _summarize(value: Any, max_len: int = 200) -> str:
    """将任意值摘要为字符串"""
    s = str(value)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s
