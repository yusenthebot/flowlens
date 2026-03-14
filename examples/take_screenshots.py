"""Generate screenshots from demo_dashboard.html for README."""
import os


def main():
    from playwright.sync_api import sync_playwright

    html_path = os.path.join(os.path.dirname(__file__), "demo_dashboard.html")
    html_url = f"file://{os.path.abspath(html_path)}"
    out_dir = os.path.dirname(__file__)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(html_url)
        page.wait_for_timeout(1500)  # let charts render

        # 1. Full dashboard overview (dark theme)
        page.screenshot(
            path=os.path.join(out_dir, "dashboard_full.png"),
            full_page=False,
        )
        print("✓ dashboard_full.png")

        # 2. Click on a trace to show detail view
        # Click on the first trace in the list
        trace_rows = page.query_selector_all("[data-trace-id]")
        if not trace_rows:
            # Try clicking on any trace-like element
            trace_rows = page.query_selector_all(".trace-row, tr[class*='trace'], [onclick*='trace']")
        if trace_rows:
            trace_rows[0].click()
            page.wait_for_timeout(800)
            page.screenshot(
                path=os.path.join(out_dir, "screenshot_overview.png"),
                full_page=False,
            )
            print("✓ screenshot_overview.png (trace detail)")
        else:
            print("⚠ No trace rows found, trying tab navigation")
            # Click traces tab
            tabs = page.query_selector_all("button, [role='tab']")
            for tab in tabs:
                text = tab.inner_text().lower()
                if "trace" in text:
                    tab.click()
                    page.wait_for_timeout(500)
                    break
            page.screenshot(
                path=os.path.join(out_dir, "screenshot_overview.png"),
                full_page=False,
            )
            print("✓ screenshot_overview.png (traces tab)")

        # 3. Navigate to DAG view if available
        tabs = page.query_selector_all("button, [role='tab']")
        dag_clicked = False
        for tab in tabs:
            text = tab.inner_text().lower()
            if "dag" in text or "graph" in text or "causal" in text:
                tab.click()
                page.wait_for_timeout(1000)
                dag_clicked = True
                break

        if not dag_clicked:
            # Try clicking inside the trace detail to find DAG tab
            detail_tabs = page.query_selector_all("[data-tab], .tab-btn, button")
            for tab in detail_tabs:
                text = tab.inner_text().lower()
                if "dag" in text or "graph" in text:
                    tab.click()
                    page.wait_for_timeout(1000)
                    dag_clicked = True
                    break

        page.screenshot(
            path=os.path.join(out_dir, "screenshot_dag.png"),
            full_page=False,
        )
        print("✓ screenshot_dag.png")

        # 4. Cost analysis view
        for tab in tabs:
            text = tab.inner_text().lower()
            if "cost" in text:
                tab.click()
                page.wait_for_timeout(800)
                break
        page.screenshot(
            path=os.path.join(out_dir, "screenshot_cost.png"),
            full_page=False,
        )
        print("✓ screenshot_cost.png")

        # 5. Patterns view
        for tab in tabs:
            text = tab.inner_text().lower()
            if "pattern" in text:
                tab.click()
                page.wait_for_timeout(800)
                break
        page.screenshot(
            path=os.path.join(out_dir, "screenshot_patterns.png"),
            full_page=False,
        )
        print("✓ screenshot_patterns.png")

        browser.close()
        print(f"\nAll screenshots saved to {out_dir}/")


if __name__ == "__main__":
    main()
