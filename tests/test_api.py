import csv
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.auth import hash_password
from app.config import settings
from app.db import Base, get_db
from app.main import app
from app.models import AuditEvent, Row, Task, User, utcnow
from app.services.files import parse_file
from app.worker import runner


@pytest.fixture
def api(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'api.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(
        settings, "session_secret", "test-only-session-secret-at-least-32-characters"
    )
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    monkeypatch.setattr(runner, "SessionLocal", factory)
    with factory.begin() as db:
        db.add(User(login="admin", password_hash=hash_password("test-only-password")))
        db.add(User(login="other", password_hash=hash_password("test-only-password")))

    def override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login", json={"login": "admin", "password": "test-only-password"}
        )
        assert response.status_code == 200
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        yield client, factory
    app.dependency_overrides.clear()
    engine.dispose()


def make_task(client, content=b"id,note\nBF-0001,first\nBF-0001,duplicate\nMISSING,absent\n"):
    response = client.post("/api/v1/imports", files={"file": ("input.csv", content, "text/csv")})
    assert response.status_code == 201, response.text
    imported = response.json()
    assert imported["row_count"] == 3
    response = client.post(
        "/api/v1/tasks",
        json={
            "name": "Registry enrichment",
            "import_id": imported["id"],
            "adapter": "registry_demo",
            "mapping": {"identifier": "id"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_full_pipeline_and_export_snapshot(api, monkeypatch):
    client, factory = api

    class DemoAdapter:
        def validate_config(self, config):
            pass

        def validate_row(self, data):
            pass

        def execute(self, data, config):
            if data["identifier"] == "MISSING":
                from app.adapters import AdapterError

                raise AdapterError("missing", "not_found", "No record")
            return {"company_name": "Example", "formula": "=1+1"}

        def normalize_result(self, result):
            return result

    monkeypatch.setitem(runner.ADAPTERS, "registry_demo", DemoAdapter())
    task = make_task(client)
    task_id = task["id"]
    assert client.post(f"/api/v1/tasks/{task_id}/start").status_code == 202
    for _ in range(3):
        assert runner.run_once()
    detail = client.get(f"/api/v1/tasks/{task_id}").json()
    assert detail["status"] == "completed_with_errors"
    assert detail["counts"]["succeeded"] == 2
    rows = client.get(f"/api/v1/tasks/{task_id}/rows").json()["items"]
    assert [r["row_number"] for r in rows] == [1, 2, 3]
    assert client.get(f"/api/v1/rows/{rows[0]['id']}/attempts").json()["items"][0]["finished_at"]
    response = client.get(f"/api/v1/tasks/{task_id}/export?format=csv")
    exported = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert len(exported) == 3
    assert exported[0]["result.formula"] == "'=1+1"
    assert exported[0]["id"] == exported[1]["id"]
    assert client.get(f"/api/v1/tasks/{task_id}/export?format=xlsx").content.startswith(b"PK")
    with factory() as db:
        assert len(db.scalars(select(AuditEvent)).all()) == 2
        assert len(db.scalars(select(Row)).all()) == 3


def test_auth_csrf_and_owner_boundaries(api):
    client, _ = api
    task = make_task(client)
    client.headers.pop("X-CSRF-Token")
    assert client.post(f"/api/v1/tasks/{task['id']}/start").status_code == 403
    result = client.post(
        "/api/v1/auth/login", json={"login": "other", "password": "test-only-password"}
    )
    client.headers["X-CSRF-Token"] = result.json()["csrf_token"]
    assert client.get("/api/v1/tasks").json()["total"] == 0
    assert client.get(f"/api/v1/tasks/{task['id']}").status_code == 404
    assert client.get(f"/api/v1/tasks/{task['id']}/export").status_code == 404
    assert client.post(f"/api/v1/tasks/{task['id']}/cancel").status_code == 404
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/tasks").status_code == 401
    assert client.get("/import", follow_redirects=False).headers["location"] == "/login"


def test_validation_and_state_conflicts(api):
    client, _ = api
    invalid = client.post("/api/v1/imports", files={"file": ("bad.xlsx", b"not a workbook")})
    assert invalid.status_code == 422
    assert invalid.json()["request_id"]
    task = make_task(client)
    assert client.post(f"/api/v1/tasks/{task['id']}/resume").status_code == 409
    assert client.post(f"/api/v1/tasks/{task['id']}/cancel").status_code == 202
    runner.maintain_tasks()
    exported = client.get(f"/api/v1/tasks/{task['id']}/export?format=csv")
    assert "pending" in exported.text
    assert client.get(f"/api/v1/tasks/{task['id']}").json()["status"] == "cancelled"
    assert client.get("/api/v1/tasks?page=0").status_code == 422
    assert client.get(f"/api/v1/tasks/{task['id']}/export?format=exe").status_code == 422


def test_html_pages_and_health(api):
    client, _ = api
    task = make_task(client)
    for url in ["/", "/import", "/sources", f"/tasks/{task['id']}"]:
        response = client.get(url)
        assert response.status_code == 200
        assert "Rowstead" in response.text
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert client.get("/health/ready").status_code == 200
    assert client.get("/samples/registry_demo").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_server_search_and_filters_cross_pagination_and_owner_boundary(api):
    client, factory = api
    first = make_task(client)
    with factory.begin() as db:
        original = db.get(Task, first["id"])
        other = db.scalar(select(User).where(User.login == "other"))
        for index in range(55):
            db.add(
                Task(
                    owner_id=original.owner_id,
                    import_id=original.import_id,
                    name=f"Ordinary batch {index}",
                    adapter="registry_demo",
                    created_at=utcnow(),
                )
            )
        db.add(
            Task(
                owner_id=original.owner_id,
                import_id=original.import_id,
                name="Unique 100% imported",
                adapter="registry_demo",
                status="paused",
            )
        )
        db.add(
            Task(
                owner_id=other.id,
                import_id=original.import_id,
                name="Unique other owner",
                adapter="registry_demo",
                status="paused",
            )
        )
    response = client.get(
        "/api/v1/tasks", params={"q": "unique", "status": "paused", "page_size": 1}
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["name"] == "Unique 100% imported"
    assert client.get("/api/v1/tasks", params={"q": "%"}).json()["total"] == 1
    assert client.get("/api/v1/tasks", params={"q": "Registry API"}).json()["total"] == 57
    assert client.get("/api/v1/tasks", params={"q": "no matching batch"}).json()["total"] == 0
    assert client.get("/api/v1/tasks?status=wrong").status_code == 422


def test_issue_filter_applies_before_pagination(api):
    client, factory = api
    task = make_task(client)
    with factory.begin() as db:
        rows = db.scalars(
            select(Row).where(Row.task_id == task["id"]).order_by(Row.row_number)
        ).all()
        rows[0].status, rows[1].status, rows[2].status = "succeeded", "missing", "failed"
    url = f"/api/v1/tasks/{task['id']}/rows"
    issues = client.get(url, params={"issues_only": "true", "page_size": 1}).json()
    assert issues["total"] == 2
    assert issues["items"][0]["status"] == "missing"
    assert client.get(url, params={"issues_only": "true", "status": "failed"}).json()["total"] == 1
    assert (
        client.get(url, params={"issues_only": "true", "status": "succeeded"}).json()["total"] == 0
    )
    assert client.get(url, params={"status": "wrong"}).status_code == 422


def test_explicit_samples_and_self_hosted_api_reference(api):
    client, _ = api
    success = client.get("/samples/registry_demo?scenario=success")
    issues = client.get("/samples/registry_demo?scenario=issues")
    assert len(parse_file("sample.csv", success.content)["rows"]) == 3
    assert len(parse_file("sample.csv", issues.content)["rows"]) == 8
    assert client.get("/samples/browser_demo?scenario=issues").status_code == 422
    assert client.get("/samples/registry_demo?scenario=unknown").status_code == 422
    response = client.get("/docs")
    assert response.status_code == 200
    assert "API reference" in response.text
    assert "/openapi.json" in response.text
    assert "cdn.jsdelivr.net" not in response.text
    assert "<script>" not in response.text
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert client.get("/openapi.json").json()["info"]["license"]["name"] == "MIT"
