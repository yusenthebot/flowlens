"""
FlowLens Auto-Instrumentation — Automatically patch popular LLM libraries.

Supported libraries:
- anthropic: Patches Anthropic.messages.create and AsyncAnthropic.messages.create
- openai: Patches OpenAI.chat.completions.create and async variant (including
          legacy openai.ChatCompletion.create and acreate); handles streaming
- langchain: Patches BaseLanguageModel.invoke/ainvoke, Chain.__call__, and
             AgentExecutor._call if available

Usage:
    from flowlens.sdk.auto_instrument import auto_instrument
    auto_instrument(["anthropic", "openai", "langchain"])

Design principles:
- Each patch is idempotent: applying it multiple times is safe
- Missing libraries never raise ImportError — they are silently skipped
- Patches preserve the original function's signature and return value
- All instrumentation follows the same gen_ai.* attribute conventions
"""

from __future__ import annotations

import functools
import logging
from typing import Any

from .context import SpanContext
from .models import SpanKind, SpanStatus
from .tracer import FlowLens

logger = logging.getLogger(__name__)

# Registry of already-patched libraries to ensure idempotency
_patched: set[str] = set()


def auto_instrument(libraries: list[str]) -> None:
    """Automatically monkey-patch the specified LLM libraries.

    Args:
        libraries: List of library names to patch. Supported values:
                   "anthropic", "openai", "langchain".

    Example:
        auto_instrument(["anthropic", "openai", "langchain"])
    """
    for lib in libraries:
        lib_lower = lib.lower()
        if lib_lower in _patched:
            logger.debug(f"[FlowLens] {lib} already instrumented — skipping")
            continue

        if lib_lower == "anthropic":
            _patch_anthropic()
        elif lib_lower == "openai":
            _patch_openai()
        elif lib_lower == "langchain":
            _patch_langchain()
        else:
            logger.warning(f"[FlowLens] Unknown library for auto-instrumentation: {lib!r}")


# ===== Anthropic =====


def _patch_anthropic() -> None:
    """Monkey-patch anthropic.Anthropic and anthropic.AsyncAnthropic."""
    try:
        import anthropic  # type: ignore
    except ImportError:
        logger.debug("[FlowLens] anthropic not installed — skipping auto-instrumentation")
        return

    # Patch sync client
    try:
        original_create = anthropic.Anthropic.messages.create  # type: ignore[attr-defined]

        @functools.wraps(original_create)
        def patched_create(self: Any, *args: Any, **kwargs: Any) -> Any:
            model = kwargs.get("model", "")
            return _wrap_sync_llm_call(
                original_create,
                args=(self,) + args,
                kwargs=kwargs,
                model=model,
                system="anthropic",
                span_name="anthropic.messages.create",
            )

        anthropic.Anthropic.messages.create = patched_create  # type: ignore[attr-defined]
        logger.debug("[FlowLens] Patched anthropic.Anthropic.messages.create")
    except AttributeError as exc:
        logger.warning(f"[FlowLens] Could not patch anthropic.Anthropic.messages.create: {exc}")

    # Patch async client
    try:
        original_acreate = anthropic.AsyncAnthropic.messages.create  # type: ignore[attr-defined]

        @functools.wraps(original_acreate)
        async def patched_acreate(self: Any, *args: Any, **kwargs: Any) -> Any:
            model = kwargs.get("model", "")
            return await _wrap_async_llm_call(
                original_acreate,
                args=(self,) + args,
                kwargs=kwargs,
                model=model,
                system="anthropic",
                span_name="anthropic.messages.create",
            )

        anthropic.AsyncAnthropic.messages.create = patched_acreate  # type: ignore[attr-defined]
        logger.debug("[FlowLens] Patched anthropic.AsyncAnthropic.messages.create")
    except AttributeError as exc:
        logger.warning(
            f"[FlowLens] Could not patch anthropic.AsyncAnthropic.messages.create: {exc}"
        )

    _patched.add("anthropic")
    logger.info("[FlowLens] anthropic auto-instrumentation enabled")


# ===== OpenAI =====


def _patch_openai() -> None:
    """Monkey-patch OpenAI chat completions (new client API + legacy API).

    New client API (openai >= 1.0):
      openai.OpenAI().chat.completions.create(...)
      openai.AsyncOpenAI().chat.completions.create(...)

    Legacy API (openai < 1.0):
      openai.ChatCompletion.create(...)
      openai.ChatCompletion.acreate(...)

    Streaming responses (stream=True) are detected and handled via a
    generator wrapper that accumulates token usage from the final chunk.
    """
    try:
        import openai  # type: ignore
    except ImportError:
        logger.debug("[FlowLens] openai not installed — skipping auto-instrumentation")
        return

    # ---- New client API: openai.OpenAI (sync) ----
    try:
        original_create = openai.OpenAI.chat.completions.create  # type: ignore[attr-defined]

        @functools.wraps(original_create)
        def patched_create(self: Any, *args: Any, **kwargs: Any) -> Any:
            model = kwargs.get("model", "")
            stream = kwargs.get("stream", False)
            if stream:
                return _wrap_sync_stream_call(
                    original_create,
                    args=(self,) + args,
                    kwargs=kwargs,
                    model=model,
                    system="openai",
                    span_name="openai.chat.completions.create",
                )
            return _wrap_sync_llm_call(
                original_create,
                args=(self,) + args,
                kwargs=kwargs,
                model=model,
                system="openai",
                span_name="openai.chat.completions.create",
            )

        openai.OpenAI.chat.completions.create = patched_create  # type: ignore[attr-defined]
        logger.debug("[FlowLens] Patched openai.OpenAI.chat.completions.create")
    except AttributeError as exc:
        logger.warning(f"[FlowLens] Could not patch openai.OpenAI.chat.completions.create: {exc}")

    # ---- New client API: openai.AsyncOpenAI (async) ----
    try:
        original_acreate = openai.AsyncOpenAI.chat.completions.create  # type: ignore[attr-defined]

        # Async generators and coroutines cannot be combined in a single function
        # (using both `yield` and `return <value>` is a SyntaxError in Python).
        # We use two separate callables and dispatch from a regular function.
        async def _acreate_stream(self: Any, *args: Any, **kwargs: Any) -> Any:
            """Async generator variant — used when stream=True."""
            model = kwargs.get("model", "")
            async for chunk in _wrap_async_stream_call(
                original_acreate,
                args=(self,) + args,
                kwargs=kwargs,
                model=model,
                system="openai",
                span_name="openai.chat.completions.create",
            ):
                yield chunk

        async def _acreate_normal(self: Any, *args: Any, **kwargs: Any) -> Any:
            """Coroutine variant — used when stream=False (default)."""
            model = kwargs.get("model", "")
            return await _wrap_async_llm_call(
                original_acreate,
                args=(self,) + args,
                kwargs=kwargs,
                model=model,
                system="openai",
                span_name="openai.chat.completions.create",
            )

        @functools.wraps(original_acreate)
        def patched_acreate(self: Any, *args: Any, **kwargs: Any) -> Any:
            if kwargs.get("stream", False):
                return _acreate_stream(self, *args, **kwargs)
            return _acreate_normal(self, *args, **kwargs)

        openai.AsyncOpenAI.chat.completions.create = patched_acreate  # type: ignore[attr-defined]
        logger.debug("[FlowLens] Patched openai.AsyncOpenAI.chat.completions.create")
    except AttributeError as exc:
        logger.warning(
            f"[FlowLens] Could not patch openai.AsyncOpenAI.chat.completions.create: {exc}"
        )

    # ---- Legacy API: openai.ChatCompletion.create / acreate (openai < 1.0) ----
    try:
        chat_completion_cls = getattr(openai, "ChatCompletion", None)
        if chat_completion_cls is not None:
            # Sync legacy
            if hasattr(chat_completion_cls, "create"):
                original_legacy_create = chat_completion_cls.create

                @functools.wraps(original_legacy_create)
                def patched_legacy_create(*args: Any, **kwargs: Any) -> Any:
                    model = kwargs.get("model", args[0] if args else "")
                    stream = kwargs.get("stream", False)
                    if stream:
                        return _wrap_sync_stream_call(
                            original_legacy_create,
                            args=args,
                            kwargs=kwargs,
                            model=model,
                            system="openai",
                            span_name="openai.ChatCompletion.create",
                        )
                    return _wrap_sync_llm_call(
                        original_legacy_create,
                        args=args,
                        kwargs=kwargs,
                        model=model,
                        system="openai",
                        span_name="openai.ChatCompletion.create",
                    )

                chat_completion_cls.create = patched_legacy_create
                logger.debug("[FlowLens] Patched openai.ChatCompletion.create (legacy)")

            # Async legacy
            if hasattr(chat_completion_cls, "acreate"):
                original_legacy_acreate = chat_completion_cls.acreate

                @functools.wraps(original_legacy_acreate)
                async def patched_legacy_acreate(*args: Any, **kwargs: Any) -> Any:
                    model = kwargs.get("model", args[0] if args else "")
                    return await _wrap_async_llm_call(
                        original_legacy_acreate,
                        args=args,
                        kwargs=kwargs,
                        model=model,
                        system="openai",
                        span_name="openai.ChatCompletion.acreate",
                    )

                chat_completion_cls.acreate = patched_legacy_acreate
                logger.debug("[FlowLens] Patched openai.ChatCompletion.acreate (legacy)")
    except Exception as exc:
        logger.debug(f"[FlowLens] Legacy openai.ChatCompletion patch skipped: {exc}")

    _patched.add("openai")
    logger.info("[FlowLens] openai auto-instrumentation enabled")


# ===== LangChain =====


def _patch_langchain() -> None:
    """Monkey-patch LangChain LLMs, Chains, and AgentExecutors.

    Patches applied (each is attempted independently; missing classes are silently skipped):

    1. langchain_core.language_models.base.BaseLanguageModel.invoke / ainvoke
       — captures LLM calls made through the LangChain interface.

    2. langchain.chains.base.Chain.__call__
       — captures full chain executions (inputs, outputs, chain name).

    3. langchain.agents.agent.AgentExecutor._call
       — captures agent loop executions (inputs, outputs).
    """
    langchain_core_available = False
    try:
        from langchain_core.language_models.base import BaseLanguageModel  # type: ignore

        langchain_core_available = True
    except ImportError:
        pass

    # Also accept a bare "langchain" package for older installations
    langchain_available = False
    try:
        import langchain  # type: ignore  # noqa: F401

        langchain_available = True
    except ImportError:
        pass

    if not langchain_core_available and not langchain_available:
        logger.debug(
            "[FlowLens] langchain / langchain_core not installed — skipping auto-instrumentation"
        )
        return

    # ---- 1. BaseLanguageModel.invoke / ainvoke ----
    if langchain_core_available:
        try:
            from langchain_core.language_models.base import BaseLanguageModel  # type: ignore

            original_invoke = BaseLanguageModel.invoke

            @functools.wraps(original_invoke)
            def patched_invoke(self: Any, *args: Any, **kwargs: Any) -> Any:
                model = (
                    getattr(self, "model_name", None) or getattr(self, "model", "") or "langchain"
                )
                return _wrap_sync_llm_call(
                    original_invoke,
                    args=(self,) + args,
                    kwargs=kwargs,
                    model=model,
                    system="langchain",
                    span_name="langchain.llm.invoke",
                )

            BaseLanguageModel.invoke = patched_invoke  # type: ignore[method-assign]
            logger.debug("[FlowLens] Patched BaseLanguageModel.invoke")
        except AttributeError as exc:
            logger.warning(f"[FlowLens] Could not patch BaseLanguageModel.invoke: {exc}")

        try:
            from langchain_core.language_models.base import BaseLanguageModel  # type: ignore

            original_ainvoke = BaseLanguageModel.ainvoke

            @functools.wraps(original_ainvoke)
            async def patched_ainvoke(self: Any, *args: Any, **kwargs: Any) -> Any:
                model = (
                    getattr(self, "model_name", None) or getattr(self, "model", "") or "langchain"
                )
                return await _wrap_async_llm_call(
                    original_ainvoke,
                    args=(self,) + args,
                    kwargs=kwargs,
                    model=model,
                    system="langchain",
                    span_name="langchain.llm.ainvoke",
                )

            BaseLanguageModel.ainvoke = patched_ainvoke  # type: ignore[method-assign]
            logger.debug("[FlowLens] Patched BaseLanguageModel.ainvoke")
        except AttributeError as exc:
            logger.warning(f"[FlowLens] Could not patch BaseLanguageModel.ainvoke: {exc}")

    # ---- 2. langchain.chains.base.Chain.__call__ ----
    try:
        from langchain.chains.base import Chain  # type: ignore

        original_chain_call = Chain.__call__

        @functools.wraps(original_chain_call)
        def patched_chain_call(self: Any, *args: Any, **kwargs: Any) -> Any:
            chain_name = getattr(self, "chain_type", None) or type(self).__name__
            return _wrap_sync_chain_call(
                original_chain_call,
                args=(self,) + args,
                kwargs=kwargs,
                chain_name=chain_name,
                span_name=f"langchain.chain.{chain_name}",
            )

        Chain.__call__ = patched_chain_call  # type: ignore[method-assign]
        logger.debug("[FlowLens] Patched langchain.chains.base.Chain.__call__")
    except (ImportError, AttributeError) as exc:
        logger.debug(f"[FlowLens] langchain.chains.base.Chain.__call__ not patched: {exc}")

    # ---- 3. langchain.agents.agent.AgentExecutor._call ----
    try:
        from langchain.agents.agent import AgentExecutor  # type: ignore

        original_agent_call = AgentExecutor._call

        @functools.wraps(original_agent_call)
        def patched_agent_call(self: Any, *args: Any, **kwargs: Any) -> Any:
            agent_name = getattr(self, "name", None) or type(self).__name__
            return _wrap_sync_chain_call(
                original_agent_call,
                args=(self,) + args,
                kwargs=kwargs,
                chain_name=agent_name,
                span_name=f"langchain.agent.{agent_name}",
            )

        AgentExecutor._call = patched_agent_call  # type: ignore[method-assign]
        logger.debug("[FlowLens] Patched langchain.agents.agent.AgentExecutor._call")
    except (ImportError, AttributeError) as exc:
        logger.debug(f"[FlowLens] langchain.agents.agent.AgentExecutor._call not patched: {exc}")

    _patched.add("langchain")
    logger.info("[FlowLens] langchain auto-instrumentation enabled")


# ===== Shared wrap helpers =====


def _build_span_attrs(
    model: str,
    system: str,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Build standard gen_ai.* span attributes from a call's kwargs."""
    attrs: dict[str, Any] = {
        "gen_ai.system": system,
        "gen_ai.request.model": model,
    }

    # Capture prompt/messages summary (truncated)
    messages = kwargs.get("messages") or kwargs.get("input") or kwargs.get("prompt")
    if messages is not None:
        attrs["gen_ai.request.messages"] = _truncate(str(messages), max_len=500)

    max_tokens = kwargs.get("max_tokens") or kwargs.get("max_completion_tokens")
    if max_tokens is not None:
        attrs["gen_ai.request.max_tokens"] = max_tokens

    temperature = kwargs.get("temperature")
    if temperature is not None:
        attrs["gen_ai.request.temperature"] = temperature

    return attrs


def _extract_usage_from_response(response: Any, model: str, span: Any) -> None:
    """Extract token usage from an LLM response and attach it to the span."""
    input_tokens = 0
    output_tokens = 0

    try:
        # Anthropic SDK: response.usage.input_tokens / output_tokens
        if hasattr(response, "usage"):
            usage = response.usage
            input_tokens = getattr(usage, "input_tokens", 0) or getattr(usage, "prompt_tokens", 0)
            output_tokens = getattr(usage, "output_tokens", 0) or getattr(
                usage, "completion_tokens", 0
            )

        # OpenAI dict-style response
        elif isinstance(response, dict) and "usage" in response:
            usage = response["usage"]
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)

        # LangChain AIMessage / generation_info
        elif hasattr(response, "response_metadata"):
            meta = response.response_metadata or {}
            token_usage = meta.get("token_usage") or meta.get("usage", {})
            if isinstance(token_usage, dict):
                input_tokens = token_usage.get("prompt_tokens", 0) or token_usage.get(
                    "input_tokens", 0
                )
                output_tokens = token_usage.get("completion_tokens", 0) or token_usage.get(
                    "output_tokens", 0
                )

        # Record output content summary
        output_text = _extract_output_text(response)
        if output_text:
            span.attributes["gen_ai.response.text"] = _truncate(output_text, max_len=500)

    except Exception as exc:
        logger.debug(f"[FlowLens] Could not extract token usage: {exc}")

    if input_tokens or output_tokens:
        span.set_token_usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
        )
        span.attributes["gen_ai.usage.input_tokens"] = input_tokens
        span.attributes["gen_ai.usage.output_tokens"] = output_tokens
        span.attributes["gen_ai.response.model"] = model


def _extract_output_text(response: Any) -> str:
    """Best-effort extraction of generated text from an LLM response."""
    try:
        # Anthropic Message
        if hasattr(response, "content") and isinstance(response.content, list):
            parts = []
            for block in response.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
            return " ".join(parts)
        # OpenAI ChatCompletion object
        if hasattr(response, "choices") and response.choices:
            choice = response.choices[0]
            if hasattr(choice, "message") and hasattr(choice.message, "content"):
                return choice.message.content or ""
        # LangChain AIMessage
        if hasattr(response, "content") and isinstance(response.content, str):
            return response.content
        # Raw string
        if isinstance(response, str):
            return response
    except Exception:
        pass
    return ""


def _wrap_sync_llm_call(
    func: Any,
    args: tuple,
    kwargs: dict[str, Any],
    model: str,
    system: str,
    span_name: str,
) -> Any:
    """Execute *func* synchronously inside a FlowLens LLM span."""
    lens = FlowLens.get_instance()
    if not lens:
        return func(*args, **kwargs)

    span_attrs = _build_span_attrs(model, system, kwargs)
    span = lens.start_span(span_name, kind=SpanKind.LLM, attributes=span_attrs)

    with SpanContext(span):
        try:
            result = func(*args, **kwargs)
            _extract_usage_from_response(result, model, span)
            span.finish(status=SpanStatus.OK)
            return result
        except Exception as exc:
            span.finish(status=SpanStatus.ERROR, error=str(exc))
            span.error_type = type(exc).__name__
            raise


async def _wrap_async_llm_call(
    func: Any,
    args: tuple,
    kwargs: dict[str, Any],
    model: str,
    system: str,
    span_name: str,
) -> Any:
    """Execute *func* asynchronously inside a FlowLens LLM span."""
    lens = FlowLens.get_instance()
    if not lens:
        return await func(*args, **kwargs)

    span_attrs = _build_span_attrs(model, system, kwargs)
    span = lens.start_span(span_name, kind=SpanKind.LLM, attributes=span_attrs)

    with SpanContext(span):
        try:
            result = await func(*args, **kwargs)
            _extract_usage_from_response(result, model, span)
            span.finish(status=SpanStatus.OK)
            return result
        except Exception as exc:
            span.finish(status=SpanStatus.ERROR, error=str(exc))
            span.error_type = type(exc).__name__
            raise


def _wrap_sync_chain_call(
    func: Any,
    args: tuple,
    kwargs: dict[str, Any],
    chain_name: str,
    span_name: str,
) -> Any:
    """Execute a LangChain chain or agent call inside a FlowLens CHAIN span.

    Captures:
    - chain.name: the LangChain class/chain type name
    - chain.inputs: summary of inputs
    - chain.outputs: summary of outputs
    """
    lens = FlowLens.get_instance()
    if not lens:
        return func(*args, **kwargs)

    # Capture inputs from first positional arg (inputs dict) or kwargs
    inputs = args[1] if len(args) > 1 else kwargs
    span_attrs: dict[str, Any] = {
        "chain.name": chain_name,
        "chain.inputs": _truncate(str(inputs), max_len=500),
    }
    span = lens.start_span(span_name, kind=SpanKind.CHAIN, attributes=span_attrs)

    with SpanContext(span):
        try:
            result = func(*args, **kwargs)
            span.attributes["chain.outputs"] = _truncate(str(result), max_len=500)
            span.finish(status=SpanStatus.OK)
            return result
        except Exception as exc:
            span.finish(status=SpanStatus.ERROR, error=str(exc))
            span.error_type = type(exc).__name__
            raise


def _wrap_sync_stream_call(
    func: Any,
    args: tuple,
    kwargs: dict[str, Any],
    model: str,
    system: str,
    span_name: str,
) -> Any:
    """Execute a streaming LLM call synchronously, accumulating token usage.

    Returns a generator that transparently proxies chunks to the caller while
    recording token usage and output text in the span when the stream ends.
    """
    lens = FlowLens.get_instance()
    if not lens:
        return func(*args, **kwargs)

    span_attrs = _build_span_attrs(model, system, kwargs)
    span_attrs["gen_ai.streaming"] = True
    span = lens.start_span(span_name, kind=SpanKind.LLM, attributes=span_attrs)

    def _generator():
        input_tokens = 0
        output_tokens = 0
        output_parts: list[str] = []

        with SpanContext(span):
            try:
                for chunk in func(*args, **kwargs):
                    # OpenAI streaming chunks
                    if hasattr(chunk, "choices") and chunk.choices:
                        delta = getattr(chunk.choices[0], "delta", None)
                        content = getattr(delta, "content", "") if delta else ""
                        if content:
                            output_parts.append(content)
                        usage = getattr(chunk, "usage", None)
                        if usage:
                            input_tokens = getattr(usage, "prompt_tokens", input_tokens)
                            output_tokens = getattr(usage, "completion_tokens", output_tokens)
                    # Generic text fallback
                    else:
                        text = getattr(chunk, "text", None) or getattr(chunk, "content", None)
                        if isinstance(text, str):
                            output_parts.append(text)
                    yield chunk

                # Estimate tokens if not provided by API
                if not output_tokens and output_parts:
                    output_tokens = max(1, len("".join(output_parts)) // 4)

                if input_tokens or output_tokens:
                    span.set_token_usage(
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        model=model,
                    )
                    span.attributes["gen_ai.usage.input_tokens"] = input_tokens
                    span.attributes["gen_ai.usage.output_tokens"] = output_tokens
                    span.attributes["gen_ai.response.model"] = model

                if output_parts:
                    full_text = "".join(output_parts)
                    span.attributes["gen_ai.response.text"] = _truncate(full_text, max_len=500)

                span.finish(status=SpanStatus.OK)

            except Exception as exc:
                span.finish(status=SpanStatus.ERROR, error=str(exc))
                span.error_type = type(exc).__name__
                raise

    return _generator()


async def _wrap_async_stream_call(
    func: Any,
    args: tuple,
    kwargs: dict[str, Any],
    model: str,
    system: str,
    span_name: str,
) -> Any:
    """Execute a streaming LLM call asynchronously, accumulating token usage.

    This is an async generator that transparently proxies chunks to the caller
    while recording token usage and output text in the span when the stream ends.
    """
    lens = FlowLens.get_instance()
    if not lens:
        async for chunk in func(*args, **kwargs):
            yield chunk
        return

    span_attrs = _build_span_attrs(model, system, kwargs)
    span_attrs["gen_ai.streaming"] = True
    span = lens.start_span(span_name, kind=SpanKind.LLM, attributes=span_attrs)

    input_tokens = 0
    output_tokens = 0
    output_parts: list[str] = []

    with SpanContext(span):
        try:
            async for chunk in func(*args, **kwargs):
                # OpenAI streaming chunks
                if hasattr(chunk, "choices") and chunk.choices:
                    delta = getattr(chunk.choices[0], "delta", None)
                    content = getattr(delta, "content", "") if delta else ""
                    if content:
                        output_parts.append(content)
                    usage = getattr(chunk, "usage", None)
                    if usage:
                        input_tokens = getattr(usage, "prompt_tokens", input_tokens)
                        output_tokens = getattr(usage, "completion_tokens", output_tokens)
                # Generic text fallback
                else:
                    text = getattr(chunk, "text", None) or getattr(chunk, "content", None)
                    if isinstance(text, str):
                        output_parts.append(text)
                yield chunk

            if not output_tokens and output_parts:
                output_tokens = max(1, len("".join(output_parts)) // 4)

            if input_tokens or output_tokens:
                span.set_token_usage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    model=model,
                )
                span.attributes["gen_ai.usage.input_tokens"] = input_tokens
                span.attributes["gen_ai.usage.output_tokens"] = output_tokens
                span.attributes["gen_ai.response.model"] = model

            if output_parts:
                full_text = "".join(output_parts)
                span.attributes["gen_ai.response.text"] = _truncate(full_text, max_len=500)

            span.finish(status=SpanStatus.OK)

        except Exception as exc:
            span.finish(status=SpanStatus.ERROR, error=str(exc))
            span.error_type = type(exc).__name__
            raise


def _truncate(text: str, max_len: int = 500) -> str:
    """Truncate a string to *max_len* characters, appending '...' if cut."""
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text
