"""
FlowLens 装饰器 — 零侵入采集 Agent 执行 trace

核心装饰器：
- @trace_agent: 装饰 Agent 主循环，创建 trace + root span
- @trace_llm: 装饰 LLM 调用，记录 token 用量和成本
- @trace_llm_stream: 装饰流式 LLM 调用，累积 token 用量
- @trace_tool: 装饰 Tool/Skill 执行，记录参数和结果

设计原则：
- 装饰器只做采集，不改变原函数行为
- 异常透传：装饰器不吞异常，但会记录错误
- 异步优先：支持 async 和 sync 函数
"""

from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import Callable
from typing import Any

from .context import SpanContext, TraceContext
from .models import Span, SpanKind, SpanStatus
from .tracer import FlowLens

logger = logging.getLogger(__name__)


def trace_agent(
    name: str = "agent",
    metadata: dict | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    experiment: str | None = None,
    tags: dict | None = None,
    **attrs: Any,
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

            trace = lens.start_trace(
                metadata=metadata,
                user_id=user_id,
                session_id=session_id,
                experiment=experiment,
                tags=tags,
            )

            with TraceContext(trace):
                span = lens.start_span(name, kind=SpanKind.AGENT, attributes=attrs or {})

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

            trace = lens.start_trace(
                metadata=metadata,
                user_id=user_id,
                session_id=session_id,
                experiment=experiment,
                tags=tags,
            )

            with TraceContext(trace):
                span = lens.start_span(name, kind=SpanKind.AGENT, attributes=attrs or {})

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

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def trace_llm(
    model: str = "",
    name: str | None = None,
    **attrs: Any,
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

            span_attrs = {
                "gen_ai.system": "anthropic" if "claude" in model.lower() else "openai",
                "gen_ai.request.model": model,
            }
            span_attrs.update(attrs or {})
            span = lens.start_span(
                span_name,
                kind=SpanKind.LLM,
                attributes=span_attrs,
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

            span_attrs = {
                "gen_ai.system": "anthropic" if "claude" in model.lower() else "openai",
                "gen_ai.request.model": model,
            }
            span_attrs.update(attrs or {})
            span = lens.start_span(
                span_name,
                kind=SpanKind.LLM,
                attributes=span_attrs,
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

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def trace_llm_stream(
    model: str = "",
    name: str | None = None,
    **attrs: Any,
) -> Callable:
    """Decorate a streaming LLM call.

    The decorated function must be a generator (sync) or async generator that
    yields stream chunks from Anthropic or OpenAI streaming APIs.  FlowLens
    transparently proxies each yielded chunk to the caller while accumulating
    token usage.  When the stream is exhausted the span is finished and token
    usage is recorded.

    Supported chunk formats:
    - Anthropic streaming: chunks with ``type`` in
      {"content_block_delta", "message_delta", "message_start"} and
      usage in ``message_start`` / ``message_delta``.
    - OpenAI streaming: chunks with ``choices[0].delta.content`` and
      optional ``usage`` on the final chunk.
    - Any chunk with a ``text`` or ``content`` string attribute is
      treated as output text (fallback).

    Args:
        model: LLM model name (used for cost calculation).
        name: Span name override; defaults to the decorated function name.
        **attrs: Extra span attributes forwarded verbatim.

    Example (async generator)::

        @trace_llm_stream(model="claude-sonnet-4-20250514")
        async def stream_response(messages):
            async with client.messages.stream(model="...", messages=messages) as s:
                async for chunk in s:
                    yield chunk

        async for chunk in stream_response(messages):
            print(chunk)

    Example (sync generator)::

        @trace_llm_stream(model="gpt-4.1")
        def stream_response(messages):
            for chunk in openai_client.chat.completions.create(
                model="gpt-4.1", messages=messages, stream=True
            ):
                yield chunk
    """

    def decorator(func: Callable) -> Callable:
        span_name = name or func.__name__

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            lens = FlowLens.get_instance()
            if not lens:
                async for chunk in func(*args, **kwargs):
                    yield chunk
                return

            span_attrs: dict[str, Any] = {
                "gen_ai.system": "anthropic" if "claude" in model.lower() else "openai",
                "gen_ai.request.model": model,
                "gen_ai.streaming": True,
            }
            span_attrs.update(attrs or {})
            span = lens.start_span(span_name, kind=SpanKind.LLM, attributes=span_attrs)

            input_tokens = 0
            output_tokens = 0
            output_text_parts: list[str] = []

            with SpanContext(span):
                try:
                    async for chunk in func(*args, **kwargs):
                        # --- accumulate Anthropic streaming usage ---
                        chunk_type = getattr(chunk, "type", None)
                        if chunk_type == "message_start":
                            usage = getattr(chunk, "message", None)
                            if usage:
                                usage = getattr(usage, "usage", None)
                            if usage:
                                input_tokens += getattr(usage, "input_tokens", 0)
                        elif chunk_type == "message_delta":
                            usage = getattr(chunk, "usage", None)
                            if usage:
                                output_tokens += getattr(usage, "output_tokens", 0)
                        elif chunk_type == "content_block_delta":
                            delta = getattr(chunk, "delta", None)
                            text = getattr(delta, "text", "") if delta else ""
                            if text:
                                output_text_parts.append(text)

                        # --- accumulate OpenAI streaming usage ---
                        elif hasattr(chunk, "choices") and chunk.choices:
                            delta = getattr(chunk.choices[0], "delta", None)
                            content = getattr(delta, "content", "") if delta else ""
                            if content:
                                output_text_parts.append(content)
                            # OpenAI sends usage on the last chunk when
                            # stream_options={"include_usage": True}
                            usage = getattr(chunk, "usage", None)
                            if usage:
                                input_tokens = getattr(usage, "prompt_tokens", input_tokens)
                                output_tokens = getattr(usage, "completion_tokens", output_tokens)

                        # --- generic fallback ---
                        else:
                            text = getattr(chunk, "text", None) or getattr(chunk, "content", None)
                            if isinstance(text, str):
                                output_text_parts.append(text)

                        yield chunk

                    # Estimate output tokens from accumulated text if not
                    # provided by the API (4 chars ≈ 1 token heuristic)
                    if not output_tokens and output_text_parts:
                        output_tokens = _estimate_tokens_from_text("".join(output_text_parts))

                    if input_tokens or output_tokens:
                        span.set_token_usage(
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            model=model,
                        )
                        span.attributes["gen_ai.usage.input_tokens"] = input_tokens
                        span.attributes["gen_ai.usage.output_tokens"] = output_tokens
                        span.attributes["gen_ai.response.model"] = model

                    if output_text_parts:
                        full_text = "".join(output_text_parts)
                        span.attributes["gen_ai.response.text"] = (
                            full_text[:500] + "..." if len(full_text) > 500 else full_text
                        )

                    span.finish(status=SpanStatus.OK)

                except Exception as e:
                    span.finish(status=SpanStatus.ERROR, error=str(e))
                    span.error_type = type(e).__name__
                    raise

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            lens = FlowLens.get_instance()
            if not lens:
                yield from func(*args, **kwargs)
                return

            span_attrs: dict[str, Any] = {
                "gen_ai.system": "anthropic" if "claude" in model.lower() else "openai",
                "gen_ai.request.model": model,
                "gen_ai.streaming": True,
            }
            span_attrs.update(attrs or {})
            span = lens.start_span(span_name, kind=SpanKind.LLM, attributes=span_attrs)

            input_tokens = 0
            output_tokens = 0
            output_text_parts: list[str] = []

            with SpanContext(span):
                try:
                    for chunk in func(*args, **kwargs):
                        chunk_type = getattr(chunk, "type", None)
                        if chunk_type == "message_start":
                            usage = getattr(chunk, "message", None)
                            if usage:
                                usage = getattr(usage, "usage", None)
                            if usage:
                                input_tokens += getattr(usage, "input_tokens", 0)
                        elif chunk_type == "message_delta":
                            usage = getattr(chunk, "usage", None)
                            if usage:
                                output_tokens += getattr(usage, "output_tokens", 0)
                        elif chunk_type == "content_block_delta":
                            delta = getattr(chunk, "delta", None)
                            text = getattr(delta, "text", "") if delta else ""
                            if text:
                                output_text_parts.append(text)
                        elif hasattr(chunk, "choices") and chunk.choices:
                            delta = getattr(chunk.choices[0], "delta", None)
                            content = getattr(delta, "content", "") if delta else ""
                            if content:
                                output_text_parts.append(content)
                            usage = getattr(chunk, "usage", None)
                            if usage:
                                input_tokens = getattr(usage, "prompt_tokens", input_tokens)
                                output_tokens = getattr(usage, "completion_tokens", output_tokens)
                        else:
                            text = getattr(chunk, "text", None) or getattr(chunk, "content", None)
                            if isinstance(text, str):
                                output_text_parts.append(text)

                        yield chunk

                    if not output_tokens and output_text_parts:
                        output_tokens = _estimate_tokens_from_text("".join(output_text_parts))

                    if input_tokens or output_tokens:
                        span.set_token_usage(
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            model=model,
                        )
                        span.attributes["gen_ai.usage.input_tokens"] = input_tokens
                        span.attributes["gen_ai.usage.output_tokens"] = output_tokens
                        span.attributes["gen_ai.response.model"] = model

                    if output_text_parts:
                        full_text = "".join(output_text_parts)
                        span.attributes["gen_ai.response.text"] = (
                            full_text[:500] + "..." if len(full_text) > 500 else full_text
                        )

                    span.finish(status=SpanStatus.OK)

                except Exception as e:
                    span.finish(status=SpanStatus.ERROR, error=str(e))
                    span.error_type = type(e).__name__
                    raise

        if inspect.isasyncgenfunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def trace_tool(
    name: str | None = None,
    **attrs: Any,
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
            span_attrs = _capture_params(func, args, kwargs)
            span_attrs.update(attrs or {})
            span = lens.start_span(
                span_name,
                kind=SpanKind.TOOL,
                attributes=span_attrs,
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

            span_attrs = _capture_params(func, args, kwargs)
            span_attrs.update(attrs or {})
            span = lens.start_span(
                span_name,
                kind=SpanKind.TOOL,
                attributes=span_attrs,
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

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def trace_chain(
    name: str = "chain",
    **attrs: Any,
) -> Callable:
    """
    装饰链/管道步骤 — 多个 LLM 调用或 tool 执行的组合

    - 创建 span (kind=CHAIN)
    - 记录链的整体执行时间和结果
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            lens = FlowLens.get_instance()
            if not lens:
                return await func(*args, **kwargs)

            span_attrs = attrs or {}
            span = lens.start_span(
                name,
                kind=SpanKind.CHAIN,
                attributes=span_attrs,
            )

            with SpanContext(span):
                try:
                    result = await func(*args, **kwargs)
                    span.attributes["chain.output_summary"] = _summarize(result)
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

            span_attrs = attrs or {}
            span = lens.start_span(
                name,
                kind=SpanKind.CHAIN,
                attributes=span_attrs,
            )

            with SpanContext(span):
                try:
                    result = func(*args, **kwargs)
                    span.attributes["chain.output_summary"] = _summarize(result)
                    span.finish(status=SpanStatus.OK)
                    return result
                except Exception as e:
                    span.finish(status=SpanStatus.ERROR, error=str(e))
                    span.error_type = type(e).__name__
                    raise

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def trace_retrieval(
    name: str = "retrieval",
    **attrs: Any,
) -> Callable:
    """
    装饰 RAG 检索步骤

    - 创建 span (kind=RETRIEVAL)
    - 记录检索的文档数、相关性分数等
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            lens = FlowLens.get_instance()
            if not lens:
                return await func(*args, **kwargs)

            span_attrs = attrs or {}
            span = lens.start_span(
                name,
                kind=SpanKind.RETRIEVAL,
                attributes=span_attrs,
            )

            with SpanContext(span):
                try:
                    result = await func(*args, **kwargs)
                    # 尝试记录检索结果的数量
                    if isinstance(result, (list, tuple)):
                        span.attributes["retrieval.result_count"] = len(result)
                    elif isinstance(result, dict) and "results" in result:
                        span.attributes["retrieval.result_count"] = len(result.get("results", []))
                    span.attributes["retrieval.output_summary"] = _summarize(result)
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

            span_attrs = attrs or {}
            span = lens.start_span(
                name,
                kind=SpanKind.RETRIEVAL,
                attributes=span_attrs,
            )

            with SpanContext(span):
                try:
                    result = func(*args, **kwargs)
                    # 尝试记录检索结果的数量
                    if isinstance(result, (list, tuple)):
                        span.attributes["retrieval.result_count"] = len(result)
                    elif isinstance(result, dict) and "results" in result:
                        span.attributes["retrieval.result_count"] = len(result.get("results", []))
                    span.attributes["retrieval.output_summary"] = _summarize(result)
                    span.finish(status=SpanStatus.OK)
                    return result
                except Exception as e:
                    span.finish(status=SpanStatus.ERROR, error=str(e))
                    span.error_type = type(e).__name__
                    raise

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def trace_embedding(
    model: str = "",
    name: str | None = None,
    **attrs: Any,
) -> Callable:
    """Decorate an embedding API call.

    Creates a span of kind EMBEDDING and captures:
    - ``embedding.model``: the model name
    - ``embedding.token_count``: total tokens used (from response usage if available)
    - ``embedding.dimension``: vector dimension (from the first embedding in the response)
    - ``embedding.input_count``: number of inputs embedded

    Args:
        model: Embedding model name (e.g. "text-embedding-3-small").
        name: Span name override; defaults to the decorated function name.
        **attrs: Extra span attributes forwarded verbatim.

    Example (sync)::

        @trace_embedding(model="text-embedding-3-small")
        def embed(texts: list[str]):
            return openai_client.embeddings.create(
                model="text-embedding-3-small", input=texts
            )

    Example (async)::

        @trace_embedding(model="text-embedding-3-small")
        async def embed_async(texts: list[str]):
            return await async_client.embeddings.create(
                model="text-embedding-3-small", input=texts
            )
    """

    def decorator(func: Callable) -> Callable:
        span_name = name or func.__name__

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            lens = FlowLens.get_instance()
            if not lens:
                return await func(*args, **kwargs)

            span_attrs: dict[str, Any] = {"embedding.model": model}
            span_attrs.update(attrs or {})
            span = lens.start_span(span_name, kind=SpanKind.EMBEDDING, attributes=span_attrs)

            with SpanContext(span):
                try:
                    result = await func(*args, **kwargs)
                    _extract_embedding_info(span, result, model)
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

            span_attrs: dict[str, Any] = {"embedding.model": model}
            span_attrs.update(attrs or {})
            span = lens.start_span(span_name, kind=SpanKind.EMBEDDING, attributes=span_attrs)

            with SpanContext(span):
                try:
                    result = func(*args, **kwargs)
                    _extract_embedding_info(span, result, model)
                    span.finish(status=SpanStatus.OK)
                    return result
                except Exception as e:
                    span.finish(status=SpanStatus.ERROR, error=str(e))
                    span.error_type = type(e).__name__
                    raise

        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# ===== Helper functions =====


def _extract_embedding_info(span: Any, result: Any, model: str) -> None:
    """Extract embedding metadata from an API response and attach it to the span.

    Supports:
    - OpenAI Embeddings SDK object: ``result.data`` list with ``embedding`` vectors,
      ``result.usage.total_tokens`` / ``prompt_tokens``.
    - Dict response: ``result["data"]`` / ``result["usage"]``.
    - Any object with ``embeddings`` attribute (generic fallback).

    Sets the following span attributes when available:
    - ``embedding.token_count``: total tokens used
    - ``embedding.dimension``: vector dimension (length of first embedding)
    - ``embedding.input_count``: number of embeddings in the response
    """
    try:
        # OpenAI SDK EmbeddingCreateResponse
        data_list = None
        usage = None

        if hasattr(result, "data") and hasattr(result, "usage"):
            data_list = result.data
            usage = result.usage
        elif isinstance(result, dict):
            data_list = result.get("data")
            usage = result.get("usage")
        elif hasattr(result, "embeddings"):
            # Some providers return .embeddings directly
            data_list = result.embeddings

        # Token count from usage
        if usage is not None:
            total_tokens = (
                getattr(usage, "total_tokens", 0)
                or getattr(usage, "prompt_tokens", 0)
                or (usage.get("total_tokens", 0) if isinstance(usage, dict) else 0)
                or (usage.get("prompt_tokens", 0) if isinstance(usage, dict) else 0)
            )
            if total_tokens:
                span.attributes["embedding.token_count"] = total_tokens

        # Input count and vector dimension
        if data_list is not None:
            try:
                count = len(data_list)
                span.attributes["embedding.input_count"] = count
                if count > 0:
                    first = data_list[0]
                    vector = (
                        getattr(first, "embedding", None)
                        or (first.get("embedding") if isinstance(first, dict) else None)
                        or (first if isinstance(first, (list, tuple)) else None)
                    )
                    if vector is not None:
                        span.attributes["embedding.dimension"] = len(vector)
            except (TypeError, IndexError):
                pass

        span.attributes["embedding.model"] = model

    except Exception as exc:
        logger.debug(f"[FlowLens] Could not extract embedding info: {exc}")


def _extract_llm_usage(span: Span, result: Any, model: str) -> None:
    """Extract token usage from an LLM response and attach it to the span.

    Supports the following response formats:
    - **Anthropic SDK**: ``result.usage.input_tokens`` / ``output_tokens``
    - **OpenAI SDK object**: ``result.usage.prompt_tokens`` / ``completion_tokens``
    - **OpenAI SDK dict**: ``result["usage"]["prompt_tokens"]`` / ``completion_tokens``
    - **Google Generative AI**: ``result.usage_metadata.prompt_token_count`` /
      ``candidates_token_count``
    - **LiteLLM**: ``result.usage.prompt_tokens`` / ``completion_tokens`` (same as
      OpenAI; also handles the ``ModelResponse`` dataclass)
    - **Amazon Bedrock**: ``result["ResponseMetadata"]`` / ``result["usage"]`` with
      ``inputTokens`` / ``outputTokens`` keys (Converse API) or
      ``result["metrics"]["inputTokenCount"]`` / ``outputTokenCount``
    - **Fallback heuristic**: if no usage data is found and the result contains
      extractable output text, token count is estimated at 4 chars ≈ 1 token.
    """
    input_tokens = 0
    output_tokens = 0
    found = False

    try:
        # ----- Anthropic SDK (object with .usage) -----
        if hasattr(result, "usage") and not isinstance(result, dict):
            usage = result.usage
            _in = getattr(usage, "input_tokens", 0)
            _out = getattr(usage, "output_tokens", 0)
            # LiteLLM / OpenAI SDK may use prompt_tokens / completion_tokens
            if not _in:
                _in = getattr(usage, "prompt_tokens", 0)
            if not _out:
                _out = getattr(usage, "completion_tokens", 0)
            input_tokens, output_tokens = _in, _out
            found = True

        # ----- Amazon Bedrock Converse API -----
        # Detected by "inputTokens" key (vs OpenAI's "prompt_tokens")
        elif isinstance(result, dict) and "usage" in result and isinstance(result["usage"], dict) and "inputTokens" in result["usage"]:
            usage = result["usage"]
            input_tokens = usage.get("inputTokens", 0)
            output_tokens = usage.get("outputTokens", 0)
            found = True

        # ----- Amazon Bedrock InvokeModel (metrics key) -----
        elif isinstance(result, dict) and "metrics" in result:
            metrics = result["metrics"]
            if isinstance(metrics, dict):
                input_tokens = metrics.get("inputTokenCount", 0)
                output_tokens = metrics.get("outputTokenCount", 0)
                found = True

        # ----- OpenAI / LiteLLM SDK dict -----
        elif isinstance(result, dict) and "usage" in result:
            usage = result["usage"]
            if isinstance(usage, dict):
                input_tokens = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)
                found = True

        # ----- Google Generative AI: usage_metadata -----
        elif hasattr(result, "usage_metadata"):
            usage = result.usage_metadata
            input_tokens = getattr(usage, "prompt_token_count", 0)
            output_tokens = getattr(usage, "candidates_token_count", 0)
            found = True

        # ----- Google Generative AI: candidates fallback -----
        elif hasattr(result, "candidates") and result.candidates:
            if hasattr(result.candidates[0], "token_count"):
                output_tokens = result.candidates[0].token_count
                found = True

    except Exception as exc:
        logger.debug(f"[FlowLens] Error extracting token usage: {exc}")

    # ----- Fallback: estimate from output text -----
    if not found or (not input_tokens and not output_tokens):
        output_text = _extract_output_text(result)
        if output_text:
            output_tokens = _estimate_tokens_from_text(output_text)

    if input_tokens or output_tokens:
        span.set_token_usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
        )
        span.attributes["gen_ai.usage.input_tokens"] = input_tokens
        span.attributes["gen_ai.usage.output_tokens"] = output_tokens
        span.attributes["gen_ai.response.model"] = model


def _extract_output_text(result: Any) -> str:
    """Best-effort extraction of generated text from an LLM response."""
    try:
        # Anthropic Message: list of content blocks
        if hasattr(result, "content") and isinstance(result.content, list):
            parts = [getattr(b, "text", "") for b in result.content if hasattr(b, "text")]
            return " ".join(p for p in parts if p)
        # OpenAI ChatCompletion object
        if hasattr(result, "choices") and result.choices:
            choice = result.choices[0]
            if hasattr(choice, "message") and hasattr(choice.message, "content"):
                return choice.message.content or ""
        # LangChain AIMessage / generic .content str
        if hasattr(result, "content") and isinstance(result.content, str):
            return result.content
        # Raw string response
        if isinstance(result, str):
            return result
        # Dict with "content" key
        if isinstance(result, dict) and "content" in result:
            return str(result["content"])
    except Exception:
        pass
    return ""


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


def _estimate_tokens_from_text(text: str) -> int:
    """Estimate token count from raw text using a 4-chars-per-token heuristic.

    This approximation is intentionally simple and avoids any dependency on
    tiktoken or other tokenizer libraries.  Use only as a last-resort fallback
    when no token usage data is available from the API response.

    Args:
        text: The text whose token count should be estimated.

    Returns:
        Estimated integer token count (minimum 0).
    """
    if not text:
        return 0
    return max(1, len(text) // 4)
