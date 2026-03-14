"""
Pattern Detection — 检测已知的 Agent 错误模式

支持的 Pattern：
1. retry_storm: 同一操作被大量重试
2. infinite_loop: Agent 在同一组 tool 间反复调用
3. context_overflow: Token 用量接近/超过模型上限
4. timeout_cascade: 超时导致下游连锁失败
5. empty_response: LLM 返回空内容
"""

from __future__ import annotations

from collections import Counter
from ..sdk.models import Span, SpanKind, SpanStatus, Trace
from .models import DetectedPattern, PatternType, CausalDAG


# 模型 context window 大小
_MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "claude-opus-4": 200_000,
    "claude-sonnet-4": 200_000,
    "claude-haiku-4": 200_000,
    "gpt-4o": 128_000,
    "gpt-4.1": 1_000_000,
    "gpt-4.1-mini": 1_000_000,
    "gemini-2.5-pro": 1_000_000,
    "deepseek-v3": 128_000,
}

DEFAULT_CONTEXT_LIMIT = 200_000


def detect_patterns(trace: Trace, dag: CausalDAG) -> list[DetectedPattern]:
    """运行所有 pattern 检测器"""
    patterns: list[DetectedPattern] = []

    patterns.extend(_detect_retry_storm(trace))
    patterns.extend(_detect_infinite_loop(trace))
    patterns.extend(_detect_context_overflow(trace))
    patterns.extend(_detect_timeout_cascade(trace, dag))
    patterns.extend(_detect_empty_response(trace))

    # 写回 DAG
    dag.patterns = patterns
    return patterns


def _detect_retry_storm(
    trace: Trace, threshold: int = 5
) -> list[DetectedPattern]:
    """检测重试风暴：同名 tool 在短时间内被调用过多次"""
    tool_spans = [s for s in trace.spans if s.kind == SpanKind.TOOL]
    name_counts = Counter(s.name for s in tool_spans)

    patterns = []
    for name, count in name_counts.items():
        if count >= threshold:
            involved = [s.span_id for s in tool_spans if s.name == name]
            error_rate = sum(
                1 for s in tool_spans
                if s.name == name and s.status == SpanStatus.ERROR
            ) / count

            patterns.append(DetectedPattern(
                pattern_type=PatternType.RETRY_STORM,
                severity="critical" if error_rate > 0.8 else "warning",
                description=(
                    f"Tool '{name}' 被调用 {count} 次"
                    f"（错误率 {error_rate:.0%}），可能存在重试风暴"
                ),
                involved_spans=involved,
                details={
                    "tool_name": name,
                    "call_count": count,
                    "error_rate": round(error_rate, 2),
                },
            ))
    return patterns


def _detect_infinite_loop(
    trace: Trace, max_repeat: int = 3
) -> list[DetectedPattern]:
    """
    检测循环：Agent 在同一组 tool 间反复调用
    例如：A → B → A → B → A → B 表示 [A,B] 循环了 3 次
    """
    tool_sequence = [
        s.name for s in sorted(trace.spans, key=lambda s: s.start_time)
        if s.kind == SpanKind.TOOL
    ]

    if len(tool_sequence) < 4:
        return []

    patterns = []
    # 检测长度为 2 和 3 的循环
    for cycle_len in (2, 3):
        for start in range(len(tool_sequence) - cycle_len * max_repeat + 1):
            cycle = tool_sequence[start:start + cycle_len]
            repeat_count = 0
            pos = start
            while pos + cycle_len <= len(tool_sequence):
                if tool_sequence[pos:pos + cycle_len] == cycle:
                    repeat_count += 1
                    pos += cycle_len
                else:
                    break

            if repeat_count >= max_repeat:
                tool_spans = [s for s in trace.spans if s.kind == SpanKind.TOOL]
                involved = [s.span_id for s in tool_spans if s.name in cycle]

                patterns.append(DetectedPattern(
                    pattern_type=PatternType.INFINITE_LOOP,
                    severity="critical",
                    description=(
                        f"检测到循环模式 {' → '.join(cycle)} "
                        f"重复 {repeat_count} 次"
                    ),
                    involved_spans=involved[:repeat_count * cycle_len],
                    details={
                        "cycle": cycle,
                        "repeat_count": repeat_count,
                    },
                ))
                return patterns  # 只报第一个循环

    return patterns


def _detect_context_overflow(
    trace: Trace, threshold_ratio: float = 0.9
) -> list[DetectedPattern]:
    """检测 context window 接近上限"""
    llm_spans = [s for s in trace.spans if s.kind == SpanKind.LLM]
    patterns = []

    for span in llm_spans:
        if not span.token_usage:
            continue

        model = span.attributes.get("gen_ai.request.model", "")
        limit = DEFAULT_CONTEXT_LIMIT
        for key, val in _MODEL_CONTEXT_LIMITS.items():
            if key in model.lower():
                limit = val
                break

        usage_ratio = span.token_usage.total_tokens / limit
        if usage_ratio >= threshold_ratio:
            patterns.append(DetectedPattern(
                pattern_type=PatternType.CONTEXT_OVERFLOW,
                severity="critical" if usage_ratio >= 1.0 else "warning",
                description=(
                    f"LLM '{span.name}' token 用量达到 context 上限的 "
                    f"{usage_ratio:.0%} ({span.token_usage.total_tokens}/{limit})"
                ),
                involved_spans=[span.span_id],
                details={
                    "model": model,
                    "total_tokens": span.token_usage.total_tokens,
                    "context_limit": limit,
                    "usage_ratio": round(usage_ratio, 3),
                },
            ))

    return patterns


def _detect_timeout_cascade(
    trace: Trace, dag: CausalDAG
) -> list[DetectedPattern]:
    """检测超时导致的级联失败"""
    timeout_spans = [
        s for s in trace.spans
        if s.status == SpanStatus.ERROR
        and s.error_message
        and "timeout" in s.error_message.lower()
    ]

    if not timeout_spans:
        return []

    patterns = []
    for ts in timeout_spans:
        # 找到因它导致的下游失败
        cascaded = _find_downstream_errors(ts.span_id, dag)
        if cascaded:
            patterns.append(DetectedPattern(
                pattern_type=PatternType.TIMEOUT_CASCADE,
                severity="critical",
                description=(
                    f"'{ts.name}' 超时后导致 {len(cascaded)} 个下游操作失败"
                ),
                involved_spans=[ts.span_id] + cascaded,
                details={
                    "timeout_span": ts.name,
                    "cascade_count": len(cascaded),
                },
            ))

    return patterns


def _detect_empty_response(trace: Trace) -> list[DetectedPattern]:
    """检测 LLM 返回空内容"""
    patterns = []
    for span in trace.spans:
        if span.kind != SpanKind.LLM:
            continue
        if (
            span.token_usage
            and span.token_usage.output_tokens == 0
            and span.status == SpanStatus.OK
        ):
            patterns.append(DetectedPattern(
                pattern_type=PatternType.EMPTY_RESPONSE,
                severity="warning",
                description=f"LLM '{span.name}' 返回 0 个 output tokens",
                involved_spans=[span.span_id],
            ))

    return patterns


def _find_downstream_errors(
    span_id: str, dag: CausalDAG
) -> list[str]:
    """在 DAG 中找到某节点的所有下游 error 节点"""
    children: dict[str, list[str]] = {}
    for e in dag.edges:
        children.setdefault(e.source_id, []).append(e.target_id)

    result = []
    queue = children.get(span_id, [])
    visited = set()
    while queue:
        nid = queue.pop(0)
        if nid in visited:
            continue
        visited.add(nid)
        result.append(nid)
        queue.extend(children.get(nid, []))

    return result
