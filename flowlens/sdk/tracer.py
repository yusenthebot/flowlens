"""
FlowLens 核心 Tracer — 管理 trace/span 生命周期

这是 SDK 的入口，用户通过 FlowLens 实例管理整个采集生命周期。
"""

from __future__ import annotations

import logging
import random
import re
import threading
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

# ---------------------------------------------------------------------------
# Span validation constants
# ---------------------------------------------------------------------------

# Maximum allowed span name length (characters)
_MAX_SPAN_NAME_LEN = 256

# Allowed span name pattern: printable non-control characters; reject null bytes
_SPAN_NAME_RE = re.compile(r"^[^\x00-\x1f\x7f]+$")

# Maximum number of spans allowed per trace to prevent memory exhaustion
_MAX_SPANS_PER_TRACE = 5_000

# Shutdown timeout in seconds
_SHUTDOWN_TIMEOUT = 10.0


def _validate_span_name(name: str) -> str:
    """
    Validate and normalise a span name.

    - Enforces a maximum length (truncates with a warning rather than raising).
    - Rejects names containing control characters (including null bytes).
    - Returns the (possibly truncated) validated name.
    """
    if not name:
        name = "unnamed"
    if len(name) > _MAX_SPAN_NAME_LEN:
        logger.warning(
            "[FlowLens] Span name truncated from %d to %d characters",
            len(name), _MAX_SPAN_NAME_LEN,
        )
        name = name[:_MAX_SPAN_NAME_LEN]
    if not _SPAN_NAME_RE.match(name):
        # Strip control characters rather than rejecting outright so that
        # instrumentation never silently drops telemetry data
        cleaned = re.sub(r"[\x00-\x1f\x7f]", "", name) or "unnamed"
        logger.warning(
            "[FlowLens] Span name contained control characters; cleaned to %r",
            cleaned,
        )
        name = cleaned
    return name


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

    Thread safety:
        The singleton reference and ``_active_traces`` dict are protected by
        ``_instance_lock`` and ``_traces_lock`` respectively, making all public
        methods safe to call from multiple threads concurrently.
    """

    # Protects reads and writes to _instance
    _instance_lock: threading.Lock = threading.Lock()
    _instance: Optional[FlowLens] = None

    def __init__(
        self,
        service_name: str = "flowlens",
        export_to: str = "console",
        output_dir: str = "./traces",
        endpoint: str = "http://localhost:8585/v1/traces/ingest",
        otlp_endpoint: str = "http://localhost:4318/v1/traces",
        verbose: bool = False,
        metadata: Optional[dict[str, Any]] = None,
        sample_rate: float = 1.0,
        on_trace_complete: Optional[Callable[[Trace], None]] = None,
    ):
        """初始化 FlowLens

        Args:
            service_name: 服务名称
            export_to: 导出目标 ('console', 'jsonl', 'http', 'otlp')
            output_dir: 输出目录 (用于 jsonl 导出)
            endpoint: HTTP 端点 (用于 http 导出，指向 FlowLens Server)
            otlp_endpoint: OTLP/HTTP 端点 (用于 otlp 导出，默认: http://localhost:4318/v1/traces)
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
            otlp_endpoint=otlp_endpoint,
            verbose=verbose,
        )
        self._active_traces: dict[str, Trace] = {}
        # Per-instance lock protecting _active_traces
        self._traces_lock: threading.Lock = threading.Lock()

        # 设为全局单例 (thread-safe)
        with FlowLens._instance_lock:
            FlowLens._instance = self

    @classmethod
    def get_instance(cls) -> Optional[FlowLens]:
        """获取全局 FlowLens 实例 (thread-safe)"""
        with cls._instance_lock:
            return cls._instance

    @classmethod
    def configure(
        cls,
        service_name: str = "flowlens",
        export_to: str = "console",
        output_dir: str = "./traces",
        endpoint: str = "http://localhost:8585/v1/traces/ingest",
        otlp_endpoint: str = "http://localhost:4318/v1/traces",
        verbose: bool = False,
        metadata: Optional[dict[str, Any]] = None,
        sample_rate: float = 1.0,
        on_trace_complete: Optional[Callable[[Trace], None]] = None,
    ) -> FlowLens:
        """流式配置方式创建 FlowLens 实例

        用法:
            lens = FlowLens.configure(
                service_name="my-agent",
                export_to="otlp",
                otlp_endpoint="http://collector:4318/v1/traces",
            )
        """
        return cls(
            service_name=service_name,
            export_to=export_to,
            output_dir=output_dir,
            endpoint=endpoint,
            otlp_endpoint=otlp_endpoint,
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
        """创建并启动一个新的 trace (thread-safe)"""
        trace = Trace(
            service_name=self.service_name,
            metadata={**self.metadata, **(metadata or {})},
        )
        with self._traces_lock:
            self._active_traces[trace.trace_id] = trace
        return trace

    def end_trace(self, trace: Trace) -> None:
        """结束 trace 并导出（如果采样命中）(thread-safe)"""
        trace.finish()

        # 采样决定
        if random.random() > self.sample_rate:
            with self._traces_lock:
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
        with self._traces_lock:
            self._active_traces.pop(trace.trace_id, None)

    # ===== Span 生命周期 =====

    def start_span(
        self,
        name: str,
        kind: SpanKind = SpanKind.CUSTOM,
        attributes: Optional[dict] = None,
    ) -> Span:
        """
        创建并启动一个 span（自动关联到当前 trace 和父 span）

        Enforces span-name validation and per-trace span limits to prevent
        memory exhaustion from runaway instrumentation loops.
        """
        name = _validate_span_name(name)

        span = Span(
            name=name,
            kind=kind,
            attributes=attributes or {},
        )

        # 关联到当前 trace
        trace = get_current_trace()
        if trace:
            # Enforce per-trace span limit
            if len(trace.spans) >= _MAX_SPANS_PER_TRACE:
                logger.warning(
                    "[FlowLens] Trace %s has reached the maximum of %d spans; "
                    "new span %r will not be recorded",
                    trace.trace_id[:12], _MAX_SPANS_PER_TRACE, name,
                )
                # Return the span un-attached so the decorated function still runs
                return span

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

    def shutdown(self, timeout: float = _SHUTDOWN_TIMEOUT) -> None:
        """
        关闭 FlowLens，刷新所有未导出的数据。

        Args:
            timeout: Maximum seconds to wait for in-flight exports to complete.
                     The shutdown operation is best-effort; if the exporter
                     does not finish within *timeout* seconds a warning is logged
                     and shutdown proceeds regardless.
        """
        # Snapshot active traces under the lock to avoid mutating while iterating
        with self._traces_lock:
            pending = list(self._active_traces.values())

        # Export pending traces in a background thread so we can honour the timeout
        def _flush() -> None:
            for trace in pending:
                try:
                    self.end_trace(trace)
                except Exception as e:
                    logger.warning("[FlowLens] Error flushing trace during shutdown: %s", e)
            try:
                self._exporter.shutdown()
            except Exception as e:
                logger.warning("[FlowLens] Exporter shutdown error: %s", e)

        flush_thread = threading.Thread(target=_flush, daemon=True, name="flowlens-shutdown")
        flush_thread.start()
        flush_thread.join(timeout=timeout)
        if flush_thread.is_alive():
            logger.warning(
                "[FlowLens] Shutdown did not complete within %.1f s; "
                "some traces may not have been exported",
                timeout,
            )

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
