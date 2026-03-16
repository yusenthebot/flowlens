"""
FlowLens Evaluation — LLM-as-a-Judge evaluator.

LLMJudge uses a language model to score another model's output against
user-defined quality criteria.  This is particularly useful for open-ended
tasks where rule-based evaluators (ExactMatch, ContainsKeywords, etc.) are
insufficient.

Architecture
------------
The evaluator builds a structured prompt that:
1. Presents the judge model with the original input context (if available).
2. Shows the output being evaluated.
3. Asks the judge to score on a numeric scale and provide reasoning.
4. Parses the score from the structured response.

Real LLM integration
--------------------
By default the judge runs in **mock mode** — it generates a deterministic
simulated score based on simple heuristics so that tests and demos work
without any API credentials.  To use a real model, either:

- Pass ``_call_fn`` (a callable) at construction time, OR
- Set the ``FLOWLENS_LLM_JUDGE_ENABLED=1`` environment variable and ensure
  the ``anthropic`` package is installed.

When the ``anthropic`` package is available and ``FLOWLENS_LLM_JUDGE_ENABLED``
is truthy, the evaluator will call the Anthropic Messages API using the model
specified in ``model``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import textwrap
from collections.abc import Callable
from typing import Any

from .evaluators import EvalResult, Evaluator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_SYSTEM_PROMPT = textwrap.dedent("""\
    You are an expert evaluator assessing the quality of AI-generated responses.
    Your job is to carefully read the response, evaluate it against the provided
    criteria, and return a numeric score along with a clear justification.

    IMPORTANT: Your response MUST follow this exact format:

    SCORE: <integer between 1 and {scale}>
    REASON: <one or two sentences explaining your score>

    Do not include any other text outside this format.
    """)

_DEFAULT_USER_TEMPLATE = textwrap.dedent("""\
    Evaluate the following AI response against the criteria below.

    Criteria: {criteria}

    Response to evaluate:
    \"\"\"
    {output}
    \"\"\"

    Score on a scale of 1 to {scale} where:
    - 1 = completely fails to meet the criteria
    - {mid} = partially meets the criteria
    - {scale} = fully and excellently meets the criteria

    Respond with:
    SCORE: <integer 1-{scale}>
    REASON: <explanation>
    """)

# ---------------------------------------------------------------------------
# Score parser
# ---------------------------------------------------------------------------


def _parse_judge_response(response: str, scale: int) -> tuple[int | None, str]:
    """Parse the structured judge response into (score, reason).

    Expected format::

        SCORE: 4
        REASON: The response is helpful and accurate, though slightly verbose.

    Returns:
        (score, reason) where score is an int in [1, scale] or None on failure.
    """
    score: int | None = None
    reason: str = ""

    score_match = re.search(r"SCORE:\s*(\d+)", response, re.IGNORECASE)
    if score_match:
        raw = int(score_match.group(1))
        score = max(1, min(scale, raw))

    reason_match = re.search(r"REASON:\s*(.+)", response, re.IGNORECASE | re.DOTALL)
    if reason_match:
        reason = reason_match.group(1).strip()
        # Trim to first two sentences to keep it concise
        sentences = re.split(r"(?<=[.!?])\s+", reason)
        reason = " ".join(sentences[:3]).strip()

    return score, reason


# ---------------------------------------------------------------------------
# Mock scoring (deterministic, no network calls)
# ---------------------------------------------------------------------------


def _mock_score(output: str, criteria: str, scale: int) -> tuple[int, str]:
    """Generate a deterministic mock score for testing and demo purposes.

    The score is derived from a stable hash of the output+criteria so that
    identical inputs always produce the same result, making tests repeatable.

    Heuristics applied on top of the hash:
    - Empty output always scores 1.
    - Very short output (< 10 chars) scores low (1 or 2).
    - Output that mentions key words from the criteria scores higher.
    """
    if not output.strip():
        return 1, "Output is empty — fails all evaluation criteria."

    if len(output.strip()) < 10:
        return max(1, scale // 4), "Output is too short to meet the evaluation criteria."

    # Keyword overlap heuristic
    criteria_words = set(re.findall(r"\w+", criteria.lower()))
    output_words = set(re.findall(r"\w+", output.lower()))
    overlap = len(criteria_words & output_words)
    overlap_ratio = overlap / max(len(criteria_words), 1)

    # Stable hash to add deterministic variation (avoids always scoring the same)
    digest = hashlib.md5((output + criteria).encode(), usedforsecurity=False).digest()
    hash_offset = (digest[0] % 3) - 1  # -1, 0, or +1

    base_score = round(1 + overlap_ratio * (scale - 1))
    score = max(1, min(scale, base_score + hash_offset))

    reason = (
        f"Mock evaluation: {overlap} criteria keyword(s) found in output "
        f"({overlap_ratio:.0%} overlap). Score adjusted to {score}/{scale}."
    )
    return score, reason


# ---------------------------------------------------------------------------
# Real Anthropic call (optional dependency)
# ---------------------------------------------------------------------------


def _call_anthropic(
    output: str,
    criteria: str,
    model: str,
    scale: int,
) -> tuple[int | None, str]:
    """Call the Anthropic Messages API and parse the judge response.

    Returns:
        (score, reason) or (None, error_message) on failure.
    """
    try:
        import anthropic  # type: ignore[import-untyped]
    except ImportError:
        return None, (
            "The 'anthropic' package is required for real LLM judging. "
            "Install it with: pip install anthropic"
        )

    mid = (scale + 1) // 2
    system_prompt = _DEFAULT_SYSTEM_PROMPT.format(scale=scale)
    user_message = _DEFAULT_USER_TEMPLATE.format(
        criteria=criteria,
        output=output,
        scale=scale,
        mid=mid,
    )

    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model=model,
            max_tokens=256,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        raw_response = message.content[0].text if message.content else ""
        return _parse_judge_response(raw_response, scale)
    except Exception as exc:
        logger.warning("LLMJudge Anthropic call failed: %s", exc)
        return None, f"LLM judge call failed: {exc}"


# ---------------------------------------------------------------------------
# LLMJudge evaluator
# ---------------------------------------------------------------------------


class LLMJudge(Evaluator):
    """Use an LLM to judge the quality of another LLM's output.

    This evaluator implements the "LLM-as-a-Judge" pattern: it sends the
    evaluated output to a judge model along with scoring criteria and parses
    the returned numeric score.

    Args:
        criteria:  Natural language description of what to judge.
                   E.g. "Is the response helpful, accurate, and complete?"
        model:     Model identifier for the judge LLM.
                   Default is ``"claude-haiku-4"`` (fast and cheap).
        scale:     Scoring scale upper bound.  Use 5 for a 1-5 scale or 10 for
                   a 1-10 scale.  Default is 5.
        _call_fn:  Optional callable with signature
                   ``(output, criteria, model, scale) -> (score | None, reason)``
                   for dependency injection in tests.  When None the evaluator
                   uses the Anthropic API (if available) or the built-in mock.

    Score normalisation:
        The raw integer score (1..scale) is normalised to [0.0, 1.0] for
        consistency with other evaluators::

            normalised = (raw_score - 1) / (scale - 1)

        A raw score of 1 maps to 0.0 (fail), ``scale`` maps to 1.0 (pass).
        Scores >= 0.6 are labelled "pass", < 0.4 are labelled "fail", and
        in between are "partial".

    Example::

        judge = LLMJudge(
            criteria="Is the response helpful, accurate, and complete?",
            model="claude-haiku-4",
            scale=5,
        )
        result = judge.evaluate(span_data, trace_data)
        print(result.score, result.label, result.reason)
    """

    name = "llm_judge"

    # Label thresholds (on the normalised 0.0–1.0 scale)
    _PASS_THRESHOLD = 0.6
    _FAIL_THRESHOLD = 0.4

    def __init__(
        self,
        criteria: str,
        model: str = "claude-haiku-4",
        scale: int = 5,
        _call_fn: Callable[..., tuple[int | None, str]] | None = None,
    ) -> None:
        if not criteria.strip():
            raise ValueError("criteria must not be empty.")
        if scale < 2:
            raise ValueError("scale must be at least 2.")
        self.criteria = criteria
        self.model = model
        self.scale = scale
        self._call_fn = _call_fn

    # ------------------------------------------------------------------
    # Internal: determine and invoke the right backend
    # ------------------------------------------------------------------

    def _invoke_judge(self, output: str) -> tuple[int | None, str]:
        """Invoke the judge backend and return (raw_score | None, reason)."""
        # Injected callable takes priority (used in tests)
        if self._call_fn is not None:
            return self._call_fn(output, self.criteria, self.model, self.scale)

        # Opt-in to real LLM calls via environment variable
        if os.environ.get("FLOWLENS_LLM_JUDGE_ENABLED", "").strip() in ("1", "true", "yes"):
            return _call_anthropic(output, self.criteria, self.model, self.scale)

        # Default: deterministic mock (no network, no API key required)
        score, reason = _mock_score(output, self.criteria, self.scale)
        return score, reason

    # ------------------------------------------------------------------
    # Normalisation helpers
    # ------------------------------------------------------------------

    def _normalise(self, raw_score: int) -> float:
        """Normalise raw_score in [1, scale] to [0.0, 1.0]."""
        if self.scale == 1:
            return 1.0
        return (raw_score - 1) / (self.scale - 1)

    def _label(self, normalised: float) -> str:
        if normalised >= self._PASS_THRESHOLD:
            return "pass"
        if normalised <= self._FAIL_THRESHOLD:
            return "fail"
        return "partial"

    # ------------------------------------------------------------------
    # evaluate
    # ------------------------------------------------------------------

    def evaluate(self, span_data: dict[str, Any], trace_data: dict[str, Any]) -> EvalResult:
        output = self._get_output(span_data, trace_data)

        if not output.strip():
            return self._fail(
                reason="Output is empty — cannot perform LLM judge evaluation.",
                metadata={
                    "criteria": self.criteria,
                    "model": self.model,
                    "scale": self.scale,
                },
            )

        raw_score, reason = self._invoke_judge(output)

        if raw_score is None:
            # Judge call failed — return partial with the error message
            return EvalResult(
                score=0.5,
                label="partial",
                reason=f"LLM judge could not produce a score: {reason}",
                evaluator=self.name,
                metadata={
                    "criteria": self.criteria,
                    "model": self.model,
                    "scale": self.scale,
                    "error": reason,
                },
            )

        normalised = self._normalise(raw_score)
        label = self._label(normalised)

        return EvalResult(
            score=normalised,
            label=label,
            reason=reason,
            evaluator=self.name,
            metadata={
                "criteria": self.criteria,
                "model": self.model,
                "scale": self.scale,
                "raw_score": raw_score,
                "normalised_score": normalised,
            },
        )


__all__ = ["LLMJudge"]
