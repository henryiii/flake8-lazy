# flake8-lazy

[![Actions Status][actions-badge]][actions-link]
[![Documentation Status][rtd-badge]][rtd-link]

[![PyPI version][pypi-version]][pypi-link]
[![PyPI platforms][pypi-platforms]][pypi-link]

flake8-lazy is a flake8 plugin that finds imports which can be made lazy in
Python 3.15.

flake8-lazy helps keep import-time overhead low by detecting imports that can be
declared as lazy in `__lazy_modules__`. For this package itself,
`flake8-lazy --help` runs roughly twice as fast when using Python 3.15's new
lazy import system.

Error messages will mention `__lazy_modules__` since that is backward compatible
with older Python versions, but the `lazy` keyword is supported too.

## Install

```bash
python -m pip install flake8-lazy
```

Usually you would include this in some sort of dependency-group in your project,
e.g. `dev` or `lint`.

flake8 will automatically discover the plugin. There's also a standalone
`flake8-lazy` runner.

## Rule codes

### 1xx: Missing lazy declarations

- `LZY101`: Missing lazy stdlib module in `__lazy_modules__`
- `LZY102`: Missing lazy third-party or local module in `__lazy_modules__`

### 2xx: `__lazy_modules__` validation

- `LZY201`: `__lazy_modules__` list is not sorted
- `LZY202`: Module listed in `__lazy_modules__` is never imported
- `LZY203`: Module listed in `__lazy_modules__` appears more than once
- `LZY204`: `__lazy_modules__` is assigned after importing modules it names

### 3xx: Native `lazy` keyword (Python 3.15+)

- `LZY301`: Lazy import inside `suppress(ImportError)` is misleading
- `LZY302`: Module is declared lazy by both `lazy` keyword and
  `__lazy_modules__`
- `LZY303`: Module is imported both eagerly and lazily

### 4xx: Lazy import safety and semantics

- `LZY401`: Module is declared lazy but accessed at the top level

## Basic example

```python
__lazy_modules__ = ["argparse"]

import argparse
import requests


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    args = parser.parse_args()

    response = requests.get(args.url, timeout=5)
    print(response.status_code)
```

In this example, `requests` is only used inside `main`, so it can be lazy. The
checker expects it in `__lazy_modules__` and emits `LZY102` until you add it.
Running `--help` will not import requests, resulting in a more responsive app!

## How detection works

flake8-lazy inspects module-scope imports and module runtime usage.

- Counts top-level `import` and `from ... import ...` statements.
- Currently treats annotation-only usage as lazy-capable
  (`from __future__ import annotations` if not using 3.14+).
- Treats usage inside `if typing.TYPE_CHECKING:` as type-only.
- Skips `from __future__ import ...`.
- Requires exact module entries for nested imports.

Nested import note:

```python
import email.header

__lazy_modules__ = ["email"]  # Not enough
```

This emits `LZY101`; the required entry is `"email.header"`. PEP 810 requires
full module names.

Missing relative imports are mentioned as `.name`, but you need to list the full
name, or generate the full name dynamically if you support embedding (rare).

## CLI

The project also provides a direct CLI runner:

```bash
flake8-lazy path/to/file.py another_file.py
# or
uvx flake8-lazy path/to/file.py another_file.py
```

Output format matches flake8-style diagnostics:

```text
path/to/file.py:12:0: LZY102 module 'numpy' should be listed in __lazy_modules__
```

The command exits with status code `1` if any error is found.

## Authoring `__lazy_modules__`

Use a static, sorted list of strings:

```python
__lazy_modules__ = [
    "argparse",
    "numpy",
    "pathlib",
]
```

Dynamic values are intentionally ignored for now.

## Local development

Run tests:

```bash
nox -s tests
# or
uv run pytest
```

Run linting:

```bash
nox -s lint
# or
prek -a
```

Build docs:

```bash
nox -s docs --non-interactive
```

Serve docs locally:

```bash
nox -s docs
```

## Acknowledgements

[GitHub Copilot](https://github.com/features/copilot) in VS Code was used to
help develop this package. The
[Scientific Python Development Guide](https://learn.scientific-python.org/development/)
template was used as a starting point.

<!-- prettier-ignore-start -->
[actions-badge]:            https://github.com/henryiii/flake8-lazy/actions/workflows/ci.yml/badge.svg
[actions-link]:             https://github.com/henryiii/flake8-lazy/actions
[pypi-link]:                https://pypi.org/project/flake8-lazy/
[pypi-platforms]:           https://img.shields.io/pypi/pyversions/flake8-lazy
[pypi-version]:             https://img.shields.io/pypi/v/flake8-lazy
[rtd-badge]:                https://readthedocs.org/projects/flake8-lazy/badge/?version=latest
[rtd-link]:                 https://flake8-lazy.readthedocs.io/en/latest/?badge=latest
<!-- prettier-ignore-end -->
