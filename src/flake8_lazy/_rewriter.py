from __future__ import annotations

__lazy_modules__ = [
    "ast",
    f"{__spec__.parent}._ast_helpers",
    f"{__spec__.parent}._visitors",
    "io",
    "tokenize",
]

import ast
import io
import tokenize
from typing import TYPE_CHECKING

from ._ast_helpers import (
    is_lazy_modules_target,
    lazy_modules_assignment_value,
    package_for_import_from,
)
from ._visitors import collect_top_level_imports

__all__ = ["apply_lazy_modules"]

if TYPE_CHECKING:
    from pathlib import Path


def _format_module_literal(module: str) -> str:
    if module.startswith('f"{__spec__.parent') and module.endswith('"'):
        return module
    return f'"{module}"'


_CONTAINER_KINDS: frozenset[str] = frozenset({"list", "tuple", "set", "frozenset"})


def _detect_container_kind(node: ast.AST) -> str:
    """Return the container kind of an existing ``__lazy_modules__`` value node."""
    match node:
        case ast.List():
            return "list"
        case ast.Tuple():
            return "tuple"
        case ast.Set():
            return "set"
        case ast.Call(func=ast.Name(id=name), keywords=[]) if name in _CONTAINER_KINDS:
            return name
        case _:
            return "list"


def _lazy_modules_assignment_line(modules: list[str], container: str = "list") -> str:
    joined_modules = ", ".join(_format_module_literal(module) for module in modules)
    match container:
        case "tuple":
            # Single-element tuples require a trailing comma.
            inner = (
                f"({joined_modules},)" if len(modules) == 1 else f"({joined_modules})"
            )
        case "set":
            inner = f"{{{joined_modules}}}"
        case "frozenset":
            inner = f"frozenset([{joined_modules}])"
        case _:
            inner = f"[{joined_modules}]"
    return f"__lazy_modules__ = {inner}"


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


def _build_insertion_block(
    assignment_line: str,
    newline: str,
    lines: list[str],
    insertion_index: int,
) -> list[str]:
    block = [f"{assignment_line}{newline}"]

    next_line = lines[insertion_index] if insertion_index < len(lines) else None
    if next_line is None or next_line.strip():
        block.append(newline)

    if insertion_index > 0 and lines[insertion_index - 1].strip():
        block.insert(0, newline)

    return block


def _rewrite_lazy_modules_source(
    source: str,
    modules: list[str],
    *,
    forced_container: str | None = None,
) -> str:
    tree = ast.parse(source)
    newline = "\r\n" if "\r\n" in source else "\n"
    lines = source.splitlines(keepends=True)

    assignments = [
        statement for statement in tree.body if _is_lazy_modules_assignment(statement)
    ]

    if not modules:
        # When no modules are recommended, remove any existing declarations
        # rather than writing an empty __lazy_modules__ = [].
        for statement in reversed(assignments):
            del lines[statement.lineno - 1 : statement.end_lineno]
        return "".join(lines)

    container = "list"
    if assignments:
        value = lazy_modules_assignment_value(assignments[0])
        if value is not None:
            container = _detect_container_kind(value)

    if forced_container is not None:
        container = forced_container

    assignment_line = _lazy_modules_assignment_line(modules, container)

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
    block = _build_insertion_block(assignment_line, newline, lines, insertion_index)

    lines[insertion_index:insertion_index] = block
    return "".join(lines)


def _collect_import_lines_to_lazify(
    tree: ast.Module, modules_set: set[str]
) -> set[int]:
    """Return 1-based line numbers of top-level imports to get a ``lazy`` prefix.

    An import statement gets the prefix only if *all* of its aliases map to
    packages that are in ``modules_set``.
    """
    lazy_lines: set[int] = set()
    for node in collect_top_level_imports(tree):
        match node:
            case ast.Import(names=aliases, lineno=lineno):
                packages = {alias.name for alias in aliases}
            case ast.ImportFrom(lineno=lineno):
                packages = set()
                for alias in node.names:
                    if alias.name == "*":
                        packages.add("")
                        break
                    pkg = package_for_import_from(node, alias)
                    packages.add(pkg if pkg is not None else "")
        if packages and packages.issubset(modules_set):
            lazy_lines.add(lineno)
    return lazy_lines


def _rewrite_native_lazy_source(source: str, modules: list[str]) -> str:
    """Rewrite ``source`` by adding ``lazy`` keyword to qualifying imports.

    Any existing ``__lazy_modules__`` assignments are removed.  Each
    top-level import whose module is listed in ``modules`` receives a
    ``lazy `` prefix.
    """
    tree = ast.parse(source)
    assert isinstance(tree, ast.Module)
    lines = list(source.splitlines(keepends=True))
    modules_set = set(modules)

    # Collect __lazy_modules__ assignment spans (1-based lineno, end_lineno).
    assignments = [stmt for stmt in tree.body if _is_lazy_modules_assignment(stmt)]

    # Collect import line numbers to prefix.
    lazy_import_lines = _collect_import_lines_to_lazify(tree, modules_set)

    # Apply deletions and prefixes from highest line to lowest to keep indices stable.
    for lineno in sorted(lazy_import_lines, reverse=True):
        idx = lineno - 1
        line = lines[idx]
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        lines[idx] = f"{indent}lazy {stripped}"

    for stmt in reversed(assignments):
        del lines[stmt.lineno - 1 : stmt.end_lineno]

    return "".join(lines)


def apply_lazy_modules(path: Path, modules: list[str], *, mode: str = "list") -> None:
    raw_bytes = path.read_bytes()
    encoding, _ = tokenize.detect_encoding(io.BytesIO(raw_bytes).readline)
    source = raw_bytes.decode(encoding)
    match mode:
        case "set":
            updated_source = _rewrite_lazy_modules_source(
                source, modules, forced_container="set"
            )
        case "native":
            updated_source = _rewrite_native_lazy_source(source, modules)
        case _:  # "list"
            updated_source = _rewrite_lazy_modules_source(
                source, modules, forced_container="list"
            )
    path.write_text(updated_source, encoding=encoding, newline="")
