#!/usr/bin/env python3
"""List modules that are always imported by Python at startup.

Run this script with the desired Python interpreter to get the list of
modules that are always loaded at startup.  These modules never benefit
from being declared in ``__lazy_modules__``.

Two modes correspond to the two built-in presets:

* **default** (no flags): Python in isolated mode (``-I``) with normal site
  initialisation.  Modules such as ``os``, ``abc``, and ``site`` are loaded.
  Use the output to regenerate ``ALWAYS_IMPORTED_DEFAULT`` in
  ``src/flake8_lazy/_always_imported.py``.

* **minimal** (``-S``): Python in isolated + no-site mode (``-IS``).  Only a
  small core set of modules is loaded (``sys``, ``time``, ``codecs``, …).
  Use the output to regenerate ``ALWAYS_IMPORTED_MINIMAL``.

Usage:
    # default preset  (python -I)
    uv run --python 3.15 python scripts/list_always_imported.py

    # minimal preset  (python -IS)
    uv run --python 3.15 python scripts/list_always_imported.py -S
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "-S",
        dest="no_site",
        action="store_true",
        help="skip site-packages initialisation (passes -S to Python); "
        "use to generate ALWAYS_IMPORTED_MINIMAL",
    )
    args = parser.parse_args()

    flags = ["-IS"] if args.no_site else ["-I"]

    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
        tmpfile = Path(f.name)

    try:
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-v", *flags, tmpfile],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            msg = (
                f"Python subprocess exited with code {result.returncode}.\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )
            raise RuntimeError(msg)
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
