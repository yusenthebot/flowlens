"""
Trace 导出器 — 将采集到的 trace 数据输出到不同目标

支持：
- ConsoleExporter: 打印到 stdout（开发调试）
- JSONLExporter: 写入 JSONL 文件（离线分析、导入 FlowLens Server）
- CallbackExporter: 自定义回调（用于测试和扩展）
- HTTPExporter: POST 到 FlowLens Server（生产部署）
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
from typing import Callable, Optional

from .models import Trace

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


def create_exporter(
    export_to: str = "console",
    output_dir: str = "./traces",
    endpoint: str = "http://localhost:8585/v1/traces/ingest",
    verbose: bool = False,
) -> TraceExporter:
    """工厂函数 — 根据配置创建导出器"""
    if export_to == "jsonl":
        return JSONLExporter(output_dir=output_dir)
    elif export_to == "http":
        return HTTPExporter(endpoint=endpoint)
    elif export_to == "console":
        return ConsoleExporter(verbose=verbose)
    else:
        raise ValueError(f"Unknown exporter: {export_to}. Use 'console', 'jsonl', or 'http'.")
