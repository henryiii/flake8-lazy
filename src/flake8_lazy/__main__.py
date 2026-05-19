from __future__ import annotations

__lazy_modules__ = [
    "argparse",
    "flake8_lazy._rewriter",
    "flake8_lazy.api",
    "flake8_lazy.checker",
    "pathlib",
    "sys",
]

import argparse
import sys
from pathlib import Path

from flake8_lazy import __version__
from flake8_lazy._rewriter import apply_lazy_modules
from flake8_lazy.api import (
    collect_declared_lazy_modules_for_file,
    collect_errors_for_file,
    collect_recommended_lazy_modules_for_file,
)
from flake8_lazy.checker import ERROR_MESSAGES

__all__ = ["main"]


def _format_lazy_modules(path: Path, modules: list[str]) -> str:
    joined_modules = ", ".join(
        module
        if module.startswith('f"{__spec__.parent') and module.endswith('"')
        else f'"{module}"'
        for module in modules
    )
    return f"{path}: __lazy_modules__ = [{joined_modules}]"


def _report_file_errors(
    path: Path,
    errors: list[tuple[int, int, str]],
    format_mode: str,
) -> bool:
    """Print errors for a single file; return True if any were found."""
    found = False
    for lineno, col_offset, message in errors:
        if format_mode == "flake8":
            sys.stdout.write(f"{path}:{lineno}:{col_offset}: {message}\n")
        found = True
    return found


def _should_apply(
    apply_mode: str,
    declared_modules: list[str] | None,
    recommended_modules: list[str],
) -> bool:
    if apply_mode == "native":
        return bool(recommended_modules) or declared_modules is not None
    return declared_modules != recommended_modules


def main(argv: list[str] | None = None) -> None:
    """Run flake8-lazy checks directly from the command line."""
    help_epilog = "\n".join(
        (f"{code}: {msg.replace('{module!r} ', '')}")
        for code, msg in ERROR_MESSAGES.items()
    )
    parser = argparse.ArgumentParser(
        allow_abbrev=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=help_epilog,
    )
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
    parser.add_argument(
        "--apply",
        nargs="?",
        const="list",
        default=None,
        metavar="MODE",
        help="rewrite files to use the recommended lazy declarations; "
        "MODE is list (default), set, or native",
    )
    namespace = parser.parse_args(list(argv) if argv is not None else None)

    if namespace.apply is not None and namespace.apply not in {"list", "set", "native"}:
        parser.error(
            f"--apply: invalid mode {namespace.apply!r}; choose from list, set, native"
        )

    found_errors = False
    for path in namespace.files:
        try:
            recommended_modules = collect_recommended_lazy_modules_for_file(path)
            declared_modules = collect_declared_lazy_modules_for_file(path)
            if namespace.apply is not None and _should_apply(
                namespace.apply, declared_modules, recommended_modules
            ):
                apply_lazy_modules(path, recommended_modules, mode=namespace.apply)
                if namespace.apply == "native":
                    # The rewritten file contains Python 3.15+ syntax; skip
                    # re-parsing and error checks on older interpreters.
                    continue
                recommended_modules = collect_recommended_lazy_modules_for_file(path)
                declared_modules = collect_declared_lazy_modules_for_file(path)
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

        if (
            namespace.format == "lazy-modules"
            and recommended_modules
            and declared_modules != recommended_modules
        ):
            sys.stdout.write(f"{_format_lazy_modules(path, recommended_modules)}\n")

        if _report_file_errors(path, errors, namespace.format):
            found_errors = True

    if found_errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
