import hashlib
import logging
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth import COOKIE, current_user, serializer, session_data, verify_password
from app.config import settings
from app.db import get_db
from app.logging_config import configure_logging
from app.models import Attempt, AuditEvent, ImportFile, Row, Task, User, new_id, utcnow
from app.services.demo_samples import sample_csv
from app.services.files import FileValidationError, export_rows, parse_file

ROOT = Path(__file__).parent
configure_logging()
logger = logging.getLogger("app.api")


@asynccontextmanager
async def lifespan(app):
    serializer()  # Fail closed rather than use an insecure default signing key.
    (settings.storage_dir / "inputs").mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="Rowstead",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    license_info={"name": "MIT"},
)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")

TaskState = Literal[
    "draft",
    "queued",
    "running",
    "completed",
    "completed_with_errors",
    "pause_requested",
    "paused",
    "cancel_requested",
    "cancelled",
    "blocked",
    "failed",
]
RowState = Literal["pending", "running", "succeeded", "missing", "invalid", "failed", "retry_wait"]


@app.middleware("http")
async def request_context(request: Request, call_next):
    started = time.perf_counter()
    request.state.request_id = str(uuid4())
    response = await call_next(request)
    logger.info(
        "request_finished",
        extra={
            "request_id": request.state.request_id,
            "method": request.method,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000),
        },
    )
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )
    if request.url.path.startswith("/api/") or "text/html" in response.headers.get(
        "content-type", ""
    ):
        response.headers["Cache-Control"] = "no-store"
    return response


def error_response(request, status, code, message, details=None):
    return JSONResponse(
        status_code=status,
        content={
            "code": code,
            "message": message,
            "details": details,
            "request_id": getattr(request.state, "request_id", None),
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_error(request, exc):
    if exc.status_code == 401 and not request.url.path.startswith("/api/"):
        return RedirectResponse("/login", status_code=303)
    return error_response(
        request,
        exc.status_code,
        {
            400: "bad_request",
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            413: "file_too_large",
            422: "validation_error",
        }.get(exc.status_code, "http_error"),
        str(exc.detail),
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Do not echo submitted passwords or uploaded data in validation errors.
    details = [{"location": list(e["loc"]), "message": e["msg"]} for e in exc.errors()]
    return error_response(request, 422, "validation_error", "Check the submitted fields", details)


@app.exception_handler(Exception)
async def internal_error(request, exc):
    logger.error(
        "Unhandled error request_id=%s type=%s", request.state.request_id, type(exc).__name__
    )
    return error_response(request, 500, "internal_error", "An unexpected error occurred")


class LoginPayload(BaseModel):
    login: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1024)


@app.post("/api/v1/auth/login")
def login(payload: LoginPayload, response: Response, db=Depends(get_db)):
    user = db.scalar(select(User).where(User.login == payload.login))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid login or password")
    csrf = secrets.token_urlsafe(32)
    response.set_cookie(
        COOKIE,
        serializer().dumps({"uid": user.id, "csrf": csrf}),
        max_age=12 * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return {"user": {"login": user.login}, "csrf_token": csrf}


@app.post("/api/v1/auth/logout")
def logout(response: Response, user=Depends(current_user)):
    response.delete_cookie(COOKIE)
    return {"message": "Signed out"}


@app.get("/api/v1/session")
def get_session(request: Request, user=Depends(current_user)):
    return {"user": {"login": user.login}, "csrf_token": session_data(request)["csrf"]}


@app.get("/api/v1/health/live")
@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/api/v1/health/ready")
@app.get("/health/ready")
def ready(db=Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db.execute(select(User.id).limit(1))
    except Exception:
        return JSONResponse({"status": "not_ready"}, status_code=503)
    return {"status": "ready"}


def owned_task(db, task_id, user, lock=False):
    statement = select(Task).where(Task.id == task_id, Task.owner_id == user.id)
    if lock:
        statement = statement.with_for_update()
    task = db.scalar(statement)
    if task is None:
        raise HTTPException(404, "Task not found")
    return task


def serialize_task(db, task):
    counts = dict.fromkeys(
        ["pending", "running", "succeeded", "missing", "invalid", "failed", "retry_wait"], 0
    )
    counts.update(
        dict(
            db.execute(
                select(Row.status, func.count()).where(Row.task_id == task.id).group_by(Row.status)
            ).all()
        )
    )
    return {
        "id": task.id,
        "name": task.name,
        "adapter": task.adapter,
        "status": task.status,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
        "blocked_reason": task.blocked_reason,
        "counts": counts,
        "total": sum(counts.values()),
    }


def audit(db, task, user, action):
    db.add(AuditEvent(task_id=task.id, actor_id=user.id, action=action))


@app.get("/api/v1/sources")
def sources(user=Depends(current_user)):
    return {
        "items": [
            {
                "id": "registry_demo",
                "name": "Registry API",
                "description": "Deterministic company registry lookup.",
                "fields": ["identifier"],
                "base_url": settings.demo_base_url,
            },
            {
                "id": "browser_demo",
                "name": "Browser calculator",
                "description": "Fill a real browser form and extract seven result fields.",
                "fields": ["identifier", "quantity", "unit_price", "discount"],
                "base_url": settings.demo_base_url,
            },
        ]
    }


@app.post("/api/v1/imports", status_code=201)
def import_file(
    file: UploadFile = File(...),
    sheet_name: str | None = Form(None),
    delimiter: str = Form(","),
    user=Depends(current_user),
    db=Depends(get_db),
):
    content = file.file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, "File exceeds upload limit")
    try:
        parsed = parse_file(
            file.filename or "", content, sheet_name=sheet_name, delimiter=delimiter
        )
    except FileValidationError as exc:
        raise HTTPException(422, str(exc)) from None
    import_id = new_id()
    storage_key = f"inputs/{import_id}.bin"
    path = settings.storage_dir / storage_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    item = ImportFile(
        id=import_id,
        owner_id=user.id,
        original_name=Path(file.filename or "upload").name[:255],
        storage_key=storage_key,
        sha256=hashlib.sha256(content).hexdigest(),
        headers=parsed["headers"],
        rows_json=parsed["rows"],
        sheet_name=parsed["sheet_name"],
    )
    db.add(item)
    try:
        db.commit()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {
        "id": item.id,
        "headers": parsed["headers"],
        "preview": parsed["rows"][:20],
        "row_count": len(parsed["rows"]),
        "sheet_names": parsed["sheet_names"],
        "sheet_name": parsed["sheet_name"],
    }


class TaskPayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    import_id: str
    adapter: str
    mapping: dict[str, str]


@app.post("/api/v1/tasks", status_code=201)
def create_task(payload: TaskPayload, user=Depends(current_user), db=Depends(get_db)):
    if payload.adapter not in {"registry_demo", "browser_demo"}:
        raise HTTPException(422, "Unknown adapter")
    item = db.scalar(
        select(ImportFile).where(ImportFile.id == payload.import_id, ImportFile.owner_id == user.id)
    )
    if item is None:
        raise HTTPException(404, "Import not found")
    allowed_fields = (
        {"identifier"}
        if payload.adapter == "registry_demo"
        else {"identifier", "quantity", "unit_price", "discount"}
    )
    if not payload.mapping.get("identifier"):
        raise HTTPException(422, "Map the identifier column")
    if any(
        key not in allowed_fields or col not in item.headers for key, col in payload.mapping.items()
    ):
        raise HTTPException(422, "Mapping contains an unknown field or column")
    task = Task(
        owner_id=user.id,
        name=payload.name.strip() or "Untitled batch",
        adapter=payload.adapter,
        import_id=item.id,
        config_json={"mapping": payload.mapping, "adapter_version": "1"},
    )
    db.add(task)
    db.flush()
    db.add_all(
        [
            Row(task_id=task.id, row_number=index, input_json=row)
            for index, row in enumerate(item.rows_json, 1)
        ]
    )
    audit(db, task, user, "created")
    db.commit()
    return serialize_task(db, task)


@app.get("/api/v1/tasks")
def tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    q: str = Query("", max_length=200),
    status: TaskState | None = None,
    user=Depends(current_user),
    db=Depends(get_db),
):
    filters = [Task.owner_id == user.id]
    term = q.strip()
    if term:
        labels = {"registry_demo": "Registry API", "browser_demo": "Browser calculator"}
        matching_adapters = [key for key, label in labels.items() if term.lower() in label.lower()]
        filters.append(
            or_(
                Task.name.icontains(term, autoescape=True),
                Task.adapter.icontains(term, autoescape=True),
                Task.adapter.in_(matching_adapters),
            )
        )
    if status:
        filters.append(Task.status == status)
    total = db.scalar(select(func.count()).select_from(Task).where(*filters))
    items = db.scalars(
        select(Task)
        .where(*filters)
        .order_by(Task.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [serialize_task(db, task) for task in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.get("/api/v1/tasks/{task_id}")
def task_detail(task_id: str, user=Depends(current_user), db=Depends(get_db)):
    return serialize_task(db, owned_task(db, task_id, user))


@app.post("/api/v1/tasks/{task_id}/{action}", status_code=202)
def task_action(task_id: str, action: str, user=Depends(current_user), db=Depends(get_db)):
    task = owned_task(db, task_id, user, lock=True)
    transitions = {
        "start": ({"draft"}, "queued"),
        "pause": ({"queued", "running"}, "pause_requested"),
        "resume": ({"paused", "blocked"}, "queued"),
        "cancel": (
            {"draft", "queued", "running", "pause_requested", "paused", "blocked"},
            "cancel_requested",
        ),
        "retry-failed": ({"completed_with_errors", "completed", "failed"}, "queued"),
    }
    if action not in transitions:
        raise HTTPException(404, "Unknown action")
    allowed, next_status = transitions[action]
    if task.status not in allowed:
        raise HTTPException(409, f"Cannot {action} a task with status {task.status}")
    if action in {"start", "resume"}:
        from app.adapters import ADAPTERS, AdapterError

        try:
            ADAPTERS[task.adapter].validate_config(task.config_json)
        except (ValueError, AdapterError) as exc:
            raise HTTPException(422, str(exc)) from None
    if action == "retry-failed":
        rows = db.scalars(select(Row).where(Row.task_id == task.id, Row.status == "failed")).all()
        if not rows:
            raise HTTPException(409, "No failed rows to retry")
        for row in rows:
            row.status, row.attempt_count = "pending", 0
            row.next_attempt_at = row.lease_until = row.worker_id = None
            row.error_code = row.error_message = None
    if action in {"start", "resume", "retry-failed"}:
        task.started_at = task.started_at or utcnow()
        task.finished_at = None
        task.blocked_reason = None
    task.status = next_status
    audit(db, task, user, action)
    db.commit()
    return serialize_task(db, task)


@app.get("/api/v1/tasks/{task_id}/rows")
def task_rows(
    task_id: str,
    status: RowState | None = None,
    issues_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user=Depends(current_user),
    db=Depends(get_db),
):
    owned_task(db, task_id, user)
    filters = [Row.task_id == task_id]
    if issues_only:
        filters.append(Row.status.in_(("failed", "invalid", "missing")))
    if status:
        filters.append(Row.status == status)
    total = db.scalar(select(func.count()).select_from(Row).where(*filters))
    items = db.scalars(
        select(Row)
        .where(*filters)
        .order_by(Row.row_number)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [
            {
                "id": row.id,
                "row_number": row.row_number,
                "input_json": row.input_json,
                "output_json": row.output_json,
                "status": row.status,
                "attempt_count": row.attempt_count,
                "error_code": row.error_code,
                "error_message": row.error_message,
            }
            for row in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.get("/api/v1/rows/{row_id}/attempts")
def attempts(row_id: str, user=Depends(current_user), db=Depends(get_db)):
    row = db.get(Row, row_id)
    if row is None:
        raise HTTPException(404, "Row not found")
    owned_task(db, row.task_id, user)
    items = db.scalars(
        select(Attempt).where(Attempt.row_id == row_id).order_by(Attempt.started_at)
    ).all()
    return {
        "items": [
            {
                "id": a.id,
                "started_at": a.started_at,
                "finished_at": a.finished_at,
                "error_code": a.error_code,
                "redacted_message": a.redacted_message,
                "duration_ms": a.duration_ms,
            }
            for a in items
        ]
    }


@app.get("/api/v1/tasks/{task_id}/export")
def export(
    task_id: str,
    format: str = Query("xlsx", pattern="^(csv|xlsx)$"),
    user=Depends(current_user),
    db=Depends(get_db),
):
    task = owned_task(db, task_id, user)
    item = db.get(ImportFile, task.import_id)
    # A single SELECT produces one consistent snapshot of rows in PostgreSQL.
    rows = (
        db.execute(
            select(
                Row.input_json,
                Row.output_json,
                Row.status,
                Row.error_code,
                Row.error_message,
                Row.row_number,
            )
            .where(Row.task_id == task.id)
            .order_by(Row.row_number)
        )
        .mappings()
        .all()
    )
    content = export_rows(item.headers, [dict(row) for row in rows], format)
    return Response(
        content,
        media_type="text/csv; charset=utf-8"
        if format == "csv"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="rowstead-{task.id}.{format}"'},
    )


def render(request, template, user, **context):
    return templates.TemplateResponse(
        request=request,
        name=template,
        context={"user": user, "csrf_token": session_data(request)["csrf"], **context},
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db=Depends(get_db)):
    try:
        user = current_user(request, db)
    except HTTPException:
        return templates.TemplateResponse(request=request, name="login.html", context={})
    return render(request, "dashboard.html", user)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={})


@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request, user=Depends(current_user)):
    return render(request, "import.html", user)


@app.get("/sources", response_class=HTMLResponse)
def sources_page(request: Request, user=Depends(current_user)):
    return render(request, "sources.html", user)


@app.get("/tasks/{task_id}", response_class=HTMLResponse)
def task_page(task_id: str, request: Request, user=Depends(current_user), db=Depends(get_db)):
    owned_task(db, task_id, user)
    return render(request, "task.html", user, task_id=task_id)


@app.get("/tasks", include_in_schema=False)
def tasks_page():
    return RedirectResponse("/")


@app.get("/samples/{adapter}")
def sample(
    adapter: str,
    scenario: Literal["legacy", "success", "issues"] = "legacy",
    user=Depends(current_user),
):
    if adapter not in {"registry_demo", "browser_demo"}:
        raise HTTPException(404, "Unknown adapter")
    try:
        content = sample_csv(adapter, scenario)
    except ValueError:
        raise HTTPException(422, "This sample is not available for this source") from None
    return Response(
        content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{adapter}-{scenario}.csv"'},
    )


@app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
def api_reference(request: Request):
    endpoints = [
        {"method": method.upper(), "path": path, "summary": operation.get("summary", "")}
        for path, operations in app.openapi()["paths"].items()
        if path.startswith(("/api/v1/", "/health/", "/samples/"))
        for method, operation in operations.items()
        if method in {"get", "post", "put", "patch", "delete"}
    ]
    return templates.TemplateResponse(
        request=request,
        name="api_docs.html",
        context={"endpoints": endpoints, "schema_json_url": "/openapi.json"},
    )
