"""Run the local demo's three independent processes with one command."""

import os
import subprocess
import sys
import time
from pathlib import Path

from app.config import settings


def main():
    root = Path(__file__).resolve().parent.parent
    if len(settings.session_secret) < 32:
        raise SystemExit("Set SESSION_SECRET in .env before starting. See README.md.")
    processes = []
    commands = [
        ["-m", "uvicorn", "demo.main:app", "--host", "127.0.0.1", "--port", "8001"],
        ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
        ["-m", "app.worker"],
    ]
    try:
        for command in commands:
            processes.append(
                subprocess.Popen([sys.executable, *command], cwd=root, env=os.environ.copy())
            )
        print("Rowstead: http://127.0.0.1:8000 — Ctrl+C stops all three processes", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
