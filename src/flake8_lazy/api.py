"""File-oriented API helpers."""

from __future__ import annotations

__lazy_modules__ = [
    "ast",
    f"{__spec__.parent}._always_imported",
    f"{__spec__.parent}._analysis",
    f"{__spec__.parent}.checker",
    "pathlib",
    "tokenize",
]

import ast
import re
import sys
import tokenize
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
    path: str | Path, *, import_preset: str = "default"
) -> list[tuple[int, int, str]]:
    """Return checker errors for a single Python file, respecting noqa comments."""
    if import_preset not in IMPORT_PRESETS:
        valid = ", ".join(sorted(IMPORT_PRESETS))
        msg = f"invalid import_preset {import_preset!r}; choose from: {valid}"
        raise ValueError(msg)
    item, tree, source = _parse_file(path)
    # Temporarily configure the checker class so run() uses the right preset.
    prev_preset = LazyImportChecker.import_preset
    LazyImportChecker.import_preset = import_preset
    try:
        checker = LazyImportChecker(tree=tree, filename=str(item))
        errors = [(line, col, message) for line, col, message, _c in checker.run()]
    finally:
        LazyImportChecker.import_preset = prev_preset
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
    path: str | Path, *, import_preset: str = "default"
) -> list[str]:
    """Return a sorted ``__lazy_modules__`` recommendation for a file."""
    if import_preset not in IMPORT_PRESETS:
        valid = ", ".join(sorted(IMPORT_PRESETS))
        msg = f"invalid import_preset {import_preset!r}; choose from: {valid}"
        raise ValueError(msg)
    always_imported = IMPORT_PRESETS[import_preset]
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


def _parse_file(path: str | Path) -> tuple[Path, ast.AST, str]:
    """Read and parse a Python file with filename-aware syntax errors."""
    item = Path(path)
    try:
        with tokenize.open(item) as f:
            source = f.read()
    except UnicodeDecodeError as exc:
        if sys.version_info >= (3, 11):
            exc.add_note(f"while reading {item}")
        raise
    return item, ast.parse(source, filename=str(item)), source
