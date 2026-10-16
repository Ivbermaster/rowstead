"""Round-trip the running local demo database into a separate disposable database.

Run after runtime verification, with no Rowstead tasks currently processing.
Never drops or overwrites the application's database or storage volume.
"""

import hashlib
import json
import subprocess
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "backup-check"


def compose(*args, **kwargs):
    return subprocess.run(
        ["docker", "compose", "--project-name", "batchflow", *args],
        cwd=ROOT,
        check=True,
        stdout=kwargs.pop("stdout", subprocess.PIPE),
        stderr=subprocess.PIPE,
        **kwargs,
    )


def sql(database, query):
    return (
        compose(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "batchflow",
            "-d",
            database,
            "-v",
            "ON_ERROR_STOP=1",
            "-At",
            "-c",
            query,
        )
        .stdout.decode()
        .strip()
    )


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    container = compose("ps", "-q", "postgres").stdout.decode().strip()
    inspected = subprocess.run(
        ["docker", "inspect", container], cwd=ROOT, capture_output=True, check=True
    )
    labels = json.loads(inspected.stdout)[0]["Config"]["Labels"]
    if (
        labels.get("com.docker.compose.project") != "batchflow"
        or labels.get("com.docker.compose.service") != "postgres"
        or Path(labels["com.docker.compose.project.working_dir"]).resolve() != ROOT
    ):
        raise SystemExit("PostgreSQL container does not belong to this Rowstead checkout")
    restore_db = f"batchflow_restore_{uuid4().hex}"
    # Pause/cancel/completion are allowed; active source I/O would make file/DB
    # snapshot coordination ambiguous, so fail before taking an inconsistent backup.
    active = int(
        sql(
            "batchflow",
            "SELECT count(*) FROM tasks WHERE status IN "
            "('queued','running','pause_requested','cancel_requested')",
        )
    )
    running_rows = int(sql("batchflow", "SELECT count(*) FROM rows WHERE status='running'"))
    if active or running_rows:
        raise SystemExit("Finish or pause active tasks before backup verification")
    snapshot = OUTPUT / "database.dump"
    with snapshot.open("wb") as stream:
        compose(
            "exec",
            "-T",
            "postgres",
            "pg_dump",
            "-U",
            "batchflow",
            "-d",
            "batchflow",
            "--format=custom",
            stdout=stream,
        )
    # Inventory captures original file hashes from the application database.
    inputs = json.loads(
        sql(
            "batchflow",
            "SELECT coalesce(json_agg(t), '[]') FROM "
            "(SELECT storage_key, sha256 FROM imports ORDER BY id) t",
        )
    )
    container_id = compose("ps", "-q", "api").stdout.decode().strip()
    if not container_id:
        raise SystemExit("Rowstead API container must be running")
    files = OUTPUT / uuid4().hex
    files.mkdir()
    compose("cp", "api:/srv/batchflow/data/inputs", str(files))
    for item in inputs:
        target = (files / item["storage_key"]).resolve()
        if not target.is_relative_to(files.resolve()) or not target.is_file():
            raise AssertionError("Original input file absent from backup")
        if hashlib.sha256(target.read_bytes()).hexdigest() != item["sha256"]:
            raise AssertionError("Original input file hash mismatch")
    # Only this randomly named verification database is created and dropped.
    compose("exec", "-T", "postgres", "createdb", "-U", "batchflow", restore_db)
    try:
        with snapshot.open("rb") as stream:
            compose(
                "exec",
                "-T",
                "postgres",
                "pg_restore",
                "-U",
                "batchflow",
                "-d",
                restore_db,
                "--exit-on-error",
                stdin=stream,
            )
        tables = [
            "users",
            "imports",
            "tasks",
            "rows",
            "attempts",
            "audit_events",
            "alembic_version",
        ]
        counts = {}
        for table in tables:
            # Ordered row digests compare all persisted columns, not just counts.
            key = "version_num" if table == "alembic_version" else "id"
            query = f"SELECT count(*), md5(coalesce(string_agg(row_to_json(t)::text, '' ORDER BY {key}), '')) FROM {table} t"
            original, restored = sql("batchflow", query), sql(restore_db, query)
            if original != restored:
                raise AssertionError(f"Restored table differs: {table}")
            counts[table] = int(original.split("|")[0])
        report = {
            "result": "passed",
            "database_tables": counts,
            "original_files_verified": len(inputs),
            "dump_bytes": snapshot.stat().st_size,
            "scope": "PostgreSQL custom dump restored to isolated database; original file hashes verified",
        }
        (OUTPUT / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report))
    finally:
        # The name is generated above, never accepted from user input or configuration.
        if not restore_db.startswith("batchflow_restore_") or len(restore_db) != 50:
            raise AssertionError("Unexpected restore verification database name")
        compose("exec", "-T", "postgres", "dropdb", "-U", "batchflow", restore_db)


if __name__ == "__main__":
    main()
