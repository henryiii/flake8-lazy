---
icon: lucide/rocket
---

# Get started

flake8-lazy helps keep import-time overhead low by detecting imports that can be
declared as lazy in `__lazy_modules__`. For this package itself,
`flake8-lazy --help` runs roughly twice as fast when using Python 3.15's new
lazy import system.

Currently, the `lazy import` syntax is not supported, only the backward-compat
mode with `__lazy_modules__`. This will be added in the future.

## Installation

```bash
python -m pip install flake8-lazy
```

Usually you would include this in some sort of dependency-group in your project,
e.g. `dev` or `lint`.

## Run through flake8

```bash
flake8 your_package
```

The plugin is auto-discovered by flake8 via entry points.

## Rule reference

| Code     | Meaning                                                            |
| -------- | ------------------------------------------------------------------ |
| `LZY001` | stdlib module should be listed in `__lazy_modules__`               |
| `LZY002` | third-party or local module should be listed in `__lazy_modules__` |
| `LZY101` | `__lazy_modules__` is not sorted                                   |

## Expected pattern

Declare a static, sorted list at module scope:

```python
__lazy_modules__ = [
    "argparse",
    "numpy",
    "pathlib",
]
```

## What is considered lazy-capable

flake8-lazy checks imports that execute at module scope and looks for runtime
uses at module scope.

An import is considered lazy-capable when it is not needed immediately during
module import.

The checker intentionally treats these as lazy-capable:

- Imports only referenced in annotations.
- Imports only referenced in `if TYPE_CHECKING:` guards.
- Imports only used inside functions.

It intentionally ignores:

- `from __future__ import ...`
- Imports inside function and class bodies

## Examples

### Missing lazy module

```python
import numpy
```

Diagnostic:

```text
LZY002 module 'numpy' should be listed in __lazy_modules__
```

### Unsorted list

```python
__lazy_modules__ = ["zlib", "abc"]
```

Diagnostic:

```text
LZY101 __lazy_modules__ should be sorted
```

### Nested imports require exact name

```python
import email.header

__lazy_modules__ = ["email"]
```

Diagnostic:

```text
LZY001 stdlib module 'email.header' should be listed in __lazy_modules__
```

## CLI mode

You can also run the checker directly:

```bash
flake8-lazy path/to/file.py
# or
uvx flake8-lazy path/to/file.py
```

Output is flake8-like:

```text
path/to/file.py:1:0: LZY002 module 'numpy' should be listed in __lazy_modules__
```

The command exits with status `1` if any diagnostics are produced.
