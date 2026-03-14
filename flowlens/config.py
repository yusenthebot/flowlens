"""
FlowLens Configuration Module

All settings are read from environment variables with the FLOWLENS_ prefix.
Environment variables take priority over the declared defaults.

Usage:
    from flowlens.config import settings

    print(settings.db_path)
    print(settings.host)
    print(settings.port)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(key: str, default: str) -> str:
    """Read an environment variable, falling back to *default*."""
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(
            f"Environment variable {key!r} must be an integer, got {raw!r}"
        ) from exc


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(
            f"Environment variable {key!r} must be a float, got {raw!r}"
        ) from exc


def _env_list(key: str, default: str) -> list[str]:
    """Read a comma-separated environment variable as a list of strings."""
    raw = os.environ.get(key, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class FlowLensConfig:
    """
    Immutable configuration snapshot.

    All values are resolved once at construction time from the process
    environment, making the configuration safe to share across threads.
    """

    # Database
    db_path: str = field(default_factory=lambda: _env("FLOWLENS_DB_PATH", "./flowlens.db"))

    # HTTP server
    host: str = field(default_factory=lambda: _env("FLOWLENS_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _env_int("FLOWLENS_PORT", 8585))

    # Logging
    log_level: str = field(default_factory=lambda: _env("FLOWLENS_LOG_LEVEL", "INFO").upper())

    # CORS
    cors_origins: list[str] = field(
        default_factory=lambda: _env_list("FLOWLENS_CORS_ORIGINS", "*")
    )

    # Rate limiting (requests per minute per IP)
    rate_limit: int = field(default_factory=lambda: _env_int("FLOWLENS_RATE_LIMIT", 120))

    # Maximum number of traces to keep in database
    max_traces: int = field(default_factory=lambda: _env_int("FLOWLENS_MAX_TRACES", 100000))

    # Pattern detection thresholds
    pattern_retry_threshold: int = field(
        default_factory=lambda: _env_int("FLOWLENS_PATTERN_RETRY_THRESHOLD", 5)
    )
    pattern_loop_repeat: int = field(
        default_factory=lambda: _env_int("FLOWLENS_PATTERN_LOOP_REPEAT", 3)
    )
    pattern_context_ratio: float = field(
        default_factory=lambda: _env_float("FLOWLENS_PATTERN_CONTEXT_RATIO", 0.9)
    )
    pattern_cost_spike_ratio: float = field(
        default_factory=lambda: _env_float("FLOWLENS_PATTERN_COST_SPIKE_RATIO", 0.5)
    )
    pattern_slow_tool_multiplier: float = field(
        default_factory=lambda: _env_float("FLOWLENS_PATTERN_SLOW_TOOL_MULT", 3.0)
    )
    pattern_token_waste_ratio: float = field(
        default_factory=lambda: _env_float("FLOWLENS_PATTERN_TOKEN_WASTE_RATIO", 10.0)
    )

    # Budget alert — cumulative cost threshold in USD (0.0 = disabled)
    alert_budget_usd: float = field(
        default_factory=lambda: _env_float("FLOWLENS_ALERT_BUDGET_USD", 0.0)
    )

    def __post_init__(self) -> None:
        valid_log_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if self.log_level not in valid_log_levels:
            raise ValueError(
                f"FLOWLENS_LOG_LEVEL must be one of {valid_log_levels}, "
                f"got {self.log_level!r}"
            )
        if not (1 <= self.port <= 65535):
            raise ValueError(
                f"FLOWLENS_PORT must be between 1 and 65535, got {self.port}"
            )
        if self.rate_limit < 1:
            raise ValueError(
                f"FLOWLENS_RATE_LIMIT must be >= 1, got {self.rate_limit}"
            )
        if self.max_traces < 1:
            raise ValueError(
                f"FLOWLENS_MAX_TRACES must be >= 1, got {self.max_traces}"
            )


def load_config() -> FlowLensConfig:
    """Create and return a validated :class:`FlowLensConfig` from the environment."""
    return FlowLensConfig()


# Module-level singleton — import this in application code.
settings: FlowLensConfig = load_config()
