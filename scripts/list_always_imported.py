#!/usr/bin/env python
"""List modules that are always imported by Python at startup.

Run this script with the desired Python interpreter to get the list of
modules that are always loaded at startup under a given set of flags.
These modules never benefit from being declared in ``__lazy_modules__``.

Two modes correspond to the two built-in presets:

* **minimal** (``-IS``): Python in isolated + no-site mode.  Only a small
  core set of modules is loaded (``sys``, ``time``, ``codecs``, …).
  Use the output to regenerate ``ALWAYS_IMPORTED_MINIMAL`` in
  ``src/flake8_lazy/_always_imported.py``.

* **default** (``-I``): Python in isolated mode with site initialisation.
  Additional modules such as ``os``, ``abc``, and ``site`` are loaded.
  Use the output to regenerate ``ALWAYS_IMPORTED_DEFAULT``.

Usage:
    # minimal preset (python -IS)
    python scripts/list_always_imported.py

    # default preset (python -I, with site)
    python scripts/list_always_imported.py --site
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
        "--site",
        action="store_true",
        help="include site-packages initialisation (omits -S flag); "
        "use to generate ALWAYS_IMPORTED_DEFAULT",
    )
    args = parser.parse_args()

    flags = ["-I"] if args.site else ["-IS"]

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
