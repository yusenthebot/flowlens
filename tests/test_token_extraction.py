"""Tests for _extract_llm_usage — improved token extraction in decorators.py."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from flowlens.sdk.decorators import _extract_llm_usage, _extract_output_text
from flowlens.sdk.models import Span, SpanKind


def _make_span() -> Span:
    return Span(name="llm_span", kind=SpanKind.LLM)


# ---------------------------------------------------------------------------
# Anthropic SDK format
# ---------------------------------------------------------------------------

class TestAnthropicFormat:
    def test_anthropic_usage_object(self):
        span = _make_span()
        response = MagicMock()
        response.usage.input_tokens = 300
        response.usage.output_tokens = 120

        _extract_llm_usage(span, response, "claude-sonnet-4-20250514")

        assert span.token_usage is not None
        assert span.token_usage.input_tokens == 300
        assert span.token_usage.output_tokens == 120
        assert span.token_usage.total_tokens == 420
        assert span.attributes["gen_ai.usage.input_tokens"] == 300
        assert span.attributes["gen_ai.usage.output_tokens"] == 120

    def test_anthropic_cost_calculated(self):
        span = _make_span()
        response = MagicMock()
        response.usage.input_tokens = 1_000_000
        response.usage.output_tokens = 1_000_000
        _extract_llm_usage(span, response, "claude-sonnet-4-20250514")
        # $3 input + $15 output = $18
        assert span.token_usage.total_cost_usd == pytest.approx(18.0, rel=1e-4)


# ---------------------------------------------------------------------------
# OpenAI SDK — object format
# ---------------------------------------------------------------------------

class TestOpenAIObjectFormat:
    def test_openai_object_usage(self):
        span = _make_span()
        response = MagicMock()
        response.usage.prompt_tokens = 400
        response.usage.completion_tokens = 80
        # Must NOT have "input_tokens" to ensure prompt_tokens path is taken
        del response.usage.input_tokens
        del response.usage.output_tokens

        _extract_llm_usage(span, response, "gpt-4.1")

        assert span.token_usage is not None
        assert span.token_usage.input_tokens == 400
        assert span.token_usage.output_tokens == 80


# ---------------------------------------------------------------------------
# OpenAI SDK — dict format
# ---------------------------------------------------------------------------

class TestOpenAIDictFormat:
    def test_openai_dict_usage(self):
        span = _make_span()
        response = {
            "usage": {"prompt_tokens": 200, "completion_tokens": 60},
            "choices": [{"message": {"content": "Hi"}, "finish_reason": "stop"}],
        }
        _extract_llm_usage(span, response, "gpt-4o")
        assert span.token_usage.input_tokens == 200
        assert span.token_usage.output_tokens == 60

    def test_openai_dict_with_input_tokens_key(self):
        """Some providers use input_tokens instead of prompt_tokens."""
        span = _make_span()
        response = {"usage": {"input_tokens": 50, "output_tokens": 20}}
        _extract_llm_usage(span, response, "some-model")
        assert span.token_usage.input_tokens == 50
        assert span.token_usage.output_tokens == 20


# ---------------------------------------------------------------------------
# Google Generative AI format
# ---------------------------------------------------------------------------

class TestGoogleFormat:
    def test_google_usage_metadata(self):
        span = _make_span()
        response = MagicMock(spec=["usage_metadata"])
        response.usage_metadata.prompt_token_count = 150
        response.usage_metadata.candidates_token_count = 40

        _extract_llm_usage(span, response, "gemini-2.5-pro")

        assert span.token_usage.input_tokens == 150
        assert span.token_usage.output_tokens == 40

    def test_google_candidates_fallback(self):
        span = _make_span()
        response = MagicMock(spec=["candidates"])
        response.candidates = [MagicMock()]
        response.candidates[0].token_count = 25

        _extract_llm_usage(span, response, "gemini-2.5-flash")
        # Only output tokens are set from candidates
        assert span.token_usage is not None
        assert span.token_usage.output_tokens == 25


# ---------------------------------------------------------------------------
# LiteLLM format
# ---------------------------------------------------------------------------

class TestLiteLLMFormat:
    def test_litellm_object_usage(self):
        """LiteLLM ModelResponse uses prompt_tokens / completion_tokens on .usage."""
        span = _make_span()
        response = MagicMock()
        response.usage.prompt_tokens = 250
        response.usage.completion_tokens = 90
        del response.usage.input_tokens
        del response.usage.output_tokens

        _extract_llm_usage(span, response, "gpt-4o-mini")
        assert span.token_usage.input_tokens == 250
        assert span.token_usage.output_tokens == 90

    def test_litellm_dict_format(self):
        """LiteLLM can also return dict responses."""
        span = _make_span()
        response = {"usage": {"prompt_tokens": 100, "completion_tokens": 30}}
        _extract_llm_usage(span, response, "gpt-4o-mini")
        assert span.token_usage.input_tokens == 100
        assert span.token_usage.output_tokens == 30


# ---------------------------------------------------------------------------
# Amazon Bedrock format
# ---------------------------------------------------------------------------

class TestBedrockFormat:
    def test_bedrock_converse_api(self):
        """Amazon Bedrock Converse API uses inputTokens / outputTokens."""
        span = _make_span()
        response = {
            "ResponseMetadata": {"HTTPStatusCode": 200},
            "usage": {"inputTokens": 500, "outputTokens": 150},
        }
        _extract_llm_usage(span, response, "anthropic.claude-3-sonnet")
        assert span.token_usage.input_tokens == 500
        assert span.token_usage.output_tokens == 150

    def test_bedrock_invoke_model_metrics(self):
        """Amazon Bedrock InvokeModel uses metrics.inputTokenCount / outputTokenCount."""
        span = _make_span()
        response = {
            "body": "...",
            "metrics": {"inputTokenCount": 120, "outputTokenCount": 45},
        }
        _extract_llm_usage(span, response, "meta.llama3-70b")
        assert span.token_usage.input_tokens == 120
        assert span.token_usage.output_tokens == 45


# ---------------------------------------------------------------------------
# Fallback — estimate from text
# ---------------------------------------------------------------------------

class TestFallbackEstimation:
    def test_fallback_from_string_response(self):
        """When result is a plain string, estimate output tokens from its length."""
        span = _make_span()
        # 400 chars → 100 estimated tokens
        response = "x" * 400
        _extract_llm_usage(span, response, "some-model")
        assert span.token_usage is not None
        assert span.token_usage.output_tokens == 100

    def test_fallback_from_anthropic_content_blocks(self):
        """Anthropic message with no usage → estimate from content blocks."""
        span = _make_span()
        block = MagicMock()
        block.text = "a" * 80  # 80 chars → 20 tokens
        response = MagicMock(spec=["content"])
        response.content = [block]

        _extract_llm_usage(span, response, "claude-sonnet-4")
        assert span.token_usage is not None
        assert span.token_usage.output_tokens >= 1

    def test_no_usage_no_text_no_crash(self):
        """Completely empty response must not raise and must not set token_usage."""
        span = _make_span()
        response = MagicMock(spec=[])  # no attributes at all
        _extract_llm_usage(span, response, "model")
        # No crash — token_usage may or may not be set; just must not raise


# ---------------------------------------------------------------------------
# _extract_output_text helper
# ---------------------------------------------------------------------------

class TestExtractOutputText:
    def test_anthropic_content_blocks(self):
        block = MagicMock()
        block.text = "Hello there"
        response = MagicMock()
        response.content = [block]
        assert "Hello there" in _extract_output_text(response)

    def test_openai_choices(self):
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = "OpenAI response"
        assert _extract_output_text(response) == "OpenAI response"

    def test_string_content(self):
        response = MagicMock(spec=["content"])
        response.content = "LangChain AIMessage"
        assert _extract_output_text(response) == "LangChain AIMessage"

    def test_raw_string(self):
        assert _extract_output_text("raw text") == "raw text"

    def test_dict_with_content(self):
        assert _extract_output_text({"content": "dict content"}) == "dict content"

    def test_empty_object_returns_empty(self):
        result = _extract_output_text(MagicMock(spec=[]))
        assert result == ""
