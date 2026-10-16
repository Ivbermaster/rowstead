# Architecture and operations

FastAPI handles authenticated import/task/control/export requests. PostgreSQL holds
immutable imported data, task config snapshots, individual rows, attempts and audit
events. An independent worker commits a row lease before external I/O. Each claim
has a unique fencing token. Heartbeats renew the lease; finalization checks token
and expiry. Task and row locks are acquired in that order to serialize controls.
After a crash, maintenance closes unfinished attempts and reclaims expired rows.
Successful rows are never reprocessed during recovery.

PostgreSQL supports concurrent workers with SKIP LOCKED; SQLite deliberately runs
one worker thread and is for local demos only. Do not start multiple SQLite workers.
Pause/cancel stop new claims and drain current requests; retry-wait rows are retained
in exports. Auth/config failures block a task instead of failing all remaining rows.

The included sources perform reads and deterministic calculations only. An operator
sets one trusted DEMO_BASE_URL origin. Identifier validation excludes URLs; HTTP
redirects are rejected, Playwright blocks off-origin requests and service workers.
Compose keeps the database, demo source and worker on an internal network. Only API
also joins a separate ingress bridge and publishes 127.0.0.1:8000; publishing from
an internal-only network was confirmed ineffective on Docker Engine 28.3.
See [Compose networking](https://docs.docker.com/compose/how-tos/networking/) for
internal network behavior. Generic allowlists, DNS rebinding protection and
arbitrary source adapters are not implemented and must precede such an extension.

## Add an adapter

Implement validate_config, validate_row, execute, normalize_result, plus version and
fields. Raise AdapterError with transient/missing/invalid/login_required/blocked/
permanent kind, a stable code and safe text. Never store raw upstream exceptions.
Register in app/adapters/__init__.py, add source field metadata and validation in
app/main.py, and test retry/error/normalization paths. Snapshot adapter version when
creating a task. The first version supports only the two bundled demo adapters.

## Recovery

- Worker crash: restart `python -m app.worker`; expired claims recover after
  LEASE_SECONDS. Keep lease duration comfortably above database interruptions.
- Blocked task: inspect blocked_reason, fix the source/browser installation, resume.
- Source 429: row waits for Retry-After (bounded to one hour), then retries.
- Export: available during execution, pause and cancellation. Each source row remains.
- Schema change: stop API/worker, back up DB and files, apply Alembic upgrade, restart.
- Backup: `pg_dump` plus the `files` volume, taken while writes are paused. Restore
  into a separate database/volume and verify row counts before switching services.
- Rehearsal: `python scripts/verify_backup.py` writes a custom dump and a copy of
  original input files under ignored `artifacts/backup-check/`. It restores to a
  randomly named verification database, compares ordered digests for every table
  and original file SHA-256, and removes only that verification database. Run with
  no active rows and no concurrent imports/task changes. See its report.json.
- Local data removal or retention cleanup is manual. No automatic deletion runs.

## Boundaries

This version uses 12-hour signed sessions. It has no password reset UI, rate limiting,
MFA, secret rotation UI, health check for worker liveness, automatic backups or
artifact TTL job. Public deployment needs HTTPS, COOKIE_SECURE=true, ingress rate
limits and a reviewed operational setup. Never expose the demo server publicly.
No browser session is persisted and no error screenshot is captured, so there are
no browser secrets or screenshot artifacts to encrypt/redact at this stage.
