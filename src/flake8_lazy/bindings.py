"""Import binding extraction utilities."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from .ast_helpers import _bound_name_for_import, _package_for_import_from
from .visitors import collect_top_level_imports, collect_top_level_lazy_imports


@dataclass(frozen=True, slots=True)
class ImportBinding:
    package: str | None
    bound_name: str
    lineno: int
    col_offset: int


def _collect_import_bindings(
    imports: list[ast.Import | ast.ImportFrom],
) -> list[ImportBinding]:
    """Return package and bound-name details for import statements."""
    bindings: list[ImportBinding] = []
    for node in imports:
        match node:
            case ast.Import(names=aliases, lineno=lineno, col_offset=col_offset):
                bindings.extend(
                    ImportBinding(
                        package=alias.name,
                        bound_name=_bound_name_for_import(alias, from_import=False),
                        lineno=lineno,
                        col_offset=col_offset,
                    )
                    for alias in aliases
                )
            case ast.ImportFrom(
                names=aliases,
                lineno=lineno,
                col_offset=col_offset,
            ):
                bindings.extend(
                    ImportBinding(
                        package=_package_for_import_from(node, alias),
                        bound_name=_bound_name_for_import(alias, from_import=True),
                        lineno=lineno,
                        col_offset=col_offset,
                    )
                    for alias in aliases
                    if alias.name != "*"
                )
            case _:
                pass
    return bindings


def collect_top_level_lazy_import_bindings(tree: ast.AST) -> list[ImportBinding]:
    """Return package and bound-name details for natively-lazy module-scope imports."""
    return _collect_import_bindings(collect_top_level_lazy_imports(tree))


def collect_top_level_import_bindings(tree: ast.AST) -> list[ImportBinding]:
    """Return package and bound-name details for module-scope imports."""
    return _collect_import_bindings(collect_top_level_imports(tree))
