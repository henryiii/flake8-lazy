"""flake8 checker implementation."""

from __future__ import annotations

__lazy_modules__ = [
    f"{__spec__.parent}.analysis",
    "importlib",
    "importlib.metadata",
    "sys",
]

import importlib.metadata
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import ast

from .analysis import (
    collect_duplicate_lazy_modules,
    collect_enclosing_lazy_modules,
    collect_invalid_lazy_module_names,
    collect_late_lazy_module_assignments,
    collect_lazy_imports_in_suppress_blocks,
    collect_missing_lazy_modules,
    collect_mixed_lazy_eager_imports,
    collect_redundant_lazy_declarations,
    collect_unnecessary_lazy_imports,
    collect_unsorted_lazy_modules,
    collect_unused_lazy_modules,
)


def _lazy_module_error_code(module: str) -> str:
    root_module = module.split(".", maxsplit=1)[0]
    if root_module in sys.stdlib_module_names:
        return "LZY101"
    return "LZY102"


class LazyImportChecker:
    """flake8 checker for imports that can be made lazy."""

    name = "flake8-lazy"
    version = importlib.metadata.version("flake8-lazy")
    __slots__ = ("filename", "tree")

    def __init__(self, tree: ast.AST, filename: str) -> None:
        self.tree = tree
        self.filename = filename

    def _build_missing_lazy_module_errors(
        self,
    ) -> list[tuple[int, int, str, type[LazyImportChecker]]]:
        errors: list[tuple[int, int, str, type[LazyImportChecker]]] = []
        for package, lineno, col_offset in collect_missing_lazy_modules(
            self.tree,
            filename=self.filename,
        ):
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
        return errors

    def _build_lazy_module_validation_errors(
        self,
    ) -> list[tuple[int, int, str, type[LazyImportChecker]]]:
        errors: list[tuple[int, int, str, type[LazyImportChecker]]] = []
        for lineno, col_offset in collect_unsorted_lazy_modules(self.tree):
            errors.append(
                (
                    lineno,
                    col_offset,
                    "LZY201 __lazy_modules__ should be sorted",
                    type(self),
                ),
            )

        for module, lineno, col_offset in collect_unused_lazy_modules(
            self.tree,
            filename=self.filename,
        ):
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

        for module, lineno, col_offset in collect_invalid_lazy_module_names(self.tree):
            errors.append(
                (
                    lineno,
                    col_offset,
                    f"LZY205 module '{module}' in __lazy_modules__ must be absolute",
                    type(self),
                ),
            )

        return errors

    def _build_lazy_keyword_errors(
        self,
    ) -> list[tuple[int, int, str, type[LazyImportChecker]]]:
        errors: list[tuple[int, int, str, type[LazyImportChecker]]] = []
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

    def _build_semantic_lazy_errors(
        self,
    ) -> list[tuple[int, int, str, type[LazyImportChecker]]]:
        errors: list[tuple[int, int, str, type[LazyImportChecker]]] = []
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
        for package, lineno, col_offset in collect_enclosing_lazy_modules(
            self.tree,
            filename=self.filename,
        ):
            errors.append(
                (
                    lineno,
                    col_offset,
                    (
                        f"LZY402 module '{package}' is an enclosing package"
                        " for this file and should not be declared lazy"
                    ),
                    type(self),
                ),
            )
        return errors

    def run(self) -> list[tuple[int, int, str, type[LazyImportChecker]]]:
        errors: list[tuple[int, int, str, type[LazyImportChecker]]] = []
        errors.extend(self._build_missing_lazy_module_errors())
        errors.extend(self._build_lazy_module_validation_errors())
        errors.extend(self._build_lazy_keyword_errors())
        errors.extend(self._build_semantic_lazy_errors())
        return errors
