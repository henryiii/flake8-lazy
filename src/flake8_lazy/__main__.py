from __future__ import annotations

__lazy_modules__ = ["argparse", "pathlib", "sys"]

import argparse
import sys
from pathlib import Path

from . import (
    __version__,
    collect_declared_lazy_modules_for_file,
    collect_errors_for_file,
    collect_recommended_lazy_modules_for_file,
)


def _format_lazy_modules(path: Path, modules: list[str]) -> str:
    joined_modules = ", ".join(f'"{module}"' for module in modules)
    return f"{path}: __lazy_modules__ = [{joined_modules}]"


def main(argv: list[str] | None = None) -> None:
    """Run flake8-lazy checks directly from the command line."""
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--format",
        choices=("flake8", "lazy-modules"),
        default="flake8",
        help="output style for results",
    )
    namespace = parser.parse_args(list(argv) if argv is not None else None)

    found_errors = False
    for path in namespace.files:
        try:
            errors = collect_errors_for_file(path)
            recommended_modules = collect_recommended_lazy_modules_for_file(path)
            declared_modules = collect_declared_lazy_modules_for_file(path)
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

        if (
            namespace.format == "lazy-modules"
            and recommended_modules
            and declared_modules != recommended_modules
        ):
            sys.stdout.write(f"{_format_lazy_modules(path, recommended_modules)}\n")

        for lineno, col_offset, message in errors:
            if namespace.format == "flake8":
                sys.stdout.write(f"{path}:{lineno}:{col_offset}: {message}\n")
            found_errors = True

    if found_errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
