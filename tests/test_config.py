"""Tests for flowlens.config — environment-driven configuration."""

from __future__ import annotations

import pytest

from flowlens.config import FlowLensConfig, load_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(**overrides: str) -> FlowLensConfig:
    """Build a FlowLensConfig by temporarily injecting env vars."""
    import os

    backup = {}
    env_keys = {
        "db_path": "FLOWLENS_DB_PATH",
        "host": "FLOWLENS_HOST",
        "port": "FLOWLENS_PORT",
        "log_level": "FLOWLENS_LOG_LEVEL",
        "cors_origins": "FLOWLENS_CORS_ORIGINS",
        "rate_limit": "FLOWLENS_RATE_LIMIT",
        "pattern_retry_threshold": "FLOWLENS_PATTERN_RETRY_THRESHOLD",
        "pattern_loop_repeat": "FLOWLENS_PATTERN_LOOP_REPEAT",
        "pattern_context_ratio": "FLOWLENS_PATTERN_CONTEXT_RATIO",
        "pattern_cost_spike_ratio": "FLOWLENS_PATTERN_COST_SPIKE_RATIO",
        "pattern_slow_tool_multiplier": "FLOWLENS_PATTERN_SLOW_TOOL_MULT",
        "pattern_token_waste_ratio": "FLOWLENS_PATTERN_TOKEN_WASTE_RATIO",
    }

    for attr, env_key in env_keys.items():
        if env_key in os.environ:
            backup[env_key] = os.environ.pop(env_key)

    for attr, value in overrides.items():
        env_key = env_keys[attr]
        os.environ[env_key] = value

    try:
        return FlowLensConfig()
    finally:
        # Restore original env
        for env_key in env_keys.values():
            os.environ.pop(env_key, None)
        for key, val in backup.items():
            os.environ[key] = val


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------

class TestDefaults:
    def test_default_db_path(self):
        cfg = _cfg()
        assert cfg.db_path == "./flowlens.db"

    def test_default_host(self):
        cfg = _cfg()
        assert cfg.host == "0.0.0.0"

    def test_default_port(self):
        cfg = _cfg()
        assert cfg.port == 8585

    def test_default_log_level(self):
        cfg = _cfg()
        assert cfg.log_level == "INFO"

    def test_default_cors_origins(self):
        cfg = _cfg()
        assert cfg.cors_origins == ["*"]

    def test_default_rate_limit(self):
        cfg = _cfg()
        assert cfg.rate_limit == 120


# ---------------------------------------------------------------------------
# Override via environment variables
# ---------------------------------------------------------------------------

class TestEnvOverrides:
    def test_override_db_path(self):
        cfg = _cfg(db_path="/tmp/custom.db")
        assert cfg.db_path == "/tmp/custom.db"

    def test_override_host(self):
        cfg = _cfg(host="127.0.0.1")
        assert cfg.host == "127.0.0.1"

    def test_override_port(self):
        cfg = _cfg(port="9000")
        assert cfg.port == 9000

    def test_override_log_level(self):
        cfg = _cfg(log_level="debug")
        assert cfg.log_level == "DEBUG"  # normalised to uppercase

    def test_override_cors_origins_single(self):
        cfg = _cfg(cors_origins="https://example.com")
        assert cfg.cors_origins == ["https://example.com"]

    def test_override_cors_origins_multiple(self):
        cfg = _cfg(cors_origins="https://a.com, https://b.com, https://c.com")
        assert cfg.cors_origins == ["https://a.com", "https://b.com", "https://c.com"]

    def test_override_rate_limit(self):
        cfg = _cfg(rate_limit="60")
        assert cfg.rate_limit == 60


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

class TestValidation:
    def test_invalid_log_level_raises(self):
        with pytest.raises(ValueError, match="FLOWLENS_LOG_LEVEL"):
            _cfg(log_level="VERBOSE")

    def test_invalid_port_string_raises(self):
        import os
        os.environ["FLOWLENS_PORT"] = "not-a-number"
        try:
            with pytest.raises(ValueError, match="FLOWLENS_PORT"):
                FlowLensConfig()
        finally:
            os.environ.pop("FLOWLENS_PORT", None)

    def test_port_zero_raises(self):
        with pytest.raises(ValueError, match="FLOWLENS_PORT"):
            _cfg(port="0")

    def test_port_too_large_raises(self):
        with pytest.raises(ValueError, match="FLOWLENS_PORT"):
            _cfg(port="99999")

    def test_rate_limit_zero_raises(self):
        with pytest.raises(ValueError, match="FLOWLENS_RATE_LIMIT"):
            _cfg(rate_limit="0")


# ---------------------------------------------------------------------------
# load_config helper
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_returns_flowlens_config(self):
        cfg = load_config()
        assert isinstance(cfg, FlowLensConfig)

    def test_config_is_immutable(self):
        cfg = load_config()
        with pytest.raises((AttributeError, TypeError)):
            cfg.port = 1234  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

class TestModuleSingleton:
    def test_settings_importable(self):
        from flowlens.config import settings

        assert isinstance(settings, FlowLensConfig)

    def test_settings_has_expected_attrs(self):
        from flowlens.config import settings

        assert hasattr(settings, "db_path")
        assert hasattr(settings, "host")
        assert hasattr(settings, "port")
        assert hasattr(settings, "log_level")
        assert hasattr(settings, "cors_origins")
        assert hasattr(settings, "rate_limit")


# ---------------------------------------------------------------------------
# Pattern detection threshold defaults
# ---------------------------------------------------------------------------

class TestPatternThresholdDefaults:
    def test_default_pattern_retry_threshold(self):
        cfg = _cfg()
        assert cfg.pattern_retry_threshold == 5

    def test_default_pattern_loop_repeat(self):
        cfg = _cfg()
        assert cfg.pattern_loop_repeat == 3

    def test_default_pattern_context_ratio(self):
        cfg = _cfg()
        assert cfg.pattern_context_ratio == 0.9

    def test_default_pattern_cost_spike_ratio(self):
        cfg = _cfg()
        assert cfg.pattern_cost_spike_ratio == 0.5

    def test_default_pattern_slow_tool_multiplier(self):
        cfg = _cfg()
        assert cfg.pattern_slow_tool_multiplier == 3.0

    def test_default_pattern_token_waste_ratio(self):
        cfg = _cfg()
        assert cfg.pattern_token_waste_ratio == 10.0


# ---------------------------------------------------------------------------
# Pattern detection threshold env var overrides
# ---------------------------------------------------------------------------

class TestPatternThresholdEnvOverrides:
    def test_override_pattern_retry_threshold(self):
        cfg = _cfg(pattern_retry_threshold="2")
        assert cfg.pattern_retry_threshold == 2

    def test_override_pattern_loop_repeat(self):
        cfg = _cfg(pattern_loop_repeat="5")
        assert cfg.pattern_loop_repeat == 5

    def test_override_pattern_context_ratio(self):
        cfg = _cfg(pattern_context_ratio="0.75")
        assert cfg.pattern_context_ratio == 0.75

    def test_override_pattern_cost_spike_ratio(self):
        cfg = _cfg(pattern_cost_spike_ratio="0.3")
        assert cfg.pattern_cost_spike_ratio == 0.3

    def test_override_pattern_slow_tool_multiplier(self):
        cfg = _cfg(pattern_slow_tool_multiplier="5.0")
        assert cfg.pattern_slow_tool_multiplier == 5.0

    def test_override_pattern_token_waste_ratio(self):
        cfg = _cfg(pattern_token_waste_ratio="20.0")
        assert cfg.pattern_token_waste_ratio == 20.0

    def test_invalid_pattern_retry_threshold_raises(self):
        import os
        os.environ["FLOWLENS_PATTERN_RETRY_THRESHOLD"] = "not-a-number"
        try:
            with pytest.raises(ValueError, match="FLOWLENS_PATTERN_RETRY_THRESHOLD"):
                FlowLensConfig()
        finally:
            os.environ.pop("FLOWLENS_PATTERN_RETRY_THRESHOLD", None)

    def test_invalid_pattern_context_ratio_raises(self):
        import os
        os.environ["FLOWLENS_PATTERN_CONTEXT_RATIO"] = "not-a-float"
        try:
            with pytest.raises(ValueError, match="FLOWLENS_PATTERN_CONTEXT_RATIO"):
                FlowLensConfig()
        finally:
            os.environ.pop("FLOWLENS_PATTERN_CONTEXT_RATIO", None)
