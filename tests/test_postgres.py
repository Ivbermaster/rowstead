"""Real PostgreSQL locking and recovery regressions, isolated in temporary schemas."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from app.adapters import AdapterError
from app.db import Base
from app.models import Attempt, ImportFile, Row, Task, User, utcnow
from app.worker import runner


@pytest.fixture
def postgres_db(monkeypatch):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL for PostgreSQL integration")
    schema = f"batchflow_test_{uuid4().hex}"
    engine = create_engine(url).execution_options(schema_translate_map={None: schema})
    if engine.dialect.name != "postgresql":
        engine.dispose()
        pytest.skip("TEST_DATABASE_URL must use PostgreSQL")
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        Base.metadata.create_all(engine)
        factory = sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(runner, "SessionLocal", factory)
        with factory.begin() as session:
            session.add(User(id="user", login="postgres-test", password_hash="unused"))
            session.flush()
            session.add(
                ImportFile(
                    id="import", owner_id="user", original_name="test.csv",
                    storage_key="unused", sha256="0" * 64, headers=["id"], rows_json=[],
                )
            )
            session.flush()
            session.add(
                Task(
                    id="task", owner_id="user", import_id="import", name="Postgres test",
                    adapter="test", status="queued", config_json={},
                )
            )
            session.flush()
            session.add_all(
                Row(id=f"row-{i}", task_id="task", row_number=i, input_json={"id": str(i)})
                for i in (1, 2)
            )
        yield factory
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


class OneHeartbeat:
    def __init__(self):
        self.calls = 0

    def wait(self, interval):
        self.calls += 1
        return self.calls > 1


@pytest.mark.parametrize("requested,settled", [
    ("pause_requested", "paused"), ("cancel_requested", "cancelled"),
])
def test_control_lock_stops_claims_and_drains_current_row(postgres_db, requested, settled):
    claim = runner.claim_row()
    # Match the API's task-first lock: an uncommitted control must exclude claims.
    with postgres_db.begin() as session:
        task = session.scalar(select(Task).where(Task.id == "task").with_for_update())
        task.status = requested
        session.flush()
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(runner.claim_row).result(timeout=10) is None
    assert runner.claim_row() is None
    runner.maintain_tasks()
    with postgres_db() as session:
        assert session.get(Task, "task").status == requested
    assert runner.finalize_claim(claim, {"done": True})
    with postgres_db() as session:
        assert session.get(Task, "task").status == settled
        untouched = session.get(Row, "row-2")
        assert untouched.status == "pending"
        assert untouched.attempt_count == 0


def test_expired_owner_cannot_heartbeat_or_overwrite_reclaimed_result(postgres_db):
    old = runner.claim_row()
    expired_at = utcnow() - timedelta(seconds=1)
    with postgres_db.begin() as session:
        session.get(Row, old["row_id"]).lease_until = expired_at
    runner.heartbeat(old, OneHeartbeat())
    with postgres_db() as session:
        assert session.get(Row, old["row_id"]).lease_until == expired_at
    assert not runner.finalize_claim(old, {"stale": True})
    assert runner.maintain_tasks()
    fresh = runner.claim_row()
    assert fresh["row_id"] == old["row_id"]
    assert fresh["token"] != old["token"]
    with postgres_db() as session:
        lease = session.get(Row, fresh["row_id"]).lease_until
    runner.heartbeat(old, OneHeartbeat())
    with postgres_db() as session:
        assert session.get(Row, fresh["row_id"]).lease_until == lease
    assert runner.finalize_claim(fresh, {"fresh": True})
    assert not runner.finalize_claim(old, {"stale": True})
    with postgres_db() as session:
        assert session.get(Row, old["row_id"]).output_json == {"fresh": True}
        attempt = session.get(Attempt, old["attempt_id"])
        assert attempt.error_code == "lease_expired"
        assert attempt.finished_at is not None


def test_recovery_and_expired_finalization_cannot_resurrect_old_claim(postgres_db):
    claim = runner.claim_row()
    with postgres_db.begin() as session:
        session.get(Row, claim["row_id"]).lease_until = utcnow() - timedelta(seconds=1)
    barrier = threading.Barrier(2)

    def recover():
        barrier.wait(timeout=10)
        return runner.maintain_tasks()

    def finish():
        barrier.wait(timeout=10)
        return runner.finalize_claim(claim, {"stale": True})

    with ThreadPoolExecutor(max_workers=2) as pool:
        recovery = pool.submit(recover)
        finalization = pool.submit(finish)
        assert finalization.result(timeout=10) is False
        recovery.result(timeout=10)
    # Recovery uses SKIP LOCKED and may lose this round to the finalizer's task lock.
    runner.maintain_tasks()
    fresh = runner.claim_row()
    assert fresh["row_id"] == claim["row_id"]
    assert runner.finalize_claim(fresh, {"fresh": True})
    with postgres_db() as session:
        assert session.get(Row, claim["row_id"]).output_json == {"fresh": True}
        attempts = session.scalars(select(Attempt).where(Attempt.row_id == claim["row_id"])).all()
        assert len(attempts) == 2
        assert all(attempt.finished_at is not None for attempt in attempts)


@pytest.mark.parametrize("with_error", [False, True])
def test_concurrent_last_rows_settle_task_once(postgres_db, with_error):
    claims = [runner.claim_row(), runner.claim_row()]
    barrier = threading.Barrier(2)

    def finish(index):
        barrier.wait(timeout=10)
        error = AdapterError("permanent", "failed_test", "Controlled failure")
        return runner.finalize_claim(
            claims[index], {"row": index}, error if with_error and index == 1 else None,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(finish, range(2)))
    assert results == [True, True]
    assert runner.claim_row() is None
    with postgres_db() as session:
        task = session.get(Task, "task")
        assert task.status == ("completed_with_errors" if with_error else "completed")
        assert task.finished_at is not None
        assert all(attempt.finished_at for attempt in session.scalars(select(Attempt)))
