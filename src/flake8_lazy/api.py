"""File-oriented API helpers."""

from __future__ import annotations

__lazy_modules__ = [
    "ast",
    f"{__spec__.parent}._always_imported",
    f"{__spec__.parent}._analysis",
    f"{__spec__.parent}.checker",
    "dataclasses",
    "pathlib",
    "tokenize",
]

import ast
import re
import sys
import tokenize
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ._always_imported import IMPORT_PRESETS
from ._analysis import (
    collect_declared_lazy_modules,
    collect_native_lazy_modules,
    collect_recommended_lazy_modules,
    has_dynamic_lazy_modules,
    has_native_lazy_imports,
)
from .checker import LazyImportChecker

__all__ = [
    "_FileAnalysis",
    "_process_single_file",
    "clear_parse_cache",
    "collect_declared_lazy_modules_for_file",
    "collect_errors_for_file",
    "collect_native_lazy_modules_for_file",
    "collect_recommended_lazy_modules_for_file",
    "has_dynamic_lazy_modules_for_file",
    "has_native_lazy_imports_for_file",
]

# Pattern matching inline noqa suppression comments, optionally followed by a
# colon-separated list of error codes (e.g. ``LZY101, LZY102``).
_NOQA_RE = re.compile(r"#\s*noqa(?:\s*:\s*([^\n]*))?", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class _FileAnalysis:
    recommended_modules: list[str]
    declared_modules: list[str] | None
    native_modules: list[str]
    is_dynamic: bool
    has_native_lazy: bool
    errors: list[tuple[int, int, str]]


def _process_single_file(
    path: Path,
    import_preset: str,
    exclude_modules: frozenset[str],
) -> tuple[Path, _FileAnalysis | None, BaseException | None]:
    """Analyze a single file for parallel execution."""
    try:
        declared_modules = collect_declared_lazy_modules_for_file(path)
        is_dynamic = has_dynamic_lazy_modules_for_file(path)
        has_native_lazy = has_native_lazy_imports_for_file(path)
        native_modules: list[str] = []
        if has_native_lazy:
            native_modules = collect_native_lazy_modules_for_file(path)
        errors = collect_errors_for_file(
            path,
            import_preset=import_preset,
            exclude_modules=exclude_modules,
        )
        recommended_modules = collect_recommended_lazy_modules_for_file(
            path,
            import_preset=import_preset,
            exclude_modules=exclude_modules,
        )
        analysis = _FileAnalysis(
            recommended_modules=recommended_modules,
            declared_modules=declared_modules,
            native_modules=native_modules,
            is_dynamic=is_dynamic,
            has_native_lazy=has_native_lazy,
            errors=errors,
        )
    except BaseException as exc:  # noqa: BLE001
        return path, None, exc
    else:
        return path, analysis, None


def _deduplicate_paths(paths: list[Path]) -> list[Path]:
    """Resolve symlinks and remove duplicate paths while preserving order."""
    seen: set[Path] = set()
    result: list[Path] = []
    for p in paths:
        resolved = p.resolve()
        if resolved not in seen:
            seen.add(resolved)
            result.append(p)
    return result


def _build_noqa_map(source: str) -> dict[int, set[str] | None]:
    """Return a map of 1-based line number to suppressed codes.

    A value of ``None`` means *all* codes are suppressed (bare ``# noqa``).
    A ``set`` value contains the specific codes suppressed on that line.
    """
    if "noqa" not in source.lower():
        return {}
    noqa_map: dict[int, set[str] | None] = {}
    for lineno, line in enumerate(source.splitlines(), start=1):
        m = _NOQA_RE.search(line)
        if m:
            codes_str = m.group(1)
            if not codes_str or not codes_str.strip():
                noqa_map[lineno] = None
            else:
                noqa_map[lineno] = {
                    c.strip() for c in codes_str.split(",") if c.strip()
                }
    return noqa_map


def collect_errors_for_file(
    path: str | Path,
    *,
    import_preset: str = "default",
    exclude_modules: frozenset[str] = frozenset(),
) -> list[tuple[int, int, str]]:
    """Return checker errors for a single Python file, respecting noqa comments."""
    if import_preset not in IMPORT_PRESETS:
        valid = ", ".join(sorted(IMPORT_PRESETS))
        msg = f"invalid import_preset {import_preset!r}; choose from: {valid}"
        raise ValueError(msg)
    item, tree, source = _parse_file(path)
    always_imported = IMPORT_PRESETS[import_preset] | exclude_modules
    checker = LazyImportChecker(tree=tree, filename=str(item))
    errors = [
        (line, col, message)
        for line, col, message, _c in checker.run(always_imported=always_imported)
    ]
    if not errors:
        return []
    noqa_map = _build_noqa_map(source)
    if not noqa_map:
        return errors
    result = []
    for line, col, message in errors:
        if line in noqa_map:
            codes = noqa_map[line]
            if codes is None or message.split()[0] in codes:
                continue
        result.append((line, col, message))
    return result


def collect_recommended_lazy_modules_for_file(
    path: str | Path,
    *,
    import_preset: str = "default",
    exclude_modules: frozenset[str] = frozenset(),
) -> list[str]:
    """Return a sorted ``__lazy_modules__`` recommendation for a file."""
    if import_preset not in IMPORT_PRESETS:
        valid = ", ".join(sorted(IMPORT_PRESETS))
        msg = f"invalid import_preset {import_preset!r}; choose from: {valid}"
        raise ValueError(msg)
    always_imported = IMPORT_PRESETS[import_preset] | exclude_modules
    item, tree, _source = _parse_file(path)
    return collect_recommended_lazy_modules(
        tree, filename=item, always_imported=always_imported
    )


def collect_native_lazy_modules_for_file(path: str | Path) -> list[str]:
    """Return a sorted list of packages declared via native ``lazy import`` syntax."""
    _item, tree, _source = _parse_file(path)
    return collect_native_lazy_modules(tree)


def collect_declared_lazy_modules_for_file(path: str | Path) -> list[str] | None:
    """Return the last static ``__lazy_modules__`` declaration for a file."""
    _item, tree, _source = _parse_file(path)
    return collect_declared_lazy_modules(tree)


def has_dynamic_lazy_modules_for_file(path: str | Path) -> bool:
    """Return True if the file has a non-static (dynamic) ``__lazy_modules__`` value."""
    _item, tree, _source = _parse_file(path)
    return has_dynamic_lazy_modules(tree)


def has_native_lazy_imports_for_file(path: str | Path) -> bool:
    """Return True if the file contains any natively-lazy imports (Python 3.15+)."""
    _item, tree, _source = _parse_file(path)
    return has_native_lazy_imports(tree)


def clear_parse_cache() -> None:
    """Clear the file-parse cache (e.g. after rewriting a file on disk)."""
    _parse_file_cached.cache_clear()


def _parse_file(path: str | Path) -> tuple[Path, ast.AST, str]:
    """Read and parse a Python file with filename-aware syntax errors."""
    item = Path(path)
    return _parse_file_cached(item)


@lru_cache(maxsize=512)
def _parse_file_cached(item: Path) -> tuple[Path, ast.AST, str]:
    """Cached version; item must be a resolved Path."""
    try:
        with tokenize.open(item) as f:
            source = f.read()
    except UnicodeDecodeError as exc:
        if sys.version_info >= (3, 11):
            exc.add_note(f"while reading {item}")
        raise
    return item, ast.parse(source, filename=str(item)), source
