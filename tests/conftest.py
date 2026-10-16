"""Keep pytest's configured temporary files inside a fresh project checkout."""

from pathlib import Path


def pytest_configure():
    # pytest creates the basetemp leaf, but its artifacts/ parent must exist first.
    (Path(__file__).resolve().parents[1] / "artifacts").mkdir(exist_ok=True)
