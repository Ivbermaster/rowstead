import logging
import random
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, or_, select, update

from app.adapters import ADAPTERS, AdapterError
from app.config import settings
from app.db import SessionLocal
from app.models import Attempt, Row, Task, utcnow

logger = logging.getLogger(__name__)
ACTIVE_ROWS = ("pending", "running", "retry_wait")


def retry_delay(attempt, retry_after=None):
    return max(min(300, 2 ** max(0, attempt - 1)) + random.uniform(0, 0.5), retry_after or 0)


def _settle_task(session, task):
    counts = dict(
        session.execute(
            select(Row.status, func.count()).where(Row.task_id == task.id).group_by(Row.status)
        ).all()
    )
    if counts.get("running", 0):
        return
    if task.status == "pause_requested":
        task.status = "paused"
    elif task.status == "cancel_requested":
        task.status = "cancelled"
        task.finished_at = utcnow()
    elif task.status in {"queued", "running"} and not any(
        counts.get(status, 0) for status in ACTIVE_ROWS
    ):
        task.status = (
            "completed_with_errors"
            if any(counts.get(status, 0) for status in ("missing", "invalid", "failed"))
            else "completed"
        )
        task.finished_at = utcnow()


def maintain_tasks():
    """Recover abandoned rows, then settle idle pause/cancel/completion requests."""
    changed = False
    with SessionLocal() as session:
        ids = session.scalars(
            select(Task.id).where(
                Task.status.in_(
                    ("queued", "running", "pause_requested", "cancel_requested", "blocked")
                )
            )
        ).all()
    for task_id in ids:
        with SessionLocal.begin() as session:
            task = session.scalar(
                select(Task).where(Task.id == task_id).with_for_update(skip_locked=True)
            )
            if task is None:
                continue
            now = utcnow()
            expired = session.scalars(
                select(Row)
                .where(
                    Row.task_id == task.id,
                    Row.status == "running",
                    or_(Row.lease_until < now, Row.lease_until.is_(None)),
                )
                .with_for_update(skip_locked=True)
            ).all()
            for row in expired:
                for attempt in session.scalars(
                    select(Attempt).where(Attempt.row_id == row.id, Attempt.finished_at.is_(None))
                ):
                    attempt.finished_at = now
                    attempt.error_code = "lease_expired"
                    attempt.redacted_message = "Worker lease expired before completion."
                    attempt.duration_ms = int((now - attempt.started_at).total_seconds() * 1000)
                row.status = "failed" if row.attempt_count >= settings.max_attempts else "pending"
                row.error_code = "lease_expired"
                row.error_message = "Worker lease expired before completion."
                row.worker_id = None
                row.lease_until = None
                changed = True
            session.flush()
            previous = task.status
            _settle_task(session, task)
            changed = changed or task.status != previous
    return changed


def claim_row():
    """Commit the claim and its attempt before making any source request."""
    with SessionLocal() as session:
        candidates = session.scalars(
            select(Task.id).where(Task.status.in_(("queued", "running"))).order_by(Task.created_at)
        ).all()
    for task_id in candidates:
        with SessionLocal.begin() as session:
            task = session.scalar(
                select(Task)
                .where(Task.id == task_id, Task.status.in_(("queued", "running")))
                .with_for_update(skip_locked=True)
            )
            if task is None:
                continue
            now = utcnow()
            row = session.scalar(
                select(Row)
                .where(
                    Row.task_id == task_id,
                    or_(
                        Row.status == "pending",
                        (Row.status == "retry_wait") & (Row.next_attempt_at <= now),
                    ),
                )
                .order_by(Row.row_number)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                continue
            token = str(uuid4())
            row.worker_id = token
            row.lease_until = now + timedelta(seconds=settings.lease_seconds)
            row.status = "running"
            row.attempt_count += 1
            row.next_attempt_at = None
            task.status = "running"
            if task.started_at is None:
                task.started_at = now
            attempt_id = str(uuid4())
            session.add(Attempt(id=attempt_id, row_id=row.id, started_at=now))
            return {
                "row_id": row.id,
                "task_id": task.id,
                "token": token,
                "attempt_id": attempt_id,
                "attempt": row.attempt_count,
                "input": dict(row.input_json),
                "config": dict(task.config_json),
                "adapter": task.adapter,
            }
    return None


def heartbeat(claim, stopped):
    interval = max(0.1, settings.lease_seconds / 3)
    while not stopped.wait(interval):
        try:
            with SessionLocal.begin() as session:
                now = utcnow()
                result = session.execute(
                    update(Row)
                    .where(
                        Row.id == claim["row_id"],
                        Row.worker_id == claim["token"],
                        Row.status == "running",
                        Row.lease_until > now,
                    )
                    .values(lease_until=now + timedelta(seconds=settings.lease_seconds))
                )
                if not result.rowcount:
                    return
        except Exception:
            logger.exception(
                "heartbeat_failed", extra={"task_id": claim["task_id"], "row_id": claim["row_id"]}
            )
            return


def finalize_claim(claim, output=None, error=None):
    with SessionLocal.begin() as session:
        task = session.scalar(select(Task).where(Task.id == claim["task_id"]).with_for_update())
        row = session.scalar(select(Row).where(Row.id == claim["row_id"]).with_for_update())
        now = utcnow()
        if (
            row is None
            or row.worker_id != claim["token"]
            or row.status != "running"
            or row.lease_until is None
            or row.lease_until <= now
        ):
            return False
        attempt = session.get(Attempt, claim["attempt_id"])
        attempt.finished_at = now
        attempt.duration_ms = max(0, int((now - attempt.started_at).total_seconds() * 1000))
        row.worker_id = None
        row.lease_until = None
        if error is None:
            row.status = "succeeded"
            row.output_json = output or {}
            row.error_code = None
            row.error_message = None
        else:
            row.error_code = attempt.error_code = error.code
            row.error_message = attempt.redacted_message = error.message
            if error.kind == "transient" and row.attempt_count < settings.max_attempts:
                row.status = "retry_wait"
                row.next_attempt_at = now + timedelta(
                    seconds=retry_delay(row.attempt_count, error.retry_after)
                )
            elif error.kind in {"blocked", "login_required"}:
                row.status = "pending"
                if task.status not in {"cancel_requested", "cancelled"}:
                    task.status = "blocked"
                    task.blocked_reason = error.code
            else:
                row.status = error.kind if error.kind in {"missing", "invalid"} else "failed"
        session.flush()
        _settle_task(session, task)
    return True


def run_once():
    changed = maintain_tasks()
    claim = claim_row()
    if claim is None:
        return changed
    stopped = threading.Event()
    thread = threading.Thread(target=heartbeat, args=(claim, stopped), daemon=True)
    thread.start()
    output, error = None, None
    try:
        adapter = ADAPTERS.get(claim["adapter"])
        if adapter is None:
            raise AdapterError(
                "blocked", "unknown_adapter", "The configured adapter is unavailable."
            )
        config = {**claim["config"], "_attempt": claim["attempt"]}
        mapping = config.get("mapping", {})
        data = {field: claim["input"].get(column) for field, column in mapping.items() if column}
        adapter.validate_config(config)
        adapter.validate_row(data)
        output = adapter.normalize_result(adapter.execute(data, config))
    except AdapterError as exc:
        error = exc
    except Exception:
        # Never persist raw exception text: upstream URLs or credentials may appear in it.
        logger.error(
            "adapter_execution_failed",
            extra={"task_id": claim["task_id"], "row_id": claim["row_id"]},
        )
        error = AdapterError(
            "permanent",
            "internal_adapter_error",
            "Adapter execution failed unexpectedly. Check worker logs.",
        )
    finally:
        stopped.set()
        thread.join(timeout=5)
    finalize_claim(claim, output, error)
    logger.info(
        "row_processed",
        extra={
            "task_id": claim["task_id"],
            "row_id": claim["row_id"],
            "status": error.kind if error else "succeeded",
        },
    )
    return True


def run_forever():
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                if not run_once():
                    stop.wait(settings.worker_poll_seconds)
            except Exception:
                logger.exception("worker_iteration_failed")
                stop.wait(settings.worker_poll_seconds)

    workers = (
        1
        if str(settings.database_url).startswith("sqlite")
        else max(1, settings.worker_concurrency)
    )
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(loop) for _ in range(workers)]
        try:
            for future in futures:
                future.result()
        except KeyboardInterrupt:
            stop.set()
