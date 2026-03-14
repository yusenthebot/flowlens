"""
Trace 比较引擎 — 对比两个 traces，用于 A/B 测试

支持的比较：
- span 级别的增删改
- token 用量和成本
- 执行时间
- pattern 差异
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..sdk.models import Span, Trace


@dataclass
class SpanDiff:
    """单个 span 的变化"""
    span_id: str
    span_name: str
    change_type: str  # "added" / "removed" / "changed"
    old_span: Span | None = None
    new_span: Span | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "span_name": self.span_name,
            "change_type": self.change_type,
            "old_duration_ms": self.old_span.duration_ms if self.old_span else None,
            "new_duration_ms": self.new_span.duration_ms if self.new_span else None,
        }


@dataclass
class TraceDiff:
    """两个 traces 之间的差异"""
    trace_a_id: str
    trace_b_id: str

    # Span 变化
    added_spans: list[SpanDiff] = field(default_factory=list)
    removed_spans: list[SpanDiff] = field(default_factory=list)
    changed_spans: list[SpanDiff] = field(default_factory=list)

    # 资源使用差异
    token_diff: int = 0  # trace_b - trace_a
    cost_diff_usd: float = 0.0  # trace_b - trace_a
    duration_diff_ms: float = 0.0  # trace_b - trace_a

    # Pattern 差异
    new_patterns: list[str] = field(default_factory=list)
    resolved_patterns: list[str] = field(default_factory=list)

    # 整体评估
    is_improvement: bool = False
    improvement_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_a_id": self.trace_a_id,
            "trace_b_id": self.trace_b_id,
            "span_changes": {
                "added": len(self.added_spans),
                "removed": len(self.removed_spans),
                "changed": len(self.changed_spans),
            },
            "resource_changes": {
                "token_diff": self.token_diff,
                "cost_diff_usd": round(self.cost_diff_usd, 4),
                "duration_diff_ms": round(self.duration_diff_ms, 1),
            },
            "pattern_changes": {
                "new": self.new_patterns,
                "resolved": self.resolved_patterns,
            },
            "is_improvement": self.is_improvement,
            "improvement_reason": self.improvement_reason,
        }


def compare_traces(trace_a: Trace, trace_b: Trace) -> TraceDiff:
    """
    比较两个 traces，返回详细的差异报告

    Args:
        trace_a: 基线 trace
        trace_b: 对比 trace

    Returns:
        TraceDiff 对象，包含所有差异和评估
    """
    diff = TraceDiff(trace_a_id=trace_a.trace_id, trace_b_id=trace_b.trace_id)

    # Step 1: 比较 span
    _compare_spans(trace_a, trace_b, diff)

    # Step 2: 比较资源使用
    diff.token_diff = trace_b.total_tokens - trace_a.total_tokens
    diff.cost_diff_usd = trace_b.total_cost_usd - trace_a.total_cost_usd
    diff.duration_diff_ms = trace_b.duration_ms - trace_a.duration_ms

    # Step 3: 评估改进
    _evaluate_improvement(trace_a, trace_b, diff)

    return diff


def _compare_spans(trace_a: Trace, trace_b: Trace, diff: TraceDiff) -> None:
    """比较两个 trace 的 spans"""
    span_map_a = {s.name: s for s in trace_a.spans}
    span_map_b = {s.name: s for s in trace_b.spans}

    # 找新增 spans
    for name, span_b in span_map_b.items():
        if name not in span_map_a:
            diff.added_spans.append(SpanDiff(
                span_id=span_b.span_id,
                span_name=name,
                change_type="added",
                new_span=span_b,
            ))

    # 找删除 spans
    for name, span_a in span_map_a.items():
        if name not in span_map_b:
            diff.removed_spans.append(SpanDiff(
                span_id=span_a.span_id,
                span_name=name,
                change_type="removed",
                old_span=span_a,
            ))

    # 找修改 spans（只看持续时间）
    for name in span_map_a:
        if name in span_map_b:
            span_a = span_map_a[name]
            span_b = span_map_b[name]
            # 持续时间变化超过 10% 视为"修改"
            if span_a.duration_ms > 0:
                duration_change = (span_b.duration_ms - span_a.duration_ms) / span_a.duration_ms
                if abs(duration_change) > 0.1:
                    diff.changed_spans.append(SpanDiff(
                        span_id=span_b.span_id,
                        span_name=name,
                        change_type="changed",
                        old_span=span_a,
                        new_span=span_b,
                    ))


def _evaluate_improvement(trace_a: Trace, trace_b: Trace, diff: TraceDiff) -> None:
    """
    评估 trace_b 是否比 trace_a 更好
    综合考虑：cost、time、error count、span count
    """
    improvements = []
    regressions = []

    # Cost 改进
    if diff.cost_diff_usd < -0.0001:
        improvements.append(
            f"成本降低 ${abs(diff.cost_diff_usd):.4f}"
        )
    elif diff.cost_diff_usd > 0.0001:
        regressions.append(
            f"成本增加 ${diff.cost_diff_usd:.4f}"
        )

    # Time 改进
    if diff.duration_diff_ms < -50:
        improvements.append(
            f"执行时间减少 {abs(diff.duration_diff_ms):.0f}ms"
        )
    elif diff.duration_diff_ms > 50:
        regressions.append(
            f"执行时间增加 {diff.duration_diff_ms:.0f}ms"
        )

    # Error 改进
    error_diff = trace_b.error_count - trace_a.error_count
    if error_diff < 0:
        improvements.append(f"错误减少 {abs(error_diff)} 个")
    elif error_diff > 0:
        regressions.append(f"错误增加 {error_diff} 个")

    # Span 数量变化
    span_diff = len(trace_b.spans) - len(trace_a.spans)
    if span_diff < 0:
        improvements.append(f"Spans 减少 {abs(span_diff)} 个")
    elif span_diff > 0:
        regressions.append(f"Spans 增加 {span_diff} 个")

    # 综合评估
    if len(improvements) > len(regressions):
        diff.is_improvement = True
        diff.improvement_reason = "；".join(improvements)
    elif len(regressions) > 0:
        diff.is_improvement = False
        diff.improvement_reason = "；".join(regressions)
    else:
        diff.is_improvement = True  # 没有明显回退视为改进
        diff.improvement_reason = "Traces 基本相同"
