"""
FlowLens Examples — Shared Utilities
=====================================
ANSI color helpers, pretty-printers, table formatter, and progress indicator
used across all FlowLens example scripts.

Import from any example:
    from _utils import c, banner, section, print_trace_tree, print_table, progress
"""

import sys
import time

# ─────────────────────────────────────────────────────────────────────────────
# ANSI escape codes
# ─────────────────────────────────────────────────────────────────────────────

RESET   = "\033[0m"
BOLD    = "\033[1m"
DIM     = "\033[2m"
ITALIC  = "\033[3m"

BLACK   = "\033[30m"
RED     = "\033[31m"
GREEN   = "\033[32m"
YELLOW  = "\033[33m"
BLUE    = "\033[34m"
MAGENTA = "\033[35m"
CYAN    = "\033[36m"
WHITE   = "\033[37m"

BRIGHT_RED     = "\033[91m"
BRIGHT_GREEN   = "\033[92m"
BRIGHT_YELLOW  = "\033[93m"
BRIGHT_BLUE    = "\033[94m"
BRIGHT_MAGENTA = "\033[95m"
BRIGHT_CYAN    = "\033[96m"
BRIGHT_WHITE   = "\033[97m"

BG_BLACK  = "\033[40m"
BG_RED    = "\033[41m"
BG_GREEN  = "\033[42m"
BG_BLUE   = "\033[44m"
BG_CYAN   = "\033[46m"


# ─────────────────────────────────────────────────────────────────────────────
# Core color helper
# ─────────────────────────────────────────────────────────────────────────────

def c(text: str, *codes: str) -> str:
    """Wrap *text* with one or more ANSI codes, appending RESET at the end."""
    return "".join(codes) + str(text) + RESET


# ─────────────────────────────────────────────────────────────────────────────
# FlowLens branding
# ─────────────────────────────────────────────────────────────────────────────

FLOWLENS_LOGO = r"""
  ███████╗██╗      ██████╗ ██╗    ██╗██╗     ███████╗███╗   ██╗███████╗
  ██╔════╝██║     ██╔═══██╗██║    ██║██║     ██╔════╝████╗  ██║██╔════╝
  █████╗  ██║     ██║   ██║██║ █╗ ██║██║     █████╗  ██╔██╗ ██║███████╗
  ██╔══╝  ██║     ██║   ██║██║███╗██║██║     ██╔══╝  ██║╚██╗██║╚════██║
  ██║     ███████╗╚██████╔╝╚███╔███╔╝███████╗███████╗██║ ╚████║███████║
  ╚═╝     ╚══════╝ ╚═════╝  ╚══╝╚══╝ ╚══════╝╚══════╝╚═╝  ╚═══╝╚══════╝
"""


def print_logo(subtitle: str = "Agent Observability Platform") -> None:
    """Print the FlowLens logo with an optional subtitle."""
    print(c(FLOWLENS_LOGO, BRIGHT_CYAN, BOLD))
    pad = (74 - len(subtitle)) // 2
    print(c(" " * pad + subtitle, BRIGHT_WHITE, DIM))
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Section / banner helpers
# ─────────────────────────────────────────────────────────────────────────────

def banner(title: str, width: int = 72) -> None:
    """Print a double-line box banner."""
    pad = (width - len(title) - 4) // 2
    right = width - len(title) - 4 - pad
    print()
    print(c("╔" + "═" * (width - 2) + "╗", BRIGHT_CYAN, BOLD))
    print(c(f"║{' ' * pad}  {title}  {' ' * right}║", BRIGHT_CYAN, BOLD))
    print(c("╚" + "═" * (width - 2) + "╝", BRIGHT_CYAN, BOLD))
    print()


def section(title: str, width: int = 72) -> None:
    """Print a single-line section header."""
    line = f"  ── {title} " + "─" * max(0, width - len(title) - 6)
    print()
    print(c(line, BRIGHT_CYAN))
    print()


def subsection(title: str) -> None:
    """Print a subdued subsection header."""
    print()
    print(c(f"  ▶ {title}", BRIGHT_YELLOW, BOLD))
    print(c("  " + "─" * 60, DIM))


# ─────────────────────────────────────────────────────────────────────────────
# Step / status helpers
# ─────────────────────────────────────────────────────────────────────────────

def step(icon: str, text: str, detail: str = "") -> None:
    ts = c(f"[{time.strftime('%H:%M:%S')}]", DIM)
    msg = f"  {ts} {icon}  {text}"
    if detail:
        msg += c(f"  ({detail})", DIM)
    print(msg)


def ok(text: str, detail: str = "") -> None:
    step(c("✓", BRIGHT_GREEN), c(text, GREEN), detail)


def err(text: str, detail: str = "") -> None:
    step(c("✗", BRIGHT_RED), c(text, RED), detail)


def info(text: str, detail: str = "") -> None:
    step(c("→", BRIGHT_BLUE), text, detail)


def warn(text: str, detail: str = "") -> None:
    step(c("⚠", BRIGHT_YELLOW), c(text, YELLOW), detail)


def note(text: str) -> None:
    print(c(f"    # {text}", DIM))


# ─────────────────────────────────────────────────────────────────────────────
# Progress bar
# ─────────────────────────────────────────────────────────────────────────────

def hbar(value: float, max_val: float = 100.0, width: int = 20,
         color: str = BRIGHT_GREEN) -> str:
    """Return a horizontal bar string of *width* chars."""
    if max_val <= 0:
        filled = 0
    else:
        filled = min(width, max(0, int((value / max_val) * width)))
    return c("█" * filled + "░" * (width - filled), color)


def progress(label: str, value: float, max_val: float = 100.0,
             suffix: str = "", color: str = BRIGHT_CYAN, width: int = 20) -> None:
    """Print a labelled horizontal progress bar."""
    bar = hbar(value, max_val, width, color)
    pct = (value / max_val * 100) if max_val > 0 else 0
    print(f"  {c(label + ':', DIM):<36}  {bar}  {c(f'{pct:.0f}%', color)}  {c(suffix, DIM)}")


# ─────────────────────────────────────────────────────────────────────────────
# Table formatter
# ─────────────────────────────────────────────────────────────────────────────

def print_table(
    headers: list[str],
    rows: list[list[str]],
    colors: list[str] | None = None,
    title: str = "",
) -> None:
    """
    Print a formatted text table with optional per-column colors.

    Parameters
    ----------
    headers : list[str]
        Column header labels.
    rows : list[list[str]]
        Data rows — each row must have the same length as *headers*.
    colors : list[str] | None
        ANSI code(s) for each column (same length as headers).
        ``None`` means no color for that column.
    title : str
        Optional title printed above the table.
    """
    # Compute column widths
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                # Strip ANSI codes for width calculation
                plain = _strip_ansi(str(cell))
                col_widths[i] = max(col_widths[i], len(plain))

    sep = "  " + "─" * (sum(col_widths) + 3 * len(col_widths) + 1)

    if title:
        print()
        print(c(f"  {title}", BRIGHT_WHITE, BOLD))
    print(c(sep, DIM))

    # Header row
    header_cells = []
    for i, h in enumerate(headers):
        header_cells.append(c(h.ljust(col_widths[i]), BRIGHT_WHITE, BOLD))
    print("  " + c(" │ ", DIM).join(header_cells))
    print(c(sep, DIM))

    # Data rows
    colors = colors or [None] * len(headers)
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            plain = _strip_ansi(str(cell))
            padded = plain.ljust(col_widths[i])
            col_color = colors[i] if i < len(colors) and colors[i] else ""
            cells.append(c(padded, col_color) if col_color else padded)
        print("  " + c(" │ ", DIM).join(cells))

    print(c(sep, DIM))


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences for length calculation."""
    import re
    return re.sub(r"\033\[[0-9;]*m", "", text)


# ─────────────────────────────────────────────────────────────────────────────
# Trace tree printer
# ─────────────────────────────────────────────────────────────────────────────

# Icons and colors per span kind
_KIND_ICON = {
    "agent":     (c("◈", BRIGHT_MAGENTA), BRIGHT_MAGENTA),
    "llm":       (c("◉", BRIGHT_BLUE),    BRIGHT_BLUE),
    "tool":      (c("◆", BRIGHT_CYAN),    BRIGHT_CYAN),
    "chain":     (c("◎", BRIGHT_YELLOW),  BRIGHT_YELLOW),
    "retrieval": (c("◐", BRIGHT_GREEN),   BRIGHT_GREEN),
    "embedding": (c("◌", BRIGHT_WHITE),   BRIGHT_WHITE),
    "custom":    (c("○", WHITE),          WHITE),
}


def print_trace_tree(trace, indent_size: int = 4) -> None:
    """
    Pretty-print the span tree of a :class:`flowlens.sdk.models.Trace`.

    Shows hierarchical parent-child relationships, span kinds, status,
    duration, and token usage.
    """
    if not trace.spans:
        print(c("  (no spans)", DIM))
        return

    # Build parent→children map
    children: dict[str | None, list] = {}
    for span in trace.spans:
        parent = span.parent_span_id
        children.setdefault(parent, []).append(span)

    # Find root spans
    root_spans = children.get(None, [])

    def _print_span(span, prefix: str, is_last: bool) -> None:
        connector = "└─ " if is_last else "├─ "
        child_prefix = prefix + ("   " if is_last else "│  ")

        kind_val = span.kind.value if hasattr(span.kind, "value") else str(span.kind)
        icon, color = _KIND_ICON.get(kind_val, (c("○", WHITE), WHITE))

        status_val = span.status.value if hasattr(span.status, "value") else str(span.status)
        status_sym = c("✓", BRIGHT_GREEN) if status_val == "ok" else (
            c("✗", BRIGHT_RED) if status_val == "error" else c("·", DIM)
        )

        duration_str = c(f"{span.duration_ms:.0f}ms", DIM)
        token_str = ""
        if span.token_usage and span.token_usage.total_tokens:
            token_str = c(f" · {span.token_usage.total_tokens:,} tok · ${span.token_usage.total_cost_usd:.5f}", DIM)

        kind_badge = c(f"[{kind_val.upper():<9}]", color)
        name_str = c(span.name, BOLD if not span.parent_span_id else "")

        line = f"  {prefix}{connector}{status_sym}  {kind_badge}  {name_str}  {duration_str}{token_str}"
        print(line)

        span_children = children.get(span.span_id, [])
        for i, child in enumerate(span_children):
            _print_span(child, child_prefix, i == len(span_children) - 1)

    print()
    print(c(f"  Trace: {trace.trace_id[:24]}…", DIM))
    print(c(f"  Service: {trace.service_name}  |  "
            f"Duration: {trace.duration_ms:.0f}ms  |  "
            f"Spans: {len(trace.spans)}  |  "
            f"Tokens: {trace.total_tokens:,}  |  "
            f"Cost: ${trace.total_cost_usd:.5f}", DIM))
    print()

    for i, root in enumerate(root_spans):
        _print_span(root, "", i == len(root_spans) - 1)
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Spinner (simple synchronous)
# ─────────────────────────────────────────────────────────────────────────────

def spin(label: str, seconds: float = 0.5) -> None:
    """Show an animated spinner for *seconds*, then clear the line."""
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    end = time.perf_counter() + seconds
    i = 0
    while time.perf_counter() < end:
        frame = c(frames[i % len(frames)], BRIGHT_CYAN)
        sys.stdout.write(f"\r  {frame}  {c(label, DIM)}")
        sys.stdout.flush()
        time.sleep(0.08)
        i += 1
    sys.stdout.write("\r" + " " * (len(label) + 10) + "\r")
    sys.stdout.flush()
