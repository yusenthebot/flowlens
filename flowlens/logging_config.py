"""
FlowLens Logging Configuration

Two modes:
- Development (FLOWLENS_ENV=development or DEV=1):
    Pretty, human-readable log lines with ANSI colours and a concise format.
- Production (default):
    Structured JSON log lines that are easy to ingest into log aggregators
    (Datadog, Splunk, Loki, etc.).

Log level is controlled by the FLOWLENS_LOG_LEVEL environment variable
(default: INFO).

Usage:
    from flowlens.logging_config import configure_logging

    configure_logging()          # call once at process start-up
    configure_logging("DEBUG")   # override level at runtime
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RESET = "\033[0m"
_BOLD = "\033[1m"

_LEVEL_COLORS: dict[str, str] = {
    "DEBUG": "\033[36m",       # cyan
    "INFO": "\033[32m",        # green
    "WARNING": "\033[33m",     # yellow
    "ERROR": "\033[31m",       # red
    "CRITICAL": "\033[35m",    # magenta
}


def _is_dev_mode() -> bool:
    """Return True when running in development mode."""
    env = os.environ.get("FLOWLENS_ENV", "").lower()
    dev = os.environ.get("DEV", "").lower()
    return env in {"development", "dev"} or dev in {"1", "true", "yes"}


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

class _JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record — suitable for log aggregators."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # Attach any extra fields passed via the `extra` kwarg to logger calls.
        standard_attrs = logging.LogRecord.__dict__.keys() | {
            "message", "asctime", "args", "exc_text", "stack_info",
        }
        for key, value in record.__dict__.items():
            if key not in standard_attrs and not key.startswith("_"):
                payload[key] = value

        return json.dumps(payload, default=str, ensure_ascii=False)


class _PrettyFormatter(logging.Formatter):
    """
    Coloured, human-readable formatter for interactive development sessions.

    Example output:
        2026-03-14 12:34:56  INFO     flowlens.server.app  Server started on 0.0.0.0:8585
    """

    _USE_COLOR: bool = sys.stderr.isatty() or sys.stdout.isatty()

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        ts = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        level = record.levelname.ljust(8)
        name = record.name[:30].ljust(30)

        if self._USE_COLOR:
            color = _LEVEL_COLORS.get(record.levelname, "")
            level_str = f"{color}{_BOLD}{level}{_RESET}"
            name_str = f"\033[90m{name}{_RESET}"  # dim grey
        else:
            level_str = level
            name_str = name

        msg = record.getMessage()
        line = f"{ts}  {level_str}  {name_str}  {msg}"

        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)

        return line


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def configure_logging(
    level: str | None = None,
    *,
    dev_mode: bool | None = None,
    stream: Any = None,
) -> None:
    """
    Configure the root logger for FlowLens.

    This function is idempotent — calling it multiple times is safe and
    simply updates the level / formatter on the existing handler.

    Args:
        level:    Override log level (e.g. ``"DEBUG"``).  When *None* the
                  value of ``FLOWLENS_LOG_LEVEL`` (default ``"INFO"``) is used.
        dev_mode: Force development (pretty) or production (JSON) mode.
                  When *None* the mode is detected automatically from the
                  ``FLOWLENS_ENV`` / ``DEV`` environment variables.
        stream:   Output stream.  Defaults to ``sys.stderr``.
    """
    from flowlens.config import settings  # lazy to avoid circular imports

    resolved_level = (level or settings.log_level).upper()
    resolved_dev = _is_dev_mode() if dev_mode is None else dev_mode
    resolved_stream = stream or sys.stderr

    formatter: logging.Formatter
    formatter = _PrettyFormatter() if resolved_dev else _JsonFormatter()

    # Configure the FlowLens package logger (not the root logger, so we
    # don't accidentally pollute third-party libraries).
    pkg_logger = logging.getLogger("flowlens")
    pkg_logger.setLevel(resolved_level)

    # Avoid adding duplicate handlers if configure_logging() is called again.
    if not pkg_logger.handlers:
        handler = logging.StreamHandler(resolved_stream)
        handler.setFormatter(formatter)
        pkg_logger.addHandler(handler)
        # Do not propagate to root — we own our own handler.
        pkg_logger.propagate = False
    else:
        # Update the existing handler's formatter and level.
        for handler in pkg_logger.handlers:
            handler.setFormatter(formatter)
            handler.setLevel(resolved_level)

    pkg_logger.debug(
        "FlowLens logging configured",
        extra={"log_level": resolved_level, "dev_mode": resolved_dev},
    )
