"""
因果分析数据模型

CausalDAG 是核心输出：从 trace 数据构建的错误传播有向无环图。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ErrorRole(Enum):
    """错误在因果链中的角色"""
    ROOT_CAUSE = "root_cause"      # 根因：没有 error 父节点的 error span
    CASCADED = "cascaded"          # 级联：由上游错误引起的
    INDEPENDENT = "independent"    # 独立：与其他错误无因果关系


class PatternType(Enum):
    """已知的错误 Pattern"""
    RETRY_STORM = "retry_storm"                # 同一操作被大量重试
    INFINITE_LOOP = "infinite_loop"            # Agent 在相同 tool 间循环
    CONTEXT_OVERFLOW = "context_overflow"      # Token 接近/超过模型上限
    HALLUCINATION_CASCADE = "hallucination_cascade"  # 幻觉输出被下游消费
    TIMEOUT_CASCADE = "timeout_cascade"        # 超时导致下游连锁失败
    EMPTY_RESPONSE = "empty_response"          # LLM 返回空内容
    COST_SPIKE = "cost_spike"                  # 单次 LLM 调用消耗超过总 token 的 50%
    SLOW_TOOL = "slow_tool"                    # Tool 耗时超过平均值的 3 倍
    REDUNDANT_CALLS = "redundant_calls"        # 相同 tool 用相同参数调用多次
    # New patterns
    TOKEN_WASTE = "token_waste"                # High input tokens with very few output tokens
    SEQUENTIAL_BOTTLENECK = "sequential_bottleneck"  # Independent tool calls run sequentially
    ERROR_RECOVERY = "error_recovery"          # Positive: agent recovered from an error


@dataclass
class CausalNode:
    """因果图中的节点（对应一个 span）"""
    span_id: str
    name: str
    kind: str                  # agent / llm / tool
    status: str                # ok / error
    error_message: Optional[str] = None
    error_role: ErrorRole = ErrorRole.INDEPENDENT
    duration_ms: float = 0.0
    token_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "name": self.name,
            "kind": self.kind,
            "status": self.status,
            "error_message": self.error_message,
            "error_role": self.error_role.value,
            "duration_ms": self.duration_ms,
            "token_count": self.token_count,
        }


@dataclass
class CausalEdge:
    """因果图中的边（表示错误传播方向）"""
    source_id: str        # 上游 span
    target_id: str        # 下游 span
    relation: str = "caused_by"  # caused_by / preceded_by

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source_id,
            "target": self.target_id,
            "relation": self.relation,
        }


@dataclass
class DetectedPattern:
    """检测到的已知错误 Pattern"""
    pattern_type: PatternType
    severity: str = "warning"    # info / warning / critical
    description: str = ""
    involved_spans: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern_type.value,
            "severity": self.severity,
            "description": self.description,
            "involved_spans": self.involved_spans,
            "details": self.details,
        }


@dataclass
class CausalDAG:
    """
    因果 DAG — trace 分析的核心输出

    包含：
    - 所有 span 作为节点
    - 错误传播边
    - root cause 标注
    - 检测到的 pattern
    """
    trace_id: str
    nodes: list[CausalNode] = field(default_factory=list)
    edges: list[CausalEdge] = field(default_factory=list)
    patterns: list[DetectedPattern] = field(default_factory=list)
    root_causes: list[str] = field(default_factory=list)  # root cause span_ids

    @property
    def has_errors(self) -> bool:
        return len(self.root_causes) > 0

    @property
    def cascade_depth(self) -> int:
        """错误级联的最大深度"""
        if not self.edges:
            return 0
        # BFS from root causes
        children: dict[str, list[str]] = {}
        for e in self.edges:
            children.setdefault(e.source_id, []).append(e.target_id)

        max_depth = 0
        for rc in self.root_causes:
            depth = self._bfs_depth(rc, children)
            max_depth = max(max_depth, depth)
        return max_depth

    def _bfs_depth(self, start: str, children: dict[str, list[str]]) -> int:
        depth = 0
        level = [start]
        while level:
            next_level = []
            for node_id in level:
                next_level.extend(children.get(node_id, []))
            if next_level:
                depth += 1
            level = next_level
        return depth

    # ------------------------------------------------------------------
    # Summary statistics
    # ------------------------------------------------------------------

    @property
    def total_errors(self) -> int:
        """Total number of error nodes in the DAG."""
        return sum(1 for n in self.nodes if n.status == "error")

    @property
    def patterns_found(self) -> int:
        """Number of detected patterns stored in this DAG."""
        return len(self.patterns)

    def summary_stats(self) -> dict[str, Any]:
        """
        Return a compact dict of summary statistics for the DAG.

        Keys
        ----
        ``total_nodes``, ``total_errors``, ``root_cause_count``,
        ``cascade_depth``, ``patterns_found``.
        """
        return {
            "total_nodes": len(self.nodes),
            "total_errors": self.total_errors,
            "root_cause_count": len(self.root_causes),
            "cascade_depth": self.cascade_depth,
            "patterns_found": self.patterns_found,
        }

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "patterns": [p.to_dict() for p in self.patterns],
            "root_causes": self.root_causes,
            "cascade_depth": self.cascade_depth,
            "has_errors": self.has_errors,
            "summary_stats": self.summary_stats(),
        }

    def to_json(self, *, indent: int = 2) -> str:
        """
        Serialise the DAG to a JSON string.

        Parameters
        ----------
        indent:
            JSON indentation level (default 2).

        Returns
        -------
        str
            Pretty-printed JSON representation of the DAG.
        """
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_markdown(self) -> str:
        """
        Generate a human-readable Markdown report of the causal DAG.

        The report includes:
        - Summary statistics (total errors, root causes, cascade depth,
          patterns found).
        - Root cause nodes.
        - Error propagation edges.
        - Detected patterns.

        Returns
        -------
        str
            Markdown-formatted report.
        """
        lines: list[str] = []

        lines.append(f"# Causal DAG Report — Trace `{self.trace_id}`\n")

        # --- Summary statistics ---
        stats = self.summary_stats()
        lines.append("## Summary\n")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Total nodes | {stats['total_nodes']} |")
        lines.append(f"| Total errors | {stats['total_errors']} |")
        lines.append(f"| Root causes | {stats['root_cause_count']} |")
        lines.append(f"| Max cascade depth | {stats['cascade_depth']} |")
        lines.append(f"| Patterns detected | {stats['patterns_found']} |")
        lines.append("")

        # --- Root causes ---
        if self.root_causes:
            lines.append("## Root Causes\n")
            node_map = {n.span_id: n for n in self.nodes}
            for rc_id in self.root_causes:
                node = node_map.get(rc_id)
                if node:
                    lines.append(
                        f"- **`{node.name}`** (`{rc_id}`)"
                        + (f": {node.error_message}" if node.error_message else "")
                    )
            lines.append("")
        else:
            lines.append("## Root Causes\n\nNo root causes detected.\n")

        # --- Error propagation edges ---
        if self.edges:
            lines.append("## Error Propagation\n")
            node_map = {n.span_id: n for n in self.nodes}
            for edge in self.edges:
                src = node_map.get(edge.source_id)
                tgt = node_map.get(edge.target_id)
                src_label = src.name if src else edge.source_id
                tgt_label = tgt.name if tgt else edge.target_id
                lines.append(
                    f"- `{src_label}` —[{edge.relation}]→ `{tgt_label}`"
                )
            lines.append("")

        # --- Detected patterns ---
        if self.patterns:
            lines.append("## Detected Patterns\n")
            for pat in self.patterns:
                severity_badge = {
                    "critical": "🔴",
                    "warning": "🟡",
                    "info": "🔵",
                }.get(pat.severity, "")
                lines.append(
                    f"### {severity_badge} `{pat.pattern_type.value}` "
                    f"({pat.severity})\n"
                )
                lines.append(f"{pat.description}\n")
                if pat.involved_spans:
                    spans_str = ", ".join(f"`{s}`" for s in pat.involved_spans)
                    lines.append(f"**Involved spans:** {spans_str}\n")
        else:
            lines.append("## Detected Patterns\n\nNo patterns detected.\n")

        # --- All nodes (collapsed table) ---
        if self.nodes:
            lines.append("## All Nodes\n")
            lines.append("| Span | Kind | Status | Duration (ms) | Tokens |")
            lines.append("|------|------|--------|---------------|--------|")
            for node in self.nodes:
                lines.append(
                    f"| `{node.name}` | {node.kind} | {node.status} "
                    f"| {node.duration_ms:.1f} | {node.token_count} |"
                )
            lines.append("")

        return "\n".join(lines)

    # Alias for JSON serialization (backward-compat)
    def dag_to_dict(self) -> dict[str, Any]:
        """Serialize the DAG to a JSON-compatible dictionary."""
        return self.to_dict()
