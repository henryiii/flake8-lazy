from __future__ import annotations

__lazy_modules__ = [
    "argparse",
    "flake8_lazy._rewriter",
    "flake8_lazy.api",
    "flake8_lazy.checker",
    "pathlib",
]

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from flake8_lazy import __version__
from flake8_lazy._rewriter import apply_lazy_modules
from flake8_lazy.api import (
    collect_declared_lazy_modules_for_file,
    collect_errors_for_file,
    collect_native_lazy_modules_for_file,
    collect_recommended_lazy_modules_for_file,
    has_dynamic_lazy_modules_for_file,
    has_native_lazy_imports_for_file,
)
from flake8_lazy.checker import ERROR_MESSAGES

__all__ = ["main"]


@dataclass(frozen=True, slots=True)
class _FileAnalysis:
    recommended_modules: list[str]
    declared_modules: list[str] | None
    native_modules: list[str]
    is_dynamic: bool
    has_native_lazy: bool
    errors: list[tuple[int, int, str]]


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
    *,
    is_dynamic: bool = False,
    has_native_lazy: bool = False,
) -> bool:
    if apply_mode == "dynamic" and is_dynamic:
        return False
    return bool(recommended_modules) or declared_modules is not None or has_native_lazy


def _analyze_file(
    path: Path,
    *,
    import_preset: str,
    exclude_modules: frozenset[str],
    apply_mode: str | None,
    include_errors: bool,
) -> _FileAnalysis:
    recommended_modules = collect_recommended_lazy_modules_for_file(
        path,
        import_preset=import_preset,
        exclude_modules=exclude_modules,
    )
    declared_modules = collect_declared_lazy_modules_for_file(path)
    is_dynamic = apply_mode == "dynamic" and has_dynamic_lazy_modules_for_file(path)
    has_native_lazy = apply_mode in {
        "list",
        "set",
        "dynamic",
    } and has_native_lazy_imports_for_file(path)
    native_modules: list[str] = []
    if has_native_lazy and apply_mode in {"list", "set"}:
        native_modules = collect_native_lazy_modules_for_file(path)
    errors = (
        collect_errors_for_file(
            path,
            import_preset=import_preset,
            exclude_modules=exclude_modules,
        )
        if include_errors
        else []
    )
    return _FileAnalysis(
        recommended_modules=recommended_modules,
        declared_modules=declared_modules,
        native_modules=native_modules,
        is_dynamic=is_dynamic,
        has_native_lazy=has_native_lazy,
        errors=errors,
    )


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
        "--lazy-import-preset",
        choices=("none", "minimal", "default"),
        default="default",
        dest="import_preset",
        metavar="PRESET",
        help=(
            "set of modules to treat as always-imported and skip from "
            "recommendations; PRESET is none, minimal, or default (default)"
        ),
    )
    parser.add_argument(
        "--lazy-exclude-modules",
        default="",
        dest="exclude_modules",
        metavar="MODULES",
        help=(
            "comma-separated list of modules to exclude from lazy-import "
            "recommendations (treated as always-imported)"
        ),
    )
    parser.add_argument(
        "--apply",
        choices=("list", "set", "native", "dynamic"),
        default=None,
        metavar="MODE",
        help="rewrite files to use the recommended lazy declarations; "
        "MODE is list, set, native, or dynamic",
    )
    namespace = parser.parse_args(list(argv) if argv is not None else None)
    exclude_modules = frozenset(
        m.strip() for m in (namespace.exclude_modules or "").split(",") if m.strip()
    )

    found_errors = False
    for path in namespace.files:
        try:
            analysis = _analyze_file(
                path,
                import_preset=namespace.import_preset,
                exclude_modules=exclude_modules,
                apply_mode=namespace.apply,
                include_errors=namespace.apply is None,
            )
            if namespace.apply is not None and _should_apply(
                namespace.apply,
                analysis.declared_modules,
                analysis.recommended_modules,
                is_dynamic=analysis.is_dynamic,
                has_native_lazy=analysis.has_native_lazy,
            ):
                effective_modules = analysis.recommended_modules
                if analysis.native_modules:
                    effective_modules = sorted(
                        set(analysis.recommended_modules) | set(analysis.native_modules)
                    )
                apply_lazy_modules(path, effective_modules, mode=namespace.apply)
                if namespace.apply == "native" and sys.version_info < (3, 15):
                    continue
                analysis = _analyze_file(
                    path,
                    import_preset=namespace.import_preset,
                    exclude_modules=exclude_modules,
                    apply_mode=namespace.apply,
                    include_errors=True,
                )
            errors = analysis.errors
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
            and analysis.recommended_modules
            and analysis.declared_modules != analysis.recommended_modules
        ):
            sys.stdout.write(
                f"{_format_lazy_modules(path, analysis.recommended_modules)}\n"
            )

        if _report_file_errors(path, errors, namespace.format):
            found_errors = True

    if found_errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
