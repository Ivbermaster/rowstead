# Dependency inventory

Recorded 2026-10-16 from the installed project `.venv` using Python
`importlib.metadata`. Every version below matched `requirements.lock`.
License expressions come from installed `License-Expression`, then `License`,
then license classifiers; project links come from that same package metadata.
This inventory records package declarations and does not cover every component
bundled in a browser, base image or operating-system package.

## Locked Python packages

| Package / upstream | Version | Declared license | Role |
|---|---|---|---|
| [alembic](https://github.com/sqlalchemy/alembic/) | 1.20.0 | MIT | Runtime direct |
| [annotated-doc](https://github.com/fastapi/annotated-doc) | 0.0.5 | MIT | Transitive |
| [annotated-types](https://github.com/annotated-types/annotated-types) | 0.8.0 | MIT | Transitive |
| [anyio](https://anyio.readthedocs.io/en/latest/) | 4.15.1 | MIT | Transitive |
| [certifi](https://github.com/certifi/python-certifi) | 2026.7.22 | MPL-2.0 | Transitive |
| [click](https://github.com/pallets/click/) | 8.5.0 | BSD-3-Clause | Transitive |
| [colorama](https://github.com/tartley/colorama) | 0.4.6 | BSD License | Transitive |
| [defusedxml](https://github.com/tiran/defusedxml) | 0.7.1 | PSFL (metadata); PSF license v2 (bundled LICENSE) | Runtime direct |
| [et_xmlfile](https://foss.heptapod.net/openpyxl/et_xmlfile) | 2.0.0 | MIT | Transitive |
| [fastapi](https://github.com/fastapi/fastapi) | 0.143.2 | MIT | Runtime direct |
| [greenlet](https://github.com/python-greenlet/greenlet) | 3.5.6 | MIT AND PSF-2.0 | Transitive |
| [h11](https://github.com/python-hyper/h11) | 0.16.0 | MIT | Transitive |
| [httpcore](https://github.com/encode/httpcore) | 1.0.9 | BSD-3-Clause | Transitive |
| [httpx](https://github.com/encode/httpx) | 0.28.1 | BSD-3-Clause | Runtime direct |
| [idna](https://github.com/kjd/idna) | 3.20 | BSD-3-Clause | Transitive |
| [iniconfig](https://github.com/pytest-dev/iniconfig) | 2.3.1 | MIT | Transitive |
| [itsdangerous](https://github.com/pallets/itsdangerous/) | 2.2.0 | BSD License | Runtime direct |
| [Jinja2](https://github.com/pallets/jinja/) | 3.1.6 | BSD License | Runtime direct |
| [Mako](https://www.makotemplates.org/) | 1.4.3 | MIT | Transitive |
| [MarkupSafe](https://github.com/pallets/markupsafe/) | 3.0.4 | BSD-3-Clause | Transitive |
| [openpyxl](https://foss.heptapod.net/openpyxl/openpyxl) | 3.1.5 | MIT | Runtime direct |
| [opentelemetry-api](https://github.com/open-telemetry/opentelemetry-python) | 1.45.1 | Apache-2.0 | Transitive |
| [packaging](https://github.com/pypa/packaging) | 26.3 | Apache-2.0 OR BSD-2-Clause | Transitive |
| [playwright](https://github.com/Microsoft/playwright-python) | 1.64.0 | Apache-2.0 | Runtime direct |
| [pluggy](https://github.com/pytest-dev/pluggy) | 1.7.0 | MIT | Transitive |
| [psycopg](https://psycopg.org/) | 3.3.6 | LGPL-3.0-only | Runtime direct |
| [psycopg-binary](https://psycopg.org/) | 3.3.6 | LGPL-3.0-only | Transitive |
| [pydantic](https://github.com/pydantic/pydantic) | 2.14.1 | MIT | Transitive |
| [pydantic_core](https://github.com/pydantic/pydantic/tree/main/pydantic-core) | 2.50.1 | MIT | Transitive |
| [pyee](https://github.com/jfhbrook/pyee) | 13.0.1 | MIT | Transitive |
| [Pygments](https://github.com/pygments/pygments) | 2.21.0 | BSD-2-Clause | Transitive |
| [pytest](https://github.com/pytest-dev/pytest) | 9.1.1 | MIT | Dev direct |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | 1.2.4 | BSD-3-Clause | Runtime direct |
| [python-multipart](https://github.com/Kludex/python-multipart) | 0.0.32 | Apache-2.0 | Runtime direct |
| [ruff](https://github.com/astral-sh/ruff) | 0.17.1 | MIT | Dev direct |
| [SQLAlchemy](https://www.sqlalchemy.org) | 2.0.54 | MIT | Runtime direct |
| [starlette](https://github.com/Kludex/starlette) | 1.8.0 | BSD-3-Clause | Transitive |
| [typing-inspection](https://github.com/pydantic/typing-inspection) | 0.4.4 | MIT | Transitive |
| [typing_extensions](https://github.com/python/typing_extensions) | 4.16.0 | PSF-2.0 | Transitive |
| [tzdata](https://github.com/python/tzdata) | 2026.5 | Apache-2.0 | Transitive |
| [uvicorn](https://github.com/Kludex/uvicorn) | 0.54.0 | BSD-3-Clause | Runtime direct |

Total: **41 locked packages**. “Transitive” can include dependencies of
runtime packages or development tools. The Docker image currently installs the
same lock, including development tools.

## Bundled license evidence and distribution scope

- `psycopg` and `psycopg-binary` each ship a `LICENSE.txt` in their installed
  distribution's `licenses/` directory and declare `LGPL-3.0-only`.
- `certifi` declares `MPL-2.0` and includes its distribution license file.
- `greenlet` declares `MIT AND PSF-2.0`; `packaging` declares
  `Apache-2.0 OR BSD-2-Clause`. Preserve these expressions in any notice inventory.
- `colorama`, `itsdangerous` and `Jinja2` use the broad BSD license classifier;
  their installed `LICENSE.txt` files were also inspected. The table preserves
  the declared classifier rather than inventing a more precise metadata value.
- `defusedxml`'s metadata says `PSFL`; its bundled `LICENSE` names the Python
  Software Foundation License Version 2.
- Playwright includes the Python distribution license, `playwright/driver/LICENSE`,
  the driver package `LICENSE`, `NOTICE`, `ThirdPartyNotices.txt` and bundled JS
  license notices. Its Apache declaration alone does not inventory Chromium or
  every bundled driver dependency.
- Chromium is downloaded separately by `playwright install`; the Docker image
  additionally contains Python, Debian packages and browser system libraries.
  A distributable container/browser bundle needs its own component/notice inventory.
  No container or browser licensing audit was performed here.

The application's own license is a separate maintainer choice. Before publishing
binary artifacts, retain the upstream license and notice material relevant to the
actual artifacts being distributed. This document does not replace those files.

## Reproduce

From the source checkout, use the same interpreter as the project environment:

```python
from importlib.metadata import distribution
from pathlib import Path

for line in Path("requirements.lock").read_text().splitlines():
    if "==" not in line:
        continue
    name, expected = line.split("==", 1)
    package = distribution(name)
    assert package.version == expected
    print(name, package.version, package.metadata.get("License-Expression"),
          package.metadata.get("License"),
          package.metadata.get_all("Classifier", []))
```

`python -m pip check` passed in the inspected environment. This checks installed
requirement compatibility; it is not a vulnerability scan or a hosted CI result.
