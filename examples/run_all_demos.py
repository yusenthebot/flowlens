#!/usr/bin/env python3
"""
FlowLens — Master Demo Runner
==============================
Runs all FlowLens example scripts sequentially, printing a header and timing
for each one.  A summary table is printed at the end.

Usage:
    python examples/run_all_demos.py          # run all demos
    python examples/run_all_demos.py --quick  # skip the dashboard (which blocks)

From the project root you can also use:
    make demo-all
    make demo
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

# ─── ANSI colour helpers ──────────────────────────────────────────────────────

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"


def _c(color: str, text: str) -> str:
    """Wrap *text* in *color* ANSI codes."""
    return f"{color}{text}{RESET}"


def banner(title: str, subtitle: str = "") -> None:
    width = 64
    print()
    print(_c(CYAN + BOLD, "═" * width))
    print(_c(CYAN + BOLD, f"  {title}"))
    if subtitle:
        print(_c(DIM, f"  {subtitle}"))
    print(_c(CYAN + BOLD, "═" * width))
    print()


def section(title: str, description: str) -> None:
    width = 64
    print()
    print(_c(BLUE + BOLD, "─" * width))
    print(_c(BLUE + BOLD, f"  {title}"))
    if description:
        print(_c(DIM, f"  {description}"))
    print(_c(BLUE + BOLD, "─" * width))
    print()


def ok(msg: str) -> None:
    print(_c(GREEN + BOLD, f"  ✓ {msg}"))


def warn(msg: str) -> None:
    print(_c(YELLOW + BOLD, f"  ! {msg}"))


def err(msg: str) -> None:
    print(_c(RED + BOLD, f"  ✗ {msg}"))


# ─── Demo definitions ─────────────────────────────────────────────────────────

EXAMPLES_DIR = Path(__file__).parent


# Each entry: (label, script_path, description, blocking)
DEMOS: list[tuple[str, str, str, bool]] = [
    (
        "Quickstart",
        "examples/quickstart.py",
        "Five progressive examples from zero to full observability",
        False,
    ),
    (
        "RAG / Demo Agent",
        "examples/demo_agent.py",
        "Multi-step research agent with causal DAG analysis",
        False,
    ),
    (
        "Auto-Instrumentation",
        "examples/auto_instrument_example.py",
        "Zero-code tracing of popular AI libraries",
        False,
    ),
    (
        "Multi-Trace Cost Analysis",
        "examples/multi_trace_analysis.py",
        "Fleet-wide performance and cost optimisation report",
        False,
    ),
    (
        "Dashboard (server_demo)",
        "examples/server_demo.py",
        "Live dashboard with sample data — blocks until Ctrl-C",
        True,  # blocking — skipped with --quick
    ),
]


# ─── Runner ───────────────────────────────────────────────────────────────────


def run_demo(
    label: str,
    script: str,
    description: str,
    project_root: Path,
) -> tuple[bool, float]:
    """
    Run a single demo script via subprocess.

    Returns ``(success, elapsed_seconds)``.
    """
    script_path = project_root / script
    if not script_path.exists():
        warn(f"Script not found, creating stub: {script_path}")
        _write_stub(script_path, label, description)

    print(_c(DIM, f"  Running: python3 {script}"))
    start = time.perf_counter()

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(project_root),
            check=False,
        )
        elapsed = time.perf_counter() - start
        if result.returncode == 0:
            ok(f"{label} completed in {elapsed:.1f}s")
            return True, elapsed
        else:
            err(f"{label} exited with code {result.returncode} ({elapsed:.1f}s)")
            return False, elapsed
    except Exception as exc:  # noqa: BLE001
        elapsed = time.perf_counter() - start
        err(f"{label} raised an exception: {exc}")
        return False, elapsed


def _write_stub(path: Path, label: str, description: str) -> None:
    """Write a minimal stub script so the runner doesn't crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"#!/usr/bin/env python3\n"
        f'"""FlowLens stub for: {label}\n\n{description}\n"""\n\n'
        f'print("[ {label} — coming soon ]")\n',
        encoding="utf-8",
    )


# ─── Summary table ────────────────────────────────────────────────────────────


def print_summary(results: list[tuple[str, bool, float]]) -> None:
    width = 64
    print()
    print(_c(CYAN + BOLD, "═" * width))
    print(_c(CYAN + BOLD, "  Demo Summary"))
    print(_c(CYAN + BOLD, "═" * width))
    print()

    passed = sum(1 for _, ok_, _ in results if ok_)
    failed = len(results) - passed

    col_w = 36
    print(f"  {'Demo':<{col_w}}  {'Status':<8}  {'Time':>8}")
    print(f"  {'-' * col_w}  {'-' * 8}  {'-' * 8}")

    for label, success, elapsed in results:
        status = _c(GREEN, "PASS") if success else _c(RED, "FAIL")
        print(f"  {label:<{col_w}}  {status:<8}  {elapsed:>6.1f}s")

    total_time = sum(t for _, _, t in results)
    print()
    print(f"  Total: {passed}/{len(results)} passed  ({total_time:.1f}s)")
    if failed:
        print(_c(YELLOW, f"\n  {failed} demo(s) failed — see output above for details."))
    else:
        print(_c(GREEN + BOLD, "\n  All demos passed!"))
    print()


# ─── Entry point ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run all FlowLens demos sequentially.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python examples/run_all_demos.py          # run everything\n"
            "  python examples/run_all_demos.py --quick  # skip blocking dashboard\n"
            "  make demo-all                             # same via Makefile\n"
        ),
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        default=False,
        help="Skip the dashboard demo (which blocks waiting for Ctrl-C).",
    )
    parser.add_argument(
        "--only",
        metavar="LABEL",
        default=None,
        help="Run only the demo whose label contains LABEL (case-insensitive).",
    )
    args = parser.parse_args(argv)

    project_root = EXAMPLES_DIR.parent

    banner(
        "FlowLens — Demo Runner",
        "Runs all examples sequentially and prints a timing summary.",
    )

    demos_to_run = [
        (label, script, desc, blocking)
        for label, script, desc, blocking in DEMOS
        if not (args.quick and blocking)
        and (args.only is None or args.only.lower() in label.lower())
    ]

    if not demos_to_run:
        warn("No demos match the given filters.")
        return 1

    results: list[tuple[str, bool, float]] = []

    for i, (label, script, description, _blocking) in enumerate(demos_to_run, start=1):
        section(
            f"Demo {i}/{len(demos_to_run)}: {label}",
            description,
        )
        success, elapsed = run_demo(label, script, description, project_root)
        results.append((label, success, elapsed))

    print_summary(results)

    failed_count = sum(1 for _, ok_, _ in results if not ok_)
    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
