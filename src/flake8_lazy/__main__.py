from __future__ import annotations

__lazy_modules__ = ["argparse", "pathlib", "sys"]

import argparse
import sys
from pathlib import Path

from . import __version__, collect_errors_for_file


def main(argv: list[str] | None = None) -> None:
    """Run flake8-lazy checks directly from the command line."""
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    namespace = parser.parse_args(list(argv) if argv is not None else None)

    found_errors = False
    for path in namespace.files:
        try:
            errors = collect_errors_for_file(path)
        except OSError as exc:
            sys.stderr.write(f"{path}:0:0: LZY000 failed to read file ({exc})\n")
            found_errors = True
            continue
        except SyntaxError as exc:
            lineno = exc.lineno if exc.lineno is not None else 0
            col_offset = (exc.offset - 1) if exc.offset is not None else 0
            sys.stderr.write(
                f"{path}:{lineno}:{col_offset}: LZY000 failed to parse Python file\n",
            )
            found_errors = True
            continue

        for lineno, col_offset, message in errors:
            sys.stdout.write(f"{path}:{lineno}:{col_offset}: {message}\n")
            found_errors = True

    if found_errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
