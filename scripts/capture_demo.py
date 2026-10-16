"""Capture the running Compose panel and a short silent, real browser walkthrough.

Uses only synthetic demo inputs. Authentication happens through the API before
recording starts, so the video contains neither passwords nor session tokens.
"""

import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def main():
    from playwright.sync_api import expect, sync_playwright

    config = dotenv_values(ROOT / ".env")
    password = os.getenv("BATCHFLOW_VERIFY_PASSWORD") or config.get("BATCHFLOW_ADMIN_PASSWORD")
    if not password:
        raise SystemExit("Set local verification credentials before recording")
    output = ROOT / "artifacts" / "compose-demo"
    output.mkdir(parents=True, exist_ok=True)
    base = os.getenv("BATCHFLOW_VERIFY_URL", "http://127.0.0.1:8000")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000}, reduced_motion="reduce", accept_downloads=True
        )
        login = context.request.post(
            base + "/api/v1/auth/login",
            data={
                "login": os.getenv("BATCHFLOW_VERIFY_LOGIN", "admin"),
                "password": password,
            },
        )
        if not login.ok:
            raise SystemExit("Demo login failed")
        # State stays in memory, never written to a cookie/session artifact.
        state = context.storage_state()
        context.close()
        context = browser.new_context(
            storage_state=state,
            viewport={"width": 1440, "height": 1000},
            record_video_dir=str(output),
            record_video_size={"width": 1440, "height": 1000},
            reduced_motion="reduce",
            accept_downloads=True,
        )
        page = context.new_page()
        page.goto(base)
        expect(page.get_by_role("heading", name="Tasks", exact=True)).to_be_visible()
        expect(page.locator("#tasks-body tr").first).to_be_visible()
        page.screenshot(path=str(output / "dashboard.png"), full_page=True)
        page.wait_for_timeout(1200)
        page.goto(base + "/import")
        sample = context.request.get(base + "/samples/browser_demo")
        if not sample.ok:
            raise SystemExit("Demo sample download failed")
        page.locator("#file").set_input_files(
            {"name": "calculator-demo.csv", "mimeType": "text/csv", "buffer": sample.body()}
        )
        page.get_by_role("button", name="Continue to mapping").click()
        expect(page.locator("#configuration")).to_be_visible()
        page.locator("#adapter").select_option("browser_demo")
        page.locator("#task-name").fill("Browser calculator · walkthrough")
        for name in ("identifier", "quantity", "unit_price", "discount"):
            page.locator(f".mapping-select[name={name}]").select_option(name)
        page.get_by_role("button", name="Review task").click()
        expect(page.locator("#review-step")).to_be_visible()
        page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
        page.screenshot(path=str(output / "import.png"), full_page=True)
        page.wait_for_timeout(1600)
        page.locator("#start-task").click()
        page.wait_for_url("**/tasks/*")
        expect(page.locator("#task-status")).to_contain_text("Completed", timeout=90000)
        expect(page.locator("#rows-body tr")).to_have_count(3)
        page.wait_for_timeout(1000)
        page.screenshot(path=str(output / "task.png"), full_page=True)
        page.get_by_role("button", name="Details", exact=False).first.click()
        expect(page.get_by_role("heading", name="Attempt history")).to_be_visible()
        page.wait_for_timeout(1800)
        page.get_by_role("button", name="Close row details").click()
        with page.expect_download() as download:
            page.locator("#export-xlsx").click()
        download.value.save_as(str(output / "calculator-result.xlsx"))
        page.wait_for_timeout(800)
        video = page.video
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=str(output / "task-mobile.png"), full_page=True)
        if page.evaluate("document.documentElement.scrollWidth > innerWidth"):
            raise AssertionError("Mobile panel overflows")
        page.wait_for_timeout(1200)
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.goto(base)
        page.wait_for_timeout(1200)
        context.close()
        video.save_as(str(output / "walkthrough.webm"))
        browser.close()
    print("Compose screenshots, XLSX and walkthrough saved under artifacts/compose-demo")


if __name__ == "__main__":
    main()
