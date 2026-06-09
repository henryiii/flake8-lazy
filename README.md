# flake8-lazy

[![Actions Status][actions-badge]][actions-link]
[![Documentation Status][rtd-badge]][rtd-link]

[![PyPI version][pypi-version]][pypi-link]
[![PyPI platforms][pypi-platforms]][pypi-link]

flake8-lazy is a flake8 plugin that finds imports which can be made lazy in
Python 3.15 (following [PEP 810](https://peps.python.org/pep-0810/)). See
[the post here](https://iscinumpy.dev/post/flake8-lazy/) for more on the
development of this tool!

flake8-lazy helps keep import-time overhead low by detecting imports that can be
declared as lazy in `__lazy_modules__`. For this package itself,
`flake8-lazy --help` runs roughly twice as fast when using Python 3.15's new
lazy import system.

Error messages will mention `__lazy_modules__` since that is backward compatible
with older Python versions, but the `lazy` keyword is supported too.

## Quick run

There's a standalone `flake8-lazy` runner. If you use uv or pipx, you can run it
from anywhere without installation:

```bash
uvx flake8-lazy <filenames>
# OR
pipx run flake8-lazy <filenames>
```

Try `--format=lazy-modules` to get copy-paste lines or even `--apply=list` to
have the tool update your lazy modules automatically! For maximum laziness, try
`--apply=dynamic`.

The standalone runner also reads defaults from a `[tool.flake8-lazy.standalone]`
table in your `pyproject.toml`; see the
[CLI docs](https://flake8-lazy.readthedocs.io/en/latest/cli/) for details.

## Install

```bash
python -m pip install flake8-lazy
```

Usually you would include this in some sort of dependency-group in your project,
e.g. `dev` or `lint`.

flake8 will automatically discover the plugin.

## Pre-commit

flake8-lazy ships a [pre-commit](https://pre-commit.com) /
[prek](https://prek.j178.dev) hook. Add it to your `.pre-commit-config.yaml`:

```yaml
- repo: https://github.com/henryiii/flake8-lazy
  rev: v0.8.1
  hooks:
    - id: flake8-lazy
```

The hook reports diagnostics by default; add `args: [--apply=list]` (or another
`--apply` mode) to have it rewrite files in place on commit. _This is the
built-in runner_, use flake8's pre-commit integration if you want flake8 to run
it.

See the [full documentation](https://flake8-lazy.readthedocs.io/) for details,
examples, and the standalone CLI runner.

## Rule codes

### 1xx: Missing lazy declarations

- `LZY101`: Missing lazy stdlib module in `__lazy_modules__`
- `LZY102`: Missing lazy third-party or local module in `__lazy_modules__`

### 2xx: `__lazy_modules__` validation

- `LZY201`: `__lazy_modules__` list is not sorted
- `LZY202`: Module listed in `__lazy_modules__` is never imported
- `LZY203`: Module listed in `__lazy_modules__` appears more than once
- `LZY204`: `__lazy_modules__` is assigned after importing modules it names
- `LZY205`: Module name in `__lazy_modules__` is relative (`.name`) instead of
  absolute

### 3xx: Native `lazy` keyword (Python 3.15+)

- `LZY301`: Lazy import inside `suppress(ImportError)` is misleading
- `LZY302`: Module is declared lazy by both `lazy` keyword and
  `__lazy_modules__`
- `LZY303`: Module is imported both eagerly and lazily

### 4xx: Lazy import safety and semantics

- `LZY401`: Module is declared lazy but accessed at the top level
- `LZY402`: Module is an enclosing package for this file and should not be lazy

## Basic example

```python
__lazy_modules__ = ["argparse", "requests"]

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

## Authoring `__lazy_modules__`

Use a static, sorted list of strings:

```python
__lazy_modules__ = [
    "argparse",
    "numpy",
    "pathlib",
]
```

You can also use sets; sets are slower to construct, but faster to check -
around 2 items is enough to make sets faster.

Dynamic values (i.e. a custom object assigned to `__lazy_modules__`) are also
supported. If flake8-lazy detects a non-static assignment it treats the file as
fully covered and suppresses all LZY1xx/LZY2xx diagnostics. Use
`--apply=dynamic` to have the tool write a simple catch-all object:

```python
class AllLazy:
    @staticmethod
    def __contains__(_: str) -> bool:
        return True


__lazy_modules__ = AllLazy()
```

## How detection works

flake8-lazy inspects module-scope imports and module runtime usage.

- Counts top-level `import` and `from ... import ...` statements.
- Currently treats annotation-only usage as lazy-capable
  (`from __future__ import annotations` if not using 3.14+).
- Treats usage inside `if typing.TYPE_CHECKING:` as type-only.
- Handles static `sys.version_info` checks
- Skips `from __future__ import ...`.
- Requires exact module entries for nested imports.
- Treats enclosing package names as non-lazy for a file. For example, in
  `a/b/c.py`, `a` and `a.b` should not be listed as lazy.

## CLI

The project also provides a direct CLI runner:

```bash
flake8-lazy path/to/file.py another_file.py
# or
uvx flake8-lazy path/to/file.py another_file.py
```

The default output format matches flake8-style diagnostics:

```console
$ flake8-lazy path/to/file.py
path/to/file.py:12:0: LZY102 module 'numpy' should be listed in __lazy_modules__
```

You can also ask for a copy-pasteable recommendation instead:

```console
$ flake8-lazy --format lazy-modules path/to/file.py
path/to/file.py: __lazy_modules__ = ["numpy", "pandas"]
```

To rewrite files in place with the recommended declaration, use `--apply`:

```bash
flake8-lazy --apply=list path/to/file.py another_file.py
```

Available modes: `list`, `set`, `native` (3.15+ syntax), `dynamic`. Long `list`
and `set` assignments are split one module per line with a trailing comma
(black/ruff style) when they exceed `--line-length` (default `88`), so the
output needs no reformatting. When an `__lazy_modules__` assignment already
exists, its quote style (single or double) is preserved, so `--apply` stays a
no-op once the module set is correct and does not fight a single-quote
formatter; new assignments use double quotes. The command exits with status code
`1` if any error is found.

## Local development

See [CONTRIBUTING.md](.github/CONTRIBUTING.md) for local development
instructions.

## FAQ

### Why is this not in Ruff?

It's really new, and it's a bit complex. Maybe someday it will be? :)

### It's missing something!

Open an issue! If it's clear and detailed and in-scope, I might even be able to
assign it to copilot!

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
