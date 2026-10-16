"""Exercise a running Compose stack, including a deliberate worker crash.

Run from the project root: python scripts/verify_runtime.py
Credentials: BATCHFLOW_VERIFY_LOGIN (default admin), BATCHFLOW_VERIFY_PASSWORD
or the ignored .env's BATCHFLOW_ADMIN_PASSWORD. Never pass passwords on the CLI.
The script creates persistent, clearly named synthetic verification tasks.
It kills and restarts only this project's worker, so run on an idle demo stack.
To continue an interrupted 3000-row observation without creating another batch,
set BATCHFLOW_VERIFY_RESUME_TASK to its task ID from artifacts/runtime-checkpoint.json.
On resume, elapsed uses persisted task timestamps and memory covers the resumed window.
"""

import csv
import hashlib
import io
import json
import os
import re
import statistics
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from dotenv import dotenv_values
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "runtime-report.md"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def docker(*args, stdin=None):
    result = subprocess.run(
        ["docker", *args], cwd=ROOT, input=stdin, capture_output=True, text=True, timeout=45
    )
    require(result.returncode == 0, "Docker operation failed: " + " ".join(args[:2]))
    return result.stdout


def service_container(service):
    ids = docker("compose", "--project-name", "batchflow", "ps", "-q", service).split()
    require(len(ids) == 1, f"Expected one running {service} container")
    info = json.loads(docker("inspect", ids[0]))[0]
    labels = info["Config"]["Labels"]
    require(labels.get("com.docker.compose.project") == "batchflow", "Wrong Compose project")
    require(labels.get("com.docker.compose.service") == service, "Wrong Compose service")
    require(
        Path(labels["com.docker.compose.project.working_dir"]).resolve() == ROOT,
        "Compose stack belongs to another checkout",
    )
    return ids[0]


class WorkerMemory:
    """Sample only the resolved worker container, never the whole Docker host."""

    def __init__(self, container):
        self.container = container
        self.samples = []
        self.errors = 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def loop(self):
        units = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}
        while not self.stop.is_set():
            try:
                value = docker("stats", "--no-stream", "--format", "{{.MemUsage}}", self.container)
                match = re.match(r"\s*([\d.]+)(B|KiB|MiB|GiB)\s*/", value)
                require(match is not None, "Unsupported Docker memory unit")
                self.samples.append(float(match[1]) * units[match[2]] / 1024**2)
            except (AssertionError, subprocess.SubprocessError):
                self.errors += 1
            self.stop.wait(1)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=50)


class API:
    def __init__(self, password, login):
        self.client = httpx.Client(
            base_url=os.getenv("BATCHFLOW_VERIFY_URL", "http://127.0.0.1:8000"),
            timeout=60,
            trust_env=False,
        )
        self.requests = 0
        session = self.call(
            "POST", "/api/v1/auth/login", json={"login": login, "password": password}
        )
        self.client.headers["X-CSRF-Token"] = session["csrf_token"]

    def response(self, method, path, **kwargs):
        self.requests += 1
        response = self.client.request(method, path, **kwargs)
        require(response.is_success, f"API {method} {path} returned {response.status_code}")
        return response

    def call(self, method, path, **kwargs):
        return self.response(method, path, **kwargs).json()

    def create(self, name, records, adapter="registry_demo", mapping=None):
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
        uploaded = self.call(
            "POST",
            "/api/v1/imports",
            files={"file": ("runtime-verification.csv", buffer.getvalue().encode(), "text/csv")},
        )
        require(uploaded["row_count"] == len(records), "Imported row count differs")
        task = self.call(
            "POST",
            "/api/v1/tasks",
            json={
                "name": name,
                "import_id": uploaded["id"],
                "adapter": adapter,
                "mapping": mapping or {"identifier": "identifier"},
            },
        )
        self.call("POST", f"/api/v1/tasks/{task['id']}/start")
        return task["id"]

    def rows(self, task_id, status=None):
        rows, page = [], 1
        while True:
            params = {"page": page, "page_size": 200}
            if status:
                params["status"] = status
            result = self.call("GET", f"/api/v1/tasks/{task_id}/rows", params=params)
            rows.extend(result["items"])
            if len(rows) >= result["total"]:
                return rows
            page += 1

    def finish(self, task_id, timeout=3600):
        deadline = time.monotonic() + timeout
        progress_at = time.monotonic() + 30
        while time.monotonic() < deadline:
            task = self.call("GET", f"/api/v1/tasks/{task_id}")
            if task["status"] in {"completed", "completed_with_errors"}:
                return task
            require(task["status"] in {"queued", "running"}, "Unexpected task state")
            if time.monotonic() >= progress_at:
                print(
                    f"Progress: {task['counts']['succeeded']}/{task['total']} succeeded", flush=True
                )
                progress_at = time.monotonic() + 30
            time.sleep(0.75)
        raise AssertionError("Task completion deadline exceeded")


def registry_truth(identifier):
    seed = int(hashlib.sha256(identifier.encode()).hexdigest()[:8], 16)
    return {
        "identifier": identifier,
        "company_name": f"Example Company {identifier}",
        "country": ["Poland", "Germany", "United Kingdom", "United States"][seed % 4],
        "industry": ["Software", "Manufacturing", "Retail", "Logistics"][seed % 4],
        "employees": 5 + seed % 995,
        "active": seed % 7 != 0,
        "risk_score": seed % 101,
    }


def check_registry(rows, originals):
    require(len(rows) == len(originals), "Result count differs from original count")
    require(len({row["id"] for row in rows}) == len(rows), "Repeated internal row identity")
    for number, (row, original) in enumerate(zip(rows, originals, strict=True), 1):
        require(row["row_number"] == number, "Original row order changed")
        require(row["input_json"] == original, "Original data changed or duplicate dropped")
        require(row["status"] == "succeeded", "Unexpected registry row failure")
        require(
            row["output_json"] == registry_truth(original["identifier"]), "Ground truth mismatch"
        )


def check_exports(api, task_id, originals):
    csv_rows = list(
        csv.DictReader(
            io.StringIO(
                api.response("GET", f"/api/v1/tasks/{task_id}/export?format=csv").content.decode(
                    "utf-8-sig"
                )
            )
        )
    )
    xlsx = load_workbook(
        io.BytesIO(api.response("GET", f"/api/v1/tasks/{task_id}/export?format=xlsx").content),
        read_only=True,
        data_only=True,
    )
    values = iter(xlsx.active.values)
    headers = next(values)
    xlsx_rows = [dict(zip(headers, record, strict=True)) for record in values]
    xlsx.close()
    for records, csv_format in ((csv_rows, True), (xlsx_rows, False)):
        require(len(records) == len(originals), "Export dropped original rows")
        for number, (row, original) in enumerate(zip(records, originals, strict=True), 1):
            require(
                all(row[key] == value for key, value in original.items()), "Export input mismatch"
            )
            require(str(row["row_number"]) == str(number), "Export original order mismatch")
            require(row["status"] == "succeeded", "Export status mismatch")
            for key, value in registry_truth(original["identifier"]).items():
                require(
                    row[f"result.{key}"] == (str(value) if csv_format else value),
                    "Export ground truth mismatch",
                )


def crash_recovery(api, worker, prefix):
    originals = [{"identifier": f"{prefix}-crash-{i:03}", "original": str(i)} for i in range(20)]
    originals[10]["identifier"] = originals[11]["identifier"] = "TIMEOUT"
    task_id = api.create("Runtime verification: crash and lease recovery", originals)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        running = api.rows(task_id, "running")
        if len(running) == 2 and all(
            row["input_json"]["identifier"] == "TIMEOUT" for row in running
        ):
            break
        time.sleep(0.15)
    else:
        raise AssertionError("No controlled in-flight request observed")
    before = {row["id"]: row for row in api.rows(task_id, "succeeded")}
    require(before, "Crash must occur after completed rows exist")
    # Confirm committed, active leases through the running application's database.
    code = (
        "import json; from sqlalchemy import select; from app.db import SessionLocal; "
        "from app.models import Row, utcnow; "
        f"s=SessionLocal(); rows=s.scalars(select(Row).where(Row.task_id=='{task_id}',"
        "Row.status=='running')).all(); "
        "print(json.dumps([{'id':r.id,'active':bool(r.worker_id and r.lease_until "
        "and r.lease_until>utcnow())} for r in rows])); s.close()"
    )
    leases = json.loads(
        docker("compose", "--project-name", "batchflow", "exec", "-T", "api", "python", "-c", code)
    )
    require(leases and all(row["active"] for row in leases), "No active committed leases")
    started = time.monotonic()
    restarted = False
    try:
        docker("compose", "--project-name", "batchflow", "kill", "--signal", "SIGKILL", "worker")
        require(
            json.loads(docker("inspect", worker))[0]["State"]["Running"] is False,
            "Worker did not stop after SIGKILL",
        )
        stopped = {row["id"]: row for row in api.rows(task_id, "succeeded")}
        require(
            all(stopped.get(key) == row for key, row in before.items()),
            "Completed rows changed while worker was stopped",
        )
        docker("start", worker)
        restarted = True
        task = api.finish(task_id, timeout=180)
    finally:
        if not restarted:
            docker("start", worker)
    rows = api.rows(task_id)
    require(task["status"] == "completed_with_errors", "TIMEOUT rows must finish with errors")
    after = {row["id"]: row for row in rows}
    require(
        all(after.get(key) == row for key, row in before.items()),
        "Recovery reprocessed or changed completed rows",
    )
    normal = [row for row in rows if row["input_json"]["identifier"] != "TIMEOUT"]
    for row in normal:
        require(
            row["status"] == "succeeded" and row["attempt_count"] == 1,
            "Non-interrupted normal row was lost or repeated",
        )
        require(
            row["output_json"] == registry_truth(row["input_json"]["identifier"]),
            "Crash recovery normal output mismatch",
        )
    expired = 0
    for lease in leases:
        attempts = api.call("GET", f"/api/v1/rows/{lease['id']}/attempts")["items"]
        expired += sum(attempt["error_code"] == "lease_expired" for attempt in attempts)
        require(
            any(
                attempt["error_code"] == "lease_expired" and attempt["finished_at"]
                for attempt in attempts
            ),
            "Interrupted attempt was not closed as lease_expired",
        )
    require(
        len(rows) == 20 and len({row["row_number"] for row in rows}) == 20,
        "Crash recovery lost original rows",
    )
    require(
        [row["input_json"] for row in rows] == originals,
        "Crash recovery changed original order or data",
    )
    require(
        all(
            row["status"] == "failed"
            for row in rows
            if row["input_json"]["identifier"] == "TIMEOUT"
        ),
        "Controlled TIMEOUT rows did not exhaust retries",
    )
    return task_id, len(before), expired, round(time.monotonic() - started, 2)


def browser_smoke(api, prefix):
    original = {
        "identifier": prefix + "-browser",
        "quantity": "2",
        "unit_price": "19.5",
        "discount": "5",
    }
    task_id = api.create(
        "Runtime verification: real Chromium",
        [original],
        "browser_demo",
        {key: key for key in original},
    )
    require(api.finish(task_id, timeout=90)["status"] == "completed", "Chromium task failed")
    row = api.rows(task_id)[0]
    require(row["input_json"] == original, "Browser original changed")
    require(
        row["output_json"]
        == {
            "identifier": original["identifier"],
            "quantity": "2",
            "unit_price": "19.50",
            "subtotal": "39.00",
            "discount_amount": "1.95",
            "tax": "7.41",
            "total": "44.46",
        },
        "Chromium calculator ground truth mismatch",
    )
    return task_id


def main():
    local = dotenv_values(ROOT / ".env")
    password = (
        os.getenv("BATCHFLOW_VERIFY_PASSWORD")
        or local.get("BATCHFLOW_VERIFY_PASSWORD")
        or local.get("BATCHFLOW_ADMIN_PASSWORD")
    )
    require(bool(password), "Set a verification password in environment or ignored .env")
    login = os.getenv("BATCHFLOW_VERIFY_LOGIN", "admin")
    worker = service_container("worker")
    demo = service_container("demo-source")
    worker_env = dict(
        item.split("=", 1)
        for item in json.loads(docker("inspect", worker))[0]["Config"]["Env"]
        if "=" in item
    )
    require(
        worker_env.get("WORKER_CONCURRENCY", "2") == "2",
        "This controlled crash scenario requires WORKER_CONCURRENCY=2",
    )
    lease_seconds = int(worker_env.get("LEASE_SECONDS", "120"))
    max_attempts = int(worker_env.get("MAX_ATTEMPTS", "3"))
    require(max_attempts >= 2, "Crash recovery verification needs at least two attempts")
    api = API(password, login)
    require(api.call("GET", "/health/ready")["status"] == "ready", "API not ready")
    resume = os.getenv("BATCHFLOW_VERIFY_RESUME_TASK")
    if resume:
        resume = str(UUID(resume))
        first = api.call("GET", f"/api/v1/tasks/{resume}/rows", params={"page_size": 1})
        require(first["total"] == 3000, "Resumed task must contain exactly 3000 originals")
        prefix = first["items"][0]["input_json"]["identifier"].rsplit("-", 1)[0]
        require(re.fullmatch(r"VERIFY-[a-f0-9]{12}", prefix), "Unknown verification task prefix")
    else:
        prefix = "VERIFY-" + uuid4().hex[:12]
    originals = [
        {
            "identifier": f"{prefix}-{i % 2400:04}",
            "original_id": str(i + 1),
            "notes": f"Synthetic row {i + 1}, сохранено",
        }
        for i in range(3000)
    ]
    print("Running 3,000-row authenticated HTTP batch and scoped memory sampling...", flush=True)
    with WorkerMemory(worker) as memory:
        started = time.monotonic()
        task_id = resume or api.create(
            "Runtime verification: 3000 originals and 600 duplicates", originals
        )
        initial_task = api.call("GET", f"/api/v1/tasks/{task_id}")
        checkpoint = {
            "task_id": task_id,
            "prefix": prefix,
            "expected_rows": 3000,
            "started_at": initial_task["started_at"],
            "created_at": initial_task["created_at"],
            "measurement_started_utc": datetime.now(timezone.utc).isoformat(),
        }
        (ROOT / "artifacts").mkdir(exist_ok=True)
        (ROOT / "artifacts" / "runtime-checkpoint.json").write_text(
            json.dumps(checkpoint, indent=2), encoding="utf-8"
        )
        task = api.finish(task_id)
        elapsed = time.monotonic() - started
    elapsed_basis = "import/task creation through terminal-state polling"
    if resume:
        elapsed = (
            datetime.fromisoformat(task["finished_at"]) - datetime.fromisoformat(task["started_at"])
        ).total_seconds()
        elapsed_basis = "persisted task start through terminal completion (resumed observation)"
    (ROOT / "artifacts" / "runtime-memory.json").write_text(
        json.dumps(
            {
                "task_id": task_id,
                "resumed_observation": bool(resume),
                "samples_mib": memory.samples,
                "sampling_errors": memory.errors,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    require(task["status"] == "completed", "3000-row task did not succeed")
    rows = api.rows(task_id)
    check_registry(rows, originals)
    require(all(row["attempt_count"] == 1 for row in rows), "Normal row was requested repeatedly")
    check_exports(api, task_id, originals)
    logs = docker("logs", demo)
    source_requests = len(
        re.findall(r'"GET /api/registry/' + re.escape(prefix) + r"-\d{4} HTTP/", logs)
    )
    require(source_requests == 3000, "Source access-log request count differs from 3000")
    require(memory.samples and memory.errors == 0, "Worker memory sampling incomplete")
    print("HTTP and CSV/XLSX checks passed; running actual SIGKILL/lease recovery...", flush=True)
    crash_id, preserved, expired, recovery_seconds = crash_recovery(api, worker, prefix)
    print("Crash recovery passed; running container Chromium calculator...", flush=True)
    browser_id = browser_smoke(api, prefix)
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report = f"""# Docker Compose runtime verification

Executed successfully at {timestamp} using `python scripts/verify_runtime.py`.
All data are synthetic. Task/import/row operations used the authenticated live API.
Stack: this checkout's `batchflow` Compose project; PostgreSQL and two worker threads.
Observed worker configuration: lease {lease_seconds} s; maximum {max_attempts} attempts.

| Check | Observed result |
|---|---|
| HTTP input | 3,000 original rows; 2,400 unique identifiers; 600 duplicate identifiers |
| HTTP completion | 3,000 succeeded; each original ID and row position present exactly once |
| Ground truth | All seven fields checked against deterministic demo registry values |
| Source requests | {source_requests:,}, counted in demo-source access logs by unique run prefix |
| Attempts | Every HTTP row has exactly one committed attempt |
| Elapsed | {elapsed:.2f} s from {elapsed_basis} |
| Observed throughput | {3000 / elapsed:.2f} original rows/s over that measured interval |
| Worker memory | {len(memory.samples)} Docker samples; min {min(memory.samples):.2f} MiB; median {statistics.median(memory.samples):.2f} MiB; sampled max {max(memory.samples):.2f} MiB |
| CSV and XLSX | Both exports checked for all 3,000 originals, order, statuses and seven output fields |
| Actual crash | SIGKILL of the resolved Compose worker, confirmed stopped, same container restarted |
| Recovery | {preserved} completed rows unchanged; {expired} interrupted attempt(s) closed as lease_expired |
| Recovery duration | {recovery_seconds:.2f} s from kill through task completion |
| Real browser | Container Chromium filled calculator form and matched all seven expected fields |

The crash task deliberately includes two TIMEOUT identifiers (20 s source delay vs
10 s HTTP timeout). These exhaust the configured retry budget and correctly finish
as failed; all 18 normal rows succeed. Its expected terminal state is
completed_with_errors. Recovery uses the deployment's configured lease duration.

Docker memory values are the worker container's `docker stats --no-stream` samples,
not a process RSS peak or continuous maximum; short spikes can fall between samples.
Memory sampling covers only this script invocation; resumed observation: {bool(resume)}.
This is a local controlled-source measurement, not an external-service SLA or a
claim about 3,000 browser rows. Verification API requests: {api.requests}.
Other Docker activity, including image builds, can compete for shared host resources;
this script does not require or establish an otherwise idle benchmark host.
Synthetic tasks remain available for inspection; the script does not delete data.

- HTTP task: `{task_id}`
- Crash task: `{crash_id}`
- Chromium task: `{browser_id}`
"""
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(report, encoding="utf-8")
    print(f"PASS: report written to {REPORT.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
