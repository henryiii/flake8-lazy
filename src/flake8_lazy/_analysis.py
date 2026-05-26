"""Collection logic for lazy import diagnostics and recommendations."""

from __future__ import annotations

__lazy_modules__ = [
    "ast",
    f"{__spec__.parent}._always_imported",
    f"{__spec__.parent}._ast_helpers",
    f"{__spec__.parent}._bindings",
    f"{__spec__.parent}._visitors",
]

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from ._always_imported import ALWAYS_IMPORTED_DEFAULT
from ._ast_helpers import (
    containing_package_prefixes,
    is_lazy_import_node,
    is_suppress_import_error_call,
    lazy_module_container_elements,
    lazy_modules_assignment_value,
    package_for_import_from,
    parse_lazy_module_list,
    parse_relative_lazy_module,
)
from ._bindings import (
    ImportBinding,
    collect_top_level_import_bindings,
    collect_top_level_lazy_import_bindings,
)
from ._visitors import (
    collect_guarded_import_packages,
    collect_non_lazy_imports,
    collect_strictly_top_level_attribute_paths,
    collect_strictly_top_level_names,
    collect_top_level_imports,
    collect_top_level_lazy_imports,
    collect_top_level_runtime_attribute_paths,
    collect_type_checking_guard_names,
)

__all__ = [
    "collect_declared_lazy_modules",
    "collect_duplicate_lazy_modules",
    "collect_enclosing_lazy_modules",
    "collect_invalid_lazy_module_names",
    "collect_late_lazy_module_assignments",
    "collect_lazy_imports_in_suppress_blocks",
    "collect_lazy_packages",
    "collect_missing_lazy_modules",
    "collect_mixed_lazy_eager_imports",
    "collect_native_lazy_modules",
    "collect_recommended_lazy_modules",
    "collect_redundant_lazy_declarations",
    "collect_side_effect_only_import_packages",
    "collect_unnecessary_lazy_imports",
    "collect_unsorted_lazy_modules",
    "collect_unused_lazy_modules",
    "has_dynamic_lazy_modules",
    "has_native_lazy_imports",
]


def _lazy_import_entries(
    stmt: ast.Import | ast.ImportFrom,
) -> list[tuple[str, int, int]]:
    """Return (module, lineno, col_offset) for a single lazy import statement."""
    match stmt:
        case ast.Import(names=aliases, lineno=lineno, col_offset=col_offset):
            return [(alias.name, lineno, col_offset) for alias in aliases]
        case ast.ImportFrom(names=aliases, lineno=lineno, col_offset=col_offset):
            for alias in aliases:
                if alias.name == "*":
                    continue
                package = package_for_import_from(stmt, alias)
                if package is not None:
                    return [(package, lineno, col_offset)]
            return []
        case _:
            return []  # type: ignore[unreachable]


def collect_lazy_imports_in_suppress_blocks(
    tree: ast.AST,
) -> list[tuple[str, int, int]]:
    """Return (module, lineno, col_offset) for lazy imports in suppress(ImportError)."""
    if not isinstance(tree, ast.Module):
        return []

    result: list[tuple[str, int, int]] = []
    for node in tree.body:
        match node:
            case ast.With(items=items, body=body) if any(
                is_suppress_import_error_call(item.context_expr) for item in items
            ):
                for stmt in body:
                    if not isinstance(stmt, (ast.Import, ast.ImportFrom)):
                        continue
                    if not is_lazy_import_node(stmt):
                        continue
                    result.extend(_lazy_import_entries(stmt))
            case _:
                continue

    return result


def collect_side_effect_only_import_packages(tree: ast.AST) -> set[str]:
    """Return packages imported purely for side effects."""
    all_loaded: set[str] = set()
    for item in ast.walk(tree):
        match item:
            case ast.Name(id=name, ctx=ast.Load()):
                all_loaded.add(name)
            case _:
                pass

    packages: set[str] = set()
    for node in collect_top_level_imports(tree):
        match node:
            case ast.Import(names=aliases):
                for alias in aliases:
                    match alias:
                        case ast.alias(name=name, asname=None) if "." in name:
                            bound_name = name.split(".", maxsplit=1)[0]
                            if bound_name not in all_loaded:
                                packages.add(name)
                        case _:
                            pass
            case _:
                continue
    return packages


def _iter_declared_lazy_module_entries(
    tree: ast.AST,
) -> list[tuple[str, int, int]]:
    """Return parsed ``__lazy_modules__`` entries with source locations."""
    if not isinstance(tree, ast.Module):
        return []

    entries: list[tuple[str, int, int]] = []
    for node in tree.body:
        value_node = lazy_modules_assignment_value(node)
        if value_node is None:
            continue

        elements = lazy_module_container_elements(value_node)
        if elements is None:
            continue

        for element in elements:
            match element:
                case ast.Constant(
                    value=str() as value,
                    lineno=lineno,
                    col_offset=col_offset,
                ):
                    entries.append((value, lineno, col_offset))
                case ast.JoinedStr(
                    lineno=lineno,
                    col_offset=col_offset,
                ):
                    parsed_relative = parse_relative_lazy_module(element)
                    if parsed_relative is not None:
                        entries.append((parsed_relative, lineno, col_offset))
                case _:
                    continue

    return entries


def _iter_static_lazy_module_assignments(
    tree: ast.AST,
) -> list[tuple[ast.Assign | ast.AnnAssign, list[str]]]:
    """Return static ``__lazy_modules__`` assignment nodes with parsed values."""
    if not isinstance(tree, ast.Module):
        return []

    assignments: list[tuple[ast.Assign | ast.AnnAssign, list[str]]] = []
    for node in tree.body:
        value_node = lazy_modules_assignment_value(node)
        if value_node is None:
            continue

        parsed = parse_lazy_module_list(value_node)
        if parsed is None:
            continue

        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            assignments.append((node, parsed))

    return assignments


def collect_declared_lazy_modules(tree: ast.AST) -> list[str] | None:
    """Return the last static ``__lazy_modules__`` declaration, if present."""
    declared: list[str] | None = None
    for _node, modules in _iter_static_lazy_module_assignments(tree):
        declared = modules

    return declared


def has_dynamic_lazy_modules(tree: ast.AST) -> bool:
    """Return True if ``__lazy_modules__`` is assigned a non-static (dynamic) value.

    A dynamic ``__lazy_modules__`` (e.g. a custom object instead of a list/tuple/set)
    is treated as "all modules are declared lazy", so no LZY1xx/LZY2xx errors are
    emitted.
    """
    if not isinstance(tree, ast.Module):
        return False
    for node in tree.body:
        value_node = lazy_modules_assignment_value(node)
        if value_node is None:
            continue
        if lazy_module_container_elements(value_node) is None:
            return True
    return False


def has_native_lazy_imports(tree: ast.AST) -> bool:
    """Return True if the module contains any natively-lazy imports (Python 3.15+).

    On Python < 3.15 this always returns False because ``lazy import`` syntax
    does not exist and the AST cannot contain such nodes.
    """
    return bool(collect_top_level_lazy_imports(tree))


def collect_native_lazy_modules(tree: ast.AST) -> list[str]:
    """Return a sorted list of package names declared via native ``lazy import`` syntax.

    On Python < 3.15 this always returns an empty list.
    """
    packages = [
        binding.package
        for binding in collect_top_level_lazy_import_bindings(tree)
        if binding.package is not None
    ]
    return sorted(set(packages))


def collect_lazy_packages(tree: ast.AST) -> set[str]:
    """Return statically-declared values of ``__lazy_modules__``."""
    lazy_modules: set[str] = set()
    for _node, modules in _iter_static_lazy_module_assignments(tree):
        lazy_modules = set(modules)

    return lazy_modules


def collect_unsorted_lazy_modules(tree: ast.AST) -> list[tuple[int, int]]:
    """Return locations of static ``__lazy_modules__`` assignments that are unsorted."""
    unsorted: list[tuple[int, int]] = []
    for node, modules in _iter_static_lazy_module_assignments(tree):
        if modules != sorted(modules):
            unsorted.append((node.lineno, node.col_offset))

    return unsorted


def _is_imported_package(module: str, imported_packages: set[str]) -> bool:
    """Return True when ``module`` or one of its child modules is imported."""
    return any(
        package == module or package.startswith(f"{module}.")
        for package in imported_packages
    )


def collect_unused_lazy_modules(
    tree: ast.AST,
    filename: str | Path | None = None,
) -> list[tuple[str, int, int]]:
    """Return modules listed in ``__lazy_modules__`` that are never imported."""
    excluded_packages = containing_package_prefixes(filename)
    imported_packages = {
        binding.package
        for binding in collect_top_level_import_bindings(tree)
        if binding.package is not None
    }

    unused: list[tuple[str, int, int]] = []
    for node, modules in _iter_static_lazy_module_assignments(tree):
        unused.extend(
            (module, node.lineno, node.col_offset)
            for module in modules
            if not _is_imported_package(module, imported_packages)
            if module not in excluded_packages
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


def collect_duplicate_lazy_modules(tree: ast.AST) -> list[tuple[str, int, int]]:
    """Return duplicated modules listed in ``__lazy_modules__``."""
    duplicated: list[tuple[str, int, int]] = []
    for node, modules in _iter_static_lazy_module_assignments(tree):
        duplicated.extend(
            (module, node.lineno, node.col_offset)
            for module in _collect_duplicate_modules(modules)
        )

    return duplicated


def collect_late_lazy_module_assignments(tree: ast.AST) -> list[tuple[int, int]]:
    """Return ``__lazy_modules__`` assignments after importing listed modules."""
    if not isinstance(tree, ast.Module):
        return []

    late_assignments: list[tuple[int, int]] = []
    imported_packages: set[str] = set()

    for node in tree.body:
        match node:
            case ast.Import(names=aliases):
                imported_packages.update(alias.name for alias in aliases)
                continue
            case ast.ImportFrom(module=module, names=aliases) if module != "__future__":
                imported_packages.update(
                    package
                    for package in (
                        package_for_import_from(node, alias) for alias in aliases
                    )
                    if package is not None
                )
                continue
            case _:
                pass

        value_node = lazy_modules_assignment_value(node)
        if value_node is None:
            continue

        modules = parse_lazy_module_list(value_node)
        if modules is None:
            continue

        if any(module in imported_packages for module in modules):
            late_assignments.append((node.lineno, node.col_offset))

    return late_assignments


def collect_invalid_lazy_module_names(tree: ast.AST) -> list[tuple[str, int, int]]:
    """Return relative ``__lazy_modules__`` entries that must be absolute."""
    return [
        (module, lineno, col_offset)
        for module, lineno, col_offset in _iter_declared_lazy_module_entries(tree)
        if module.startswith(".")
    ]


def _is_non_lazy_binding(
    binding: ImportBinding,
    non_lazy_names: set[str],
    runtime_attribute_paths: set[str],
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
            and root not in self.side_effect_packages
            and root not in self.guard_packages
            and root not in self.non_lazy_packages
        )


def _collect_recommended_lazy_bindings(
    tree: ast.AST,
    *,
    excluded_packages: set[str] | None = None,
    always_imported: frozenset[str] = ALWAYS_IMPORTED_DEFAULT,
) -> list[ImportBinding]:
    """Return module-scope imports that should appear in ``__lazy_modules__``."""
    if excluded_packages is None:
        excluded_packages = set()

    bindings = collect_top_level_import_bindings(tree)
    non_lazy_names = set(collect_non_lazy_imports(tree))
    runtime_attribute_paths = collect_top_level_runtime_attribute_paths(tree)
    guard_names = collect_type_checking_guard_names(tree)
    side_effect_packages = collect_side_effect_only_import_packages(tree)
    guarded_packages = collect_guarded_import_packages(tree)
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
        if _is_non_lazy_binding(binding, non_lazy_names, runtime_attribute_paths)
    }
    blocked_packages = (
        side_effect_packages
        | guard_packages
        | guarded_packages
        | non_lazy_packages
        | non_lazy_names
        | guard_names
        | always_imported
    )
    policy = _RecommendationPolicy(
        excluded_packages=excluded_packages,
        blocked_packages=blocked_packages,
        side_effect_packages=side_effect_packages,
        guard_packages=guard_packages,
        non_lazy_packages=non_lazy_packages,
    )

    recommended: list[ImportBinding] = []
    seen_packages: set[str] = set()
    for binding in bindings:
        package = binding.package
        if package is None:
            continue
        if policy.should_skip(package, seen_packages=seen_packages):
            continue
        recommended.append(binding)
        seen_packages.add(package)

        if "." in package and "{" not in package:
            # Add all parent packages from root to immediate parent
            parts = package.split(".")
            for i in range(1, len(parts)):
                parent = ".".join(parts[:i])
                if policy.should_add_root(parent, seen_packages=seen_packages):
                    recommended.append(
                        ImportBinding(
                            package=parent,
                            bound_name=parent,
                            lineno=binding.lineno,
                            col_offset=binding.col_offset,
                        )
                    )
                    seen_packages.add(parent)

    return recommended


def collect_recommended_lazy_modules(
    tree: ast.AST,
    filename: str | Path | None = None,
    *,
    always_imported: frozenset[str] = ALWAYS_IMPORTED_DEFAULT,
) -> list[str]:
    """Return a sorted ``__lazy_modules__`` recommendation for ``tree``."""
    excluded_packages = containing_package_prefixes(filename)
    recommended_modules: list[str] = []
    for binding in _collect_recommended_lazy_bindings(
        tree,
        excluded_packages=excluded_packages,
        always_imported=always_imported,
    ):
        package = binding.package
        if package is None:
            continue
        recommended_modules.append(package)
    return sorted(recommended_modules)


def collect_missing_lazy_modules(
    tree: ast.AST,
    filename: str | Path | None = None,
    *,
    always_imported: frozenset[str] = ALWAYS_IMPORTED_DEFAULT,
) -> list[tuple[str, int, int]]:
    """Return lazy-capable packages missing from ``__lazy_modules__``."""
    if has_dynamic_lazy_modules(tree):
        return []
    lazy_modules = collect_lazy_packages(tree)
    excluded_packages = containing_package_prefixes(filename)
    missing: list[tuple[str, int, int]] = []
    for binding in _collect_recommended_lazy_bindings(
        tree,
        excluded_packages=excluded_packages,
        always_imported=always_imported,
    ):
        package = binding.package
        if package is None or package in lazy_modules:
            continue
        missing.append((package, binding.lineno, binding.col_offset))
    return missing


def _check_binding_unnecessary(
    binding: ImportBinding,
    strict_names: set[str],
    strict_attribute_paths: set[str],
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
    tree: ast.AST,
) -> list[tuple[str, int, int]]:
    """Return lazy imports whose bound names are used at the strict module top level."""
    lazy_packages = collect_lazy_packages(tree)
    strict_names = collect_strictly_top_level_names(tree)
    strict_attribute_paths = collect_strictly_top_level_attribute_paths(tree)
    unnecessary: list[tuple[str, int, int]] = []
    seen_packages: set[str] = set()

    for binding in collect_top_level_import_bindings(tree):
        if _check_binding_unnecessary(
            binding,
            strict_names,
            strict_attribute_paths,
            seen_packages,
            require_lazy_package=True,
            lazy_packages=lazy_packages,
        ):
            package = binding.package
            if package is None:
                continue
            unnecessary.append((package, binding.lineno, binding.col_offset))
            seen_packages.add(package)

    for binding in collect_top_level_lazy_import_bindings(tree):
        if _check_binding_unnecessary(
            binding,
            strict_names,
            strict_attribute_paths,
            seen_packages,
            require_lazy_package=False,
            lazy_packages=lazy_packages,
        ):
            package = binding.package
            if package is None:
                continue
            unnecessary.append((package, binding.lineno, binding.col_offset))
            seen_packages.add(package)

    return unnecessary


def collect_enclosing_lazy_modules(
    tree: ast.AST,
    filename: str | Path | None = None,
) -> list[tuple[str, int, int]]:
    """Return lazily-declared enclosing package modules for ``filename``."""
    excluded_packages = containing_package_prefixes(filename)
    enclosing_lazy_modules: list[tuple[str, int, int]] = []
    seen_modules: set[str] = set()

    for module, lineno, col_offset in _iter_declared_lazy_module_entries(tree):
        if module not in excluded_packages:
            continue
        if module in seen_modules:
            continue
        enclosing_lazy_modules.append((module, lineno, col_offset))
        seen_modules.add(module)

    for binding in collect_top_level_lazy_import_bindings(tree):
        package = binding.package
        if package is None:
            continue
        if package not in excluded_packages:
            continue
        if package in seen_modules:
            continue
        enclosing_lazy_modules.append((package, binding.lineno, binding.col_offset))
        seen_modules.add(package)

    return enclosing_lazy_modules


def collect_redundant_lazy_declarations(tree: ast.AST) -> list[tuple[str, int, int]]:
    """Return (module, lineno, col_offset) for ``lazy`` imports in __lazy_modules__."""
    lazy_packages = collect_lazy_packages(tree)
    if not lazy_packages:
        return []

    result: list[tuple[str, int, int]] = []
    seen: set[str] = set()
    for binding in collect_top_level_lazy_import_bindings(tree):
        package = binding.package
        if package is None:
            continue
        if package in lazy_packages and package not in seen:
            result.append((package, binding.lineno, binding.col_offset))
            seen.add(package)
    return result


def collect_mixed_lazy_eager_imports(tree: ast.AST) -> list[tuple[str, int, int]]:
    """Return modules imported both eagerly and lazily.

    Returns tuples of ``(module, lineno, col_offset)``.
    """
    eager_packages = {
        binding.package
        for binding in collect_top_level_import_bindings(tree)
        if binding.package is not None
    }
    if not eager_packages:
        return []

    result: list[tuple[str, int, int]] = []
    seen: set[str] = set()
    for binding in collect_top_level_lazy_import_bindings(tree):
        package = binding.package
        if package is None:
            continue
        if package in eager_packages and package not in seen:
            result.append((package, binding.lineno, binding.col_offset))
            seen.add(package)
    return result
