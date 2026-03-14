"""
FlowLens CLI — command-line entry point.

Commands:
    flowlens serve   [--host 0.0.0.0] [--port 8585] [--db ./flowlens.db]
    flowlens analyze <trace-file.jsonl>
    flowlens version
    flowlens demo
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click

import flowlens as _fl_pkg
from flowlens.logging_config import configure_logging


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------

@click.group()
def cli() -> None:
    """FlowLens — Agent Observability Platform."""


# ---------------------------------------------------------------------------
# `flowlens version`
# ---------------------------------------------------------------------------

@cli.command()
def version() -> None:
    """Print the installed FlowLens version and exit."""
    click.echo(f"FlowLens {_fl_pkg.__version__}")


# ---------------------------------------------------------------------------
# `flowlens serve`
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--host",
    default=None,
    show_default="FLOWLENS_HOST or 0.0.0.0",
    help="Host address to bind the server to.",
)
@click.option(
    "--port",
    default=None,
    type=int,
    show_default="FLOWLENS_PORT or 8585",
    help="TCP port to listen on.",
)
@click.option(
    "--db",
    "db_path",
    default=None,
    show_default="FLOWLENS_DB_PATH or ./flowlens.db",
    help="Path to the SQLite database file.",
)
@click.option(
    "--log-level",
    default=None,
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], case_sensitive=False),
    show_default="FLOWLENS_LOG_LEVEL or INFO",
    help="Log verbosity level.",
)
@click.option(
    "--dev",
    is_flag=True,
    default=False,
    help="Enable development mode (pretty coloured logs, auto-reload).",
)
def serve(
    host: str | None,
    port: int | None,
    db_path: str | None,
    log_level: str | None,
    dev: bool,
) -> None:
    """Start the FlowLens observability server."""
    try:
        import uvicorn
    except ImportError:
        click.echo(
            "uvicorn is required to run the server.  Install it with:\n"
            "    pip install uvicorn",
            err=True,
        )
        sys.exit(1)

    from flowlens.config import settings
    from flowlens.server.app import create_app

    resolved_host = host or settings.host
    resolved_port = port or settings.port
    resolved_db = db_path or settings.db_path
    resolved_level = (log_level or settings.log_level).upper()

    configure_logging(level=resolved_level, dev_mode=dev)

    click.echo(
        f"Starting FlowLens {_fl_pkg.__version__} on "
        f"http://{resolved_host}:{resolved_port}  (db={resolved_db})"
    )

    app = create_app(db_path=resolved_db)

    uvicorn.run(
        app,
        host=resolved_host,
        port=resolved_port,
        log_level=resolved_level.lower(),
        reload=dev,
    )


# ---------------------------------------------------------------------------
# `flowlens analyze`
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("trace_file", type=click.Path(exists=True, readable=True, path_type=Path))
@click.option(
    "--format",
    "output_format",
    default="text",
    type=click.Choice(["text", "json"], case_sensitive=False),
    show_default=True,
    help="Output format for the analysis report.",
)
def analyze(trace_file: Path, output_format: str) -> None:
    """Analyze a JSONL trace file and print a report.

    TRACE_FILE must be a newline-delimited JSON file where each line is a
    serialized FlowLens trace (as produced by the JSONL exporter).
    """
    from flowlens.server.app import _reconstruct_trace
    from flowlens.analysis.dag_builder import build_causal_dag
    from flowlens.analysis.patterns import detect_patterns
    from flowlens.analysis.advisor import TraceAdvisor

    configure_logging()

    traces_data: list[dict[str, Any]] = []
    errors = 0

    with trace_file.open() as fh:
        for line_no, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                traces_data.append(json.loads(raw))
            except json.JSONDecodeError as exc:
                click.echo(f"Warning: line {line_no} is not valid JSON — {exc}", err=True)
                errors += 1

    if not traces_data:
        click.echo("No traces found in the file.", err=True)
        sys.exit(1)

    reports: list[dict[str, Any]] = []

    for td in traces_data:
        trace = _reconstruct_trace(td)
        dag = build_causal_dag(trace)
        patterns = detect_patterns(trace, dag)
        advisor = TraceAdvisor(trace=trace, dag=dag, patterns=patterns)
        report = advisor.generate_report()
        report["trace_id"] = trace.trace_id
        report["service_name"] = trace.service_name
        report["duration_ms"] = trace.duration_ms
        report["total_tokens"] = trace.total_tokens
        report["total_cost_usd"] = trace.total_cost_usd
        report["error_count"] = trace.error_count
        reports.append(report)

    if output_format == "json":
        click.echo(json.dumps(reports, indent=2, ensure_ascii=False))
        return

    # ---- human-readable text output ----
    click.echo(f"\nFlowLens Analysis Report — {trace_file}")
    click.echo(f"Traces analyzed : {len(reports)}  (parse errors: {errors})")
    click.echo("=" * 72)

    for report in reports:
        sev = report["severity_level"].upper()
        score = report["severity_score"]
        click.echo(
            f"\nTrace : {report['trace_id'][:16]}...  "
            f"service={report['service_name']}  "
            f"duration={report['duration_ms']:.0f}ms"
        )
        click.echo(
            f"  Tokens : {report['total_tokens']}  "
            f"Cost : ${report['total_cost_usd']:.4f}  "
            f"Errors : {report['error_count']}"
        )
        click.echo(f"  Severity : {sev} (score={score}/100)")
        click.echo(f"  Status   : {report['error_summary']}")

        if report["pattern_summary"] and report["pattern_summary"] != ["未检测到已知 patterns"]:
            click.echo("  Patterns :")
            for ps in report["pattern_summary"]:
                click.echo(f"    - {ps}")

        if report["recommendations"] and report["recommendations"] != ["当前 trace 无明显优化建议"]:
            click.echo("  Recommendations :")
            for rec in report["recommendations"]:
                click.echo(f"    * {rec}")

        savings = report["estimated_savings"]
        if savings["token_savings"] or savings["cost_savings_usd"] or savings["time_savings_ms"]:
            click.echo(
                f"  Estimated savings : "
                f"{savings['token_savings']} tokens  "
                f"${savings['cost_savings_usd']:.4f}  "
                f"{savings['time_savings_ms']:.0f}ms"
            )

    click.echo("\n" + "=" * 72)


# ---------------------------------------------------------------------------
# `flowlens demo`
# ---------------------------------------------------------------------------

@cli.command()
def demo() -> None:
    """Run the built-in FlowLens demo agent.

    Executes a simulated multi-step research agent that deliberately triggers
    timeouts and cascading errors, then prints a causal analysis report.
    """
    try:
        import asyncio
        from examples.demo_agent import main as _demo_main  # type: ignore[import]
    except ImportError:
        click.echo(
            "Could not import the demo agent.  Make sure you are running from "
            "the project root directory:\n    flowlens demo",
            err=True,
        )
        sys.exit(1)

    asyncio.run(_demo_main())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Console-script entry point registered in pyproject.toml."""
    cli()


if __name__ == "__main__":
    main()
