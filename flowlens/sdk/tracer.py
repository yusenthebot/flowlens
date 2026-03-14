"""
FlowLens 核心 Tracer — 管理 trace/span 生命周期

这是 SDK 的入口，用户通过 FlowLens 实例管理整个采集生命周期。
"""

from __future__ import annotations

import logging
import random
from typing import Optional, Any, Callable

from .models import Span, SpanKind, SpanStatus, Trace
from .context import (
    TraceContext,
    SpanContext,
    get_current_trace,
    get_current_span,
    set_current_trace,
)
from .exporters import TraceExporter, create_exporter

logger = logging.getLogger(__name__)


class FlowLens:
    """
    FlowLens 全局实例 — 管理采集生命周期

    用法：
        lens = FlowLens(service_name="my-agent", export_to="jsonl")

        # 方式 1: 装饰器（推荐）
        @trace_agent(name="bot")
        async def run(): ...

        # 方式 2: 手动 API
        trace = lens.start_trace()
        span = lens.start_span("do_something", kind=SpanKind.TOOL)
        span.finish()
        lens.end_trace(trace)
    """

    _instance: Optional[FlowLens] = None

    def __init__(
        self,
        service_name: str = "flowlens",
        export_to: str = "console",
        output_dir: str = "./traces",
        endpoint: str = "http://localhost:8585/v1/traces/ingest",
        verbose: bool = False,
        metadata: Optional[dict[str, Any]] = None,
        sample_rate: float = 1.0,
        on_trace_complete: Optional[Callable[[Trace], None]] = None,
    ):
        """初始化 FlowLens

        Args:
            service_name: 服务名称
            export_to: 导出目标 ('console', 'jsonl', 'http')
            output_dir: 输出目录 (用于 jsonl 导出)
            endpoint: HTTP 端点 (用于 http 导出)
            verbose: 详细输出
            metadata: 全局元数据
            sample_rate: 采样率 (0.0 to 1.0) — 只采集指定比例的 trace
            on_trace_complete: trace 完成时的回调函数
        """
        self.service_name = service_name
        self.metadata = metadata or {}
        self.sample_rate = max(0.0, min(1.0, sample_rate))
        self.on_trace_complete = on_trace_complete
        self._exporter: TraceExporter = create_exporter(
            export_to=export_to,
            output_dir=output_dir,
            endpoint=endpoint,
            verbose=verbose,
        )
        self._active_traces: dict[str, Trace] = {}

        # 设为全局单例
        FlowLens._instance = self

    @classmethod
    def get_instance(cls) -> Optional[FlowLens]:
        """获取全局 FlowLens 实例"""
        return cls._instance

    @classmethod
    def configure(
        cls,
        service_name: str = "flowlens",
        export_to: str = "console",
        output_dir: str = "./traces",
        endpoint: str = "http://localhost:8585/v1/traces/ingest",
        verbose: bool = False,
        metadata: Optional[dict[str, Any]] = None,
        sample_rate: float = 1.0,
        on_trace_complete: Optional[Callable[[Trace], None]] = None,
    ) -> FlowLens:
        """流式配置方式创建 FlowLens 实例

        用法:
            lens = FlowLens.configure(
                service_name="my-agent",
                export_to="jsonl",
                sample_rate=0.1,
            )
        """
        return cls(
            service_name=service_name,
            export_to=export_to,
            output_dir=output_dir,
            endpoint=endpoint,
            verbose=verbose,
            metadata=metadata,
            sample_rate=sample_rate,
            on_trace_complete=on_trace_complete,
        )

    def set_exporter(self, exporter: TraceExporter) -> None:
        """替换导出器"""
        self._exporter = exporter

    # ===== Trace 生命周期 =====

    def start_trace(self, metadata: Optional[dict] = None) -> Trace:
        """创建并启动一个新的 trace"""
        trace = Trace(
            service_name=self.service_name,
            metadata={**self.metadata, **(metadata or {})},
        )
        self._active_traces[trace.trace_id] = trace
        return trace

    def end_trace(self, trace: Trace) -> None:
        """结束 trace 并导出（如果采样命中）"""
        trace.finish()

        # 采样决定
        if random.random() > self.sample_rate:
            self._active_traces.pop(trace.trace_id, None)
            return

        # 执行回调
        if self.on_trace_complete:
            try:
                self.on_trace_complete(trace)
            except Exception as e:
                logger.warning(f"Callback on_trace_complete failed: {e}")

        # 导出
        self._exporter.export(trace)
        self._active_traces.pop(trace.trace_id, None)

    # ===== Span 生命周期 =====

    def start_span(
        self,
        name: str,
        kind: SpanKind = SpanKind.CUSTOM,
        attributes: Optional[dict] = None,
    ) -> Span:
        """创建并启动一个 span（自动关联到当前 trace 和父 span）"""
        span = Span(
            name=name,
            kind=kind,
            attributes=attributes or {},
        )

        # 关联到当前 trace
        trace = get_current_trace()
        if trace:
            span.trace_id = trace.trace_id
            trace.spans.append(span)
            if not trace.root_span_id:
                trace.root_span_id = span.span_id

        # 关联到父 span
        parent = get_current_span()
        if parent:
            span.parent_span_id = parent.span_id

        return span

    # ===== 便捷方法 =====

    def checkpoint(self, name: str, **attrs: Any) -> None:
        """在当前 span 中标记 checkpoint"""
        span = get_current_span()
        if span:
            span.add_event(f"checkpoint:{name}", **attrs)

    def shutdown(self) -> None:
        """关闭 FlowLens，刷新所有未导出的数据"""
        # 导出所有未结束的 trace
        for trace in list(self._active_traces.values()):
            self.end_trace(trace)
        self._exporter.shutdown()
        logger.info("FlowLens shut down")


# ===== Utility functions =====


def get_current_trace() -> Optional[Trace]:
    """获取当前 trace（全局便捷函数）

    用法:
        trace = get_current_trace()
        if trace:
            trace.metadata["user_id"] = "123"
    """
    from .context import get_current_trace as _get_current_trace
    return _get_current_trace()


def get_current_span() -> Optional[Span]:
    """获取当前 span（全局便捷函数）

    用法:
        span = get_current_span()
        if span:
            span.attributes["custom_key"] = "value"
    """
    from .context import get_current_span as _get_current_span
    return _get_current_span()
