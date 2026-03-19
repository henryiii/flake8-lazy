"""Copyright (c) 2026 Henry Schreiner. All rights reserved.

flake8-lazy: Detect imports that can be lazy
"""

from __future__ import annotations

__lazy_modules__ = ["argparse", "ast", "dataclasses", "pathlib", "sys", "tokenize"]

import argparse
import ast
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path

__version__ = "0.1.0"

__all__ = [
    "LazyImportChecker",
    "__version__",
    "main",
]


def __dir__() -> list[str]:
    return __all__


@dataclass(frozen=True)
class _ImportBinding:
    package: str | None
    bound_name: str
    lineno: int
    col_offset: int


class _TopLevelScopeVisitor(ast.NodeVisitor):
    """Visit nodes while tracking module-level vs nested scope."""

    def __init__(self) -> None:
        self._scope_depth = 0

    @property
    def in_top_level_scope(self) -> bool:
        return self._scope_depth == 0

    def _visit_nested_scope(self, node: ast.AST) -> None:
        self._scope_depth += 1
        self.generic_visit(node)
        self._scope_depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_nested_scope(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_nested_scope(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_nested_scope(node)

    def visit_If(self, node: ast.If) -> None:
        if _is_type_checking_guard(node.test):
            for item in node.orelse:
                self.visit(item)
            return
        self.generic_visit(node)


class _TopLevelImportCollector(_TopLevelScopeVisitor):
    """Collect imports that are executed in module scope."""

    def __init__(self) -> None:
        super().__init__()
        self.imports: list[ast.Import | ast.ImportFrom] = []

    def visit_Import(self, node: ast.Import) -> None:
        if self.in_top_level_scope and not _is_lazy_import_node(node):
            self.imports.append(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if self.in_top_level_scope and not _is_lazy_import_node(node):
            self.imports.append(node)


def _is_lazy_import_node(node: ast.Import | ast.ImportFrom) -> bool:
    return False if sys.version_info < (3, 15) else bool(node.is_lazy)  # type: ignore[union-attr]


def _is_type_checking_guard(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "TYPE_CHECKING"
    if isinstance(node, ast.Attribute):
        return (
            isinstance(node.value, ast.Name)
            and node.value.id == "typing"
            and node.attr == "TYPE_CHECKING"
        )
    return False


def _collect_loaded_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for item in ast.walk(node):
        if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load):
            names.add(item.id)
    return names


class _TypeCheckingGuardNameCollector(_TopLevelScopeVisitor):
    """Collect names used in top-level TYPE_CHECKING guard expressions."""

    def __init__(self) -> None:
        super().__init__()
        self.names: set[str] = set()

    def visit_If(self, node: ast.If) -> None:
        if self.in_top_level_scope and _is_type_checking_guard(node.test):
            self.names.update(_collect_loaded_names(node.test))
            for item in node.orelse:
                self.visit(item)
            return
        self.generic_visit(node)


def collect_type_checking_guard_names(tree: ast.AST) -> set[str]:
    """Return names used in module-scope TYPE_CHECKING guards."""
    collector = _TypeCheckingGuardNameCollector()
    collector.visit(tree)
    return collector.names


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


def _package_for_import_from(node: ast.ImportFrom, alias: ast.alias) -> str | None:
    if alias.name == "*":
        return None

    prefix = "." * node.level
    if node.module is None:
        return f"{prefix}{alias.name}"

    root_module = node.module.split(".", maxsplit=1)[0]
    return f"{prefix}{root_module}"


def collect_top_level_imported_names(tree: ast.AST) -> list[str]:
    """Return imported names as bound in module scope."""
    names: list[str] = []
    for node in collect_top_level_imports(tree):
        if isinstance(node, ast.Import):
            names.extend(
                _bound_name_for_import(alias, from_import=False) for alias in node.names
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
                    package=alias.name,
                    bound_name=_bound_name_for_import(alias, from_import=False),
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                )
                for alias in node.names
            )
        else:
            bindings.extend(
                _ImportBinding(
                    package=_package_for_import_from(node, alias),
                    bound_name=_bound_name_for_import(alias, from_import=True),
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                )
                for alias in node.names
                if alias.name != "*"
            )
    return bindings


class _TopLevelRuntimeNameCollector(_TopLevelScopeVisitor):
    """Collect names loaded at module runtime.

    Names in class scopes and annotation contexts are ignored.
    """

    def __init__(self) -> None:
        super().__init__()
        self.names: set[str] = set()
        self._annotation_depth = 0

    def _visit_annotation(self, node: ast.AST | None) -> None:
        if node is None:
            return
        self._annotation_depth += 1
        self.visit(node)
        self._annotation_depth -= 1

    def visit_Name(self, node: ast.Name) -> None:
        if (
            self._annotation_depth == 0
            and self.in_top_level_scope
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

    def _visit_function_signature(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in node.args.defaults:
            self.visit(default)
        for kw_default in node.args.kw_defaults:
            if kw_default is None:
                continue
            self.visit(kw_default)
        self._visit_annotation(node.returns)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function_signature(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function_signature(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for default in node.args.defaults:
            self.visit(default)
        for kw_default in node.args.kw_defaults:
            if kw_default is None:
                continue
            self.visit(kw_default)
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


def _parse_lazy_module_list(node: ast.AST) -> list[str] | None:
    if not isinstance(node, ast.List):
        return None
    modules: list[str] = []
    for element in node.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            return None
        modules.append(element.value)
    return modules


def _parse_lazy_module_set(node: ast.AST) -> set[str] | None:
    parsed = _parse_lazy_module_list(node)
    if parsed is None:
        return None
    return set(parsed)


def collect_lazy_packages(tree: ast.AST) -> set[str]:
    """Return statically-declared values of ``__lazy_modules__``."""
    if not isinstance(tree, ast.Module):
        return set()

    lazy_modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == "__lazy_modules__"
                for target in node.targets
            ):
                parsed_assign = _parse_lazy_module_set(node.value)
                if parsed_assign is not None:
                    lazy_modules = parsed_assign
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "__lazy_modules__"
        ):
            parsed_annassign = (
                _parse_lazy_module_set(node.value) if node.value is not None else None
            )
            if parsed_annassign is not None:
                lazy_modules = parsed_annassign

    return lazy_modules


def collect_unsorted_lazy_modules(tree: ast.AST) -> list[tuple[int, int]]:
    """Return locations of static ``__lazy_modules__`` assignments that are unsorted."""
    if not isinstance(tree, ast.Module):
        return []

    unsorted: list[tuple[int, int]] = []
    for node in tree.body:
        value_node: ast.AST | None = None
        match node:
            case ast.Assign(targets=targets, value=value) if any(
                isinstance(target, ast.Name) and target.id == "__lazy_modules__"
                for target in targets
            ):
                value_node = value
            case ast.AnnAssign(target=ast.Name(id="__lazy_modules__"), value=value):
                value_node = value

        if value_node is None:
            continue

        values = _parse_lazy_module_list(value_node)
        if values is None:
            continue
        if values != sorted(values):
            unsorted.append((node.lineno, node.col_offset))

    return unsorted


def collect_unused_lazy_modules(tree: ast.AST) -> list[tuple[str, int, int]]:
    """Return modules listed in ``__lazy_modules__`` that are never imported."""
    if not isinstance(tree, ast.Module):
        return []

    imported_packages = {
        binding.package
        for binding in collect_top_level_import_bindings(tree)
        if binding.package is not None
    }

    unused: list[tuple[str, int, int]] = []
    for node in tree.body:
        value_node: ast.AST | None = None
        match node:
            case ast.Assign(targets=targets, value=value) if any(
                isinstance(target, ast.Name) and target.id == "__lazy_modules__"
                for target in targets
            ):
                value_node = value
            case ast.AnnAssign(target=ast.Name(id="__lazy_modules__"), value=value) if (
                value is not None
            ):
                value_node = value

        if value_node is None:
            continue

        modules = _parse_lazy_module_list(value_node)
        if modules is None:
            continue

        unused.extend(
            (module, node.lineno, node.col_offset)
            for module in modules
            if module not in imported_packages
        )

    return unused


def collect_missing_lazy_modules(tree: ast.AST) -> list[tuple[str, int, int]]:
    """Return lazy-capable packages missing from ``__lazy_modules__``."""
    bindings = collect_top_level_import_bindings(tree)
    non_lazy_names = set(collect_non_lazy_imports(tree))
    guard_names = collect_type_checking_guard_names(tree)
    lazy_modules = collect_lazy_packages(tree)
    guard_packages = {
        binding.package
        for binding in bindings
        if binding.package is not None and binding.bound_name in guard_names
    }

    missing: list[tuple[str, int, int]] = []
    seen_packages: set[str] = set()
    for binding in bindings:
        if binding.package is None:
            continue
        if binding.package == "__future__":
            continue
        if binding.package in guard_packages:
            continue
        if binding.bound_name in non_lazy_names:
            continue
        if binding.bound_name in guard_names:
            continue
        if binding.package in lazy_modules or binding.package in seen_packages:
            continue
        missing.append((binding.package, binding.lineno, binding.col_offset))
        seen_packages.add(binding.package)

    return missing


def _lazy_module_error_code(module: str) -> str:
    root_module = module.split(".", maxsplit=1)[0]
    if root_module in sys.stdlib_module_names:
        return "LZY001"
    return "LZY002"


class LazyImportChecker:
    """flake8 checker for imports that can be made lazy."""

    name = "flake8-lazy"
    version = __version__

    def __init__(self, tree: ast.AST, filename: str) -> None:
        self.tree = tree
        self.filename = filename

    def run(self) -> list[tuple[int, int, str, type[LazyImportChecker]]]:
        errors: list[tuple[int, int, str, type[LazyImportChecker]]] = []
        for package, lineno, col_offset in collect_missing_lazy_modules(self.tree):
            code = _lazy_module_error_code(package)
            stdlib = " stdlib" if code == "LZY001" else ""
            errors.append(
                (
                    lineno,
                    col_offset,
                    (
                        f"{code}{stdlib} module '{package}' should be listed in "
                        "__lazy_modules__"
                    ),
                    type(self),
                ),
            )

        for lineno, col_offset in collect_unsorted_lazy_modules(self.tree):
            errors.append(
                (
                    lineno,
                    col_offset,
                    "LZY101 __lazy_modules__ should be sorted",
                    type(self),
                ),
            )

        for module, lineno, col_offset in collect_unused_lazy_modules(self.tree):
            errors.append(
                (
                    lineno,
                    col_offset,
                    (
                        f"LZY102 module '{module}' is listed in __lazy_modules__"
                        " but never imported"
                    ),
                    type(self),
                ),
            )

        return errors


def collect_errors_for_file(path: str | Path) -> list[tuple[int, int, str]]:
    """Return checker errors for a single Python file."""
    item = Path(path)
    try:
        with tokenize.open(item) as f:
            source = f.read()
    except UnicodeDecodeError as exc:
        if sys.version_info >= (3, 11):
            exc.add_note(f"while reading {item}")
        raise
    tree = ast.parse(source, filename=str(item))
    checker = LazyImportChecker(tree=tree, filename=str(item))
    return [(line, col, message) for line, col, message, _checker in checker.run()]


def main(argv: list[str] | None = None) -> None:
    """Run flake8-lazy checks directly from the command line."""
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("files", nargs="+", type=Path)
    namespace = parser.parse_args(list(argv) if argv is not None else None)

    found_errors = False
    for path in namespace.files:
        try:
            errors = collect_errors_for_file(path)
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

        for lineno, col_offset, message in errors:
            sys.stdout.write(f"{path}:{lineno}:{col_offset}: {message}\n")
            found_errors = True

    if found_errors:
        raise SystemExit(1)
