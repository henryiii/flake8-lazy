"""File-oriented API helpers."""

from __future__ import annotations

__lazy_modules__ = [
    "ast",
    f"{__spec__.parent}._always_imported",
    f"{__spec__.parent}._analysis",
    f"{__spec__.parent}._collect",
    f"{__spec__.parent}.checker",
    "pathlib",
    "tokenize",
]

import ast
import re
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path

from ._always_imported import IMPORT_PRESETS
from ._analysis import (
    collect_native_lazy_modules,
    collect_recommended_lazy_modules,
    has_native_lazy_imports,
)
from ._collect import build_module_info
from .checker import build_diagnostics

__all__ = [
    "_FileAnalysis",
    "_process_single_file",
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
    *,
    apply_mode: str | None,
    include_errors: bool,
) -> tuple[Path, _FileAnalysis]:
    """Analyze a single file for parallel execution."""
    item, tree, source = _parse_file(path)
    info = build_module_info(tree, item)
    always_imported = IMPORT_PRESETS[import_preset] | exclude_modules

    declared_modules = info.declared_lazy_modules
    is_dynamic = apply_mode == "dynamic" and info.has_dynamic_lazy_modules
    has_native_lazy = apply_mode in {
        "list",
        "set",
        "dynamic",
    } and has_native_lazy_imports(info)
    native_modules: list[str] = []
    if has_native_lazy and apply_mode in {"list", "set"}:
        native_modules = collect_native_lazy_modules(info)

    if include_errors:
        errors = build_diagnostics(info, always_imported=always_imported)
        if errors:
            noqa_map = _build_noqa_map(source)
            if noqa_map:
                filtered: list[tuple[int, int, str]] = []
                for line, col, message in errors:
                    codes = noqa_map.get(line)
                    if codes is None and line in noqa_map:
                        continue
                    if codes is not None and message.split()[0] in codes:
                        continue
                    filtered.append((line, col, message))
                errors = filtered
    else:
        errors = []

    recommended_modules = collect_recommended_lazy_modules(
        info,
        always_imported=always_imported,
    )

    return path, _FileAnalysis(
        recommended_modules=recommended_modules,
        declared_modules=declared_modules,
        native_modules=native_modules,
        is_dynamic=is_dynamic,
        has_native_lazy=has_native_lazy,
        errors=errors,
    )


def _deduplicate_paths(paths: list[Path]) -> list[Path]:
    """Resolve symlinks and remove duplicate paths while preserving order."""
    seen: set[Path] = set()
    result: list[Path] = []
    for p in paths:
        resolved = p.resolve(strict=False)
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
    info = build_module_info(tree, item)
    errors = build_diagnostics(info, always_imported=always_imported)
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
    info = build_module_info(tree, item)
    return collect_recommended_lazy_modules(info, always_imported=always_imported)


def collect_native_lazy_modules_for_file(path: str | Path) -> list[str]:
    """Return a sorted list of packages declared via native ``lazy import`` syntax."""
    _item, tree, _source = _parse_file(path)
    return collect_native_lazy_modules(build_module_info(tree))


def collect_declared_lazy_modules_for_file(path: str | Path) -> list[str] | None:
    """Return the last static ``__lazy_modules__`` declaration for a file."""
    _item, tree, _source = _parse_file(path)
    return build_module_info(tree).declared_lazy_modules


def has_dynamic_lazy_modules_for_file(path: str | Path) -> bool:
    """Return True if the file has a non-static (dynamic) ``__lazy_modules__`` value."""
    _item, tree, _source = _parse_file(path)
    return build_module_info(tree).has_dynamic_lazy_modules


def has_native_lazy_imports_for_file(path: str | Path) -> bool:
    """Return True if the file contains any natively-lazy imports (Python 3.15+)."""
    _item, tree, _source = _parse_file(path)
    return has_native_lazy_imports(build_module_info(tree))


def _parse_file(path: str | Path) -> tuple[Path, ast.AST, str]:
    """Read and parse a Python file with filename-aware syntax errors."""
    item = Path(path).resolve(strict=False)
    try:
        with tokenize.open(item) as f:
            source = f.read()
    except UnicodeDecodeError as exc:
        if sys.version_info >= (3, 11):
            exc.add_note(f"while reading {item}")
        raise
    return item, ast.parse(source, filename=str(item)), source
