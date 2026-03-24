"""Internal AST helpers for flake8-lazy."""

from __future__ import annotations

__lazy_modules__ = ["ast", "pathlib", "sys"]

import ast
import sys
from pathlib import Path


def _is_lazy_import_node(node: ast.Import | ast.ImportFrom) -> bool:
    return False if sys.version_info < (3, 15) else bool(node.is_lazy)  # type: ignore[union-attr]


def _is_type_checking_guard(node: ast.AST) -> bool:
    match node:
        case ast.Name(id="TYPE_CHECKING"):
            return True
        case ast.Attribute(value=ast.Name(id="typing"), attr="TYPE_CHECKING"):
            return True
        case _:
            return False


def _is_import_error_name(node: ast.AST) -> bool:
    match node:
        case ast.Name(id="ImportError" | "ModuleNotFoundError"):
            return True
        case _:
            return False


def _is_suppress_import_error_call(node: ast.expr) -> bool:
    """Return True if ``node`` is suppress(ImportError/ModuleNotFoundError)."""
    match node:
        case ast.Call(func=ast.Name(id="suppress"), args=args):
            return any(_is_import_error_name(arg) for arg in args)
        case ast.Call(
            func=ast.Attribute(value=ast.Name(id="contextlib"), attr="suppress"),
            args=args,
        ):
            return any(_is_import_error_name(arg) for arg in args)
        case _:
            return False


def _collect_loaded_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for item in ast.walk(node):
        match item:
            case ast.Name(id=name, ctx=ast.Load()):
                names.add(name)
            case _:
                pass
    return names


def _bound_name_for_import(alias: ast.alias, *, from_import: bool) -> str:
    if alias.asname is not None:
        return alias.asname
    if from_import:
        return alias.name
    return alias.name.split(".", maxsplit=1)[0]


def _relative_parent_expression(*, level: int) -> str:
    if level == 1:
        return "__spec__.parent"
    return f'__spec__.parent.rsplit(".", {level - 1})[0]'


def _relative_import_package_name(*, level: int, root_module: str) -> str:
    parent_expression = _relative_parent_expression(level=level)
    return f'f"{{{parent_expression}}}.{root_module}"'


def _relative_parent_level(node: ast.AST) -> int | None:
    match node:
        case ast.Attribute(value=ast.Name(id="__spec__"), attr="parent"):
            return 1
        case ast.Subscript(
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Attribute(
                        value=ast.Name(id="__spec__"),
                        attr="parent",
                    ),
                    attr="rsplit",
                ),
                args=[
                    ast.Constant(value="."),
                    ast.Constant(value=int() as level_minus_one),
                ],
                keywords=[],
            ),
            slice=ast.Constant(value=0),
        ):
            return level_minus_one + 1
        case _:
            return None


def _parse_relative_lazy_module(node: ast.JoinedStr) -> str | None:
    match node:
        case ast.JoinedStr(
            values=[
                ast.FormattedValue(
                    value=expression,
                    conversion=-1,
                    format_spec=None,
                ),
                ast.Constant(value=str() as suffix),
            ],
        ) if suffix.startswith("."):
            level = _relative_parent_level(expression)
            if level is None:
                return None

            root_module = suffix.removeprefix(".")
            if not root_module:
                return None

            return _relative_import_package_name(level=level, root_module=root_module)
        case _:
            return None


def _containing_package_prefixes(filename: str | Path | None) -> set[str]:
    """Return enclosing package names for a file based on ``__init__.py`` parents."""
    if filename is None:
        return set()

    path = Path(filename)
    if path.name in {"-", "stdin"}:
        return set()

    current_dir = path.parent
    package_parts: list[str] = []
    while (current_dir / "__init__.py").is_file():
        package_parts.insert(0, current_dir.name)
        parent_dir = current_dir.parent
        if parent_dir == current_dir:
            break
        current_dir = parent_dir

    return {
        ".".join(package_parts[:index]) for index in range(1, len(package_parts) + 1)
    }


def _package_for_import_from(node: ast.ImportFrom, alias: ast.alias) -> str | None:
    match alias:
        case ast.alias(name="*"):
            return None
        case _:
            pass

    match node:
        case ast.ImportFrom(module=None):
            return None
        case ast.ImportFrom(module=str() as module, level=0):
            return module
        case ast.ImportFrom(module=str() as module, level=level):
            root_module = module.split(".", maxsplit=1)[0]
            return _relative_import_package_name(level=level, root_module=root_module)
        case _:
            return None


def _is_lazy_modules_target(node: ast.AST) -> bool:
    match node:
        case ast.Name(id="__lazy_modules__"):
            return True
        case _:
            return False


def _lazy_modules_assignment_value(node: ast.AST) -> ast.AST | None:
    match node:
        case ast.Assign(targets=targets, value=value) if any(
            _is_lazy_modules_target(target) for target in targets
        ):
            return value
        case ast.AnnAssign(target=ast.Name(id="__lazy_modules__"), value=value):
            return value
        case _:
            return None


def _parse_lazy_module_list(node: ast.AST) -> list[str] | None:
    match node:
        case ast.List(elts=elements):
            pass
        case _:
            return None

    modules: list[str] = []
    for element in elements:
        match element:
            case ast.Constant(value=str() as value):
                modules.append(value)
            case ast.JoinedStr():
                parsed_relative = _parse_relative_lazy_module(element)
                if parsed_relative is None:
                    return None
                modules.append(parsed_relative)
            case _:
                return None
    return modules
