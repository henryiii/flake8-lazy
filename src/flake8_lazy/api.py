"""File-oriented API helpers."""

from __future__ import annotations

__lazy_modules__ = [
    "ast",
    f"{__spec__.parent}.analysis",
    f"{__spec__.parent}.checker",
    "pathlib",
    "sys",
    "tokenize",
]

import ast
import sys
import tokenize
from pathlib import Path

from .analysis import collect_declared_lazy_modules, collect_recommended_lazy_modules
from .checker import LazyImportChecker


def collect_errors_for_file(path: str | Path) -> list[tuple[int, int, str]]:
    """Return checker errors for a single Python file."""
    item, tree = _parse_file(path)
    checker = LazyImportChecker(tree=tree, filename=str(item))
    return [(line, col, message) for line, col, message, _checker in checker.run()]


def collect_recommended_lazy_modules_for_file(path: str | Path) -> list[str]:
    """Return a sorted ``__lazy_modules__`` recommendation for a file."""
    item, tree = _parse_file(path)
    return collect_recommended_lazy_modules(tree, filename=item)


def collect_declared_lazy_modules_for_file(path: str | Path) -> list[str] | None:
    """Return the last static ``__lazy_modules__`` declaration for a file."""
    _item, tree = _parse_file(path)
    return collect_declared_lazy_modules(tree)


def _parse_file(path: str | Path) -> tuple[Path, ast.AST]:
    """Read and parse a Python file with filename-aware syntax errors."""
    item = Path(path)
    try:
        with tokenize.open(item) as f:
            source = f.read()
    except UnicodeDecodeError as exc:
        if sys.version_info >= (3, 11):
            exc.add_note(f"while reading {item}")
        raise
    return item, ast.parse(source, filename=str(item))
