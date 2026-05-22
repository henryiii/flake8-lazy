---
icon: lucide/code
---

# Examples

### Missing lazy module

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

Diagnostic:

```text
LZY102 module 'requests' should be listed in __lazy_modules__
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

### Relative names are invalid in `__lazy_modules__`

```python
__lazy_modules__ = [".local"]
```

Diagnostic:

```text
LZY205 module '.local' in __lazy_modules__ must be absolute
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

### Enclosing package listed as lazy

```python
# file: a/b/c.py
__lazy_modules__ = ["a", "a.b", "requests"]

# Python 3.15+ equivalent
# lazy import a
# lazy import a.b
```

Diagnostics:

```text
LZY402 module 'a' is an enclosing package for this file and should not be declared lazy
LZY402 module 'a.b' is an enclosing package for this file and should not be declared lazy
```

### Lazy import inside `suppress(ImportError)` (Python 3.15+)

```python3.15
from contextlib import suppress

with suppress(ImportError):
    lazy import numpy
```

Diagnostic:

```text
LZY301 lazy import 'numpy' inside suppress(ImportError) is misleading
```

With a lazy import, the actual import happens at first use of the module, which
occurs _outside_ the `with suppress(ImportError):` block. The suppression
therefore has no effect.

### Redundant `lazy` and `__lazy_modules__` declaration (Python 3.15+)

```python3.15
__lazy_modules__ = ["numpy"]
lazy import numpy
```

Diagnostic:

```text
LZY302 module 'numpy' is declared lazy by both 'lazy' keyword and __lazy_modules__
```

The `lazy import` keyword already makes the import lazy; listing the module in
`__lazy_modules__` as well is redundant.

### Module imported both eagerly and lazily (Python 3.15+)

```python3.15
import numpy
lazy import numpy
```

Diagnostic:

```text
LZY303 module 'numpy' is imported both eagerly and lazily
```
