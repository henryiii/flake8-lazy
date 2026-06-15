"""Single-pass AST collection for lazy-import analysis (Phase 1).

``build_module_info`` walks the parsed module exactly once and returns a
:class:`~flake8_lazy._model.ModuleInfo`.  Every check in ``_analysis`` reads only
that model, so the AST is never traversed again on the analysis path.

The builder always descends into the whole tree (so ``all_loaded_names`` matches
``ast.walk`` semantics, which side-effect-only detection relies on), while a few
state flags decide which buckets each node feeds:

* ``_scope_depth`` — function/class/lambda nesting; gates the runtime/strict
  name buckets and whether an import counts as module-scope.
* ``_annotation_depth`` — inside an annotation; gates runtime/strict (not
  ``all_loaded``).
* ``_conditional_depth`` — inside ``if``/``for``/``while``/``with``/``try``;
  gates the *strict* buckets only.
* ``_try_depth`` — inside ``try``/``except``/``finally``; marks imports that can
  never be made lazy (``lazy`` there is a ``SyntaxError``), so they are dropped
  from recommendations.
* ``_runtime_dead`` — inside a ``TYPE_CHECKING`` if-body, which never runs at
  runtime; suppresses runtime *and* strict name/attribute collection.
* ``_guard_active`` — region blocked from lazy recommendation (``TYPE_CHECKING``
  or a ``sys.version_info`` guard excluding 3.15+); marks imports guarded.

Native ``lazy`` imports inside a top-level ``suppress(ImportError)`` block
(LZY301) are collected directly from the ``with`` body, matching the original's
"direct children only" rule.
"""

from __future__ import annotations

__lazy_modules__ = [
    f"{__spec__.parent}._ast_helpers",
    f"{__spec__.parent}._model",
]

import ast
from typing import TYPE_CHECKING

from ._ast_helpers import (
    bound_name_for_import,
    collect_loaded_names,
    containing_package_prefixes,
    is_lazy_import_node,
    is_suppress_import_error_call,
    is_type_checking_guard,
    lazy_module_container_elements,
    lazy_modules_assignment_value,
    package_for_import_from,
    parse_lazy_module_list,
    parse_relative_lazy_module,
    version_guard_excludes_315_plus,
)
from ._model import ImportInfo, LazyAssignment, ModuleInfo

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

__all__ = [
    "build_module_info",
    "collect_top_level_imports",
    "collect_top_level_lazy_imports",
]


class _ModuleInfoBuilder(ast.NodeVisitor):
    """Collect everything the lazy-import checks need in a single pass."""

    def __init__(self) -> None:
        self._scope_depth = 0
        self._annotation_depth = 0
        self._conditional_depth = 0
        self._try_depth = 0
        self._runtime_dead = False
        self._guard_active = False

        self.imports: list[ImportInfo] = []
        self.static_assignments: list[LazyAssignment] = []
        self.lazy_entries: list[tuple[str, int, int]] = []
        self.suppress_lazy_imports: list[tuple[str, int, int]] = []
        self.declared: list[str] | None = None
        self.has_dynamic = False
        self.late_locations: list[tuple[int, int]] = []
        self.imported_before: set[str] = set()
        self.runtime_names: set[str] = set()
        self.runtime_attrs: set[str] = set()
        self.strict_names: set[str] = set()
        self.strict_attrs: set[str] = set()
        self.all_loaded: set[str] = set()
        self.guard_names: set[str] = set()
        self.guarded_packages: set[str] = set()

    # -- recording helpers ---------------------------------------------------

    @property
    def _at_top_level(self) -> bool:
        """True for direct ``Module.body`` statements (no scope, no block)."""
        return self._scope_depth == 0 and self._conditional_depth == 0

    @property
    def _records_runtime(self) -> bool:
        return (
            self._scope_depth == 0
            and self._annotation_depth == 0
            and not self._runtime_dead
        )

    def _record_name(self, name: str) -> None:
        self.all_loaded.add(name)
        if self._records_runtime:
            self.runtime_names.add(name)
            if self._conditional_depth == 0:
                self.strict_names.add(name)

    def _record_attribute_path(self, path: str) -> None:
        if self._records_runtime:
            self.runtime_attrs.add(path)
            if self._conditional_depth == 0:
                self.strict_attrs.add(path)

    # -- leaf visitors -------------------------------------------------------

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self._record_name(node.id)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.ctx, ast.Load):
            path = _attribute_path(node)
            if path is not None:
                self._record_attribute_path(path)
        self.generic_visit(node)

    # -- imports -------------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        self._record_import(node, is_from=False)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self._record_import(node, is_from=True)

    def _record_import(
        self, node: ast.Import | ast.ImportFrom, *, is_from: bool
    ) -> None:
        if self._scope_depth != 0:
            return
        lazy = is_lazy_import_node(node)
        for alias in node.names:
            if alias.name == "*":
                continue
            package = (
                package_for_import_from(node, alias)
                if isinstance(node, ast.ImportFrom)
                else alias.name
            )
            self.imports.append(
                ImportInfo(
                    package=package,
                    bound_name=bound_name_for_import(alias, from_import=is_from),
                    is_aliased=alias.asname is not None,
                    is_from_import=is_from,
                    is_lazy=lazy,
                    is_guarded=self._guard_active,
                    in_try_block=self._try_depth != 0,
                    runtime_visible=not self._runtime_dead,
                    lineno=node.lineno,
                    col_offset=node.col_offset,
                )
            )

        if not lazy and self._guard_active:
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    package = package_for_import_from(node, alias)
                    if package is not None:
                        self.guarded_packages.add(package)
            else:
                self.guarded_packages.update(alias.name for alias in node.names)

        self._accumulate_imported_before(node)

    def _accumulate_imported_before(self, node: ast.Import | ast.ImportFrom) -> None:
        """Track direct-body imports for late ``__lazy_modules__`` detection."""
        if not self._at_top_level:
            return
        if isinstance(node, ast.Import):
            self.imported_before.update(alias.name for alias in node.names)
        elif node.module != "__future__":
            self.imported_before.update(
                package
                for alias in node.names
                if (package := package_for_import_from(node, alias)) is not None
            )

    # -- assignments / __lazy_modules__ --------------------------------------

    def visit_Assign(self, node: ast.Assign) -> None:
        if self._at_top_level:
            self._handle_lazy_modules(node)
        for target in node.targets:
            self.visit(target)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if self._at_top_level:
            self._handle_lazy_modules(node)
        if node.value is not None:
            self.visit(node.value)
        self._visit_annotation(node.annotation)

    def _handle_lazy_modules(self, node: ast.Assign | ast.AnnAssign) -> None:
        value_node = lazy_modules_assignment_value(node)
        if value_node is None:
            return
        elements = lazy_module_container_elements(value_node)
        if elements is None:
            self.has_dynamic = True
            return
        for element in elements:
            match element:
                case ast.Constant(value=str() as value, lineno=line, col_offset=col):
                    self.lazy_entries.append((value, line, col))
                case ast.JoinedStr(lineno=line, col_offset=col):
                    relative = parse_relative_lazy_module(element)
                    if relative is not None:
                        self.lazy_entries.append((relative, line, col))
                case _:
                    pass
        modules = parse_lazy_module_list(value_node)
        if modules is not None:
            self.static_assignments.append(
                LazyAssignment(modules, node.lineno, node.col_offset)
            )
            self.declared = modules
            if any(module in self.imported_before for module in modules):
                self.late_locations.append((node.lineno, node.col_offset))

    # -- scopes --------------------------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._visit_arguments(node.args)
        self._visit_annotation(node.returns)
        self._visit_body(node.body)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_arguments(node.args)
        self._scope_depth += 1
        self.visit(node.body)
        self._scope_depth -= 1

    def _visit_arguments(self, args: ast.arguments) -> None:
        for default in args.defaults:
            self.visit(default)
        for kw_default in args.kw_defaults:
            if kw_default is not None:
                self.visit(kw_default)
        all_args = [
            *args.posonlyargs,
            *args.args,
            *args.kwonlyargs,
            args.vararg,
            args.kwarg,
        ]
        for arg in all_args:
            if arg is not None:
                self._visit_annotation(arg.annotation)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        self._visit_body(node.body)

    def _visit_body(self, body: list[ast.stmt]) -> None:
        self._scope_depth += 1
        for stmt in body:
            self.visit(stmt)
        self._scope_depth -= 1

    def _visit_annotation(self, node: ast.expr | None) -> None:
        if node is None:
            return
        self._annotation_depth += 1
        self.visit(node)
        self._annotation_depth -= 1

    # -- conditionals --------------------------------------------------------

    def visit_If(self, node: ast.If) -> None:
        if self._scope_depth != 0:
            self._visit_conditional(node)
            return

        test = node.test
        self._conditional_depth += 1
        if is_type_checking_guard(test):
            self.guard_names |= collect_loaded_names(test)
            self._visit_region([test], runtime_dead=True, guard=self._guard_active)
            self._visit_region(node.body, runtime_dead=True, guard=True)
            self._visit_region(node.orelse, runtime_dead=self._runtime_dead, guard=True)
        elif isinstance(test, ast.Compare) and version_guard_excludes_315_plus(test):
            self._visit_region(
                [test], runtime_dead=self._runtime_dead, guard=self._guard_active
            )
            self._visit_region(node.body, runtime_dead=self._runtime_dead, guard=True)
            self._visit_region(
                node.orelse, runtime_dead=self._runtime_dead, guard=self._guard_active
            )
        else:
            self._visit_region(
                [test, *node.body, *node.orelse],
                runtime_dead=self._runtime_dead,
                guard=self._guard_active,
            )
        self._conditional_depth -= 1

    def _visit_region(
        self, nodes: Sequence[ast.AST], *, runtime_dead: bool, guard: bool
    ) -> None:
        previous_dead, previous_guard = self._runtime_dead, self._guard_active
        self._runtime_dead, self._guard_active = runtime_dead, guard
        for node in nodes:
            self.visit(node)
        self._runtime_dead, self._guard_active = previous_dead, previous_guard

    def visit_For(self, node: ast.For) -> None:
        self._visit_conditional(node)

    def visit_While(self, node: ast.While) -> None:
        self._visit_conditional(node)

    def visit_Try(self, node: ast.Try) -> None:
        self._visit_try(node)

    def visit_TryStar(self, node: ast.AST) -> None:  # Python 3.11+ try/except*
        self._visit_try(node)

    def _visit_try(self, node: ast.AST) -> None:
        self._try_depth += 1
        self._visit_conditional(node)
        self._try_depth -= 1

    def visit_With(self, node: ast.With) -> None:
        if self._at_top_level and any(
            is_suppress_import_error_call(item.context_expr) for item in node.items
        ):
            for stmt in node.body:
                if isinstance(
                    stmt, (ast.Import, ast.ImportFrom)
                ) and is_lazy_import_node(stmt):
                    self.suppress_lazy_imports.extend(_lazy_import_entries(stmt))
        self._visit_conditional(node)

    def _visit_conditional(self, node: ast.AST) -> None:
        self._conditional_depth += 1
        self.generic_visit(node)
        self._conditional_depth -= 1


def _lazy_import_entries(
    stmt: ast.Import | ast.ImportFrom,
) -> list[tuple[str, int, int]]:
    """Return ``(module, lineno, col)`` entries for one lazy import statement.

    Plain imports yield one entry per alias; from-imports yield a single entry
    for the first alias that resolves to a package.
    """
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


def _attribute_path(node: ast.Attribute) -> str | None:
    """Return the dotted path of an attribute chain rooted at a ``Name``."""
    parts: list[str] = [node.attr]
    current: ast.expr = node.value
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def build_module_info(tree: ast.AST, filename: str | Path | None = None) -> ModuleInfo:
    """Walk ``tree`` once and return the collected :class:`ModuleInfo`."""
    builder = _ModuleInfoBuilder()
    builder.visit(tree)

    all_loaded = frozenset(builder.all_loaded)
    side_effect_only = frozenset(
        imp.package
        for imp in builder.imports
        if imp.package is not None
        and imp.runtime_visible
        and not imp.is_lazy
        and not imp.is_from_import
        and not imp.is_aliased
        and "." in imp.package
        and imp.bound_name not in all_loaded
    )

    return ModuleInfo(
        imports=tuple(builder.imports),
        static_lazy_assignments=tuple(builder.static_assignments),
        lazy_module_entries=tuple(builder.lazy_entries),
        suppress_lazy_imports=tuple(builder.suppress_lazy_imports),
        declared_lazy_modules=builder.declared,
        has_dynamic_lazy_modules=builder.has_dynamic,
        late_lazy_module_locations=tuple(builder.late_locations),
        runtime_names=frozenset(builder.runtime_names),
        runtime_attribute_paths=frozenset(builder.runtime_attrs),
        strict_names=frozenset(builder.strict_names),
        strict_attribute_paths=frozenset(builder.strict_attrs),
        all_loaded_names=all_loaded,
        type_checking_guard_names=frozenset(builder.guard_names),
        guarded_packages=frozenset(builder.guarded_packages),
        side_effect_only_packages=side_effect_only,
        enclosing_packages=frozenset(containing_package_prefixes(filename)),
    )


# ---------------------------------------------------------------------------
# Node-returning collectors used by the source rewriter (``--apply``).
#
# The rewriter re-parses its own tree and needs the raw ``ast.Import`` /
# ``ast.ImportFrom`` nodes (for ``.names``/``.end_lineno``), so it keeps a small
# dedicated walk rather than going through ``ModuleInfo``.
# ---------------------------------------------------------------------------


class _TopLevelImportNodeCollector(ast.NodeVisitor):
    """Collect module-scope import nodes, matching ``lazy`` keyword status."""

    def __init__(self, *, lazy: bool) -> None:
        self._depth = 0
        self._lazy = lazy
        self.nodes: list[ast.Import | ast.ImportFrom] = []

    def _visit_nested(self, node: ast.AST) -> None:
        self._depth += 1
        self.generic_visit(node)
        self._depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_nested(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_nested(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_nested(node)

    def visit_Try(self, node: ast.Try) -> None:
        self._visit_nested(node)

    def visit_TryStar(self, node: ast.AST) -> None:  # Python 3.11+ try/except*
        self._visit_nested(node)

    def visit_If(self, node: ast.If) -> None:
        if is_type_checking_guard(node.test):
            for item in node.orelse:
                self.visit(item)
            return
        self.generic_visit(node)

    def _record(self, node: ast.Import | ast.ImportFrom) -> None:
        if self._depth == 0 and is_lazy_import_node(node) == self._lazy:
            self.nodes.append(node)

    def visit_Import(self, node: ast.Import) -> None:
        self._record(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self._record(node)


def collect_top_level_imports(tree: ast.AST) -> list[ast.Import | ast.ImportFrom]:
    """Return eager module-scope import nodes.

    Excludes the ``TYPE_CHECKING`` body and ``try``/``except``/``finally`` blocks,
    where the ``lazy`` keyword is not permitted.
    """
    collector = _TopLevelImportNodeCollector(lazy=False)
    collector.visit(tree)
    return collector.nodes


def collect_top_level_lazy_imports(
    tree: ast.AST,
) -> list[ast.Import | ast.ImportFrom]:
    """Return native ``lazy`` module-scope import nodes (Python 3.15+)."""
    collector = _TopLevelImportNodeCollector(lazy=True)
    collector.visit(tree)
    return collector.nodes
