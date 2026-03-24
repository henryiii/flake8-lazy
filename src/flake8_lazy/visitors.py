"""AST visitors for scope-sensitive import and runtime-name collection."""

from __future__ import annotations

__lazy_modules__ = [f"{__spec__.parent}.ast_helpers"]

import ast

from .ast_helpers import (
    _bound_name_for_import,
    _collect_loaded_names,
    _is_lazy_import_node,
    _is_type_checking_guard,
)


class _TopLevelScopeVisitor(ast.NodeVisitor):
    """Visit nodes while tracking module-level vs nested scope."""

    __slots__ = ("_scope_depth",)

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

    __slots__ = ("imports",)

    def __init__(self) -> None:
        super().__init__()
        self.imports: list[ast.Import | ast.ImportFrom] = []

    def visit_Import(self, node: ast.Import) -> None:
        if self.in_top_level_scope and not _is_lazy_import_node(node):
            self.imports.append(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if self.in_top_level_scope and not _is_lazy_import_node(node):
            self.imports.append(node)


class _TopLevelLazyImportCollector(_TopLevelScopeVisitor):
    """Collect natively-lazy imports executed in module scope (Python 3.15+)."""

    __slots__ = ("imports",)

    def __init__(self) -> None:
        super().__init__()
        self.imports: list[ast.Import | ast.ImportFrom] = []

    def visit_Import(self, node: ast.Import) -> None:
        if self.in_top_level_scope and _is_lazy_import_node(node):
            self.imports.append(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if self.in_top_level_scope and _is_lazy_import_node(node):
            self.imports.append(node)


class _TypeCheckingGuardNameCollector(_TopLevelScopeVisitor):
    """Collect names used in top-level TYPE_CHECKING guard expressions."""

    __slots__ = ("names",)

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


def collect_top_level_lazy_imports(tree: ast.AST) -> list[ast.Import | ast.ImportFrom]:
    """Return natively-lazy imports that execute at module scope (Python 3.15+)."""
    collector = _TopLevelLazyImportCollector()
    collector.visit(tree)
    return collector.imports


def collect_top_level_imported_names(tree: ast.AST) -> list[str]:
    """Return imported names as bound in module scope."""
    names: list[str] = []
    for node in collect_top_level_imports(tree):
        match node:
            case ast.Import(names=aliases):
                names.extend(
                    _bound_name_for_import(alias, from_import=False)
                    for alias in aliases
                )
            case ast.ImportFrom(names=aliases):
                names.extend(
                    _bound_name_for_import(alias, from_import=True)
                    for alias in aliases
                    if alias.name != "*"
                )
            case _:
                pass
    return names


class _TopLevelRuntimeNameCollector(_TopLevelScopeVisitor):
    """Collect names loaded at module runtime.

    Names in class scopes and annotation contexts are ignored.
    """

    __slots__ = ("_annotation_depth", "names")

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

    def _visit_class_signature(self, node: ast.ClassDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)

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

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_class_signature(node)


def collect_top_level_runtime_names(tree: ast.AST) -> set[str]:
    """Return names loaded at top-level module runtime."""
    collector = _TopLevelRuntimeNameCollector()
    collector.visit(tree)
    return collector.names


class _StrictTopLevelRuntimeNameCollector(_TopLevelRuntimeNameCollector):
    """Like _TopLevelRuntimeNameCollector but skips all conditional block bodies."""

    __slots__ = ()

    def visit_If(self, node: ast.If) -> None:
        pass

    def visit_For(self, node: ast.For) -> None:
        pass

    def visit_While(self, node: ast.While) -> None:
        pass

    def visit_With(self, node: ast.With) -> None:
        pass

    def visit_Try(self, node: ast.Try) -> None:
        pass

    def visit_TryStar(self, node: ast.AST) -> None:  # Python 3.11+ try/except*
        pass


def collect_strictly_top_level_names(tree: ast.AST) -> set[str]:
    """Return names loaded at the strict top level (no conditional blocks)."""
    collector = _StrictTopLevelRuntimeNameCollector()
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
