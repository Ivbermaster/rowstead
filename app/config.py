import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path.cwd() / ".env")


@dataclass
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./data/batchflow.db")
    )
    storage_dir: Path = field(default_factory=lambda: Path(os.getenv("STORAGE_DIR", "data")))
    session_secret: str = field(default_factory=lambda: os.getenv("SESSION_SECRET", ""))
    demo_base_url: str = field(
        default_factory=lambda: os.getenv("DEMO_BASE_URL", "http://127.0.0.1:8001")
    )
    worker_poll_seconds: float = field(
        default_factory=lambda: float(os.getenv("WORKER_POLL_SECONDS", "1"))
    )
    lease_seconds: int = field(default_factory=lambda: int(os.getenv("LEASE_SECONDS", "120")))
    max_attempts: int = field(default_factory=lambda: int(os.getenv("MAX_ATTEMPTS", "3")))
    worker_concurrency: int = field(
        default_factory=lambda: int(os.getenv("WORKER_CONCURRENCY", "2"))
    )
    max_upload_mb: int = field(default_factory=lambda: int(os.getenv("MAX_UPLOAD_MB", "20")))
    cookie_secure: bool = field(
        default_factory=lambda: os.getenv("COOKIE_SECURE", "false").lower() == "true"
    )


settings = Settings()
