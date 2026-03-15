"""
Generate screenshots from the live FlowLens dashboard at http://localhost:8585.

Usage:
    python3 examples/take_screenshots.py

Requirements:
    pip install playwright
    playwright install chromium

The server must be running:
    flowlens serve   # or: python3 examples/live_dashboard.py
"""

import os
import sys


BASE_URL = "http://localhost:8585"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
VIEWPORT = {"width": 1440, "height": 900}
# Extra wait after navigating to a tab (ms) — allows charts/WebSocket data to render
TAB_WAIT = 2500


def _click_tab(page, tab_name: str) -> None:
    """Click a top-level nav tab by its data-tab attribute."""
    selector = f"button[data-tab='{tab_name}']"
    page.locator(selector).click()
    page.wait_for_timeout(TAB_WAIT)


def main() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    with sync_playwright() as p:
        # Disable web security to allow CDN scripts past the server CSP headers;
        # also ignore HTTPS errors in case of self-signed certs.
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-web-security", "--disable-features=IsolateOrigins,site-per-process"],
        )
        context = browser.new_context(
            viewport=VIEWPORT,
            ignore_https_errors=True,
            bypass_csp=True,
        )

        page = context.new_page()

        # Inject dark-mode preference into localStorage before the page loads
        # (the dashboard reads this key on startup to set html.dark class)
        page.add_init_script("localStorage.setItem('flowlens-theme', 'dark')")

        print(f"Opening {BASE_URL} ...")
        try:
            page.goto(BASE_URL, wait_until="networkidle", timeout=20000)
        except Exception as exc:
            print(f"ERROR: Could not reach {BASE_URL}: {exc}")
            print("Is the server running? Try: flowlens serve")
            browser.close()
            sys.exit(1)

        # Give the dashboard JS time to boot and fetch initial data
        page.wait_for_timeout(3000)

        # Force dark mode on the HTML element directly (belt-and-suspenders)
        page.evaluate("document.documentElement.classList.add('dark')")
        page.wait_for_timeout(500)

        # ------------------------------------------------------------------
        # 1. dashboard_full.png — full overview (default landing page)
        # ------------------------------------------------------------------
        _click_tab(page, "overview")
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1000)
        page.screenshot(path=os.path.join(OUT_DIR, "dashboard_full.png"), full_page=False)
        print("  dashboard_full.png")

        # ------------------------------------------------------------------
        # 2. screenshot_overview.png — overview tab zoomed / stat cards area
        # ------------------------------------------------------------------
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(400)
        page.screenshot(path=os.path.join(OUT_DIR, "screenshot_overview.png"), full_page=False)
        print("  screenshot_overview.png")

        # ------------------------------------------------------------------
        # 3. screenshot_dag.png — Trace detail with Causal DAG sub-tab
        # ------------------------------------------------------------------
        _click_tab(page, "traces")
        page.evaluate("window.scrollTo(0, 0)")

        # Wait for trace rows to appear (they load via API after tab switch)
        try:
            # Find a visible trace row (not hidden, not empty placeholder)
            page.locator("#view-traces .trace-row:not(.trace-empty-row)").first.wait_for(
                state="visible", timeout=8000
            )
        except Exception:
            pass

        # Click the first visible, non-empty trace row
        trace_selector = "#view-traces .trace-row:not(.trace-empty-row)"
        first_trace = page.locator(trace_selector).first
        if first_trace.count() > 0:
            try:
                first_trace.click(timeout=5000)
                page.wait_for_timeout(1500)
                # Switch to the Causal DAG sub-tab inside trace detail
                dag_btn = page.locator("button[data-dtab='dag']")
                if dag_btn.count() > 0:
                    dag_btn.click()
                    page.wait_for_timeout(1200)
            except Exception:
                pass
        page.screenshot(path=os.path.join(OUT_DIR, "screenshot_dag.png"), full_page=False)
        print("  screenshot_dag.png")

        # ------------------------------------------------------------------
        # 4. screenshot_cost.png — Cost Analysis tab
        # ------------------------------------------------------------------
        _click_tab(page, "cost")
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=os.path.join(OUT_DIR, "screenshot_cost.png"), full_page=False)
        print("  screenshot_cost.png")

        # ------------------------------------------------------------------
        # 5. screenshot_patterns.png — Patterns tab
        # ------------------------------------------------------------------
        _click_tab(page, "patterns")
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=os.path.join(OUT_DIR, "screenshot_patterns.png"), full_page=False)
        print("  screenshot_patterns.png")

        # ------------------------------------------------------------------
        # 6. screenshot_sessions.png — Sessions tab (NEW)
        # ------------------------------------------------------------------
        _click_tab(page, "sessions")
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=os.path.join(OUT_DIR, "screenshot_sessions.png"), full_page=False)
        print("  screenshot_sessions.png")

        # ------------------------------------------------------------------
        # 7. screenshot_agents.png — Agents tab (NEW)
        # ------------------------------------------------------------------
        _click_tab(page, "agents")
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=os.path.join(OUT_DIR, "screenshot_agents.png"), full_page=False)
        print("  screenshot_agents.png")

        browser.close()

    print(f"\nAll screenshots saved to {OUT_DIR}/")
    saved = [
        "dashboard_full.png",
        "screenshot_overview.png",
        "screenshot_dag.png",
        "screenshot_cost.png",
        "screenshot_patterns.png",
        "screenshot_sessions.png",
        "screenshot_agents.png",
    ]
    for name in saved:
        path = os.path.join(OUT_DIR, name)
        size = os.path.getsize(path) if os.path.exists(path) else 0
        status = f"{size // 1024}KB" if size else "MISSING"
        print(f"  {name}: {status}")


if __name__ == "__main__":
    main()
