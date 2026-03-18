"""Copyright (c) 2026 Henry Schreiner. All rights reserved.

flake8-lazy: Detect imports that can be lazy
"""

from __future__ import annotations

import ast

__version__ = "0.1.0"


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


class LazyImportChecker:
    """flake8 checker for imports that can be made lazy."""

    name = "flake8-lazy"
    version = __version__

    def __init__(self, tree: ast.AST, filename: str) -> None:
        self.tree = tree
        self.filename = filename

    def run(self) -> list[tuple[int, int, str, type[LazyImportChecker]]]:
        collect_top_level_imports(self.tree)
        return []


__all__ = ["LazyImportChecker", "__version__", "collect_top_level_imports"]
