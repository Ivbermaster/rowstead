# Contributing

Start with the [README](README.md) for setup and [architecture](docs/architecture.md)
for worker leases, recovery and adapter boundaries. Use synthetic data when
reporting an issue or demonstrating a change. Keep fixes focused and include a
reproduction for behavior changes.

Run these from the project directory with its virtual environment active:

```sh
python -m ruff check .
python -m pytest -q
python scripts/check_release.py --require-git
```

Without `TEST_DATABASE_URL`, PostgreSQL tests are skipped. Use the disposable-test
instructions in the README to exercise real PostgreSQL. With Chromium installed,
set `BATCHFLOW_E2E=1` and run `python -m pytest -q tests/test_ui_e2e.py` for the real
browser scenario. See [verification](docs/verification.md) for the heavier local
Compose checks; the runtime verifier deliberately crashes the demo worker.

Before staging, review `git status --short`. Stage explicit public paths. Keep
`.env`, uploads, database files, exports, browser profiles, backups and generated
videos private. Public CSV examples belong in `examples/`. The release checker
uses an explicit public-source/asset allowlist; update that policy deliberately
when adding an asset. Its findings show paths and line numbers, never matched
credential values. It checks working files and staged blobs plus HEAD/archive
paths; it is a heuristic guard and does not audit all historical commits.

The only credential exceptions are exact disposable CI/test literals in named
files. Do not add real credentials to exceptions or suppress the entire tests
directory. Account and session values for live demos must be generated locally.

The [CI workflow](.github/workflows/ci.yml) runs source preflight, lint, migrations
on SQLite/PostgreSQL, unit/integration tests, a real Chromium scenario and an image
build. It uploads only synthetic screenshots and JUnit reports for seven days.
Hosted CI results become available after an authorized GitHub push; local checks
alone do not establish a hosted run. CI follows GitHub's documented
[workflow permissions and timeouts](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax),
[PostgreSQL services](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers)
and [artifact options](https://github.com/actions/upload-artifact).

Describe the problem, resulting behavior and checks in your pull request. Follow
[SECURITY.md](SECURITY.md) for security findings. Contributions use the project's
[MIT license](LICENSE).
