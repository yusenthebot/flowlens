"""Tests for the FlowLens CLI (flowlens.cli)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

import flowlens as _fl_pkg
from flowlens.cli import cli


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def runner() -> CliRunner:
    """Return an isolated Click test runner."""
    return CliRunner()


@pytest.fixture()
def sample_jsonl(tmp_path: Path) -> Path:
    """Write a minimal JSONL trace file and return its path."""
    trace = {
        "trace_id": "cli-test-trace-001",
        "service_name": "cli-test",
        "start_time": 1000.0,
        "end_time": 1001.0,
        "duration_ms": 1000.0,
        "span_count": 1,
        "total_tokens": 500,
        "total_cost_usd": 0.005,
        "has_errors": False,
        "error_count": 0,
        "metadata": {},
        "spans": [
            {
                "span_id": "s1",
                "trace_id": "cli-test-trace-001",
                "parent_span_id": None,
                "name": "agent",
                "kind": "agent",
                "status": "ok",
                "start_time": 1000.0,
                "end_time": 1001.0,
                "duration_ms": 1000.0,
                "attributes": {},
                "events": [],
            }
        ],
    }
    p = tmp_path / "traces.jsonl"
    p.write_text(json.dumps(trace) + "\n")
    return p


@pytest.fixture()
def multi_trace_jsonl(tmp_path: Path) -> Path:
    """Two traces — one clean, one with errors."""
    traces = [
        {
            "trace_id": "t1",
            "service_name": "svc-a",
            "start_time": 1000.0,
            "end_time": 1001.0,
            "duration_ms": 1000.0,
            "span_count": 1,
            "total_tokens": 200,
            "total_cost_usd": 0.001,
            "has_errors": False,
            "error_count": 0,
            "metadata": {},
            "spans": [
                {
                    "span_id": "s1",
                    "trace_id": "t1",
                    "name": "tool",
                    "kind": "tool",
                    "status": "ok",
                    "start_time": 1000.0,
                    "end_time": 1001.0,
                    "duration_ms": 1000.0,
                    "attributes": {},
                    "events": [],
                }
            ],
        },
        {
            "trace_id": "t2",
            "service_name": "svc-b",
            "start_time": 2000.0,
            "end_time": 2001.0,
            "duration_ms": 1000.0,
            "span_count": 1,
            "total_tokens": 100,
            "total_cost_usd": 0.001,
            "has_errors": True,
            "error_count": 1,
            "metadata": {},
            "spans": [
                {
                    "span_id": "s2",
                    "trace_id": "t2",
                    "name": "tool",
                    "kind": "tool",
                    "status": "error",
                    "start_time": 2000.0,
                    "end_time": 2001.0,
                    "duration_ms": 1000.0,
                    "attributes": {},
                    "events": [],
                    "error": {"message": "timeout"},
                }
            ],
        },
    ]
    p = tmp_path / "multi.jsonl"
    p.write_text("\n".join(json.dumps(t) for t in traces) + "\n")
    return p


# ---------------------------------------------------------------------------
# `flowlens version`
# ---------------------------------------------------------------------------

class TestVersionCommand:
    def test_prints_version(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["version"])
        assert result.exit_code == 0
        assert _fl_pkg.__version__ in result.output

    def test_contains_flowlens(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["version"])
        assert "FlowLens" in result.output


# ---------------------------------------------------------------------------
# `flowlens --help` / root group
# ---------------------------------------------------------------------------

class TestHelpOutput:
    def test_root_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "serve" in result.output
        assert "analyze" in result.output
        assert "version" in result.output
        assert "demo" in result.output

    def test_serve_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--host" in result.output
        assert "--port" in result.output
        assert "--db" in result.output

    def test_analyze_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["analyze", "--help"])
        assert result.exit_code == 0
        assert "TRACE_FILE" in result.output
        assert "--format" in result.output


# ---------------------------------------------------------------------------
# `flowlens analyze` — text output
# ---------------------------------------------------------------------------

class TestAnalyzeCommand:
    def test_analyze_single_trace_text(self, runner: CliRunner, sample_jsonl: Path) -> None:
        result = runner.invoke(cli, ["analyze", str(sample_jsonl)])
        assert result.exit_code == 0
        assert "FlowLens Analysis Report" in result.output
        assert "cli-test-trace-0" in result.output

    def test_analyze_shows_service_name(self, runner: CliRunner, sample_jsonl: Path) -> None:
        result = runner.invoke(cli, ["analyze", str(sample_jsonl)])
        assert result.exit_code == 0
        assert "cli-test" in result.output

    def test_analyze_shows_severity(self, runner: CliRunner, sample_jsonl: Path) -> None:
        result = runner.invoke(cli, ["analyze", str(sample_jsonl)])
        assert result.exit_code == 0
        assert "Severity" in result.output

    def test_analyze_multi_trace(self, runner: CliRunner, multi_trace_jsonl: Path) -> None:
        result = runner.invoke(cli, ["analyze", str(multi_trace_jsonl)])
        assert result.exit_code == 0
        assert "Traces analyzed : 2" in result.output
        assert "t1" in result.output
        assert "t2" in result.output

    def test_analyze_json_output(self, runner: CliRunner, sample_jsonl: Path) -> None:
        result = runner.invoke(cli, ["analyze", str(sample_jsonl), "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1
        report = data[0]
        assert report["trace_id"] == "cli-test-trace-001"
        assert "severity_level" in report
        assert "severity_score" in report
        assert "recommendations" in report

    def test_analyze_json_multi_trace(self, runner: CliRunner, multi_trace_jsonl: Path) -> None:
        result = runner.invoke(cli, ["analyze", str(multi_trace_jsonl), "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 2

    def test_analyze_nonexistent_file(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["analyze", "/nonexistent/path/traces.jsonl"])
        assert result.exit_code != 0

    def test_analyze_empty_file(self, runner: CliRunner, tmp_path: Path) -> None:
        empty = tmp_path / "empty.jsonl"
        empty.write_text("")
        result = runner.invoke(cli, ["analyze", str(empty)])
        assert result.exit_code != 0

    def test_analyze_file_with_blank_lines(self, runner: CliRunner, tmp_path: Path) -> None:
        trace = {
            "trace_id": "t-blank",
            "service_name": "svc",
            "start_time": 0.0,
            "end_time": 1.0,
            "duration_ms": 1000.0,
            "span_count": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "has_errors": False,
            "error_count": 0,
            "metadata": {},
            "spans": [],
        }
        p = tmp_path / "blank_lines.jsonl"
        p.write_text("\n" + json.dumps(trace) + "\n\n")
        result = runner.invoke(cli, ["analyze", str(p)])
        assert result.exit_code == 0
        assert "t-blank" in result.output

    def test_analyze_invalid_json_lines_warns(self, runner: CliRunner, tmp_path: Path) -> None:
        trace = {
            "trace_id": "t-valid",
            "service_name": "svc",
            "start_time": 0.0,
            "end_time": 1.0,
            "duration_ms": 1000.0,
            "span_count": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "has_errors": False,
            "error_count": 0,
            "metadata": {},
            "spans": [],
        }
        p = tmp_path / "mixed.jsonl"
        p.write_text("not-valid-json\n" + json.dumps(trace) + "\n")
        result = runner.invoke(cli, ["analyze", str(p)])
        # Should succeed (1 valid trace) but warn about the bad line
        assert result.exit_code == 0
        assert "Warning" in result.stderr or "parse errors: 1" in result.output

    def test_analyze_json_report_fields(self, runner: CliRunner, sample_jsonl: Path) -> None:
        result = runner.invoke(cli, ["analyze", str(sample_jsonl), "--format", "json"])
        assert result.exit_code == 0
        reports = json.loads(result.output)
        report = reports[0]
        expected_keys = {
            "severity_score", "severity_level", "error_summary",
            "recommendations", "estimated_savings", "trace_id",
            "service_name", "duration_ms", "total_tokens", "total_cost_usd",
            "error_count",
        }
        assert expected_keys.issubset(report.keys())


# ---------------------------------------------------------------------------
# `flowlens serve` — startup validation (no actual binding)
# ---------------------------------------------------------------------------

class TestServeCommand:
    def test_serve_help_exits_zero(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["serve", "--help"])
        assert result.exit_code == 0

    def test_serve_missing_uvicorn_exits_nonzero(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When uvicorn is not installed the command should fail gracefully."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "uvicorn":
                raise ImportError("uvicorn not found")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        result = runner.invoke(cli, ["serve"])
        assert result.exit_code != 0
        assert "uvicorn" in result.output.lower() or "uvicorn" in (result.stderr or "").lower()


# ---------------------------------------------------------------------------
# `flowlens demo` — import fallback
# ---------------------------------------------------------------------------

class TestDemoCommand:
    def test_demo_help(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["demo", "--help"])
        assert result.exit_code == 0
        assert "demo" in result.output.lower()
