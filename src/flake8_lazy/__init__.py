"""Copyright (c) 2026 Henry Schreiner. All rights reserved.

flake8-lazy: Detect imports that can be lazy
"""

from __future__ import annotations

__lazy_modules__ = ["ast", "dataclasses", "pathlib", "sys", "tokenize"]

import ast
import importlib.metadata
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path

__version__ = importlib.metadata.version("flake8-lazy")

__all__ = [
    "LazyImportChecker",
    "__version__",
    "collect_errors_for_file",
    "collect_recommended_lazy_modules",
    "collect_recommended_lazy_modules_for_file",
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


class _TopLevelLazyImportCollector(_TopLevelScopeVisitor):
    """Collect natively-lazy imports executed in module scope (Python 3.15+)."""

    def __init__(self) -> None:
        super().__init__()
        self.imports: list[ast.Import | ast.ImportFrom] = []

    def visit_Import(self, node: ast.Import) -> None:
        if self.in_top_level_scope and _is_lazy_import_node(node):
            self.imports.append(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if self.in_top_level_scope and _is_lazy_import_node(node):
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


def _is_suppress_import_error_call(node: ast.expr) -> bool:
    """Return True if ``node`` is suppress(ImportError/ModuleNotFoundError).

    Recognises both ``suppress(ImportError)`` and
    ``contextlib.suppress(ImportError)``, as well as ``ModuleNotFoundError``.
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        is_suppress = func.id == "suppress"
    elif isinstance(func, ast.Attribute):
        is_suppress = (
            func.attr == "suppress"
            and isinstance(func.value, ast.Name)
            and func.value.id == "contextlib"
        )
    else:
        is_suppress = False
    if not is_suppress:
        return False
    import_error_names = {"ImportError", "ModuleNotFoundError"}
    return any(
        isinstance(arg, ast.Name) and arg.id in import_error_names for arg in node.args
    )


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
        return None

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


def collect_top_level_lazy_imports(tree: ast.AST) -> list[ast.Import | ast.ImportFrom]:
    """Return natively-lazy imports that execute at module scope (Python 3.15+)."""
    collector = _TopLevelLazyImportCollector()
    collector.visit(tree)
    return collector.imports


def _lazy_import_entries(
    stmt: ast.Import | ast.ImportFrom,
) -> list[tuple[str, int, int]]:
    """Return (module, lineno, col_offset) for a single lazy import statement."""
    if isinstance(stmt, ast.Import):
        return [(alias.name, stmt.lineno, stmt.col_offset) for alias in stmt.names]
    # ImportFrom: report the source module once per statement.
    for alias in stmt.names:
        if alias.name == "*":
            continue
        package = _package_for_import_from(stmt, alias)
        if package is not None:
            return [(package, stmt.lineno, stmt.col_offset)]
    return []


def collect_lazy_imports_in_suppress_blocks(
    tree: ast.AST,
) -> list[tuple[str, int, int]]:
    """Return (module, lineno, col_offset) for lazy imports in suppress(ImportError).

    With lazy imports the actual import happens at first use, which occurs
    *outside* the ``with suppress(ImportError):`` block, so the suppression
    has no effect and the author's intent is probably not met.

    Only checks module-level ``with`` statements (Python 3.15+).
    """
    if not isinstance(tree, ast.Module):
        return []

    result: list[tuple[str, int, int]] = []
    for node in tree.body:
        if not isinstance(node, ast.With):
            continue
        if not any(
            _is_suppress_import_error_call(item.context_expr) for item in node.items
        ):
            continue
        for stmt in node.body:
            if not isinstance(stmt, (ast.Import, ast.ImportFrom)):
                continue
            if not _is_lazy_import_node(stmt):
                continue
            result.extend(_lazy_import_entries(stmt))

    return result


def collect_top_level_lazy_import_bindings(tree: ast.AST) -> list[_ImportBinding]:
    """Return package and bound-name details for natively-lazy module-scope imports."""
    bindings: list[_ImportBinding] = []
    for node in collect_top_level_lazy_imports(tree):
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


class _StrictTopLevelRuntimeNameCollector(_TopLevelRuntimeNameCollector):
    """Like _TopLevelRuntimeNameCollector but skips all conditional block bodies."""

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


def collect_side_effect_only_import_packages(tree: ast.AST) -> set[str]:
    """Return packages imported purely for side effects.

    These are unaliased dotted imports (e.g. ``import a.b``) whose top-level
    bound name is never loaded anywhere in the module.  Such imports are used
    only for the side effects of loading the submodule (e.g. registering
    plugins or handlers) and cannot be made lazy without defeating that
    purpose.  Imports with an ``as`` alias are *not* considered side-effect
    only, because the alias shows deliberate intent to use the binding.
    """
    all_loaded = _collect_loaded_names(tree)
    packages: set[str] = set()
    for node in collect_top_level_imports(tree):
        if not isinstance(node, ast.Import):
            continue
        for alias in node.names:
            if alias.asname is not None:
                # `import a.b as ab` — the alias is intentionally used
                continue
            if "." not in alias.name:
                # plain `import a` — not a dotted side-effect import
                continue
            bound_name = alias.name.split(".", maxsplit=1)[0]
            if bound_name not in all_loaded:
                packages.add(alias.name)
    return packages


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
    if not isinstance(tree, ast.Module):
        return []

    duplicated: list[tuple[str, int, int]] = []
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
        if isinstance(node, ast.Import):
            imported_packages.update(alias.name for alias in node.names)
            continue

        if isinstance(node, ast.ImportFrom) and node.module != "__future__":
            imported_packages.update(
                package
                for package in (
                    _package_for_import_from(node, alias) for alias in node.names
                )
                if package is not None
            )
            continue

        is_lazy_modules_assignment = (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__lazy_modules__"
                for target in node.targets
            )
        ) or (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "__lazy_modules__"
        )

        if not is_lazy_modules_assignment:
            continue

        value_node: ast.AST | None = None
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value_node = node.value

        modules = (
            _parse_lazy_module_list(value_node) if value_node is not None else None
        )
        if modules is None:
            continue

        if any(module in imported_packages for module in modules):
            late_assignments.append((node.lineno, node.col_offset))

    return late_assignments


def _collect_recommended_lazy_bindings(tree: ast.AST) -> list[_ImportBinding]:
    """Return module-scope imports that should appear in ``__lazy_modules__``."""
    bindings = collect_top_level_import_bindings(tree)
    non_lazy_names = set(collect_non_lazy_imports(tree))
    guard_names = collect_type_checking_guard_names(tree)
    side_effect_packages = collect_side_effect_only_import_packages(tree)
    guard_packages = {
        binding.package
        for binding in bindings
        if binding.package is not None and binding.bound_name in guard_names
    }

    recommended: list[_ImportBinding] = []
    seen_packages: set[str] = set()
    for binding in bindings:
        if binding.package is None:
            continue
        if binding.package == "__future__":
            continue
        if binding.package in side_effect_packages:
            continue
        if binding.package in guard_packages:
            continue
        if binding.bound_name in non_lazy_names:
            continue
        if binding.bound_name in guard_names:
            continue
        if binding.package in seen_packages:
            continue
        recommended.append(binding)
        seen_packages.add(binding.package)

    return recommended


def collect_recommended_lazy_modules(tree: ast.AST) -> list[str]:
    """Return a sorted ``__lazy_modules__`` recommendation for ``tree``."""
    recommended_modules: list[str] = []
    for binding in _collect_recommended_lazy_bindings(tree):
        package = binding.package
        if package is None:
            continue
        recommended_modules.append(package)
    return sorted(recommended_modules)


def collect_missing_lazy_modules(tree: ast.AST) -> list[tuple[str, int, int]]:
    """Return lazy-capable packages missing from ``__lazy_modules__``."""
    lazy_modules = collect_lazy_packages(tree)
    missing: list[tuple[str, int, int]] = []
    for binding in _collect_recommended_lazy_bindings(tree):
        package = binding.package
        if package is None or package in lazy_modules:
            continue
        missing.append((package, binding.lineno, binding.col_offset))
    return missing


def _check_binding_unnecessary(
    binding: _ImportBinding,
    strict_names: set[str],
    seen_packages: set[str],
    *,
    require_lazy_package: bool,
    lazy_packages: set[str],
) -> bool:
    """Return True if the binding represents an unnecessarily lazy import."""
    if binding.package is None:
        return False
    if binding.package == "__future__":
        return False
    if require_lazy_package and binding.package not in lazy_packages:
        return False
    if binding.bound_name not in strict_names:
        return False
    return binding.package not in seen_packages


def collect_unnecessary_lazy_imports(tree: ast.AST) -> list[tuple[str, int, int]]:
    """Return lazy imports whose bound names are used at the strict module top level."""
    lazy_packages = collect_lazy_packages(tree)
    strict_names = collect_strictly_top_level_names(tree)
    unnecessary: list[tuple[str, int, int]] = []
    seen_packages: set[str] = set()

    for binding in collect_top_level_import_bindings(tree):
        if _check_binding_unnecessary(
            binding,
            strict_names,
            seen_packages,
            require_lazy_package=True,
            lazy_packages=lazy_packages,
        ):
            unnecessary.append((binding.package, binding.lineno, binding.col_offset))  # type: ignore[arg-type]
            seen_packages.add(binding.package)  # type: ignore[arg-type]

    for binding in collect_top_level_lazy_import_bindings(tree):
        if _check_binding_unnecessary(
            binding,
            strict_names,
            seen_packages,
            require_lazy_package=False,
            lazy_packages=lazy_packages,
        ):
            unnecessary.append((binding.package, binding.lineno, binding.col_offset))  # type: ignore[arg-type]
            seen_packages.add(binding.package)  # type: ignore[arg-type]

    return unnecessary


def collect_redundant_lazy_declarations(tree: ast.AST) -> list[tuple[str, int, int]]:
    """Return (module, lineno, col_offset) for ``lazy`` imports in __lazy_modules__.

    A ``lazy import`` statement already makes the import lazy; listing the
    module in ``__lazy_modules__`` as well is redundant.
    """
    lazy_packages = collect_lazy_packages(tree)
    if not lazy_packages:
        return []

    result: list[tuple[str, int, int]] = []
    seen: set[str] = set()
    for binding in collect_top_level_lazy_import_bindings(tree):
        if binding.package is None:
            continue
        if binding.package in lazy_packages and binding.package not in seen:
            result.append((binding.package, binding.lineno, binding.col_offset))
            seen.add(binding.package)
    return result


def collect_mixed_lazy_eager_imports(tree: ast.AST) -> list[tuple[str, int, int]]:
    """Return (module, lineno, col_offset) for modules imported both eagerly and lazily.

    Having both ``import foo`` and ``lazy import foo`` in the same file is
    unusual and likely unintentional; the eager import defeats laziness.
    Reports the ``lazy import`` statement.
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
        if binding.package is None:
            continue
        if binding.package in eager_packages and binding.package not in seen:
            result.append((binding.package, binding.lineno, binding.col_offset))
            seen.add(binding.package)
    return result


def _lazy_module_error_code(module: str) -> str:
    root_module = module.split(".", maxsplit=1)[0]
    if root_module in sys.stdlib_module_names:
        return "LZY101"
    return "LZY102"


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
            stdlib = " stdlib" if code == "LZY101" else ""
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
                    "LZY201 __lazy_modules__ should be sorted",
                    type(self),
                ),
            )

        for module, lineno, col_offset in collect_unused_lazy_modules(self.tree):
            errors.append(
                (
                    lineno,
                    col_offset,
                    (
                        f"LZY202 module '{module}' is listed in __lazy_modules__"
                        " but never imported"
                    ),
                    type(self),
                ),
            )

        for module, lineno, col_offset in collect_duplicate_lazy_modules(self.tree):
            errors.append(
                (
                    lineno,
                    col_offset,
                    f"LZY203 module '{module}' is duplicated in __lazy_modules__",
                    type(self),
                ),
            )

        for lineno, col_offset in collect_late_lazy_module_assignments(self.tree):
            errors.append(
                (
                    lineno,
                    col_offset,
                    (
                        "LZY204 __lazy_modules__ should be assigned before"
                        " importing modules it names"
                    ),
                    type(self),
                ),
            )

        for package, lineno, col_offset in collect_unnecessary_lazy_imports(self.tree):
            errors.append(
                (
                    lineno,
                    col_offset,
                    (
                        f"LZY401 module '{package}' is declared lazy"
                        " but accessed at the top level"
                    ),
                    type(self),
                ),
            )

        for module, lineno, col_offset in collect_lazy_imports_in_suppress_blocks(
            self.tree
        ):
            errors.append(
                (
                    lineno,
                    col_offset,
                    (
                        f"LZY301 lazy import '{module}' inside suppress(ImportError)"
                        " is misleading"
                    ),
                    type(self),
                ),
            )

        for module, lineno, col_offset in collect_redundant_lazy_declarations(
            self.tree
        ):
            errors.append(
                (
                    lineno,
                    col_offset,
                    (
                        f"LZY302 module '{module}' is declared lazy"
                        " by both 'lazy' keyword and __lazy_modules__"
                    ),
                    type(self),
                ),
            )

        for module, lineno, col_offset in collect_mixed_lazy_eager_imports(self.tree):
            errors.append(
                (
                    lineno,
                    col_offset,
                    f"LZY303 module '{module}' is imported both eagerly and lazily",
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


def collect_recommended_lazy_modules_for_file(path: str | Path) -> list[str]:
    """Return a sorted ``__lazy_modules__`` recommendation for a file."""
    item = Path(path)
    try:
        with tokenize.open(item) as f:
            source = f.read()
    except UnicodeDecodeError as exc:
        if sys.version_info >= (3, 11):
            exc.add_note(f"while reading {item}")
        raise
    tree = ast.parse(source, filename=str(item))
    return collect_recommended_lazy_modules(tree)
