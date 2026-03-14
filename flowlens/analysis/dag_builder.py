"""
Causal DAG Builder — 从 trace 数据构建错误因果图

核心算法：
1. 从 trace spans 构建 parent-child 树
2. 标记 error spans
3. 反向遍历识别 root cause
4. 构建 error propagation edges
5. 标注 error role（root_cause / cascaded / independent）
"""

from __future__ import annotations

from ..sdk.models import Span, SpanStatus, Trace
from .models import CausalDAG, CausalNode, CausalEdge, ErrorRole


def build_causal_dag(trace: Trace) -> CausalDAG:
    """
    从 Trace 构建因果 DAG

    Args:
        trace: 一次完整的 agent 执行 trace

    Returns:
        CausalDAG: 包含节点、因果边、root cause 标注
    """
    dag = CausalDAG(trace_id=trace.trace_id)

    if not trace.spans:
        return dag

    # Step 1: 构建节点
    span_map: dict[str, Span] = {}
    for span in trace.spans:
        span_map[span.span_id] = span
        dag.nodes.append(CausalNode(
            span_id=span.span_id,
            name=span.name,
            kind=span.kind.value,
            status=span.status.value,
            error_message=span.error_message,
            duration_ms=span.duration_ms,
            token_count=span.token_usage.total_tokens if span.token_usage else 0,
        ))

    # Step 2: 构建 parent-child 索引
    children_of: dict[str, list[str]] = {}
    parent_of: dict[str, str] = {}
    for span in trace.spans:
        if span.parent_span_id:
            children_of.setdefault(span.parent_span_id, []).append(span.span_id)
            parent_of[span.span_id] = span.parent_span_id

    # Step 3: 按时间排序构建执行顺序的 preceded_by 边
    sorted_spans = sorted(trace.spans, key=lambda s: s.start_time)
    # 同一 parent 下的兄弟节点，前一个 → 后一个
    sibling_groups: dict[str, list[str]] = {}
    for span in sorted_spans:
        key = span.parent_span_id or "__root__"
        sibling_groups.setdefault(key, []).append(span.span_id)

    # Step 4: 识别 error spans 和错误传播
    error_span_ids = {
        s.span_id for s in trace.spans
        if s.status == SpanStatus.ERROR
    }

    if not error_span_ids:
        return dag  # 无错误，直接返回

    # Step 5: 找 root cause — 没有 error 祖先的 error span
    node_map = {n.span_id: n for n in dag.nodes}

    for span_id in error_span_ids:
        has_error_ancestor = _has_error_ancestor(
            span_id, parent_of, error_span_ids
        )
        has_error_predecessor = _has_error_predecessor(
            span_id, sibling_groups, error_span_ids, parent_of
        )

        if not has_error_ancestor and not has_error_predecessor:
            node_map[span_id].error_role = ErrorRole.ROOT_CAUSE
            dag.root_causes.append(span_id)
        else:
            node_map[span_id].error_role = ErrorRole.CASCADED

    # Step 6: 构建因果边（error parent → error child, error sibling → next error sibling）
    for span_id in error_span_ids:
        # 从 error parent 到 error child
        p_id = parent_of.get(span_id)
        if p_id and p_id in error_span_ids:
            dag.edges.append(CausalEdge(
                source_id=p_id,
                target_id=span_id,
                relation="caused_by",
            ))

        # 从前一个 error sibling 到当前
        group_key = parent_of.get(span_id, "__root__")
        siblings = sibling_groups.get(group_key, [])
        idx = siblings.index(span_id) if span_id in siblings else -1
        if idx > 0:
            prev_id = siblings[idx - 1]
            if prev_id in error_span_ids:
                dag.edges.append(CausalEdge(
                    source_id=prev_id,
                    target_id=span_id,
                    relation="preceded_by",
                ))

    return dag


def _has_error_ancestor(
    span_id: str,
    parent_of: dict[str, str],
    error_set: set[str],
) -> bool:
    """检查是否有 error 祖先"""
    current = parent_of.get(span_id)
    while current:
        if current in error_set:
            return True
        current = parent_of.get(current)
    return False


def _has_error_predecessor(
    span_id: str,
    sibling_groups: dict[str, list[str]],
    error_set: set[str],
    parent_of: dict[str, str],
) -> bool:
    """检查同 parent 下是否有更早执行的 error sibling"""
    group_key = parent_of.get(span_id, "__root__")
    siblings = sibling_groups.get(group_key, [])
    idx = siblings.index(span_id) if span_id in siblings else -1
    if idx > 0:
        for i in range(idx):
            if siblings[i] in error_set:
                return True
    return False
