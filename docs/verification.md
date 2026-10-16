# Verification — 2026-10-15

Environment: Windows, Python 3.11.3, local project virtual environment;
Docker Engine 28.3, Linux containers with Python 3.12.15 and PostgreSQL 17.11.
Playwright 1.64.0 with bundled Chromium 156.0.8078.4. Tested dependency versions
are recorded in `requirements.lock`; the application targets Python 3.11+.

## Executed

| Check | Result |
|---|---|
| Ruff | All checks passed |
| Host regular pytest suite | 70 passed, 8 skipped (PG + browser opt-in) |
| Full suite inside Compose / PostgreSQL | 77 passed, 1 skipped (browser opt-in), 55.06s |
| Real browser E2E, explicitly enabled | 1 passed (final UI run 52.72s) |
| Alembic upgrade on SQLite and PostgreSQL | Passed |
| Alembic schema drift check, including final container | No new upgrade operations detected |
| Docker build / Compose startup | Passed; final image runs all app services |
| Host access | 127.0.0.1:8000 ready; DB/source/worker stay on private network |
| Compose config validation | Passed with actual ignored .env |
| JavaScript syntax | `node --check app/static/app.js` passed |
| Live HTTP batch | 3,000 succeeded; duplicates, order, all fields and both exports checked |
| Actual SIGKILL / restart | Passed; committed results preserved and expired attempts recovered |
| Container Chromium | Seven calculator fields matched ground truth |
| PostgreSQL backup / restore | All 7 tables and original file SHA-256 matched |

The seven host PostgreSQL skips were enabled and passed inside Compose, including
claim uniqueness, pause/cancel locks, heartbeat expiry and concurrent fencing/finalization.
The browser test was separately enabled and passed.
Starlette emits one deprecation warning about using httpx in TestClient; current
test execution succeeds. Windows sandbox socket restrictions required running
network-dependent tests with loopback access outside that sandbox.

Files tests cover malformed CSV/XLSX, ZIP expansion limits, DTD/entities, formula
rejection and export escaping, duplicate headers/columns, sheet selection,
CSV delimiters, column collisions, duplicate rows and 3,000-row import/export
preservation. The separate live Compose batch now covers the complete HTTP worker path.

Worker tests cover committed claims, retries/exhaustion, Retry-After, heartbeat,
expired leases, stale writer rejection, source blocking and pause/cancel draining.
These unit/integration checks simulate expiry; the live runtime harness additionally
performed an actual SIGKILL and restarted the same worker container.
API tests exercise owner isolation, CSRF, task transitions, attempt history,
partial export, healthy startup and the full pipeline with a deterministic adapter.

Real browser E2E starts independent API, source and worker subprocesses with isolated
SQLite data. It signs in, uploads a sample, maps columns, pauses/resumes, observes
retry/missing results, opens attempt history and downloads CSV. It also runs the
actual Playwright browser adapter and downloads its XLSX result. Desktop and mobile
screenshots were inspected; no JS errors or mobile document overflow were found.
Final UI adds readable field summaries, larger text/contrast, mobile row cards,
accessible processed counters and mobile sign out / sign in coverage.

Screenshots (generated locally, ignored by Git):
`artifacts/login-desktop.png`, `import-desktop.png`, `task-desktop.png`,
`task-mobile.png`, `browser-task-desktop.png`.

## Live batch and crash evidence

See [runtime report](runtime-report.md) for task IDs, checks and measurement scope.
The real 3,000-row batch included 600 duplicate identifiers and completed in
601.91s with exactly 3,000 source requests. All original row positions and seven
result fields were checked in the API and both CSV/XLSX exports. Worker sampled
memory ranged 46.45–108.70 MiB (135 Docker samples, median 58.74 MiB).
The shared Docker host was concurrently building/exporting an image; these numbers
are observations of that run, not an isolated capacity estimate.

After SIGKILL, recovery finished in 35.80s. Ten already completed rows were unchanged,
two abandoned attempts were closed as lease_expired, and all 18 ordinary rows
succeeded. Two intentionally slow source records exhausted their timeout/retry
budget and correctly remained failed. This verifies preservation and recovery,
including explicit partial failure rather than claiming universal success.

## Backup rehearsal

`python scripts/verify_backup.py` passed on the completed runtime dataset:
1 user, 3 imports, 3 tasks, 3,021 rows, 3,025 attempts, 6 audit events and 1 migration
version. A 381,640-byte PostgreSQL custom dump was restored to a fresh disposable
database. Ordered content digests of all seven tables matched, and all three
original input files matched their SHA-256. The disposable database was removed;
the live database/files remained. Evidence is ignored `artifacts/backup-check/report.json`.
This snapshot precedes any extra task created by the final UI walkthrough.

## Final Compose UI capture

The final shared image was deployed and `python scripts/capture_demo.py` executed
against localhost's actual PostgreSQL/API/worker stack. Its three-row calculator
task completed, row attempt history opened, XLSX downloaded, and mobile overflow
was checked. Desktop/mobile screenshots were visually inspected and copied to
`docs/screenshots/`. A 2,718,025-byte silent `walkthrough.webm` is available locally
under `artifacts/compose-demo/`; it records UI interaction after API authentication.
The four completed synthetic tasks remain available in the running demo panel.

## Reproduce

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -q
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\data\browsers"
$env:BATCHFLOW_E2E = "1"
.\.venv\Scripts\python.exe -m pytest -q tests/test_ui_e2e.py --basetemp=artifacts/pytest-e2e
.\.venv\Scripts\python.exe scripts/test_postgres.py
.\.venv\Scripts\python.exe scripts/verify_runtime.py
.\.venv\Scripts\python.exe scripts/verify_backup.py
```

Set TEST_DATABASE_URL to a dedicated PostgreSQL test database to enable concurrent
claims verification on the host, or use the container helper to keep the DB private.
PostgreSQL tests create and remove only their unique temporary schemas.
CI is configured for PostgreSQL migrations, concurrent claims, browser E2E and image
builds, but no hosted CI run has occurred in this local workspace.

## Not verified yet

- A 3,000-row browser batch (HTTP batch and small real browser cases are verified).
- Long-duration stress, off-site recovery and public deployment.
- Hosted CI runs and binary/container notice review before publishing.

No production speed, scale or deployment readiness is claimed by these checks.

## UI and GitHub preparation — 2026-10-16

These checks apply to the revised three-step import UI, server-side task search,
issue-only row filter, offline API reference and publication helpers:

- Local non-browser suite: **83 passed, 8 skipped** (19.60 s). Skips are seven
  PostgreSQL tests and the opt-in Chromium test; one upstream Starlette/httpx
  deprecation warning remains.
- Separate real Chromium E2E: **1 passed** (38.97 s). Covered CSV and two-sheet
  XLSX mapping, review/edit, sample scenarios, start failure/retry without a second
  task, pause/resume, issues, search, exports, public API reference and 320 px UI.
- Ruff and JavaScript syntax checks passed.
- Final API-only rerun after endpoint-reference filtering: **7 passed** (26.79 s).
- Wheel built successfully; MIT chosen by the owner. Dependency metadata and
  reproduction commands are in [dependencies](dependencies.md).
- Publication preflight checks public working files, staged blobs and HEAD paths;
  it deliberately excludes local secrets/runtime material. It is a heuristic
  guard, not a guarantee about all possible secrets or historical commits.
- Public file staging was checked separately: 80 working/index paths, no HEAD
  commit yet; preflight and `git diff --cached --check` passed. Local `.env`,
  runtime directories, original planning notes and internal audit stay ignored.

Docker Desktop initially had no Engine pipe, then started successfully after a
delay. The revised image built, Compose migrations completed and services became
healthy. The updated runtime suite in Compose/PostgreSQL passed: **80 passed,
1 skipped** (26.06 s); the skip is the separate opt-in browser test. Publication
guard tests run in the source checkout/CI because the runtime image contains no
Git or release tooling. The helper was corrected after an initial collection
failure exposed that distinction. The longer 2026-10-15 HTTP/recovery/backup
measurements above were not repeated. Hosted GitHub Actions have not run and the
repository has not been published.

The revised UI was captured first on an isolated SQLite/API/demo/worker stack;
its temporary processes were stopped. After Docker became available, the updated
`scripts/capture_demo.py` completed again against the new Compose image and
PostgreSQL: three real Chromium calculations succeeded, attempt history opened,
XLSX downloaded and mobile overflow was checked. The four public screenshots were
replaced with this final Compose capture and visually inspected. The current
local WebM and XLSX are under ignored `artifacts/compose-demo/`. The revised demo
is left running on localhost:8000.

A clean source copy of only the 80 public files also passed SQLite migrations,
schema drift and **83 tests** with 8 expected PostgreSQL/browser skips (36.58 s).
It contained no `.env`, used a sanitized environment and generated session key,
and disabled dotenv loading. This reused the existing dependency environment;
it was not a fresh dependency installation. The check exposed a missing parent
directory for pytest's configured temporary path; `tests/conftest.py` now creates
that project-local parent automatically.

The final wheel's MIT metadata/LICENSE and application assets match the source.
A separate `pip --target --no-deps` install loaded the real login page, CSS and
sample generator successfully. Details are local ignored
`artifacts/release-smoke/report.json`.

## Rowstead rename and release checks — 2026-10-16

The public product, interface, Python distribution and export filenames are now
**Rowstead**. Existing technical namespaces stay compatible with the local demo;
see [development](development.md#existing-local-demo-compatibility).

- Ruff and browser JavaScript syntax passed.
- Full local suite: **83 passed, 8 skipped** (59.59 s).
- Real Chromium E2E with the Rowstead UI: **1 passed** (122.91 s), including
  CSV/XLSX import, review, controls, browser calculations and 320 px layout.
- New Docker image built and deployed with existing database/file volumes.
- Compose/PostgreSQL runtime suite: **80 passed, 1 skipped** (63.39 s).
- Four public screenshots refreshed from the actual Rowstead Compose UI and
  visually checked. The capture for this release did not record video.

The longer batch/recovery/backup measurements above remain the original dated
evidence. Local recordings and other runtime files are excluded from the release.
Hosted CI results follow below.

## Public release — 2026-10-16

Published [Rowstead v0.1.0](https://github.com/Ivbermaster/rowstead/releases/tag/v0.1.0)
from commit `57e2ffaa51c626e5de0d148acfec6d13e12f1ce6`.
The first hosted [GitHub Actions run](https://github.com/Ivbermaster/rowstead/actions/runs/38906034190)
completed successfully:

- Publication preflight and Ruff passed.
- SQLite and PostgreSQL migrations/model drift passed.
- **90 tests passed, 1 skipped** (7.49 s); the skip is the separately run browser test.
- Actual Chromium E2E: **1 passed** (31.29 s).
- Container build and packaged application imports passed.

The release contains source and synthetic screenshots. Videos, databases, uploads,
backups, local environment files and internal notes are excluded. Earlier mentions
of unpublished state in this report describe the checkpoints before this release.
