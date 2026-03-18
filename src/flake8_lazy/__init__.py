"""Copyright (c) 2026 Henry Schreiner. All rights reserved.

flake8-lazy: Detect imports that can be lazy
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

__version__ = "0.1.0"


@dataclass(frozen=True)
class _ImportBinding:
    package: str | None
    bound_name: str
    lineno: int
    col_offset: int


class _TopLevelImportCollector(ast.NodeVisitor):
    """Collect imports that are executed in module scope."""

    def __init__(self) -> None:
        self.imports: list[ast.Import | ast.ImportFrom] = []
        self._scope_depth = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scope_depth += 1
        self.generic_visit(node)
        self._scope_depth -= 1

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._scope_depth += 1
        self.generic_visit(node)
        self._scope_depth -= 1

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope_depth += 1
        self.generic_visit(node)
        self._scope_depth -= 1

    def visit_Import(self, node: ast.Import) -> None:
        if self._scope_depth == 0:
            self.imports.append(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if self._scope_depth == 0:
            self.imports.append(node)


def collect_top_level_imports(tree: ast.AST) -> list[ast.Import | ast.ImportFrom]:
    """Return all imports that execute at module scope in ``tree``."""
    collector = _TopLevelImportCollector()
    collector.visit(tree)
    return collector.imports


def _bound_name_for_import(alias: ast.alias, *, from_import: bool) -> str:
    if alias.asname is not None:
        return alias.asname
    if from_import:
        return alias.name
    return alias.name.split(".", maxsplit=1)[0]


def collect_top_level_imported_names(tree: ast.AST) -> list[str]:
    """Return imported names as bound in module scope."""
    names: list[str] = []
    for node in collect_top_level_imports(tree):
        if isinstance(node, ast.Import):
            names.extend(
                _bound_name_for_import(alias, from_import=False)
                for alias in node.names
            )
        else:
            names.extend(
                _bound_name_for_import(alias, from_import=True)
                for alias in node.names
                if alias.name != "*"
            )
    return names


def collect_top_level_import_bindings(tree: ast.AST) -> list[_ImportBinding]:
    """Return package and bound-name details for module-scope imports."""
    bindings: list[_ImportBinding] = []
    for node in collect_top_level_imports(tree):
        if isinstance(node, ast.Import):
            bindings.extend(
                _ImportBinding(
                    package=alias.name.split(".", maxsplit=1)[0],
                    bound_name=_bound_name_for_import(alias, from_import=False),
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                )
                for alias in node.names
            )
        else:
            package = (
                node.module.split(".", maxsplit=1)[0]
                if node.module is not None
                else None
            )
            bindings.extend(
                _ImportBinding(
                    package=package,
                    bound_name=_bound_name_for_import(alias, from_import=True),
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                )
                for alias in node.names
                if alias.name != "*"
            )
    return bindings


class _TopLevelRuntimeNameCollector(ast.NodeVisitor):
    """Collect names loaded at module runtime.

    Names in class scopes and annotation contexts are ignored.
    """

    def __init__(self) -> None:
        self.names: set[str] = set()
        self._annotation_depth = 0
        self._scope_depth = 0

    def _visit_annotation(self, node: ast.AST | None) -> None:
        if node is None:
            return
        self._annotation_depth += 1
        self.visit(node)
        self._annotation_depth -= 1

    def visit_Name(self, node: ast.Name) -> None:
        if (
            self._annotation_depth == 0
            and self._scope_depth == 0
            and isinstance(node.ctx, ast.Load)
        ):
            self.names.add(node.id)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
        self._visit_annotation(node.annotation)

    def visit_arg(self, node: ast.arg) -> None:
        self._visit_annotation(node.annotation)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self.visit(target)
        self.visit(node.value)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in node.args.defaults:
            self.visit(default)
        for default in node.args.kw_defaults:
            if default is not None:
                self.visit(default)
        self._visit_annotation(node.returns)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in node.args.defaults:
            self.visit(default)
        for default in node.args.kw_defaults:
            if default is not None:
                self.visit(default)
        self._visit_annotation(node.returns)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for default in node.args.defaults:
            self.visit(default)
        for default in node.args.kw_defaults:
            if default is not None:
                self.visit(default)
        self._scope_depth += 1
        self.visit(node.body)
        self._scope_depth -= 1

    def visit_ClassDef(self, _node: ast.ClassDef) -> None:
        return


def collect_top_level_runtime_names(tree: ast.AST) -> set[str]:
    """Return names loaded at top-level module runtime."""
    collector = _TopLevelRuntimeNameCollector()
    collector.visit(tree)
    return collector.names


def collect_non_lazy_imports(tree: ast.AST) -> list[str]:
    """Return imported names that are used at top-level runtime."""
    imported_names = collect_top_level_imported_names(tree)
    used_names = collect_top_level_runtime_names(tree)
    non_lazy: list[str] = []
    seen: set[str] = set()
    for name in imported_names:
        if name in used_names and name not in seen:
            non_lazy.append(name)
            seen.add(name)
    return non_lazy


def _parse_lazy_package_list(node: ast.AST) -> set[str] | None:
    if not isinstance(node, ast.List):
        return None
    packages: set[str] = set()
    for element in node.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            return None
        packages.add(element.value)
    return packages


def collect_lazy_packages(tree: ast.AST) -> set[str]:
    """Return statically-declared values of ``__lazy_packages__``."""
    if not isinstance(tree, ast.Module):
        return set()

    lazy_packages: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == "__lazy_packages__"
                for target in node.targets
            ):
                parsed = _parse_lazy_package_list(node.value)
                if parsed is not None:
                    lazy_packages = parsed
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "__lazy_packages__"
        ):
            parsed = (
                _parse_lazy_package_list(node.value)
                if node.value is not None
                else None
            )
            if parsed is not None:
                lazy_packages = parsed

    return lazy_packages


def collect_missing_lazy_packages(tree: ast.AST) -> list[tuple[str, int, int]]:
    """Return lazy-capable packages missing from ``__lazy_packages__``."""
    non_lazy_names = set(collect_non_lazy_imports(tree))
    lazy_packages = collect_lazy_packages(tree)

    missing: list[tuple[str, int, int]] = []
    seen_packages: set[str] = set()
    for binding in collect_top_level_import_bindings(tree):
        if binding.package is None:
            continue
        if binding.bound_name in non_lazy_names:
            continue
        if binding.package in lazy_packages or binding.package in seen_packages:
            continue
        missing.append((binding.package, binding.lineno, binding.col_offset))
        seen_packages.add(binding.package)

    return missing


class LazyImportChecker:
    """flake8 checker for imports that can be made lazy."""

    name = "flake8-lazy"
    version = __version__

    def __init__(self, tree: ast.AST, filename: str) -> None:
        self.tree = tree
        self.filename = filename

    def run(self) -> list[tuple[int, int, str, type[LazyImportChecker]]]:
        errors: list[tuple[int, int, str, type[LazyImportChecker]]] = []
        for package, lineno, col_offset in collect_missing_lazy_packages(self.tree):
            errors.append(
                (
                    lineno,
                    col_offset,
                    f"LZY001 package '{package}' should be listed in __lazy_packages__",
                    type(self),
                ),
            )
        return errors


__all__ = [
    "LazyImportChecker",
    "__version__",
    "collect_lazy_packages",
    "collect_missing_lazy_packages",
    "collect_non_lazy_imports",
    "collect_top_level_import_bindings",
    "collect_top_level_imported_names",
    "collect_top_level_imports",
    "collect_top_level_runtime_names",
]
