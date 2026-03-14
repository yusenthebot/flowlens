"""
Trace 导出器 — 将采集到的 trace 数据输出到不同目标

支持：
- ConsoleExporter: 打印到 stdout（开发调试）
- JSONLExporter: 写入 JSONL 文件（离线分析、导入 FlowLens Server）
- CallbackExporter: 自定义回调（用于测试和扩展）
- HTTPExporter: POST 到 FlowLens Server（生产部署）
- OTLPExporter: 导出到 OpenTelemetry OTLP/HTTP 端点（兼容 Jaeger、Tempo 等）
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Optional

from .models import Span, SpanKind, SpanStatus, Trace

logger = logging.getLogger(__name__)


class TraceExporter(ABC):
    """导出器基类"""

    @abstractmethod
    def export(self, trace: Trace) -> None:
        """导出一条完整的 trace"""
        ...

    def shutdown(self) -> None:
        """清理资源"""
        pass


class ConsoleExporter(TraceExporter):
    """打印到控制台（开发调试用）"""

    def __init__(self, colored: bool = True, verbose: bool = False):
        self.colored = colored and sys.stdout.isatty()
        self.verbose = verbose

    def export(self, trace: Trace) -> None:
        if self.colored:
            header = f"\033[96m\033[1m[FlowLens]\033[0m"
        else:
            header = "[FlowLens]"

        status = "ERROR" if trace.has_errors else "OK"
        if self.colored:
            status_color = "\033[91m" if trace.has_errors else "\033[92m"
            status = f"{status_color}{status}\033[0m"

        print(
            f"{header} Trace {trace.trace_id[:12]}... "
            f"| {len(trace.spans)} spans "
            f"| {trace.duration_ms:.0f}ms "
            f"| {trace.total_tokens} tokens "
            f"| ${trace.total_cost_usd:.4f} "
            f"| {status}"
        )

        if self.verbose:
            # 构建 span 树，然后打印
            self._print_span_tree(trace)

    def _print_span_tree(self, trace: Trace) -> None:
        """打印 span 树结构（带缩进表示层级）"""
        # 构建 parent -> children 映射
        children_map: dict[Optional[str], list] = {}
        for span in trace.spans:
            parent_id = span.parent_span_id
            if parent_id not in children_map:
                children_map[parent_id] = []
            children_map[parent_id].append(span)

        # 从 root span 开始递归打印
        root_spans = children_map.get(None, [])
        for span in root_spans:
            self._print_span_node(span, children_map, depth=0)

    def _print_span_node(self, span, children_map: dict, depth: int = 0) -> None:
        """递归打印单个 span 节点及其子节点"""
        # 缩进
        indent = "  " * depth
        tree_prefix = "└─ " if depth > 0 else ""

        # 图标
        kind_icon = {
            "agent": "🤖",
            "llm": "🧠",
            "tool": "🔧",
            "chain": "🔗",
            "retrieval": "🔍",
            "custom": "📌",
        }.get(span.kind.value, "•")

        # 错误标记
        err = ""
        if span.error_message:
            err = f" ❌ {span.error_message[:60]}"

        # Token 统计
        tokens = ""
        if span.token_usage:
            tokens = f" [{span.token_usage.total_tokens} tok]"

        # 打印 span
        print(
            f"{indent}{tree_prefix}{kind_icon} {span.name} "
            f"({span.duration_ms:.0f}ms){tokens}{err}"
        )

        # 打印子 span
        children = children_map.get(span.span_id, [])
        for child in children:
            self._print_span_node(child, children_map, depth + 1)


class JSONLExporter(TraceExporter):
    """
    写入 JSONL 文件 — 每行一个完整 trace
    模式来源：OpenClaw 的 JSONL session 持久化
    """

    def __init__(self, output_dir: str | Path = "./traces"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._file_path = self.output_dir / "traces.jsonl"
        self._file = open(self._file_path, "a", encoding="utf-8")

    def export(self, trace: Trace) -> None:
        line = json.dumps(trace.to_dict(), ensure_ascii=False)
        self._file.write(line + "\n")
        self._file.flush()
        logger.debug(f"Exported trace {trace.trace_id[:12]} to {self._file_path}")

    def shutdown(self) -> None:
        if self._file and not self._file.closed:
            self._file.close()


class CallbackExporter(TraceExporter):
    """自定义回调导出器（用于测试）"""

    def __init__(self, callback: Callable[[Trace], None]):
        self._callback = callback

    def export(self, trace: Trace) -> None:
        self._callback(trace)


class HTTPExporter(TraceExporter):
    """POST 到 FlowLens Server"""

    def __init__(self, endpoint: str = "http://localhost:8585/v1/traces/ingest"):
        self.endpoint = endpoint

    def export(self, trace: Trace) -> None:
        # MVP: 同步 POST（生产环境应改为异步批量）
        try:
            import urllib.request
            data = json.dumps(trace.to_dict(), ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                self.endpoint,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
            logger.debug(f"Exported trace {trace.trace_id[:12]} to {self.endpoint}")
        except Exception as e:
            logger.warning(f"Failed to export trace to {self.endpoint}: {e}")


class BatchHTTPExporter(TraceExporter):
    """批量 POST 到 FlowLens Server — 优化网络吞吐量"""

    def __init__(
        self,
        endpoint: str = "http://localhost:8585/v1/traces/ingest",
        batch_size: int = 10,
        flush_interval: float = 5.0,
    ):
        """初始化批量导出器

        Args:
            endpoint: FlowLens Server 端点
            batch_size: 批量大小（达到此数量时自动 flush）
            flush_interval: 刷新间隔（秒）— 定期 flush 缓冲的 trace
        """
        self.endpoint = endpoint
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self._batch: list[Trace] = []
        self._lock = threading.Lock()
        self._last_flush = time.time()
        self._shutdown = False
        # 后台线程定期 flush
        self._flush_thread = threading.Thread(target=self._periodic_flush, daemon=True)
        self._flush_thread.start()

    def export(self, trace: Trace) -> None:
        with self._lock:
            self._batch.append(trace)
            if len(self._batch) >= self.batch_size:
                self._flush_batch()

    def _flush_batch(self) -> None:
        """内部方法，假设已持有 lock"""
        if not self._batch:
            return

        batch_to_send = self._batch[:]
        self._batch.clear()
        self._last_flush = time.time()

        # 在锁外执行网络 I/O
        try:
            import urllib.request
            data = json.dumps(
                {"traces": [t.to_dict() for t in batch_to_send]},
                ensure_ascii=False,
            ).encode("utf-8")
            req = urllib.request.Request(
                self.endpoint,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=10)
            logger.debug(f"Exported batch of {len(batch_to_send)} traces to {self.endpoint}")
        except Exception as e:
            logger.warning(f"Failed to export batch to {self.endpoint}: {e}")

    def _periodic_flush(self) -> None:
        """后台线程：定期刷新缓冲"""
        while not self._shutdown:
            time.sleep(self.flush_interval)
            with self._lock:
                if self._batch and time.time() - self._last_flush >= self.flush_interval:
                    self._flush_batch()

    def shutdown(self) -> None:
        """关闭导出器，刷新所有待导出的 trace"""
        self._shutdown = True
        with self._lock:
            self._flush_batch()
        self._flush_thread.join(timeout=5.0)


class FilterExporter(TraceExporter):
    """包装导出器 — 只导出满足条件的 trace"""

    def __init__(
        self,
        inner: TraceExporter,
        predicate: Callable[[Trace], bool],
    ):
        """初始化过滤导出器

        Args:
            inner: 内部导出器
            predicate: 过滤函数 — 返回 True 的 trace 会被导出
        """
        self.inner = inner
        self.predicate = predicate

    def export(self, trace: Trace) -> None:
        if self.predicate(trace):
            self.inner.export(trace)

    def shutdown(self) -> None:
        self.inner.shutdown()


class MultiExporter(TraceExporter):
    """同时向多个导出器发送 trace"""

    def __init__(self, exporters: list[TraceExporter]):
        """初始化多导出器

        Args:
            exporters: 导出器列表
        """
        self.exporters = exporters

    def export(self, trace: Trace) -> None:
        for exporter in self.exporters:
            try:
                exporter.export(trace)
            except Exception as e:
                logger.warning(f"Exporter {type(exporter).__name__} failed: {e}")

    def shutdown(self) -> None:
        for exporter in self.exporters:
            try:
                exporter.shutdown()
            except Exception as e:
                logger.warning(f"Shutdown of {type(exporter).__name__} failed: {e}")


class OTLPExporter(TraceExporter):
    """
    Export traces to an OpenTelemetry OTLP/HTTP endpoint.

    Converts FlowLens Span/Trace objects to the OTLP protobuf-JSON format and
    POSTs them to a configurable collector endpoint (default: http://localhost:4318/v1/traces).

    Requires the ``opentelemetry-exporter-otlp-proto-http`` package (installed via
    ``pip install 'flowlens[otlp]'``).  When the package is absent the exporter
    logs a warning and silently drops every trace instead of crashing.

    SpanKind mapping
    ----------------
    FlowLens kind  → OTel SpanKind int
    AGENT          → INTERNAL  (2)
    LLM            → CLIENT    (3)
    TOOL           → INTERNAL  (2)
    CHAIN          → INTERNAL  (2)
    RETRIEVAL      → CLIENT    (3)
    CUSTOM         → INTERNAL  (2)

    SpanStatus mapping
    ------------------
    FlowLens status → OTel StatusCode
    UNSET           → STATUS_CODE_UNSET (0)
    OK              → STATUS_CODE_OK    (1)
    ERROR           → STATUS_CODE_ERROR (2)

    Attributes
    ----------
    Token-usage fields are preserved under the ``gen_ai.*`` namespace so they
    appear as first-class attributes in any OTel-compatible backend.
    """

    # OTel SpanKind constants (mirrors opentelemetry.trace.SpanKind values)
    _OTEL_SPAN_KIND_INTERNAL = 1
    _OTEL_SPAN_KIND_SERVER = 2
    _OTEL_SPAN_KIND_CLIENT = 3
    _OTEL_SPAN_KIND_PRODUCER = 4
    _OTEL_SPAN_KIND_CONSUMER = 5

    _KIND_MAP: dict[SpanKind, int] = {
        SpanKind.AGENT: _OTEL_SPAN_KIND_INTERNAL,
        SpanKind.LLM: _OTEL_SPAN_KIND_CLIENT,
        SpanKind.TOOL: _OTEL_SPAN_KIND_INTERNAL,
        SpanKind.CHAIN: _OTEL_SPAN_KIND_INTERNAL,
        SpanKind.RETRIEVAL: _OTEL_SPAN_KIND_CLIENT,
        SpanKind.CUSTOM: _OTEL_SPAN_KIND_INTERNAL,
    }

    # OTel StatusCode constants
    _STATUS_CODE_UNSET = 0
    _STATUS_CODE_OK = 1
    _STATUS_CODE_ERROR = 2

    _STATUS_MAP: dict[SpanStatus, int] = {
        SpanStatus.UNSET: _STATUS_CODE_UNSET,
        SpanStatus.OK: _STATUS_CODE_OK,
        SpanStatus.ERROR: _STATUS_CODE_ERROR,
    }

    def __init__(
        self,
        endpoint: str = "http://localhost:4318/v1/traces",
        headers: Optional[dict[str, str]] = None,
        timeout: float = 10.0,
        service_name: str = "flowlens",
    ) -> None:
        """Initialise the OTLP exporter.

        Args:
            endpoint: OTLP/HTTP traces endpoint URL.
            headers: Optional HTTP headers (e.g. authentication tokens).
            timeout: HTTP request timeout in seconds.
            service_name: Fallback service name used when a Trace has none set.
        """
        self.endpoint = endpoint
        self.headers = headers or {}
        self.timeout = timeout
        self.service_name = service_name
        self._available = self._check_availability()

    # ------------------------------------------------------------------
    # Availability check
    # ------------------------------------------------------------------

    @staticmethod
    def _check_availability() -> bool:
        """Return True if the opentelemetry packages are importable."""
        try:
            import opentelemetry  # noqa: F401
            return True
        except ImportError:
            logger.warning(
                "opentelemetry packages are not installed. "
                "OTLPExporter will silently drop all traces. "
                "Install them with: pip install 'flowlens[otlp]'"
            )
            return False

    # ------------------------------------------------------------------
    # Public export interface
    # ------------------------------------------------------------------

    def export(self, trace: Trace) -> None:
        """Export a completed trace synchronously via OTLP/HTTP."""
        if not self._available:
            return
        payload = self._build_payload(trace)
        self._send(payload)

    async def export_async(self, trace: Trace) -> None:
        """Export a completed trace asynchronously via OTLP/HTTP."""
        if not self._available:
            return
        import asyncio

        payload = self._build_payload(trace)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._send, payload)

    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------

    def _build_payload(self, trace: Trace) -> dict[str, Any]:
        """Convert a FlowLens Trace into an OTLP/JSON ResourceSpans payload."""
        svc_name = trace.service_name or self.service_name

        resource_attrs = [
            _otel_str_attr("service.name", svc_name),
            _otel_str_attr("telemetry.sdk.name", "flowlens"),
            _otel_str_attr("telemetry.sdk.language", "python"),
        ]

        otel_spans = [self._convert_span(span, trace) for span in trace.spans]

        return {
            "resourceSpans": [
                {
                    "resource": {"attributes": resource_attrs},
                    "scopeSpans": [
                        {
                            "scope": {
                                "name": "flowlens.tracer",
                                "version": "0.1.0",
                            },
                            "spans": otel_spans,
                        }
                    ],
                }
            ]
        }

    def _convert_span(self, span: Span, trace: Trace) -> dict[str, Any]:
        """Convert a single FlowLens Span to an OTLP span dict."""
        # Timestamps must be in nanoseconds (Unix epoch)
        start_ns = int(span.start_time * 1_000_000_000)
        end_ns = int(span.end_time * 1_000_000_000) if span.end_time > 0 else start_ns

        # IDs: OTel expects lowercase hex, 16 chars for span, 32 for trace
        trace_id_hex = _pad_hex(trace.trace_id, 32)
        span_id_hex = _pad_hex(span.span_id, 16)
        parent_hex = _pad_hex(span.parent_span_id, 16) if span.parent_span_id else ""

        attributes = self._build_attributes(span)

        events = [
            {
                "timeUnixNano": str(int(ev.timestamp * 1_000_000_000)),
                "name": ev.name,
                "attributes": _dict_to_otel_attrs(ev.attributes),
            }
            for ev in span.events
        ]

        otel_status: dict[str, Any] = {
            "code": self._STATUS_MAP.get(span.status, self._STATUS_CODE_UNSET)
        }
        if span.status == SpanStatus.ERROR and span.error_message:
            otel_status["message"] = span.error_message

        result: dict[str, Any] = {
            "traceId": trace_id_hex,
            "spanId": span_id_hex,
            "name": span.name,
            "kind": self._KIND_MAP.get(span.kind, self._OTEL_SPAN_KIND_INTERNAL),
            "startTimeUnixNano": str(start_ns),
            "endTimeUnixNano": str(end_ns),
            "attributes": attributes,
            "events": events,
            "status": otel_status,
        }

        if parent_hex:
            result["parentSpanId"] = parent_hex

        return result

    def _build_attributes(self, span: Span) -> list[dict[str, Any]]:
        """Build the OTel attributes list from a FlowLens Span."""
        attrs: dict[str, Any] = {}

        # Copy span-level attributes directly
        attrs.update(span.attributes)

        # Map SpanKind to gen_ai.operation.name
        attrs["gen_ai.operation.name"] = span.kind.value

        # Token usage → gen_ai.* attributes
        if span.token_usage:
            tu = span.token_usage
            attrs["gen_ai.usage.input_tokens"] = tu.input_tokens
            attrs["gen_ai.usage.output_tokens"] = tu.output_tokens
            attrs["gen_ai.usage.total_tokens"] = tu.total_tokens
            attrs["gen_ai.usage.input_cost_usd"] = tu.input_cost_usd
            attrs["gen_ai.usage.output_cost_usd"] = tu.output_cost_usd
            attrs["gen_ai.usage.total_cost_usd"] = tu.total_cost_usd

        # Error details
        if span.error_message:
            attrs["exception.message"] = span.error_message
        if span.error_type:
            attrs["exception.type"] = span.error_type

        return _dict_to_otel_attrs(attrs)

    # ------------------------------------------------------------------
    # HTTP transport
    # ------------------------------------------------------------------

    def _send(self, payload: dict[str, Any]) -> None:
        """POST the OTLP JSON payload to the configured endpoint."""
        try:
            import urllib.request

            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                **self.headers,
            }
            req = urllib.request.Request(
                self.endpoint,
                data=body,
                headers=headers,
                method="POST",
            )
            urllib.request.urlopen(req, timeout=self.timeout)
            logger.debug("OTLPExporter: exported %d span(s) to %s", len(payload.get("resourceSpans", [])), self.endpoint)
        except Exception as exc:
            logger.warning("OTLPExporter: failed to export to %s — %s", self.endpoint, exc)


# ---------------------------------------------------------------------------
# OTLP attribute helpers
# ---------------------------------------------------------------------------

def _pad_hex(value: Optional[str], length: int) -> str:
    """Ensure a hex string has exactly *length* characters (pad or truncate)."""
    if not value:
        return "0" * length
    clean = value.replace("-", "").lower()
    if len(clean) < length:
        clean = clean.zfill(length)
    return clean[:length]


def _otel_str_attr(key: str, value: str) -> dict[str, Any]:
    """Return a single OTel attribute dict with a string value."""
    return {"key": key, "value": {"stringValue": value}}


def _dict_to_otel_attrs(d: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a plain Python dict to a list of typed OTel attribute dicts."""
    attrs: list[dict[str, Any]] = []
    for key, value in d.items():
        attrs.append({"key": str(key), "value": _to_otel_value(value)})
    return attrs


def _to_otel_value(value: Any) -> dict[str, Any]:
    """Map a Python value to the appropriate OTel AnyValue representation."""
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": value}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, (list, tuple)):
        return {"arrayValue": {"values": [_to_otel_value(v) for v in value]}}
    if isinstance(value, dict):
        return {
            "kvlistValue": {
                "values": [
                    {"key": str(k), "value": _to_otel_value(v)}
                    for k, v in value.items()
                ]
            }
        }
    # Fallback: stringify
    return {"stringValue": str(value)}


def create_exporter(
    export_to: str = "console",
    output_dir: str = "./traces",
    endpoint: str = "http://localhost:8585/v1/traces/ingest",
    otlp_endpoint: str = "http://localhost:4318/v1/traces",
    verbose: bool = False,
) -> TraceExporter:
    """工厂函数 — 根据配置创建导出器"""
    if export_to == "jsonl":
        return JSONLExporter(output_dir=output_dir)
    elif export_to == "http":
        return HTTPExporter(endpoint=endpoint)
    elif export_to == "otlp":
        return OTLPExporter(endpoint=otlp_endpoint)
    elif export_to == "console":
        return ConsoleExporter(verbose=verbose)
    else:
        raise ValueError(
            f"Unknown exporter: {export_to}. Use 'console', 'jsonl', 'http', or 'otlp'."
        )
