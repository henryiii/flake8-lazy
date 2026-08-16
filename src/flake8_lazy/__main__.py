from __future__ import annotations

__lazy_modules__ = [
    "argparse",
    "flake8_lazy._ast_helpers",
    "flake8_lazy._config",
    "flake8_lazy._options",
    "flake8_lazy._rewriter",
    "flake8_lazy.api",
    "flake8_lazy.checker",
    "pathlib",
]

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from flake8_lazy import __version__
from flake8_lazy._ast_helpers import format_module_literal, lazy_module_sort_key
from flake8_lazy._config import ConfigError, load_standalone_defaults
from flake8_lazy._options import (
    APPLY_CHOICES,
    DEFAULT_EXCLUDE_MODULES,
    DEFAULT_IMPORT_PRESET,
    DEFAULT_STRICT_TYPING,
    FORMAT_CHOICES,
    IMPORT_PRESET_CHOICES,
    parse_exclude_modules,
)
from flake8_lazy._rewriter import DEFAULT_LINE_LENGTH, apply_lazy_modules
from flake8_lazy.api import (
    _deduplicate_paths,
    _FileAnalysis,
    _process_single_file,
)
from flake8_lazy.checker import ERROR_MESSAGES

__all__ = ["main"]


def _analyze_file(
    path: Path,
    *,
    import_preset: str,
    exclude_modules: frozenset[str],
    apply_mode: str | None,
    include_errors: bool,
    strict_typing: bool,
) -> _FileAnalysis:
    _path, analysis = _process_single_file(
        path,
        import_preset=import_preset,
        exclude_modules=exclude_modules,
        apply_mode=apply_mode,
        include_errors=include_errors,
        strict_typing=strict_typing,
    )
    return analysis


def _format_lazy_modules(path: Path, modules: list[str]) -> str:
    joined_modules = ", ".join(format_module_literal(module) for module in modules)
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


def _parse_jobs(value: str) -> int:
    if value.lower() == "auto":
        return 0
    try:
        jobs = int(value)
    except ValueError:
        msg = f"invalid int value: {value!r}"
        raise argparse.ArgumentTypeError(msg) from None
    if jobs <= 0:
        msg = "jobs must be a positive integer or 'auto'"
        raise argparse.ArgumentTypeError(msg)
    return jobs


def _parse_line_length(value: str) -> int:
    try:
        length = int(value)
    except ValueError:
        msg = f"invalid int value: {value!r}"
        raise argparse.ArgumentTypeError(msg) from None
    if length < 0:
        msg = "line-length must be a non-negative integer"
        raise argparse.ArgumentTypeError(msg)
    return length


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
        choices=FORMAT_CHOICES,
        default="flake8",
        help="output style for results",
    )
    parser.add_argument(
        "--lazy-import-preset",
        choices=IMPORT_PRESET_CHOICES,
        default=DEFAULT_IMPORT_PRESET,
        dest="import_preset",
        metavar="PRESET",
        help=(
            "set of modules to treat as always-imported and skip from "
            "recommendations; PRESET is none, minimal, or default (default)"
        ),
    )
    parser.add_argument(
        "--lazy-exclude-modules",
        default=DEFAULT_EXCLUDE_MODULES,
        dest="exclude_modules",
        metavar="MODULES",
        help=(
            "comma-separated list of modules to exclude from lazy-import "
            "recommendations (treated as always-imported)"
        ),
    )
    parser.add_argument(
        "--apply",
        choices=APPLY_CHOICES,
        default=None,
        metavar="MODE",
        help="rewrite files to use the recommended lazy declarations; "
        "MODE is list, set, native, or dynamic",
    )
    parser.add_argument(
        "--line-length",
        type=_parse_line_length,
        default=DEFAULT_LINE_LENGTH,
        dest="line_length",
        metavar="N",
        help="max length of a single-line __lazy_modules__ assignment before "
        "--apply splits it across multiple lines, black/ruff style; "
        f"0 disables splitting (default: {DEFAULT_LINE_LENGTH})",
    )
    parser.add_argument(
        "--strict-typing",
        action=argparse.BooleanOptionalAction,
        default=DEFAULT_STRICT_TYPING,
        dest="strict_typing",
        help="render multi-level relative imports with a '(__spec__.parent or "
        '"")\' guard so they type-check under strict optional checking '
        f"(default: {'on' if DEFAULT_STRICT_TYPING else 'off'})",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=_parse_jobs,
        default=0,
        metavar="N",
        help="number of parallel processes (default: auto)",
    )
    try:
        config_defaults = load_standalone_defaults(Path.cwd())
    except ConfigError as exc:
        parser.error(str(exc))
    parser.set_defaults(**config_defaults)

    namespace = parser.parse_args(list(argv) if argv is not None else None)
    exclude_modules = parse_exclude_modules(namespace.exclude_modules)

    paths = _deduplicate_paths(namespace.files)
    jobs = namespace.jobs
    if jobs == 0:
        jobs = os.cpu_count() or 1

    found_errors = _run_parallel(
        paths,
        namespace=namespace,
        exclude_modules=exclude_modules,
        jobs=jobs,
    )

    if found_errors:
        raise SystemExit(1)


def _run_sequential(
    paths: list[Path],
    *,
    namespace: argparse.Namespace,
    exclude_modules: frozenset[str],
) -> bool:
    found_errors = False
    for path in paths:
        exc: Exception | None = None
        analysis: _FileAnalysis | None = None
        try:
            analysis = _analyze_file(
                path,
                import_preset=namespace.import_preset,
                exclude_modules=exclude_modules,
                apply_mode=namespace.apply,
                include_errors=namespace.apply is None,
                strict_typing=namespace.strict_typing,
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
                        set(analysis.recommended_modules)
                        | set(analysis.native_modules),
                        key=lazy_module_sort_key,
                    )
                apply_lazy_modules(
                    path,
                    effective_modules,
                    mode=namespace.apply,
                    line_length=namespace.line_length,
                    strict_typing=namespace.strict_typing,
                )
                if namespace.apply == "native" and sys.version_info < (3, 15):
                    continue
                analysis = _analyze_file(
                    path,
                    import_preset=namespace.import_preset,
                    exclude_modules=exclude_modules,
                    apply_mode=namespace.apply,
                    include_errors=True,
                    strict_typing=namespace.strict_typing,
                )
        except OSError as exc_:
            exc = exc_
            found_errors = True
        except SyntaxError as exc_:
            exc = exc_
            found_errors = True

        if _emit_output(path, namespace=namespace, analysis=analysis, exc=exc):
            found_errors = True

    return found_errors


def _emit_output(
    path: Path,
    *,
    namespace: argparse.Namespace,
    analysis: _FileAnalysis | None = None,
    exc: Exception | None = None,
) -> bool:
    """Emit output (errors or lazy-modules) for one file; return True if errors."""
    found_errors = False
    if exc is not None:
        if isinstance(exc, OSError):
            sys.stderr.write(f"{path}:0:0: LZY000 failed to read file ({exc})\n")
        elif isinstance(exc, SyntaxError):
            lineno = exc.lineno if exc.lineno is not None else 0
            col_offset = (exc.offset - 1) if exc.offset is not None else 0
            sys.stderr.write(
                f"{path}:{lineno}:{col_offset}: LZY000 failed to parse Python file\n",
            )
        else:
            raise exc
        return True

    if analysis is None:
        return False

    if (
        namespace.format == "lazy-modules"
        and analysis.recommended_modules
        and analysis.declared_modules != analysis.recommended_modules
    ):
        sys.stdout.write(
            f"{_format_lazy_modules(path, analysis.recommended_modules)}\n"
        )

    if _report_file_errors(path, analysis.errors, namespace.format):
        found_errors = True

    return found_errors


def _apply_rewrites(
    paths: list[Path],
    results: dict[Path, _FileAnalysis],
    errors_by_path: dict[Path, Exception],
    *,
    apply_mode: str,
    import_preset: str,
    exclude_modules: frozenset[str],
    line_length: int,
    strict_typing: bool,
) -> tuple[dict[Path, _FileAnalysis], dict[Path, Exception], bool]:
    """Apply rewrites sequentially in argument order."""
    found_errors = False
    for path in paths:
        analysis = results.get(path)
        if analysis is None:
            continue
        if _should_apply(
            apply_mode,
            analysis.declared_modules,
            analysis.recommended_modules,
            is_dynamic=analysis.is_dynamic,
            has_native_lazy=analysis.has_native_lazy,
        ):
            effective_modules = analysis.recommended_modules
            if analysis.native_modules:
                effective_modules = sorted(
                    set(analysis.recommended_modules) | set(analysis.native_modules),
                    key=lazy_module_sort_key,
                )
            try:
                apply_lazy_modules(
                    path,
                    effective_modules,
                    mode=apply_mode,
                    line_length=line_length,
                    strict_typing=strict_typing,
                )
            except OSError as exc:
                errors_by_path[path] = exc
                found_errors = True
                continue
            if apply_mode == "native" and sys.version_info < (3, 15):
                continue
            try:
                results[path] = _analyze_file(
                    path,
                    import_preset=import_preset,
                    exclude_modules=exclude_modules,
                    apply_mode=apply_mode,
                    include_errors=True,
                    strict_typing=strict_typing,
                )
            except (OSError, SyntaxError) as exc:
                errors_by_path[path] = exc
                found_errors = True
    return results, errors_by_path, found_errors


def _run_parallel(
    paths: list[Path],
    *,
    namespace: argparse.Namespace,
    exclude_modules: frozenset[str],
    jobs: int,
) -> bool:
    found_errors = False
    results: dict[Path, _FileAnalysis] = {}
    errors_by_path: dict[Path, Exception] = {}

    max_workers = min(jobs, len(paths), os.cpu_count() or 1)
    if max_workers <= 1:
        return _run_sequential(
            paths,
            namespace=namespace,
            exclude_modules=exclude_modules,
        )

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _process_single_file,
                path,
                namespace.import_preset,
                exclude_modules,
                apply_mode=namespace.apply,
                include_errors=namespace.apply is None,
                strict_typing=namespace.strict_typing,
            ): path
            for path in paths
        }
        for future in as_completed(futures):
            path = futures[future]
            try:
                result_path, analysis = future.result()
            except (OSError, SyntaxError) as exc:
                errors_by_path[path] = exc
                found_errors = True
                continue
            results[result_path] = analysis

    # Apply mode: rewrite files sequentially in argument order
    if namespace.apply is not None:
        results, errors_by_path, apply_errors = _apply_rewrites(
            paths,
            results,
            errors_by_path,
            apply_mode=namespace.apply,
            import_preset=namespace.import_preset,
            exclude_modules=exclude_modules,
            line_length=namespace.line_length,
            strict_typing=namespace.strict_typing,
        )
        if apply_errors:
            found_errors = True

    # Emit output in original argument order
    for path in paths:
        if _emit_output(
            path,
            namespace=namespace,
            analysis=results.get(path),
            exc=errors_by_path.get(path),
        ):
            found_errors = True

    return found_errors


if __name__ == "__main__":
    main()
