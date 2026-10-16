"""Generate a private local .env once; never read or overwrite existing secrets."""

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    destination = ROOT / ".env"
    content = (
        f"SESSION_SECRET={secrets.token_urlsafe(48)}\n"
        f"POSTGRES_PASSWORD={secrets.token_urlsafe(32)}\n"
        "WORKER_CONCURRENCY=2\n"
        "WORKER_POLL_SECONDS=1\n"
        "LEASE_SECONDS=120\n"
        "MAX_ATTEMPTS=3\n"
        "MAX_UPLOAD_MB=20\n"
        "COOKIE_SECURE=false\n"
        "PLAYWRIGHT_BROWSERS_PATH=data/browsers\n"
    )
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print("Existing .env preserved; no settings changed.")
        return
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
    print("Created private .env. Next: docker compose build api")


if __name__ == "__main__":
    main()
