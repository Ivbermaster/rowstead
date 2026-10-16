import os
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
def worker_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'worker.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(runner, "SessionLocal", factory)
    with factory.begin() as session:
        session.add(User(id="user", login="worker-test", password_hash="unused"))
        session.add(
            ImportFile(
                id="import",
                owner_id="user",
                original_name="test.csv",
                storage_key="unused",
                sha256="0" * 64,
                headers=["id"],
                rows_json=[],
            )
        )
        session.add(
            Task(
                id="task",
                owner_id="user",
                import_id="import",
                name="Test",
                adapter="test",
                status="queued",
                config_json={"mapping": {"identifier": "id"}},
            )
        )
        session.add_all(
            [
                Row(id=f"row-{i}", task_id="task", row_number=i, input_json={"id": f"BF-{i}"})
                for i in range(1, 3)
            ]
        )
    yield factory
    engine.dispose()


class FakeAdapter:
    def validate_config(self, config):
        pass

    def validate_row(self, data):
        pass

    def execute(self, data, config):
        return {"identifier": data["identifier"]}

    def normalize_result(self, result):
        return result


def test_success_preserves_mapping_and_finishes_task(worker_db, monkeypatch):
    monkeypatch.setitem(runner.ADAPTERS, "test", FakeAdapter())
    assert runner.run_once()
    assert runner.run_once()
    assert not runner.run_once()
    with worker_db() as session:
        assert session.get(Task, "task").status == "completed"
        assert session.get(Row, "row-1").output_json == {"identifier": "BF-1"}
        attempts = session.scalars(select(Attempt)).all()
        assert len(attempts) == 2
        assert all(a.finished_at and a.error_code is None for a in attempts)


def test_retry_after_and_attempt_exhaustion(worker_db, monkeypatch):
    class Failing(FakeAdapter):
        def execute(self, data, config):
            raise AdapterError("transient", "rate_limited", "Try later", retry_after=20)

    monkeypatch.setitem(runner.ADAPTERS, "test", Failing())
    before = utcnow()
    assert runner.run_once()
    with worker_db.begin() as session:
        row = session.get(Row, "row-1")
        assert row.status == "retry_wait"
        assert row.next_attempt_at >= before + timedelta(seconds=20)
        row.next_attempt_at = before - timedelta(seconds=1)
        row.attempt_count = runner.settings.max_attempts - 1
    assert runner.run_once()
    with worker_db() as session:
        assert session.get(Row, "row-1").status == "failed"


def test_expired_claim_recovered_and_old_worker_fenced(worker_db):
    old = runner.claim_row()
    with worker_db.begin() as session:
        session.get(Row, old["row_id"]).lease_until = utcnow() - timedelta(seconds=1)
    assert runner.maintain_tasks()
    new = runner.claim_row()
    assert new["row_id"] == old["row_id"]
    assert new["token"] != old["token"]
    assert not runner.finalize_claim(old, {"stale": True})
    assert runner.finalize_claim(new, {"fresh": True})
    with worker_db() as session:
        assert session.get(Row, old["row_id"]).output_json == {"fresh": True}
        assert session.get(Attempt, old["attempt_id"]).error_code == "lease_expired"


def test_expired_claim_cannot_write_before_recovery(worker_db):
    claim = runner.claim_row()
    with worker_db.begin() as session:
        session.get(Row, claim["row_id"]).lease_until = utcnow() - timedelta(seconds=1)
    assert not runner.finalize_claim(claim, {"expired": True})
    with worker_db() as session:
        assert session.get(Row, claim["row_id"]).output_json == {}


def test_heartbeat_renews_only_current_owner(worker_db):
    claim = runner.claim_row()
    with worker_db.begin() as session:
        row = session.get(Row, claim["row_id"])
        row.lease_until = utcnow() + timedelta(seconds=5)

    class OneBeat:
        calls = 0

        def wait(self, interval):
            self.calls += 1
            return self.calls > 1

    runner.heartbeat(claim, OneBeat())
    with worker_db() as session:
        assert session.get(Row, claim["row_id"]).lease_until > utcnow() + timedelta(seconds=10)
    with worker_db.begin() as session:
        row = session.get(Row, claim["row_id"])
        row.worker_id = "different-owner"
        preserved = row.lease_until
    runner.heartbeat(claim, OneBeat())
    with worker_db() as session:
        assert session.get(Row, claim["row_id"]).lease_until == preserved


@pytest.mark.parametrize(
    "requested,settled", [("pause_requested", "paused"), ("cancel_requested", "cancelled")]
)
def test_stop_claiming_and_finish_current_row(worker_db, requested, settled):
    claim = runner.claim_row()
    with worker_db.begin() as session:
        session.get(Task, "task").status = requested
    assert runner.claim_row() is None
    runner.maintain_tasks()
    with worker_db() as session:
        assert session.get(Task, "task").status == requested
    runner.finalize_claim(claim, {"done": True})
    with worker_db() as session:
        assert session.get(Task, "task").status == settled
        assert session.get(Row, "row-2").status == "pending"


def test_authorization_failure_blocks_task_without_failing_all_rows(worker_db, monkeypatch):
    class LoginRequired(FakeAdapter):
        def execute(self, data, config):
            raise AdapterError("login_required", "login_required", "Refresh the source session.")

    monkeypatch.setitem(runner.ADAPTERS, "test", LoginRequired())
    assert runner.run_once()
    assert not runner.run_once()
    with worker_db() as session:
        assert session.get(Task, "task").status == "blocked"
        assert session.get(Task, "task").blocked_reason == "login_required"
        assert session.get(Row, "row-1").status == "pending"
        assert session.get(Row, "row-2").attempt_count == 0


def test_lease_exhaustion_finalizes_task(worker_db):
    with worker_db.begin() as session:
        session.get(Row, "row-2").status = "succeeded"
    claim = runner.claim_row()
    with worker_db.begin() as session:
        row = session.get(Row, claim["row_id"])
        row.attempt_count = runner.settings.max_attempts
        row.lease_until = utcnow() - timedelta(seconds=1)
    assert runner.maintain_tasks()
    with worker_db() as session:
        assert session.get(Row, claim["row_id"]).status == "failed"
        assert session.get(Task, "task").status == "completed_with_errors"


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Set TEST_DATABASE_URL for PostgreSQL integration"
)
def test_postgres_concurrent_claims_are_unique(monkeypatch):
    """Use a temporary schema; never clear application tables in the supplied database."""
    schema = f"batchflow_test_{uuid4().hex}"
    engine = create_engine(os.environ["TEST_DATABASE_URL"]).execution_options(
        schema_translate_map={None: schema}
    )
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
            session.add(User(id="user", login="pg-worker-test", password_hash="unused"))
            session.flush()
            session.add(
                ImportFile(
                    id="import",
                    owner_id="user",
                    original_name="test.csv",
                    storage_key="unused",
                    sha256="0" * 64,
                    headers=["id"],
                    rows_json=[],
                )
            )
            session.flush()
            session.add(
                Task(
                    id="task",
                    owner_id="user",
                    import_id="import",
                    name="Concurrent test",
                    adapter="test",
                    status="queued",
                    config_json={"mapping": {"identifier": "id"}},
                )
            )
            session.flush()
            session.add_all(
                Row(id=f"row-{i}", task_id="task", row_number=i, input_json={"id": str(i)})
                for i in range(20)
            )

        def claim_available():
            claims = []
            while claim := runner.claim_row():
                claims.append(claim)
            return claims

        with ThreadPoolExecutor(max_workers=4) as pool:
            claims = [
                claim
                for batch in pool.map(lambda _: claim_available(), range(4))
                for claim in batch
            ]
        assert len(claims) == 20
        assert len({claim["row_id"] for claim in claims}) == 20
        assert len({claim["token"] for claim in claims}) == 20
    finally:
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()
