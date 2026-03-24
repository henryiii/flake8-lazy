from __future__ import annotations

__lazy_modules__ = ["ast", f"{__spec__.parent}._ast_helpers", "io", "tokenize"]

import ast
import io
import tokenize
from typing import TYPE_CHECKING

from ._ast_helpers import is_lazy_modules_target

__all__ = ["apply_lazy_modules"]

if TYPE_CHECKING:
    from pathlib import Path


def _format_module_literal(module: str) -> str:
    if module.startswith('f"{__spec__.parent') and module.endswith('"'):
        return module
    return f'"{module}"'


def _lazy_modules_assignment_line(modules: list[str]) -> str:
    joined_modules = ", ".join(_format_module_literal(module) for module in modules)
    return f"__lazy_modules__ = [{joined_modules}]"


def _is_lazy_modules_assignment(node: ast.stmt) -> bool:
    match node:
        case ast.Assign(targets=targets) if any(
            is_lazy_modules_target(target) for target in targets
        ):
            return True
        case ast.AnnAssign(target=ast.Name(id="__lazy_modules__")):
            return True
        case _:
            return False


def _first_non_comment_non_string_line(source: str) -> int | None:
    stream = io.StringIO(source)
    for token_info in tokenize.generate_tokens(stream.readline):
        if token_info.type in {
            tokenize.COMMENT,
            tokenize.ENCODING,
            tokenize.ENDMARKER,
            tokenize.NL,
            tokenize.NEWLINE,
            tokenize.STRING,
        }:
            continue
        return token_info.start[0]
    return None


def _insertion_line_for_lazy_modules(tree: ast.Module, source: str) -> int:
    future_end_line = 0
    body = tree.body
    index = 0

    match body:
        case [
            ast.Expr(
                value=ast.Constant(value=str()),
                lineno=lineno,
                end_lineno=end_lineno,
            ),
            *_rest,
        ]:
            future_end_line = max(future_end_line, end_lineno or lineno)
            index = 1
        case _:
            pass

    while index < len(body):
        match body[index]:
            case ast.ImportFrom(module="__future__", lineno=lineno, end_lineno=end):
                future_end_line = max(
                    future_end_line,
                    end or lineno,
                )
                index += 1
                continue
            case _:
                break

    first_line = _first_non_comment_non_string_line(source)
    if first_line is None:
        return len(source.splitlines()) + 1

    return max(first_line, future_end_line + 1)


def _rewrite_lazy_modules_source(source: str, modules: list[str]) -> str:
    tree = ast.parse(source)
    assignment_line = _lazy_modules_assignment_line(modules)
    newline = "\r\n" if "\r\n" in source else "\n"
    lines = source.splitlines(keepends=True)

    assignments = [
        statement for statement in tree.body if _is_lazy_modules_assignment(statement)
    ]

    if assignments:
        first_assignment = assignments[0]
        lines[first_assignment.lineno - 1 : first_assignment.end_lineno] = [
            f"{assignment_line}{newline}",
        ]

        for statement in reversed(assignments[1:]):
            del lines[statement.lineno - 1 : statement.end_lineno]

        return "".join(lines)

    insertion_line = _insertion_line_for_lazy_modules(tree, source)
    insertion_index = max(0, insertion_line - 1)
    block = [f"{assignment_line}{newline}"]

    if insertion_index < len(lines):
        if lines[insertion_index].strip():
            block.append(newline)
    elif lines:
        if lines[-1].strip():
            block.append(newline)
    else:
        block.append(newline)

    lines[insertion_index:insertion_index] = block
    return "".join(lines)


def apply_lazy_modules(path: Path, modules: list[str]) -> None:
    raw_bytes = path.read_bytes()
    encoding, _ = tokenize.detect_encoding(io.BytesIO(raw_bytes).readline)
    source = raw_bytes.decode(encoding)
    updated_source = _rewrite_lazy_modules_source(source, modules)
    path.write_text(updated_source, encoding=encoding, newline="")
