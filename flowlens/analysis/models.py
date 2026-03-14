"""
因果分析数据模型

CausalDAG 是核心输出：从 trace 数据构建的错误传播有向无环图。
"""

from __future__ import annotations

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "patterns": [p.to_dict() for p in self.patterns],
            "root_causes": self.root_causes,
            "cascade_depth": self.cascade_depth,
            "has_errors": self.has_errors,
        }
