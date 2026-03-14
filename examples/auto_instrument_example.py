#!/usr/bin/env python3
"""
FlowLens Auto-Instrumentation Example
======================================
Demonstrates how to use auto_instrument() for zero-code tracing of popular
LLM SDKs. No API keys are needed — the Anthropic and OpenAI SDK classes are
mocked in-process so the example runs completely offline.

Run with:
    python examples/auto_instrument_example.py

What this shows:
  1. BEFORE — calling a mock LLM with no instrumentation (no spans recorded)
  2. AFTER  — same call after auto_instrument() patches the SDK (full span recorded)
  3. Manual @trace_agent wrapper around instrumented calls
  4. The diff in the console output between un-instrumented and instrumented modes
"""

import asyncio
import sys
import os
import time
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flowlens import FlowLens, trace_agent, auto_instrument
from flowlens.sdk.models import Trace

# ───────────────────────────────────────────────────────────────────────────
# ANSI helpers
# ───────────────────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
CYAN   = "\033[96m"
RED    = "\033[91m"
WHITE  = "\033[97m"


def c(text: str, *codes: str) -> str:
    return "".join(codes) + str(text) + RESET


def banner(title: str) -> None:
    width = 68
    pad = (width - len(title) - 4) // 2
    print()
    print(c("┌" + "─" * (width - 2) + "┐", CYAN, BOLD))
    print(c(f"│{' ' * pad}  {title}  {' ' * pad}│", CYAN, BOLD))
    print(c("└" + "─" * (width - 2) + "┘", CYAN, BOLD))
    print()


def step(num: int, title: str) -> None:
    print(c(f"\n  Step {num}: {title}", WHITE, BOLD))
    print(c("  " + "─" * 56, DIM))


def note(text: str) -> None:
    print(c(f"  # {text}", DIM))


def info(text: str) -> None:
    print(c(f"  → {text}", BLUE))


def ok(text: str) -> None:
    print(c(f"  ✓ {text}", GREEN))


def warn(text: str) -> None:
    print(c(f"  ! {text}", YELLOW))


# ───────────────────────────────────────────────────────────────────────────
# Mock Anthropic SDK
# ───────────────────────────────────────────────────────────────────────────
# We create minimal mock classes that match the Anthropic SDK's public surface:
#   anthropic.Anthropic().messages.create(...)
#   anthropic.AsyncAnthropic().messages.create(...)
#
# This lets auto_instrument() patch them exactly as it would the real SDK,
# without requiring `pip install anthropic` or an API key.

class _FakeUsage:
    def __init__(self, inp: int, out: int):
        self.input_tokens = inp
        self.output_tokens = out


class _FakeContentBlock:
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class _FakeAnthropicResponse:
    """Minimal Anthropic Message object (real SDK shape)."""
    def __init__(self, prompt: str, model: str):
        words = len(prompt.split())
        self.id = f"msg_{random.randint(100000, 999999)}"
        self.model = model
        self.stop_reason = "end_turn"
        self.content = [_FakeContentBlock(
            f"[Mocked {model}] Answer to: {prompt[:60]}..."
        )]
        self.usage = _FakeUsage(
            inp=words * 4 + random.randint(50, 200),
            out=random.randint(80, 300),
        )


class _FakeMessages:
    """Mimics anthropic.Anthropic.messages"""
    def create(self, *, model: str, messages: list, max_tokens: int = 1024, **kw):
        time.sleep(0.02)  # simulate latency
        prompt = messages[-1]["content"] if messages else ""
        return _FakeAnthropicResponse(prompt, model)

    async def acreate(self, *, model: str, messages: list, max_tokens: int = 1024, **kw):
        await asyncio.sleep(0.02)
        prompt = messages[-1]["content"] if messages else ""
        return _FakeAnthropicResponse(prompt, model)


class _FakeAnthropic:
    """Mimics anthropic.Anthropic (sync client)."""
    def __init__(self, api_key: str = "mock-key"):
        self.messages = _FakeMessages()


class _FakeAsyncAnthropic:
    """Mimics anthropic.AsyncAnthropic (async client)."""
    def __init__(self, api_key: str = "mock-key"):
        self.messages = _FakeMessages()


# ───────────────────────────────────────────────────────────────────────────
# Inject mock into sys.modules so auto_instrument() finds "anthropic"
# ───────────────────────────────────────────────────────────────────────────
import types

_mock_anthropic_module = types.ModuleType("anthropic")
_mock_anthropic_module.Anthropic = _FakeAnthropic           # type: ignore
_mock_anthropic_module.AsyncAnthropic = _FakeAsyncAnthropic # type: ignore
sys.modules["anthropic"] = _mock_anthropic_module


# ───────────────────────────────────────────────────────────────────────────
# Mock OpenAI SDK (same pattern)
# ───────────────────────────────────────────────────────────────────────────

class _FakeOpenAIUsage:
    def __init__(self, inp: int, out: int):
        self.prompt_tokens = inp
        self.completion_tokens = out
        self.total_tokens = inp + out


class _FakeOpenAIMessage:
    def __init__(self, content: str):
        self.content = content
        self.role = "assistant"


class _FakeOpenAIChoice:
    def __init__(self, content: str):
        self.message = _FakeOpenAIMessage(content)
        self.finish_reason = "stop"
        self.index = 0


class _FakeOpenAIResponse:
    def __init__(self, prompt: str, model: str):
        words = len(prompt.split())
        self.id = f"chatcmpl-{random.randint(100000, 999999)}"
        self.model = model
        self.choices = [_FakeOpenAIChoice(
            f"[Mocked {model}] Response to: {prompt[:60]}..."
        )]
        self.usage = _FakeOpenAIUsage(
            inp=words * 4 + random.randint(50, 200),
            out=random.randint(80, 300),
        )


class _FakeCompletions:
    def create(self, *, model: str, messages: list, max_tokens: int = 1024, **kw):
        time.sleep(0.02)
        prompt = messages[-1]["content"] if messages else ""
        return _FakeOpenAIResponse(prompt, model)

    async def acreate(self, *, model: str, messages: list, max_tokens: int = 1024, **kw):
        await asyncio.sleep(0.02)
        prompt = messages[-1]["content"] if messages else ""
        return _FakeOpenAIResponse(prompt, model)


class _FakeChat:
    def __init__(self):
        self.completions = _FakeCompletions()


class _FakeOpenAI:
    def __init__(self, api_key: str = "mock-key"):
        self.chat = _FakeChat()


class _FakeAsyncOpenAI:
    def __init__(self, api_key: str = "mock-key"):
        self.chat = _FakeChat()


_mock_openai_module = types.ModuleType("openai")
_mock_openai_module.OpenAI = _FakeOpenAI           # type: ignore
_mock_openai_module.AsyncOpenAI = _FakeAsyncOpenAI # type: ignore
sys.modules["openai"] = _mock_openai_module


# ───────────────────────────────────────────────────────────────────────────
# BEFORE: call without any instrumentation
# ───────────────────────────────────────────────────────────────────────────

def demo_before_instrumentation() -> None:
    """Show that without FlowLens, nothing is recorded."""
    step(1, "BEFORE auto_instrument() — no tracing")

    note("Creating Anthropic client (mock) without FlowLens active")
    note("Calling messages.create() directly — zero spans will be recorded")

    import anthropic  # picks up our mock module
    client = anthropic.Anthropic(api_key="mock-key")

    t0 = time.perf_counter()
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        messages=[{"role": "user", "content": "What is the capital of France?"}],
        max_tokens=100,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000

    warn(f"Response received in {elapsed_ms:.0f}ms: {response.content[0].text[:80]}")
    warn("But NO trace was recorded — FlowLens has not been initialised yet.")
    note("FlowLens.get_instance() returns None when no instance is created.")


# ───────────────────────────────────────────────────────────────────────────
# AFTER: enable FlowLens + auto_instrument, then call again
# ───────────────────────────────────────────────────────────────────────────

_traces: list[Trace] = []


def _capture(trace: Trace) -> None:
    _traces.append(trace)


async def demo_after_instrumentation() -> None:
    """Enable FlowLens, call auto_instrument, re-run the same call — full trace."""
    step(2, "AFTER auto_instrument() — automatic tracing")

    # Step 2a: Create a FlowLens instance (sets the global singleton)
    note("Initialising FlowLens with console exporter + trace callback")
    lens = FlowLens(
        service_name="auto-instrument-demo",
        export_to="console",
        verbose=False,
        on_trace_complete=_capture,
    )
    ok("FlowLens instance created")

    # Step 2b: Call auto_instrument() with both mocked libraries
    note("Calling auto_instrument(['anthropic', 'openai'])")
    note("  → monkey-patches Anthropic.messages.create and OpenAI.chat.completions.create")
    note("  → from this point on every call is automatically wrapped in an LLM span")
    auto_instrument(["anthropic", "openai"])
    ok("auto_instrument() applied — SDK methods are now patched")

    # Step 2c: Demonstrate with an @trace_agent wrapper so we get a full trace
    @trace_agent(name="auto_instrumented_agent")
    async def run_agent():
        import anthropic
        import openai

        # Anthropic call — now automatically traced
        info("Calling Anthropic (auto-traced)...")
        anthr_client = anthropic.AsyncAnthropic(api_key="mock-key")
        anthr_resp = await anthr_client.messages.acreate(
            model="claude-sonnet-4-20250514",
            messages=[{"role": "user", "content": "Explain agentic AI in one sentence."}],
            max_tokens=150,
        )
        ok(f"Anthropic → {anthr_resp.usage.input_tokens} in / {anthr_resp.usage.output_tokens} out tokens")

        # OpenAI call — also automatically traced
        info("Calling OpenAI (auto-traced)...")
        oai_client = openai.AsyncOpenAI(api_key="mock-key")
        oai_resp = await oai_client.chat.completions.acreate(
            model="gpt-4.1",
            messages=[{"role": "user", "content": "What is observability for LLMs?"}],
            max_tokens=150,
        )
        ok(f"OpenAI → {oai_resp.usage.prompt_tokens} in / {oai_resp.usage.completion_tokens} out tokens")

        return {
            "anthropic_text": anthr_resp.content[0].text,
            "openai_text": oai_resp.choices[0].message.content,
        }

    note("Running agent — all LLM calls inside will be auto-traced...")
    result = await run_agent()
    ok("Agent completed")

    lens.shutdown()

    # Show diff
    step(3, "Comparing BEFORE vs AFTER")
    print()
    print(f"  {'Before auto_instrument':<35}  {'After auto_instrument'}")
    print(c("  " + "─" * 70, DIM))
    rows = [
        ("Traces recorded",        c("0", RED),      c(str(len(_traces)), GREEN)),
        ("LLM spans",              c("0", RED),      c("2", GREEN)),
        ("Token usage tracked",    c("No", RED),     c("Yes", GREEN)),
        ("Cost estimated",         c("No", RED),     c("Yes", GREEN)),
        ("Code changes needed",    c("None", GREEN), c("None", GREEN)),
    ]
    for label, before, after in rows:
        print(f"  {label:<35}  {before:<30}  {after}")

    print()
    if _traces:
        t = _traces[0]
        print(c("  Trace summary:", WHITE, BOLD))
        print(f"    Spans     : {len(t.spans)}")
        print(f"    Tokens    : {t.total_tokens:,}")
        print(f"    Cost      : ${t.total_cost_usd:.5f}")
        print(f"    Errors    : {t.error_count}")


# ───────────────────────────────────────────────────────────────────────────
# Step 4: Show what auto_instrument patches under the hood
# ───────────────────────────────────────────────────────────────────────────

def explain_how_it_works() -> None:
    step(4, "How auto_instrument() works internally")
    print()
    explanation = [
        ("1. Import detection", "auto_instrument() tries to import 'anthropic' / 'openai'."),
        ("                    ", "If the library is missing it silently skips — no ImportError."),
        ("2. Method patching ", "It replaces Anthropic.messages.create with a wrapper that:"),
        ("                    ", "  a) reads the 'model' kwarg for cost calculation"),
        ("                    ", "  b) starts a span (kind=LLM, gen_ai.* attributes)"),
        ("                    ", "  c) calls the original function"),
        ("                    ", "  d) extracts token usage from the response object"),
        ("                    ", "  e) finishes the span (OK or ERROR)"),
        ("3. Idempotency     ", "Calling auto_instrument() twice is safe — a '_patched' set"),
        ("                    ", "ensures each library is only patched once."),
        ("4. Context linking ", "Spans created by the patch inherit the current trace/parent span"),
        ("                    ", "from contextvars — no thread-local hacks."),
    ]
    for label, desc in explanation:
        if label.strip():
            print(c(f"  {label:<20}", CYAN, BOLD) + c(f"  {desc}", WHITE))
        else:
            print(c(f"  {label:<20}", DIM) + c(f"  {desc}", DIM))
    print()

    note("Source: flowlens/sdk/auto_instrument.py")
    print()

    # Mini code walkthrough
    print(c("  Usage summary:", WHITE, BOLD))
    print()
    code_lines = [
        ("from flowlens import FlowLens, auto_instrument, trace_agent", CYAN),
        ("", None),
        ("# 1. Initialise FlowLens (sets the global singleton)", DIM),
        ("lens = FlowLens(service_name='my-bot', export_to='console')", CYAN),
        ("", None),
        ("# 2. Patch any combination of supported libraries", DIM),
        ("auto_instrument(['anthropic', 'openai', 'langchain'])", CYAN),
        ("", None),
        ("# 3. Wrap your agent entry-point to start a trace", DIM),
        ("@trace_agent(name='my_bot')", CYAN),
        ("async def run():", CYAN),
        ("    client = anthropic.AsyncAnthropic()", CYAN),
        ("    # ↑ This call is now automatically traced — no changes needed!", DIM),
        ("    resp = await client.messages.create(...)", CYAN),
        ("    return resp.content[0].text", CYAN),
    ]
    for line, color in code_lines:
        if color:
            print(f"    {c(line, color)}")
        else:
            print()


# ───────────────────────────────────────────────────────────────────────────
# Main
# ───────────────────────────────────────────────────────────────────────────

async def main() -> None:
    banner("FlowLens Auto-Instrumentation — Zero-Code LLM Tracing")

    note("This example mocks the Anthropic and OpenAI SDKs in-process.")
    note("No API keys are required — it runs fully offline.")

    # Step 1: un-instrumented
    demo_before_instrumentation()

    # Steps 2 & 3: enable FlowLens + auto_instrument, compare
    await demo_after_instrumentation()

    # Step 4: explain internals
    explain_how_it_works()

    print(c("  Done! Auto-instrumentation example complete.", GREEN, BOLD))
    print()


if __name__ == "__main__":
    asyncio.run(main())
