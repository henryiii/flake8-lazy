---
icon: lucide/rocket
---

# Get started

flake8-lazy helps keep import-time overhead low by detecting imports that can be
declared as lazy in `__lazy_modules__`. For this package itself,
`flake8-lazy --help` runs roughly twice as fast when using Python 3.15's new
lazy import system.

Error messages will mention `__lazy_modules__`, but the `lazy` keyword is
supported too.

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

### 1xx: Missing lazy declarations

| Code     | Meaning                                                            |
| -------- | ------------------------------------------------------------------ |
| `LZY101` | stdlib module should be listed in `__lazy_modules__`               |
| `LZY102` | third-party or local module should be listed in `__lazy_modules__` |

### 2xx: `__lazy_modules__` validation

| Code     | Meaning                                               |
| -------- | ----------------------------------------------------- |
| `LZY201` | `__lazy_modules__` is not sorted                      |
| `LZY202` | module listed in `__lazy_modules__` is never imported |
| `LZY203` | module listed in `__lazy_modules__` is duplicated     |

### 4xx: Lazy import safety and semantics

| Code     | Meaning                                               |
| -------- | ----------------------------------------------------- |
| `LZY401` | module is declared lazy but accessed at the top level |

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
LZY102 module 'numpy' should be listed in __lazy_modules__
```

### Unsorted list

```python
__lazy_modules__ = ["zlib", "abc"]
```

Diagnostic:

```text
LZY201 __lazy_modules__ should be sorted
```

### Nested imports require exact name

```python
import email.header

__lazy_modules__ = ["email"]
```

Diagnostic:

```text
LZY101 stdlib module 'email.header' should be listed in __lazy_modules__
```

### Unused entry in `__lazy_modules__`

```python
__lazy_modules__ = ["numpy", "pandas"]
import numpy
```

Diagnostic:

```text
LZY202 module 'pandas' is listed in __lazy_modules__ but never imported
```

### Duplicate entry in `__lazy_modules__`

```python
__lazy_modules__ = ["numpy", "numpy"]
import numpy
```

Diagnostic:

```text
LZY203 module 'numpy' is duplicated in __lazy_modules__
```

### Module accessed at module scope

```python
__lazy_modules__ = ["pathlib"]
import pathlib

BASE = pathlib.Path("/tmp")
```

Diagnostic:

```text
LZY401 module 'pathlib' is declared lazy but accessed at the top level
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
path/to/file.py:1:0: LZY102 module 'numpy' should be listed in __lazy_modules__
```

The command exits with status `1` if any diagnostics are produced.

## Acknowledgements

[GitHub Copilot](https://github.com/features/copilot) in VS Code was used to
help develop this package. The
[Scientific Python Development Guide](https://learn.scientific-python.org/development/)
template was used as a starting point.
