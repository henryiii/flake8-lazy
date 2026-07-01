---
icon: lucide/search
---

# How it works

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
- Imports only referenced in `if typing.TYPE_CHECKING:` guards.
- Imports only used inside functions.

It intentionally ignores:

- `from __future__ import ...`
- Imports inside function and class bodies
- Imports inside `try`/`except`/`finally` blocks, where lazy imports are not
  permitted (the `lazy` keyword is a `SyntaxError`, and `__lazy_modules__` would
  defer an `ImportError` the block exists to catch)

For files inside a package, enclosing package names are also treated as
non-lazy. For example, in `a/b/c.py`, names `a` and `a.b` should not be declared
lazy (either in `__lazy_modules__` or with `lazy import`).

## Relative imports and type checking

A deferred relative import is rendered against `__spec__.parent` so the entry
stays correct if the package is renamed or vendored, e.g.
`f"{__spec__.parent}.helper"` for `from .helper import ...`. This is valid under
a strict type checker in a normal module, where `__spec__` is always set.

In a `__main__.py` file `__spec__` is typed `ModuleSpec | None` (the module can
be run directly), so `__spec__.parent` trips a strict checker's optional-access
check. **Use absolute imports in `__main__.py`** —
`from mypkg.helper import ...` rather than `from .helper import ...`.
flake8-lazy then records the plain absolute name (`"mypkg.helper"`), which
type-checks cleanly.
