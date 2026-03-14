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
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable

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
            for span in trace.spans:
                indent = "  "
                kind_icon = {
                    "agent": "🤖", "llm": "🧠", "tool": "🔧",
                    "chain": "🔗", "retrieval": "🔍", "custom": "📌",
                }.get(span.kind.value, "•")

                err = ""
                if span.error_message:
                    err = f" ❌ {span.error_message[:60]}"

                tokens = ""
                if span.token_usage:
                    tokens = f" [{span.token_usage.total_tokens} tok]"

                print(
                    f"{indent}{kind_icon} {span.name} "
                    f"({span.duration_ms:.0f}ms){tokens}{err}"
                )


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
