"""Run runtime tests inside Compose against its private PostgreSQL.

No database port is published; integration tests use isolated random schemas.
Publication-guard tests run from the source checkout/CI, which includes Git.
"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    command = [
        "docker",
        "compose",
        "--project-name",
        "batchflow",
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "--volume",
        "./tests:/srv/batchflow/tests:ro",
        "--volume",
        "./artifacts:/srv/batchflow/artifacts",
        "api",
        "python",
        "-c",
        "import os, pytest; os.environ['TEST_DATABASE_URL'] = os.environ['DATABASE_URL']; "
        "raise SystemExit(pytest.main(['-q', 'tests', '--ignore=tests/test_release_check.py', "
        "'--basetemp=artifacts/pytest-postgres']))",
    ]
    raise SystemExit(subprocess.run(command, cwd=ROOT, check=False).returncode)


if __name__ == "__main__":
    main()
