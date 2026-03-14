"""
FlowLens CLI — command-line entry point.

Commands:
    flowlens serve   [--host 0.0.0.0] [--port 8585] [--db ./flowlens.db]
    flowlens analyze <trace-file.jsonl>
    flowlens export  [--format json|csv|jsonl] [--output FILE] [--service NAME] [--since DATETIME] [--limit N]
    flowlens import  <json-file> [--db PATH]
    flowlens stats   [--db PATH]
    flowlens health  [--db PATH]
    flowlens version
    flowlens demo
"""

from __future__ import annotations

import csv
import io
import json
import sys
import time
from datetime import datetime, timezone
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
# `flowlens export`
# ---------------------------------------------------------------------------

def _resolve_db_path(db_path: str | None) -> str:
    """Return db_path from argument or fall back to configured default."""
    if db_path:
        return db_path
    from flowlens.config import settings
    return settings.db_path


@cli.command("export")
@click.option(
    "--format",
    "output_format",
    default="json",
    type=click.Choice(["json", "csv", "jsonl"], case_sensitive=False),
    show_default=True,
    help="Output format.",
)
@click.option(
    "--output",
    "output_file",
    default=None,
    type=click.Path(dir_okay=False, writable=True),
    help="Write output to FILE instead of stdout.",
)
@click.option(
    "--service",
    "service_name",
    default=None,
    help="Filter traces by service name.",
)
@click.option(
    "--since",
    "since_dt",
    default=None,
    help="Filter traces with start_time >= DATETIME (ISO-8601 or Unix timestamp).",
)
@click.option(
    "--limit",
    "limit",
    default=None,
    type=int,
    help="Maximum number of traces to export.",
)
@click.option(
    "--db",
    "db_path",
    default=None,
    show_default="FLOWLENS_DB_PATH or ./flowlens.db",
    help="Path to the SQLite database file.",
)
def export_cmd(
    output_format: str,
    output_file: str | None,
    service_name: str | None,
    since_dt: str | None,
    limit: int | None,
    db_path: str | None,
) -> None:
    """Export traces from the local SQLite database.

    Supports JSON, JSONL, and CSV output formats.
    """
    from flowlens.server.storage import TraceStore

    resolved_db = _resolve_db_path(db_path)
    db_file = Path(resolved_db)
    if not db_file.exists():
        click.echo(f"Database not found: {resolved_db}", err=True)
        sys.exit(1)

    store = TraceStore(db_path=resolved_db)

    # Parse --since into a Unix timestamp
    since_ts: float | None = None
    if since_dt is not None:
        try:
            since_ts = float(since_dt)
        except ValueError:
            try:
                # Try ISO-8601 parsing
                dt = datetime.fromisoformat(since_dt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                since_ts = dt.timestamp()
            except ValueError:
                click.echo(
                    f"Cannot parse --since value {since_dt!r}. "
                    "Use ISO-8601 format (e.g. 2024-01-01T00:00:00) or a Unix timestamp.",
                    err=True,
                )
                sys.exit(1)

    # Fetch traces
    fetch_limit = limit if limit is not None else 10_000
    traces = store.list_traces(limit=fetch_limit, service_name=service_name)

    # Apply --since filter (list_traces doesn't support it natively)
    if since_ts is not None:
        traces = [t for t in traces if t.get("start_time", 0) >= since_ts]

    # Apply --limit after filtering
    if limit is not None:
        traces = traces[:limit]

    # Serialise
    if output_format == "jsonl":
        content = "\n".join(json.dumps(t, ensure_ascii=False) for t in traces) + ("\n" if traces else "")
    elif output_format == "csv":
        buf = io.StringIO()
        fieldnames = [
            "trace_id", "service_name", "start_time", "end_time",
            "duration_ms", "span_count", "total_tokens", "total_cost_usd",
            "has_errors", "error_count",
        ]
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(traces)
        content = buf.getvalue()
    else:  # json
        content = json.dumps(traces, indent=2, ensure_ascii=False) + "\n"

    if output_file:
        Path(output_file).write_text(content, encoding="utf-8")
        click.echo(f"Exported {len(traces)} trace(s) to {output_file}")
    else:
        click.echo(content, nl=False)


# ---------------------------------------------------------------------------
# `flowlens import`
# ---------------------------------------------------------------------------

@cli.command("import")
@click.argument("json_file", type=click.Path(exists=True, readable=True, path_type=Path))
@click.option(
    "--db",
    "db_path",
    default=None,
    show_default="FLOWLENS_DB_PATH or ./flowlens.db",
    help="Path to the SQLite database file.",
)
def import_cmd(json_file: Path, db_path: str | None) -> None:
    """Import traces from a JSON file into the local SQLite database.

    JSON_FILE must be a JSON file containing a list of trace objects, or a
    single trace object, or a newline-delimited JSONL file.
    """
    from flowlens.server.storage import TraceStore

    resolved_db = _resolve_db_path(db_path)
    store = TraceStore(db_path=resolved_db)

    raw = json_file.read_text(encoding="utf-8")

    # Try parsing as JSON array / object first, then fall back to JSONL
    traces_data: list[dict[str, Any]] = []
    parse_errors = 0

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            traces_data = parsed
        elif isinstance(parsed, dict):
            traces_data = [parsed]
        else:
            click.echo("JSON file must contain an array or object at the top level.", err=True)
            sys.exit(1)
    except json.JSONDecodeError:
        # Try JSONL
        for line_no, line in enumerate(raw.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                traces_data.append(json.loads(line))
            except json.JSONDecodeError as exc:
                click.echo(f"Warning: line {line_no} is not valid JSON — {exc}", err=True)
                parse_errors += 1

    if not traces_data:
        click.echo("No valid traces found in the file.", err=True)
        sys.exit(1)

    imported = 0
    failed = 0
    for td in traces_data:
        if not isinstance(td, dict) or "trace_id" not in td:
            click.echo(f"Skipping entry without trace_id: {str(td)[:80]}", err=True)
            failed += 1
            continue
        try:
            store.save_trace(td)
            imported += 1
        except Exception as exc:
            click.echo(f"Failed to import trace {td.get('trace_id', '?')}: {exc}", err=True)
            failed += 1

    click.echo(f"Imported {imported} trace(s) into {resolved_db}" + (f"  ({failed} failed)" if failed else ""))


# ---------------------------------------------------------------------------
# `flowlens stats`
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--db",
    "db_path",
    default=None,
    show_default="FLOWLENS_DB_PATH or ./flowlens.db",
    help="Path to the SQLite database file.",
)
def stats(db_path: str | None) -> None:
    """Show aggregate statistics from the local SQLite database."""
    from flowlens.server.storage import TraceStore

    resolved_db = _resolve_db_path(db_path)
    db_file = Path(resolved_db)
    if not db_file.exists():
        click.echo(f"Database not found: {resolved_db}", err=True)
        sys.exit(1)

    store = TraceStore(db_path=resolved_db)

    s = store.get_stats()
    total_traces = s.get("total_traces") or 0
    total_spans = s.get("total_spans") or 0
    total_tokens = s.get("total_tokens") or 0
    total_cost = s.get("total_cost") or 0.0
    error_traces = s.get("error_traces") or 0
    error_rate = (error_traces / total_traces * 100) if total_traces else 0.0

    # Date range
    from flowlens.server.storage import _ConnectionPool  # use a lightweight direct query
    import sqlite3
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    date_row = conn.execute(
        "SELECT MIN(start_time) as earliest, MAX(start_time) as latest FROM traces"
    ).fetchone()

    # Top services
    service_rows = conn.execute(
        """SELECT service_name, COUNT(*) as cnt FROM traces
           GROUP BY service_name ORDER BY cnt DESC LIMIT 10"""
    ).fetchall()
    conn.close()

    earliest = date_row["earliest"]
    latest = date_row["latest"]
    if earliest:
        earliest_str = datetime.fromtimestamp(earliest, tz=timezone.utc).isoformat()
        latest_str = datetime.fromtimestamp(latest, tz=timezone.utc).isoformat()
        date_range = f"{earliest_str}  →  {latest_str}"
    else:
        date_range = "no data"

    click.echo("FlowLens Database Statistics")
    click.echo("=" * 50)
    click.echo(f"  Traces      : {total_traces}")
    click.echo(f"  Spans       : {total_spans}")
    click.echo(f"  Error rate  : {error_rate:.1f}%  ({error_traces} traces with errors)")
    click.echo(f"  Total tokens: {total_tokens}")
    click.echo(f"  Total cost  : ${total_cost:.6f}")
    click.echo(f"  Date range  : {date_range}")

    if service_rows:
        click.echo("\n  Top services by trace count:")
        for row in service_rows:
            click.echo(f"    {row['service_name'] or '(unknown)':30s}  {row['cnt']}")

    click.echo("")


# ---------------------------------------------------------------------------
# `flowlens health`
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--db",
    "db_path",
    default=None,
    show_default="FLOWLENS_DB_PATH or ./flowlens.db",
    help="Path to the SQLite database file.",
)
@click.option(
    "--host",
    default=None,
    help="Server host to check (default: from config).",
)
@click.option(
    "--port",
    default=None,
    type=int,
    help="Server port to check (default: from config).",
)
def health(db_path: str | None, host: str | None, port: int | None) -> None:
    """Check the health of the FlowLens server and local database."""
    from flowlens.config import settings

    resolved_db = _resolve_db_path(db_path)
    resolved_host = host or settings.host
    resolved_port = port or settings.port

    click.echo("FlowLens Health Check")
    click.echo("=" * 50)

    # --- Server connectivity ---
    import socket
    server_ok = False
    try:
        with socket.create_connection((resolved_host, resolved_port), timeout=2):
            server_ok = True
    except OSError:
        pass

    server_status = "RUNNING" if server_ok else "NOT RUNNING"
    click.echo(f"  Server ({resolved_host}:{resolved_port}) : {server_status}")

    # --- Database ---
    db_file = Path(resolved_db)
    if db_file.exists():
        size_bytes = db_file.stat().st_size
        if size_bytes >= 1024 * 1024:
            size_str = f"{size_bytes / (1024 * 1024):.2f} MB"
        elif size_bytes >= 1024:
            size_str = f"{size_bytes / 1024:.2f} KB"
        else:
            size_str = f"{size_bytes} B"

        try:
            from flowlens.server.storage import TraceStore
            store = TraceStore(db_path=resolved_db)
            s = store.get_stats()
            trace_count = s.get("total_traces") or 0
            click.echo(f"  Database path   : {resolved_db}")
            click.echo(f"  Database size   : {size_str}")
            click.echo(f"  Trace count     : {trace_count}")
        except Exception as exc:
            click.echo(f"  Database path   : {resolved_db}")
            click.echo(f"  Database size   : {size_str}")
            click.echo(f"  Database status : ERROR — {exc}", err=True)
    else:
        click.echo(f"  Database path   : {resolved_db}")
        click.echo(f"  Database status : NOT FOUND")

    # --- Config summary ---
    click.echo("\n  Configuration:")
    click.echo(f"    FLOWLENS_HOST      = {settings.host}")
    click.echo(f"    FLOWLENS_PORT      = {settings.port}")
    click.echo(f"    FLOWLENS_DB_PATH   = {settings.db_path}")
    click.echo(f"    FLOWLENS_LOG_LEVEL = {settings.log_level}")
    click.echo("")


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
