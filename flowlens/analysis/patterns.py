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
    patterns.extend(_detect_hallucination_cascade(trace, dag))
    patterns.extend(_detect_cost_spike(trace))
    patterns.extend(_detect_slow_tool(trace))
    patterns.extend(_detect_redundant_calls(trace))

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


def _detect_hallucination_cascade(
    trace: Trace, dag: CausalDAG
) -> list[DetectedPattern]:
    """
    检测幻觉级联：LLM 输出被用作 tool 输入，导致 tool 失败
    特征：LLM span (OK) → TOOL span (ERROR)，且 tool 接收了 LLM 的输出
    """
    patterns = []

    # 构建 span 索引
    span_map = {s.span_id: s for s in trace.spans}
    sorted_spans = sorted(trace.spans, key=lambda s: s.start_time)

    # LLM span 后面紧跟 TOOL span 且 TOOL 出错
    for i, span in enumerate(sorted_spans):
        if span.kind != SpanKind.LLM or span.status != SpanStatus.OK:
            continue

        # 找后续同一级别或子级的失败 tool
        for j in range(i + 1, len(sorted_spans)):
            next_span = sorted_spans[j]
            if next_span.kind != SpanKind.TOOL or next_span.status != SpanStatus.ERROR:
                continue

            # 检查是否是直接后续（时间接近且可能有数据流）
            if next_span.start_time - span.end_time < 1.0:  # 1 秒内
                # 检查 tool 的属性是否引用了 LLM 的输出
                tool_attrs_str = str(next_span.attributes).lower()
                if "output" in tool_attrs_str or "result" in tool_attrs_str:
                    patterns.append(DetectedPattern(
                        pattern_type=PatternType.HALLUCINATION_CASCADE,
                        severity="critical",
                        description=(
                            f"LLM '{span.name}' 输出被 TOOL '{next_span.name}' 消费，"
                            f"导致 tool 失败：{next_span.error_message}"
                        ),
                        involved_spans=[span.span_id, next_span.span_id],
                        details={
                            "llm_span": span.name,
                            "tool_span": next_span.name,
                            "tool_error": next_span.error_message,
                        },
                    ))

    return patterns


def _detect_cost_spike(trace: Trace) -> list[DetectedPattern]:
    """
    检测成本尖峰：单次 LLM 调用消耗超过总 tokens 的 50%
    """
    total_tokens = trace.total_tokens
    if total_tokens == 0:
        return []

    patterns = []
    llm_spans = [s for s in trace.spans if s.kind == SpanKind.LLM and s.token_usage]

    for span in llm_spans:
        if span.token_usage.total_tokens > total_tokens * 0.5:
            cost_pct = (span.token_usage.total_tokens / total_tokens) * 100
            patterns.append(DetectedPattern(
                pattern_type=PatternType.COST_SPIKE,
                severity="warning",
                description=(
                    f"LLM '{span.name}' 消耗了总 tokens 的 {cost_pct:.1f}%"
                    f"（{span.token_usage.total_tokens}/{total_tokens} tokens，"
                    f"${span.token_usage.total_cost_usd:.4f}）"
                ),
                involved_spans=[span.span_id],
                details={
                    "llm_name": span.name,
                    "token_count": span.token_usage.total_tokens,
                    "total_trace_tokens": total_tokens,
                    "cost_pct": round(cost_pct, 1),
                    "cost_usd": round(span.token_usage.total_cost_usd, 6),
                },
            ))

    return patterns


def _detect_slow_tool(trace: Trace) -> list[DetectedPattern]:
    """
    检测慢速工具：tool 耗时超过中位数的 3 倍或显著超过同名工具的平均耗时
    """
    tool_spans = [s for s in trace.spans if s.kind == SpanKind.TOOL]
    if len(tool_spans) < 2:
        return []

    # 按工具名分组计算平均耗时
    tool_groups: dict[str, list[float]] = {}
    for span in tool_spans:
        tool_groups.setdefault(span.name, []).append(span.duration_ms)

    patterns = []

    for span in tool_spans:
        tool_durations = tool_groups[span.name]
        if len(tool_durations) < 2:
            continue

        # 计算同名工具的平均耗时（不含当前 span）
        other_durations = [d for d in tool_durations if d != span.duration_ms]
        if not other_durations:
            continue

        avg_duration = sum(other_durations) / len(other_durations)
        threshold = avg_duration * 3

        if span.duration_ms > threshold:
            slowness_factor = span.duration_ms / avg_duration
            patterns.append(DetectedPattern(
                pattern_type=PatternType.SLOW_TOOL,
                severity="warning",
                description=(
                    f"TOOL '{span.name}' 耗时 {span.duration_ms:.0f}ms，"
                    f"是平均耗时的 {slowness_factor:.1f}x"
                ),
                involved_spans=[span.span_id],
                details={
                    "tool_name": span.name,
                    "duration_ms": round(span.duration_ms, 1),
                    "avg_tool_duration_ms": round(avg_duration, 1),
                    "slowness_factor": round(slowness_factor, 1),
                },
            ))

    return patterns


def _detect_redundant_calls(trace: Trace) -> list[DetectedPattern]:
    """
    检测冗余调用：相同 tool 以相同参数调用多次
    """
    tool_spans = [s for s in trace.spans if s.kind == SpanKind.TOOL]

    # 按 (name, attributes) 分组
    call_groups: dict[tuple, list[str]] = {}
    for span in tool_spans:
        # 创建一个规范的参数签名
        attrs_key = tuple(sorted((k, str(v)) for k, v in span.attributes.items()))
        key = (span.name, attrs_key)
        call_groups.setdefault(key, []).append(span.span_id)

    patterns = []
    for (tool_name, _), span_ids in call_groups.items():
        if len(span_ids) > 1:
            patterns.append(DetectedPattern(
                pattern_type=PatternType.REDUNDANT_CALLS,
                severity="info",
                description=(
                    f"TOOL '{tool_name}' 被相同参数调用了 {len(span_ids)} 次，"
                    f"可能造成浪费"
                ),
                involved_spans=span_ids,
                details={
                    "tool_name": tool_name,
                    "call_count": len(span_ids),
                },
            ))

    return patterns
