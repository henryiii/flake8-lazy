# flake8-lazy

[![Actions Status][actions-badge]][actions-link]
[![Documentation Status][rtd-badge]][rtd-link]

[![PyPI version][pypi-version]][pypi-link]
[![PyPI platforms][pypi-platforms]][pypi-link]

<!-- prettier-ignore-start -->
[actions-badge]:            https://github.com/henryiii/flake8-lazy/actions/workflows/ci.yml/badge.svg
[actions-link]:             https://github.com/henryiii/flake8-lazy/actions
[pypi-link]:                https://pypi.org/project/flake8-lazy/
[pypi-platforms]:           https://img.shields.io/pypi/pyversions/flake8-lazy
[pypi-version]:             https://img.shields.io/pypi/v/flake8-lazy
[rtd-badge]:                https://readthedocs.org/projects/flake8-lazy/badge/?version=latest
[rtd-link]:                 https://flake8-lazy.readthedocs.io/en/latest/?badge=latest

<!-- prettier-ignore-end -->

flake8-lazy is a flake8 plugin that finds imports which can be made lazy.

flake8-lazy helps keep import-time overhead low by detecting imports that can be
declared as lazy in `__lazy_modules__`. For this package itself,
`flake8-lazy --help` runs roughly twice as fast when using Python 3.15's new
lazy import system.

Error messages will mention `__lazy_modules__`, but the `lazy` keyword is
supported too.

## Install

```bash
python -m pip install flake8-lazy
```

Usually you would include this in some sort of dependency-group in your project,
e.g. `dev` or `lint`.

## Use with flake8

flake8 discovers the plugin via the `flake8.extension` entry point.

```bash
flake8 your_package
```

## Rule codes

- `LZY001`: Missing lazy stdlib module in `__lazy_modules__`
- `LZY002`: Missing lazy third-party or local module in `__lazy_modules__`
- `LZY101`: `__lazy_modules__` list is not sorted
- `LZY102`: Module listed in `__lazy_modules__` is never imported

## Basic example

```python
__lazy_modules__ = ["argparse", "pathlib"]

import argparse
import pathlib
import numpy


def run() -> None:
    print(argparse.ArgumentParser)
```

In this example, `numpy` is never used at module runtime, so the checker expects
it in `__lazy_modules__` and emits `LZY002`.

## How detection works

flake8-lazy inspects module-scope imports and module runtime usage.

- Counts top-level `import` and `from ... import ...` statements.
- Ignores imports inside functions and classes.
- Treats annotation-only usage as lazy-capable.
- Treats usage inside `if TYPE_CHECKING:` as type-only.
- Skips `from __future__ import ...`.
- Requires exact module entries for nested imports.

Nested import note:

```python
import email.header

__lazy_modules__ = ["email"]  # Not enough
```

This emits `LZY001`; the required entry is `"email.header"`. PEP 810 requires
full module names.

## CLI

The project also provides a direct CLI runner:

```bash
flake8-lazy path/to/file.py another_file.py
# or
uvx flake8-lazy path/to/file.py another_file.py
```

Output format matches flake8-style diagnostics:

```text
path/to/file.py:12:0: LZY002 module 'numpy' should be listed in __lazy_modules__
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
