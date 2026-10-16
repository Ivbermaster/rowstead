"""Opt-in real browser smoke: BATCHFLOW_E2E=1 pytest tests/test_ui_e2e.py.

Requires the Playwright Chromium runtime. All services and data are isolated.
"""

import io
import os
import re
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("BATCHFLOW_E2E") != "1", reason="Set BATCHFLOW_E2E=1 to run real browser E2E"
)
ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_ready(url, process, log_path):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(f"Server stopped: {log_path.read_text(errors='replace')}")
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (URLError, TimeoutError, OSError):
            pass
        time.sleep(0.25)
    pytest.fail(f"Server did not become ready: {log_path.read_text(errors='replace')}")


def test_real_upload_process_export_and_mobile(tmp_path):
    from playwright.sync_api import expect, sync_playwright

    api_port, demo_port = free_port(), free_port()
    while demo_port == api_port:
        demo_port = free_port()
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": "sqlite:///" + (tmp_path / "e2e.db").as_posix(),
            "STORAGE_DIR": str(tmp_path / "storage"),
            "SESSION_SECRET": secrets.token_urlsafe(48),
            "DEMO_BASE_URL": f"http://127.0.0.1:{demo_port}",
            "WORKER_POLL_SECONDS": "0.1",
            "COOKIE_SECURE": "false",
        }
    )
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / "data" / "browsers"))
    password = secrets.token_urlsafe(24)
    env["BATCHFLOW_E2E_PASSWORD"] = password
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        timeout=90,
    )
    # A separate process keeps this test's database/config out of other pytest modules.
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import os; from sqlalchemy import create_engine; "
            "from sqlalchemy.orm import sessionmaker; from app.auth import hash_password; "
            "from app.models import User; "
            "factory=sessionmaker(bind=create_engine(os.environ['DATABASE_URL'])); "
            "db=factory(); db.add(User(login='e2e-admin', "
            "password_hash=hash_password(os.environ['BATCHFLOW_E2E_PASSWORD']))); "
            "db.commit(); db.close()",
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        timeout=90,
    )
    processes, handles = [], []

    def start(name, args):
        log_path = tmp_path / f"{name}.log"
        handle = log_path.open("w", encoding="utf-8")
        handles.append(handle)
        process = subprocess.Popen(
            [sys.executable, *args],
            cwd=ROOT,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        processes.append(process)
        return process, log_path

    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    old_browser_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = env["PLAYWRIGHT_BROWSERS_PATH"]
    try:
        demo, demo_log = start(
            "demo",
            ["-m", "uvicorn", "demo.main:app", "--host", "127.0.0.1", "--port", str(demo_port)],
        )
        api, api_log = start(
            "api", ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(api_port)]
        )
        base = f"http://127.0.0.1:{api_port}"
        wait_ready(f"http://127.0.0.1:{demo_port}/openapi.json", demo, demo_log)
        wait_ready(base + "/health/ready", api, api_log)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 1000}, accept_downloads=True
            )
            page = context.new_page()
            page.emulate_media(reduced_motion="reduce")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base + "/docs")
            expect(page.get_by_role("heading", name="Rowstead API", exact=True)).to_be_visible()
            expect(page.get_by_role("heading", name="Authentication and CSRF")).to_be_visible()
            expect(page.get_by_role("link", name="OpenAPI JSON")).to_have_attribute("href", "/openapi.json")
            page.screenshot(path=str(artifacts / "api-docs-desktop.png"), full_page=True)
            page.goto(base)
            expect(page.get_by_role("heading", name="Welcome back.")).to_be_visible()
            page.screenshot(path=str(artifacts / "login-desktop.png"), full_page=True)
            page.get_by_label("Username").fill("e2e-admin")
            page.get_by_label("Password").fill(password)
            page.get_by_role("button", name="Sign in").click()
            expect(page.get_by_role("heading", name="Tasks", exact=True)).to_be_visible(
                timeout=30000
            )
            expect(page.get_by_text("Start with a sample or your own spreadsheet")).to_be_visible()
            page.get_by_role("link", name="Upload your spreadsheet", exact=True).click()
            # Bad files keep the user on upload with a useful error.
            page.locator("#file").set_input_files(
                {"name": "broken.csv", "mimeType": "text/csv", "buffer": b"\xff\xff"}
            )
            page.get_by_role("button", name="Continue to mapping").click()
            expect(page.locator("#upload-error")).to_be_visible()
            expect(page.locator("#upload-step")).to_be_visible()
            page.get_by_text("Want to explore error handling?").click()
            page.get_by_role("button", name="Load error-handling sample").click()
            expect(page.locator("#configuration")).to_be_visible(timeout=30000)
            expect(page.locator("#review-step")).to_be_hidden()
            page.locator("#task-name").fill("Registry smoke test")
            expect(page.locator(".mapping-select[name=identifier]")).to_have_value("identifier")
            page.get_by_role("button", name="Review task").focus()
            page.keyboard.press("Enter")
            expect(page.locator("#review-step")).to_be_visible()
            expect(page.locator("#review-summary")).to_contain_text("error-handling-sample.csv")
            expect(page.locator("#review-summary")).to_contain_text("Company name")
            page.get_by_role("button", name="Change column mapping").click()
            expect(page.locator("#task-name")).to_have_value("Registry smoke test")
            expect(page.locator(".mapping-select[name=identifier]")).to_have_value("identifier")
            page.get_by_role("button", name="Review task").click()
            page.screenshot(path=str(artifacts / "import-review-desktop.png"), full_page=True)
            creates = []
            page.on("request", lambda request: creates.append(request.url)
                    if request.method == "POST" and request.url == base + "/api/v1/tasks" else None)
            failed_start = {"done": False}

            def fail_first_start(route):
                if not failed_start["done"]:
                    failed_start["done"] = True
                    route.fulfill(status=503, json={"message": "Temporary start failure for recovery check"})
                else:
                    route.continue_()

            page.route("**/api/v1/tasks/*/start", fail_first_start)
            page.get_by_role("button", name="Start processing", exact=True).click()
            expect(page.locator("#create-error")).to_contain_text("Task saved")
            expect(page.get_by_role("button", name="Retry start", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="Change file")).to_be_disabled()
            assert len(creates) == 1
            page.get_by_role("button", name="Retry start", exact=True).click()
            page.wait_for_url(re.compile(r"/tasks/[a-f0-9-]+$"), timeout=30000)
            expect(page.locator("#task-status")).to_contain_text("Queued", timeout=30000)
            page.get_by_role("button", name="Pause", exact=False).click()
            expect(page.locator("#task-status")).to_contain_text("Pause requested", timeout=30000)
            start("worker", ["-m", "app.worker"])
            expect(page.locator("#task-status")).to_contain_text("Paused", timeout=45000)
            page.get_by_role("button", name="Resume", exact=False).click()
            expect(page.locator("#task-status")).to_contain_text("Completed", timeout=90000)
            expect(page.locator("#rows-body tr")).not_to_have_count(0)
            expect(page.locator("#toast")).to_be_hidden(timeout=10000)
            expect(page.locator("#progress-number")).to_have_text("100%")
            expect(page.locator("#processed-summary")).to_have_text("8 of 8 rows processed")
            expect(page.locator("#rows-body .status-missing")).to_have_count(1)
            expect(page.locator("#rows-body .status-invalid")).to_have_count(1)
            expect(page.locator("#rows-body .status-failed")).to_have_count(1)
            assert len(creates) == 1, "Retrying start created a duplicate task"
            page.get_by_role("button", name="Review 3 issues").click()
            expect(page.locator("#rows-body tr")).to_have_count(3)
            expect(page.locator("#rows-body .status-succeeded")).to_have_count(0)
            expect(page.locator("#row-filter-help")).to_contain_text("failed, invalid and missing")
            page.locator("#row-filter").select_option("")
            expect(page.locator("#rows-body tr")).to_have_count(8)
            page.screenshot(path=str(artifacts / "task-desktop.png"), full_page=True)
            page.get_by_role("button", name="Details", exact=False).first.click()
            expect(page.get_by_role("heading", name="Attempt history")).to_be_visible()
            expect(page.locator(".attempt-item").first).to_be_visible()
            page.get_by_role("button", name="Close row details").click()
            with page.expect_download() as download:
                page.locator("#export-csv").click()
            path = download.value.path()
            content = Path(path).read_text(encoding="utf-8-sig")
            assert "identifier" in content and "succeeded" in content
            page.set_viewport_size({"width": 390, "height": 844})
            first_row = page.locator("#rows-body tr").first
            expect(first_row.locator(".row-status")).to_be_visible()
            expect(first_row.get_by_role("button", name="Details for row 1")).to_be_visible()
            assert first_row.locator(".row-status").bounding_box()["x"] < 390
            assert first_row.locator(".row-action").bounding_box()["x"] < 390
            first_row.get_by_role("button", name="Details for row 1").click()
            expect(page.get_by_role("heading", name="Attempt history")).to_be_visible()
            page.get_by_role("button", name="Close row details").click()
            page.screenshot(path=str(artifacts / "task-mobile.png"), full_page=True)
            page.goto(base)
            expect(page.locator("#tasks-body tr")).to_have_count(1)
            expect(page.locator("#tasks-body .status-completed_with_errors")).to_be_visible()
            page.screenshot(path=str(artifacts / "dashboard-mobile.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
                "Mobile document overflows horizontally"
            )
            page.get_by_role("link", name="Sources", exact=False).first.click()
            expect(page.get_by_role("heading", name="Sources", exact=True)).to_be_visible()
            expect(page.locator(".source-card")).to_have_count(2)
            page.screenshot(path=str(artifacts / "sources-mobile.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            expect(page.get_by_role("button", name="Sign out", exact=True)).to_be_visible()
            page.get_by_role("button", name="Sign out", exact=True).click()
            expect(page.get_by_role("heading", name="Welcome back.")).to_be_visible()
            page.get_by_label("Username").fill("e2e-admin")
            page.get_by_label("Password").fill(password)
            page.get_by_role("button", name="Sign in").click()
            expect(page.get_by_role("heading", name="Tasks", exact=True)).to_be_visible()
            page.get_by_role("link", name="Sources", exact=False).first.click()
            expect(page.locator(".source-card")).to_have_count(2)
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.screenshot(path=str(artifacts / "sources-desktop.png"), full_page=True)
            page.goto(base)
            expect(page.locator("#tasks-body tr")).to_have_count(1)
            page.screenshot(path=str(artifacts / "dashboard-desktop.png"), full_page=True)
            # A second task exercises the actual Chromium calculator adapter,
            # including mapping numeric columns and downloading an XLSX result.
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.goto(base + "/import")
            browser_sample = context.request.get(base + "/samples/browser_demo")
            assert browser_sample.ok
            page.locator("#file").set_input_files(
                {
                    "name": "browser-sample.csv",
                    "mimeType": "text/csv",
                    "buffer": browser_sample.body(),
                }
            )
            page.get_by_role("button", name="Continue to mapping").click()
            expect(page.locator("#configuration")).to_be_visible(timeout=30000)
            page.locator("#adapter").select_option("browser_demo")
            page.locator("#task-name").fill("Browser calculator smoke test")
            expect(page.locator(".mapping-select[name=quantity]")).to_have_value("quantity")
            page.locator(".mapping-select[name=discount]").select_option("")
            page.get_by_role("button", name="Review task").click()
            expect(page.locator("#review-summary")).to_contain_text("Default: 0")
            page.get_by_role("button", name="Change column mapping").click()
            expect(page.locator(".mapping-select[name=discount]")).to_have_value("")
            page.get_by_role("button", name="Review task").click()
            page.get_by_role("button", name="Start processing", exact=True).click()
            page.wait_for_url(re.compile(r"/tasks/[a-f0-9-]+$"), timeout=30000)
            expect(page.locator("#task-status")).to_contain_text("Completed", timeout=90000)
            expect(page.locator("#rows-body .status-succeeded").first).to_be_visible()
            page.get_by_role("button", name="Details", exact=False).first.click()
            expect(page.locator("#row-detail-content pre").nth(1)).to_contain_text('"total"')
            expect(page.locator("#row-detail-content pre").nth(1)).to_contain_text('"tax"')
            page.get_by_role("button", name="Close row details").click()
            page.screenshot(path=str(artifacts / "browser-task-desktop.png"), full_page=True)
            with page.expect_download() as xlsx_download:
                page.locator("#export-xlsx").click()
            assert Path(xlsx_download.value.path()).read_bytes().startswith(b"PK")
            # The recommended sample starts with successful rows and works on narrow screens.
            page.set_viewport_size({"width": 320, "height": 844})
            page.goto(base)
            page.get_by_role("link", name="New task", exact=False).click()
            page.get_by_role("button", name="Use company sample").click()
            expect(page.locator("#configuration")).to_be_visible(timeout=30000)
            page.get_by_role("button", name="Back to upload").click()
            expect(page.locator("#file-label")).to_have_text("company-sample.csv")
            page.get_by_role("button", name="Continue to mapping").click()
            expect(page.locator(".mapping-select[name=identifier]")).to_have_value("identifier")
            page.get_by_role("button", name="Review task").click()
            expect(page.locator("#review-summary")).to_contain_text("company-sample.csv")
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(artifacts / "import-review-mobile.png"), full_page=True)
            page.get_by_role("button", name="Start processing", exact=True).focus()
            page.keyboard.press("Enter")
            page.wait_for_url(re.compile(r"/tasks/[a-f0-9-]+$"), timeout=30000)
            expect(page.locator("#task-status")).to_have_text("Completed", timeout=90000)
            expect(page.locator("#rows-body .status-succeeded")).to_have_count(3)
            expect(page.locator("#task-issues")).to_be_hidden()
            page.goto(base)
            page.locator("#task-search").fill("Registry smoke")
            expect(page.locator("#tasks-body tr")).to_have_count(1)
            page.locator("#task-status-filter").select_option("completed")
            expect(page.locator("#tasks-no-match")).to_be_visible()
            page.get_by_role("button", name="Clear filters").click()
            expect(page.locator("#tasks-body tr")).to_have_count(3)
            # XLSX worksheet changes re-import correctly without losing the task name.
            from openpyxl import Workbook

            workbook = Workbook()
            workbook.active.title = "Unmapped"
            workbook.active.append(["company_id", "notes"])
            workbook.active.append(["BF-0001", "First worksheet"])
            other = workbook.create_sheet("Ready")
            other.append(["identifier", "notes"])
            other.append(["BF-0002", "Second worksheet"])
            payload = io.BytesIO()
            workbook.save(payload)
            page.goto(base + "/import")
            page.locator("#file").set_input_files(
                {"name": "two-sheets.xlsx", "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "buffer": payload.getvalue()}
            )
            page.get_by_role("button", name="Continue to mapping").click()
            expect(page.locator("#configuration")).to_be_visible()
            expect(page.locator(".mapping-select[name=identifier]")).to_have_value("")
            page.locator("#task-name").fill("Keep this task name")
            page.get_by_role("button", name="Review task").click()
            expect(page.locator("#configuration")).to_be_visible()
            expect(page.locator("#review-step")).to_be_hidden()
            page.get_by_text("Preview uploaded rows", exact=False).click()
            expect(page.locator("#sheet-field")).to_be_visible()
            page.locator("#sheet-name").select_option("Ready")
            expect(page.locator("#preview-table")).to_contain_text("Second worksheet")
            expect(page.locator("#task-name")).to_have_value("Keep this task name")
            page.locator(".mapping-select[name=identifier]").select_option("identifier")
            page.get_by_role("button", name="Review task").click()
            expect(page.locator("#review-summary")).to_contain_text("Ready")
            expect(page.locator("#review-summary")).to_contain_text("Keep this task name")
            page.get_by_role("button", name="Change processing").click()
            page.locator("#task-name").fill("Updated before start")
            page.locator("#step-three button").click()
            expect(page.locator("#review-summary")).to_contain_text("Updated before start")
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert not errors, "Browser JavaScript errors: " + "; ".join(errors)
            browser.close()
    finally:
        if old_browser_path is None:
            os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
        else:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = old_browser_path
        for process in reversed(processes):
            if process.poll() is None:
                if sys.platform == "win32":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        check=False,
                        capture_output=True,
                        timeout=15,
                    )
                else:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        for handle in handles:
            handle.close()
