"""
Core data models for FlowLens tracing.

All trace data flows through these models:
  Span → SpanEvent → Trace → (export to JSONL / OTLP / API)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class SpanKind(Enum):
    """Span 类型 — 对应 Agent 执行的不同阶段"""
    AGENT = "agent"         # Agent 主循环
    LLM = "llm"             # LLM 调用
    TOOL = "tool"           # Tool/Skill 执行
    CHAIN = "chain"         # 多步链
    RETRIEVAL = "retrieval"  # RAG 检索
    CUSTOM = "custom"       # 用户自定义


class SpanStatus(Enum):
    """Span 执行状态"""
    UNSET = "unset"
    OK = "ok"
    ERROR = "error"


@dataclass
class SpanEvent:
    """Span 内的离散事件（如 checkpoint、异常）"""
    name: str
    timestamp: float = field(default_factory=time.time)
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class TokenUsage:
    """LLM Token 用量"""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    input_cost_usd: float = 0.0
    output_cost_usd: float = 0.0
    total_cost_usd: float = 0.0


@dataclass
class Span:
    """
    Trace 的基本单元 — 表示一次操作（LLM 调用、Tool 执行等）

    设计参考：OpenTelemetry Span 模型 + GenAI Semantic Conventions
    """
    # 标识
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    trace_id: str = ""
    parent_span_id: Optional[str] = None

    # 元数据
    name: str = ""
    kind: SpanKind = SpanKind.CUSTOM
    status: SpanStatus = SpanStatus.UNSET

    # 时间
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0

    # 属性 (OTEL GenAI conventions: gen_ai.*)
    attributes: dict[str, Any] = field(default_factory=dict)

    # 事件
    events: list[SpanEvent] = field(default_factory=list)

    # LLM 专属
    token_usage: Optional[TokenUsage] = None

    # 错误信息
    error_message: Optional[str] = None
    error_type: Optional[str] = None

    @property
    def duration_ms(self) -> float:
        """执行时长 (ms)"""
        if self.end_time > 0:
            return (self.end_time - self.start_time) * 1000
        return 0.0

    def finish(
        self,
        status: SpanStatus = SpanStatus.OK,
        error: Optional[str] = None,
    ) -> None:
        """结束 Span"""
        self.end_time = time.time()
        self.status = status
        if error:
            self.status = SpanStatus.ERROR
            self.error_message = error

    def add_event(self, name: str, **attrs: Any) -> None:
        """添加事件"""
        self.events.append(SpanEvent(name=name, attributes=attrs))

    def set_token_usage(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: str = "",
    ) -> None:
        """设置 token 用量并自动计算成本"""
        total = input_tokens + output_tokens
        # 成本估算（基于 2026 主流定价）
        costs = _estimate_cost(model, input_tokens, output_tokens)
        self.token_usage = TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total,
            **costs,
        )

    def to_dict(self) -> dict[str, Any]:
        """序列化为 dict（用于 JSONL 导出）"""
        d: dict[str, Any] = {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "kind": self.kind.value,
            "status": self.status.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "attributes": self.attributes,
            "events": [
                {"name": e.name, "timestamp": e.timestamp, "attributes": e.attributes}
                for e in self.events
            ],
        }
        if self.token_usage:
            d["token_usage"] = {
                "input_tokens": self.token_usage.input_tokens,
                "output_tokens": self.token_usage.output_tokens,
                "total_tokens": self.token_usage.total_tokens,
                "input_cost_usd": self.token_usage.input_cost_usd,
                "output_cost_usd": self.token_usage.output_cost_usd,
                "total_cost_usd": self.token_usage.total_cost_usd,
            }
        if self.error_message:
            d["error"] = {
                "message": self.error_message,
                "type": self.error_type,
            }
        return d


@dataclass
class Trace:
    """一次完整的 Agent 执行追踪"""
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    service_name: str = ""
    root_span_id: Optional[str] = None
    spans: list[Span] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        if self.end_time > 0:
            return (self.end_time - self.start_time) * 1000
        return 0.0

    @property
    def total_tokens(self) -> int:
        return sum(
            s.token_usage.total_tokens
            for s in self.spans
            if s.token_usage
        )

    @property
    def total_cost_usd(self) -> float:
        return sum(
            s.token_usage.total_cost_usd
            for s in self.spans
            if s.token_usage
        )

    @property
    def has_errors(self) -> bool:
        return any(s.status == SpanStatus.ERROR for s in self.spans)

    @property
    def error_count(self) -> int:
        return sum(1 for s in self.spans if s.status == SpanStatus.ERROR)

    def finish(self) -> None:
        self.end_time = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "service_name": self.service_name,
            "root_span_id": self.root_span_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "total_tokens": self.total_tokens,
            "total_cost_usd": self.total_cost_usd,
            "has_errors": self.has_errors,
            "error_count": self.error_count,
            "span_count": len(self.spans),
            "metadata": self.metadata,
            "spans": [s.to_dict() for s in self.spans],
        }


# ===== Cost estimation =====

# 定价表 (USD per 1M tokens, 2026 主流模型)
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    # (input_per_1m, output_per_1m)
    "claude-opus-4-20250514": (15.0, 75.0),
    "claude-sonnet-4-20250514": (3.0, 15.0),
    "claude-haiku-4-20250514": (0.25, 1.25),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.6),
    "gpt-4.1": (2.0, 8.0),
    "gpt-4.1-mini": (0.4, 1.6),
    "gemini-2.5-pro": (1.25, 10.0),
    "gemini-2.5-flash": (0.15, 0.6),
    "deepseek-v3": (0.27, 1.1),
    "deepseek-r1": (0.55, 2.19),
}

# 默认定价 (中等模型)
_DEFAULT_PRICING = (3.0, 15.0)


def _estimate_cost(
    model: str, input_tokens: int, output_tokens: int
) -> dict[str, float]:
    """估算 LLM 调用成本"""
    # 模糊匹配模型名
    pricing = _DEFAULT_PRICING
    model_lower = model.lower()
    for key, val in _MODEL_PRICING.items():
        if key in model_lower or model_lower in key:
            pricing = val
            break

    input_cost = (input_tokens / 1_000_000) * pricing[0]
    output_cost = (output_tokens / 1_000_000) * pricing[1]
    return {
        "input_cost_usd": round(input_cost, 6),
        "output_cost_usd": round(output_cost, 6),
        "total_cost_usd": round(input_cost + output_cost, 6),
    }
