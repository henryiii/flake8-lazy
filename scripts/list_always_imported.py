#!/usr/bin/env python
"""List modules that are always imported by Python at startup.

Run this script with the desired Python interpreter to get the list of
modules that are always loaded regardless of what your program imports.
These modules never benefit from being declared in __lazy_modules__.

Usage:
    python scripts/list_always_imported.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
        tmpfile = Path(f.name)

    try:
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-v", "-IS", tmpfile],
            capture_output=True,
            text=True,
            check=False,
        )
        modules: set[str] = set()
        for line in result.stderr.splitlines():
            if line.startswith("# destroy "):
                name = line[len("# destroy ") :]
                # Skip private modules (starting with _ or containing ._)
                if name.startswith("_") or "._" in name:
                    continue
                modules.add(name)
        for module in sorted(modules):
            print(module)  # noqa: T201
    finally:
        tmpfile.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
