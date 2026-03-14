"""
FlowLens Auto-Instrumentation — Automatically patch popular LLM libraries.

Supported libraries:
- anthropic: Patches Anthropic.messages.create and AsyncAnthropic.messages.create
- openai: Patches OpenAI.chat.completions.create and async variant
- langchain: Patches BaseLanguageModel.invoke and ainvoke

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
import time
from typing import Any, Optional

from .models import SpanKind, SpanStatus
from .context import SpanContext, get_current_trace
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
                span_name=f"anthropic.messages.create",
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
        logger.warning(f"[FlowLens] Could not patch anthropic.AsyncAnthropic.messages.create: {exc}")

    _patched.add("anthropic")
    logger.info("[FlowLens] anthropic auto-instrumentation enabled")


# ===== OpenAI =====

def _patch_openai() -> None:
    """Monkey-patch openai.OpenAI and openai.AsyncOpenAI chat completions."""
    try:
        import openai  # type: ignore
    except ImportError:
        logger.debug("[FlowLens] openai not installed — skipping auto-instrumentation")
        return

    # Patch sync client
    try:
        original_create = openai.OpenAI.chat.completions.create  # type: ignore[attr-defined]

        @functools.wraps(original_create)
        def patched_create(self: Any, *args: Any, **kwargs: Any) -> Any:
            model = kwargs.get("model", "")
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

    # Patch async client
    try:
        original_acreate = openai.AsyncOpenAI.chat.completions.create  # type: ignore[attr-defined]

        @functools.wraps(original_acreate)
        async def patched_acreate(self: Any, *args: Any, **kwargs: Any) -> Any:
            model = kwargs.get("model", "")
            return await _wrap_async_llm_call(
                original_acreate,
                args=(self,) + args,
                kwargs=kwargs,
                model=model,
                system="openai",
                span_name="openai.chat.completions.create",
            )

        openai.AsyncOpenAI.chat.completions.create = patched_acreate  # type: ignore[attr-defined]
        logger.debug("[FlowLens] Patched openai.AsyncOpenAI.chat.completions.create")
    except AttributeError as exc:
        logger.warning(f"[FlowLens] Could not patch openai.AsyncOpenAI.chat.completions.create: {exc}")

    _patched.add("openai")
    logger.info("[FlowLens] openai auto-instrumentation enabled")


# ===== LangChain =====

def _patch_langchain() -> None:
    """Monkey-patch langchain_core BaseLanguageModel invoke / ainvoke."""
    try:
        from langchain_core.language_models.base import BaseLanguageModel  # type: ignore
    except ImportError:
        logger.debug("[FlowLens] langchain_core not installed — skipping auto-instrumentation")
        return

    # Patch sync invoke
    try:
        original_invoke = BaseLanguageModel.invoke

        @functools.wraps(original_invoke)
        def patched_invoke(self: Any, *args: Any, **kwargs: Any) -> Any:
            model = getattr(self, "model_name", None) or getattr(self, "model", "") or "langchain"
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

    # Patch async ainvoke
    try:
        original_ainvoke = BaseLanguageModel.ainvoke

        @functools.wraps(original_ainvoke)
        async def patched_ainvoke(self: Any, *args: Any, **kwargs: Any) -> Any:
            model = getattr(self, "model_name", None) or getattr(self, "model", "") or "langchain"
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
            output_tokens = getattr(usage, "output_tokens", 0) or getattr(usage, "completion_tokens", 0)

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
                input_tokens = token_usage.get("prompt_tokens", 0) or token_usage.get("input_tokens", 0)
                output_tokens = token_usage.get("completion_tokens", 0) or token_usage.get("output_tokens", 0)

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


def _truncate(text: str, max_len: int = 500) -> str:
    """Truncate a string to *max_len* characters, appending '...' if cut."""
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text
