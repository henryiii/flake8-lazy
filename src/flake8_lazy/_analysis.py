"""Lazy-import checks (Phase 2).

Every function here is pure over a :class:`~flake8_lazy._model.ModuleInfo`
produced by ``_collect.build_module_info`` — they never traverse the AST.  Each
``collect_*`` corresponds to one or more LZY diagnostics and returns
``(module, lineno, col_offset)`` (or ``(lineno, col_offset)``) tuples for the
checker to format.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._always_imported import ALWAYS_IMPORTED_DEFAULT, BROKEN

if TYPE_CHECKING:
    from collections.abc import Callable

    from ._model import ImportInfo, ModuleInfo

__all__ = [
    "collect_broken_lazy_modules",
    "collect_duplicate_lazy_modules",
    "collect_enclosing_lazy_modules",
    "collect_invalid_lazy_module_names",
    "collect_late_lazy_module_assignments",
    "collect_lazy_imports_in_suppress_blocks",
    "collect_missing_lazy_modules",
    "collect_mixed_lazy_eager_imports",
    "collect_native_lazy_modules",
    "collect_non_lazy_imports",
    "collect_recommended_lazy_modules",
    "collect_redundant_lazy_declarations",
    "collect_unnecessary_lazy_imports",
    "collect_unsorted_lazy_modules",
    "collect_unused_lazy_modules",
    "has_native_lazy_imports",
]


def _eager_imports(info: ModuleInfo) -> list[ImportInfo]:
    """Module-scope eager imports, as ``collect_top_level_imports`` returned.

    Imports inside ``try``/``except``/``finally`` are excluded: they can never be
    made lazy (the ``lazy`` keyword is a ``SyntaxError`` there, and listing them
    in ``__lazy_modules__`` would defer an ``ImportError`` the block exists to
    catch), so they are neither recommended nor counted as eager usage.
    """
    return [
        imp
        for imp in info.imports
        if imp.runtime_visible and not imp.is_lazy and not imp.in_try_block
    ]


def _lazy_imports(info: ModuleInfo) -> list[ImportInfo]:
    """Module-scope native ``lazy`` imports (Python 3.15+)."""
    return [imp for imp in info.imports if imp.runtime_visible and imp.is_lazy]


# ---------------------------------------------------------------------------
# Native lazy imports (Python 3.15+)
# ---------------------------------------------------------------------------


def has_native_lazy_imports(info: ModuleInfo) -> bool:
    """Return True if the module contains any natively-lazy imports."""
    return any(imp.is_lazy and imp.runtime_visible for imp in info.imports)


def collect_native_lazy_modules(info: ModuleInfo) -> list[str]:
    """Return sorted package names declared via native ``lazy import`` syntax."""
    return sorted(
        {imp.package for imp in _lazy_imports(info) if imp.package is not None}
    )


# ---------------------------------------------------------------------------
# __lazy_modules__ validation (LZY2xx)
# ---------------------------------------------------------------------------


def collect_unsorted_lazy_modules(info: ModuleInfo) -> list[tuple[int, int]]:
    """Return locations of static ``__lazy_modules__`` assignments that are unsorted."""
    return [
        (assignment.lineno, assignment.col_offset)
        for assignment in info.static_lazy_assignments
        if assignment.modules != sorted(assignment.modules)
    ]


def _is_imported_package(module: str, imported_packages: set[str]) -> bool:
    """Return True when ``module`` or one of its child modules is imported."""
    return any(
        package == module or package.startswith(f"{module}.")
        for package in imported_packages
    )


def collect_unused_lazy_modules(info: ModuleInfo) -> list[tuple[str, int, int]]:
    """Return modules listed in ``__lazy_modules__`` that are never imported."""
    imported_packages = {
        imp.package for imp in _eager_imports(info) if imp.package is not None
    }
    unused: list[tuple[str, int, int]] = []
    for assignment in info.static_lazy_assignments:
        unused.extend(
            (module, assignment.lineno, assignment.col_offset)
            for module in assignment.modules
            if not _is_imported_package(module, imported_packages)
            if module not in info.enclosing_packages
        )
    return unused


def _collect_duplicate_modules(modules: list[str]) -> list[str]:
    """Return duplicate module names preserving first duplicate appearance order."""
    duplicates: list[str] = []
    seen: set[str] = set()
    seen_duplicates: set[str] = set()
    for module in modules:
        if module in seen:
            if module not in seen_duplicates:
                duplicates.append(module)
                seen_duplicates.add(module)
            continue
        seen.add(module)
    return duplicates


def collect_duplicate_lazy_modules(info: ModuleInfo) -> list[tuple[str, int, int]]:
    """Return duplicated modules listed in ``__lazy_modules__``."""
    duplicated: list[tuple[str, int, int]] = []
    for assignment in info.static_lazy_assignments:
        duplicated.extend(
            (module, assignment.lineno, assignment.col_offset)
            for module in _collect_duplicate_modules(assignment.modules)
        )
    return duplicated


def collect_late_lazy_module_assignments(info: ModuleInfo) -> list[tuple[int, int]]:
    """Return ``__lazy_modules__`` assignments after importing listed modules."""
    return list(info.late_lazy_module_locations)


def collect_invalid_lazy_module_names(info: ModuleInfo) -> list[tuple[str, int, int]]:
    """Return relative ``__lazy_modules__`` entries that must be absolute."""
    return [
        (module, lineno, col_offset)
        for module, lineno, col_offset in info.lazy_module_entries
        if module.startswith(".")
    ]


def collect_broken_lazy_modules(
    info: ModuleInfo,
    *,
    broken: frozenset[str] = BROKEN,
) -> list[tuple[str, int, int]]:
    """Return modules listed in ``__lazy_modules__`` that are known broken."""
    return [
        (module, lineno, col_offset)
        for module, lineno, col_offset in info.lazy_module_entries
        if module in broken
    ]


# ---------------------------------------------------------------------------
# Native lazy keyword diagnostics (LZY3xx)
# ---------------------------------------------------------------------------


def collect_lazy_imports_in_suppress_blocks(
    info: ModuleInfo,
) -> list[tuple[str, int, int]]:
    """Return lazy imports declared inside ``suppress(ImportError)`` (LZY301)."""
    return list(info.suppress_lazy_imports)


def _unique_lazy_binding_packages(
    info: ModuleInfo,
    *,
    include: Callable[[str], bool],
) -> list[tuple[str, int, int]]:
    result: list[tuple[str, int, int]] = []
    seen: set[str] = set()
    for binding in _lazy_imports(info):
        package = binding.package
        if package is None or package in seen or not include(package):
            continue
        result.append((package, binding.lineno, binding.col_offset))
        seen.add(package)
    return result


def collect_redundant_lazy_declarations(
    info: ModuleInfo,
) -> list[tuple[str, int, int]]:
    """Return ``lazy`` imports also named in ``__lazy_modules__`` (LZY302)."""
    lazy_packages = info.lazy_packages
    if not lazy_packages:
        return []
    return _unique_lazy_binding_packages(info, include=lazy_packages.__contains__)


def collect_mixed_lazy_eager_imports(info: ModuleInfo) -> list[tuple[str, int, int]]:
    """Return modules imported both eagerly and lazily (LZY303)."""
    eager_packages = {
        imp.package for imp in _eager_imports(info) if imp.package is not None
    }
    if not eager_packages:
        return []
    return _unique_lazy_binding_packages(info, include=eager_packages.__contains__)


# ---------------------------------------------------------------------------
# Non-lazy / recommendation analysis (LZY1xx)
# ---------------------------------------------------------------------------


def _compute_non_lazy_names(
    bindings: list[ImportInfo],
    runtime_names: frozenset[str],
) -> list[str]:
    """Return bound names from ``bindings`` that appear in ``runtime_names``."""
    non_lazy: list[str] = []
    seen: set[str] = set()
    for binding in bindings:
        name = binding.bound_name
        if name in runtime_names and name not in seen:
            non_lazy.append(name)
            seen.add(name)
    return non_lazy


def collect_non_lazy_imports(info: ModuleInfo) -> list[str]:
    """Return imported names that are used at top-level runtime."""
    return _compute_non_lazy_names(_eager_imports(info), info.runtime_names)


def _is_non_lazy_binding(
    binding: ImportInfo,
    non_lazy_names: set[str],
    runtime_attribute_paths: frozenset[str],
) -> bool:
    if binding.package is None or binding.bound_name not in non_lazy_names:
        return False
    if binding.package in runtime_attribute_paths:
        return True
    root = binding.package.split(".", maxsplit=1)[0]
    if binding.package == binding.bound_name:
        return True
    if binding.is_aliased:
        return True
    return binding.bound_name != root


@dataclass(frozen=True, slots=True)
class _RecommendationPolicy:
    excluded_packages: set[str]
    blocked_packages: set[str]
    side_effect_packages: set[str]
    guard_packages: set[str]
    non_lazy_packages: set[str]

    def should_skip(self, package: str, *, seen_packages: set[str]) -> bool:
        return (
            package == "__future__"
            or package in self.excluded_packages
            or package in self.blocked_packages
            or package in seen_packages
        )

    def should_add_root(self, root: str, *, seen_packages: set[str]) -> bool:
        return (
            root not in seen_packages
            and root not in self.excluded_packages
            and root not in self.blocked_packages
            and root not in self.side_effect_packages
            and root not in self.guard_packages
            and root not in self.non_lazy_packages
        )


def _collect_recommended_lazy_entries(
    info: ModuleInfo,
    *,
    always_imported: frozenset[str] = ALWAYS_IMPORTED_DEFAULT,
) -> list[tuple[str, int, int]]:
    """Return ``(package, lineno, col_offset)`` recommendations in source order."""
    bindings = _eager_imports(info)
    guard_names = info.type_checking_guard_names
    non_lazy_names = set(_compute_non_lazy_names(bindings, info.runtime_names))
    guard_packages: set[str] = {
        package
        for binding in bindings
        if (package := binding.package) is not None
        if binding.bound_name in guard_names
    }
    non_lazy_packages: set[str] = {
        package
        for binding in bindings
        if (package := binding.package) is not None
        if _is_non_lazy_binding(binding, non_lazy_names, info.runtime_attribute_paths)
    }
    side_effect_packages = set(info.side_effect_only_packages)
    blocked_packages = (
        side_effect_packages
        | guard_packages
        | set(info.guarded_packages)
        | non_lazy_packages
        | non_lazy_names
        | set(guard_names)
        | set(always_imported)
    )
    policy = _RecommendationPolicy(
        excluded_packages=set(info.enclosing_packages),
        blocked_packages=blocked_packages,
        side_effect_packages=side_effect_packages,
        guard_packages=guard_packages,
        non_lazy_packages=non_lazy_packages,
    )

    recommended: list[tuple[str, int, int]] = []
    seen_packages: set[str] = set()
    for binding in bindings:
        package = binding.package
        if package is None:
            continue
        if policy.should_skip(package, seen_packages=seen_packages):
            continue
        recommended.append((package, binding.lineno, binding.col_offset))
        seen_packages.add(package)

        if "." in package and "{" not in package:
            # Add all parent packages from root to immediate parent.
            parts = package.split(".")
            for index in range(1, len(parts)):
                parent = ".".join(parts[:index])
                if policy.should_add_root(parent, seen_packages=seen_packages):
                    recommended.append((parent, binding.lineno, binding.col_offset))
                    seen_packages.add(parent)

    return recommended


def collect_recommended_lazy_modules(
    info: ModuleInfo,
    *,
    always_imported: frozenset[str] = ALWAYS_IMPORTED_DEFAULT,
) -> list[str]:
    """Return a sorted ``__lazy_modules__`` recommendation for ``info``."""
    return sorted(
        package
        for package, _lineno, _col in _collect_recommended_lazy_entries(
            info, always_imported=always_imported
        )
    )


def collect_missing_lazy_modules(
    info: ModuleInfo,
    *,
    always_imported: frozenset[str] = ALWAYS_IMPORTED_DEFAULT,
) -> list[tuple[str, int, int]]:
    """Return lazy-capable packages missing from ``__lazy_modules__``."""
    if info.has_dynamic_lazy_modules:
        return []
    lazy_modules = info.lazy_packages
    return [
        (package, lineno, col_offset)
        for package, lineno, col_offset in _collect_recommended_lazy_entries(
            info, always_imported=always_imported
        )
        if package not in lazy_modules
    ]


# ---------------------------------------------------------------------------
# Semantic diagnostics (LZY4xx)
# ---------------------------------------------------------------------------


def _check_binding_unnecessary(
    binding: ImportInfo,
    strict_names: frozenset[str],
    strict_attribute_paths: frozenset[str],
    seen_packages: set[str],
    *,
    require_lazy_package: bool,
    lazy_packages: set[str],
) -> bool:
    """Return True if the binding represents an unnecessarily lazy import."""
    package = binding.package
    if package is None:
        return False
    if package == "__future__":
        return False
    if require_lazy_package and package not in lazy_packages:
        return False
    if binding.bound_name not in strict_names:
        return False
    if package in strict_attribute_paths:
        return package not in seen_packages

    root = package.split(".", maxsplit=1)[0]
    if (
        package != binding.bound_name
        and not binding.is_aliased
        and binding.bound_name == root
    ):
        return False
    return package not in seen_packages


def collect_unnecessary_lazy_imports(
    info: ModuleInfo,
) -> list[tuple[str, int, int]]:
    """Return lazy imports whose bound names are used at the strict top level."""
    lazy_packages = info.lazy_packages
    strict_names = info.strict_names
    strict_attribute_paths = info.strict_attribute_paths
    unnecessary: list[tuple[str, int, int]] = []
    seen_packages: set[str] = set()

    candidates = [(binding, True) for binding in _eager_imports(info)] + [
        (binding, False) for binding in _lazy_imports(info)
    ]
    for binding, require_lazy_package in candidates:
        if _check_binding_unnecessary(
            binding,
            strict_names,
            strict_attribute_paths,
            seen_packages,
            require_lazy_package=require_lazy_package,
            lazy_packages=lazy_packages,
        ):
            package = binding.package
            if package is None:
                continue
            unnecessary.append((package, binding.lineno, binding.col_offset))
            seen_packages.add(package)

    return unnecessary


def collect_enclosing_lazy_modules(
    info: ModuleInfo,
) -> list[tuple[str, int, int]]:
    """Return lazily-declared enclosing package modules for the analysed file."""
    enclosing_lazy_modules: list[tuple[str, int, int]] = []
    seen_modules: set[str] = set()

    for module, lineno, col_offset in info.lazy_module_entries:
        if module not in info.enclosing_packages or module in seen_modules:
            continue
        enclosing_lazy_modules.append((module, lineno, col_offset))
        seen_modules.add(module)

    for binding in _lazy_imports(info):
        package = binding.package
        if package is None:
            continue
        if package not in info.enclosing_packages or package in seen_modules:
            continue
        enclosing_lazy_modules.append((package, binding.lineno, binding.col_offset))
        seen_modules.add(package)

    return enclosing_lazy_modules
