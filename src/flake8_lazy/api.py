"""File-oriented API helpers."""

from __future__ import annotations

__lazy_modules__ = {
    "ast",
    f"{__spec__.parent}._analysis",
    f"{__spec__.parent}.checker",
    "pathlib",
    "re",
    "sys",
    "tokenize",
}

import ast
import re
import sys
import tokenize
from pathlib import Path

from ._analysis import collect_declared_lazy_modules, collect_recommended_lazy_modules
from .checker import LazyImportChecker

__all__ = [
    "collect_declared_lazy_modules_for_file",
    "collect_errors_for_file",
    "collect_recommended_lazy_modules_for_file",
]

# Pattern matching inline noqa suppression comments, optionally followed by a
# colon-separated list of error codes (e.g. ``LZY101, LZY102``).
_NOQA_PATTERN = r"#\s*noqa(?:\s*:\s*([^\n]*))?"


def _build_noqa_map(source: str) -> dict[int, set[str] | None]:
    """Return a map of 1-based line number to suppressed codes.

    A value of ``None`` means *all* codes are suppressed (bare ``# noqa``).
    A ``set`` value contains the specific codes suppressed on that line.
    """
    noqa_map: dict[int, set[str] | None] = {}
    noqa_re = re.compile(_NOQA_PATTERN, re.IGNORECASE)
    for lineno, line in enumerate(source.splitlines(), start=1):
        m = noqa_re.search(line)
        if m:
            codes_str = m.group(1)
            if not codes_str or not codes_str.strip():
                noqa_map[lineno] = None
            else:
                noqa_map[lineno] = {
                    c.strip() for c in codes_str.split(",") if c.strip()
                }
    return noqa_map


def collect_errors_for_file(path: str | Path) -> list[tuple[int, int, str]]:
    """Return checker errors for a single Python file, respecting noqa comments."""
    item, tree, source = _parse_file(path)
    checker = LazyImportChecker(tree=tree, filename=str(item))
    noqa_map = _build_noqa_map(source)
    result = []
    for line, col, message, _checker in checker.run():
        if line in noqa_map:
            codes = noqa_map[line]
            if codes is None or message.split()[0] in codes:
                continue
        result.append((line, col, message))
    return result


def collect_recommended_lazy_modules_for_file(path: str | Path) -> list[str]:
    """Return a sorted ``__lazy_modules__`` recommendation for a file."""
    item, tree, _source = _parse_file(path)
    return collect_recommended_lazy_modules(tree, filename=item)


def collect_declared_lazy_modules_for_file(path: str | Path) -> list[str] | None:
    """Return the last static ``__lazy_modules__`` declaration for a file."""
    _item, tree, _source = _parse_file(path)
    return collect_declared_lazy_modules(tree)


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
