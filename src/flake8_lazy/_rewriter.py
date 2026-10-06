from __future__ import annotations

__lazy_modules__ = [
    "ast",
    "io",
    "tokenize",
    f"{__spec__.parent}._ast_helpers",
    f"{__spec__.parent}._collect",
]

import ast
import io
import tokenize
from typing import TYPE_CHECKING

from ._ast_helpers import (
    format_module_literal,
    is_lazy_modules_target,
    lazy_modules_assignment_value,
    package_for_import_from,
)
from ._collect import collect_top_level_imports, collect_top_level_lazy_imports

__all__ = ["apply_lazy_modules"]

if TYPE_CHECKING:
    from pathlib import Path


#: Maximum length of a single-line ``__lazy_modules__`` assignment before
#: ``--apply`` splits it across multiple lines (black/ruff default).
DEFAULT_LINE_LENGTH = 88


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


def _single_line_assignment(literals: list[str], container: str) -> str:
    joined = ", ".join(literals)
    match container:
        case "tuple":
            # Single-element tuples require a trailing comma.
            inner = f"({joined},)" if len(literals) == 1 else f"({joined})"
        case "set":
            inner = f"{{{joined}}}"
        case "frozenset":
            inner = f"frozenset([{joined}])"
        case _:
            inner = f"[{joined}]"
    return f"__lazy_modules__ = {inner}"


def _multiline_assignment(literals: list[str], container: str, newline: str) -> str:
    """Format the assignment black/ruff-style, one item per line + trailing comma.

    The trailing comma is a "magic trailing comma": it makes black and ruff keep
    the collection exploded across lines instead of collapsing it back.
    """
    items = "".join(f"    {literal},{newline}" for literal in literals)
    match container:
        case "tuple":
            inner = f"({newline}{items})"
        case "set":
            inner = f"{{{newline}{items}}}"
        case "frozenset":
            nested = "".join(f"        {literal},{newline}" for literal in literals)
            inner = f"frozenset({newline}    [{newline}{nested}    ]{newline})"
        case _:
            inner = f"[{newline}{items}]"
    return f"__lazy_modules__ = {inner}"


def _lazy_modules_assignment_line(
    modules: list[str],
    container: str = "list",
    *,
    line_length: int = DEFAULT_LINE_LENGTH,
    newline: str = "\n",
    quote: str = '"',
) -> str:
    literals = [format_module_literal(module, quote) for module in modules]
    single_line = _single_line_assignment(literals, container)
    # A line length of 0 disables splitting: always write a single line.
    if not line_length or len(single_line) <= line_length:
        return single_line
    return _multiline_assignment(literals, container, newline)


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
    block: list[str],
    newline: str,
    lines: list[str],
    insertion_index: int,
) -> list[str]:
    insertion_block = list(block)

    next_line = lines[insertion_index] if insertion_index < len(lines) else None
    if next_line is None or next_line.strip():
        insertion_block.append(newline)

    if insertion_index > 0 and lines[insertion_index - 1].strip():
        insertion_block.insert(0, newline)

    return insertion_block


def _remove_native_lazy_prefixes(tree: ast.Module, lines: list[str]) -> None:
    """Strip the ``lazy`` keyword prefix from natively-lazy imports (Python 3.15+).

    On Python < 3.15 ``collect_top_level_lazy_imports`` returns an empty list,
    so this is always a no-op on those versions.
    """
    for node in collect_top_level_lazy_imports(tree):
        idx = node.lineno - 1
        if 0 <= idx < len(lines):
            line = lines[idx]
            stripped = line.lstrip()
            indent = line[: len(line) - len(stripped)]
            if (
                stripped.startswith("lazy")
                and len(stripped) > 4
                and stripped[4].isspace()
            ):
                lines[idx] = f"{indent}{stripped[4:].lstrip()}"


def _rewrite_lazy_modules_source(
    source: str,
    modules: list[str],
    *,
    forced_container: str | None = None,
    line_length: int = DEFAULT_LINE_LENGTH,
) -> str:
    tree = ast.parse(source)
    assert isinstance(tree, ast.Module)
    newline = "\r\n" if "\r\n" in source else "\n"
    lines = source.splitlines(keepends=True)

    _remove_native_lazy_prefixes(tree, lines)

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
    quote = '"'
    if assignments:
        value = lazy_modules_assignment_value(assignments[0])
        if value is not None:
            container = _detect_container_kind(value)
            # Keep the project's quote style instead of forcing double quotes.
            segment = ast.get_source_segment(source, value) or ""
            quote = next((char for char in segment if char in "'\""), '"')

    if forced_container is not None:
        container = forced_container

    assignment_line = _lazy_modules_assignment_line(
        modules, container, line_length=line_length, newline=newline, quote=quote
    )

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
    block = _build_insertion_block(
        [f"{assignment_line}{newline}"],
        newline,
        lines,
        insertion_index,
    )

    lines[insertion_index:insertion_index] = block
    return "".join(lines)


def _import_alias_packages(
    node: ast.Import | ast.ImportFrom, *, strict_typing: bool
) -> list[str]:
    """Return the package of each alias; ``""`` marks one that cannot be lazy."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    packages = []
    for alias in node.names:
        if alias.name == "*":
            return [""]
        pkg = package_for_import_from(node, alias, strict_typing=strict_typing)
        packages.append(pkg if pkg is not None else "")
    return packages


def _code_before(node: ast.stmt, lines: list[str]) -> bool:
    """Return True if other code comes before ``node`` on its first line."""
    first = lines[node.lineno - 1].encode()
    return bool(first[: node.col_offset].strip())


def _format_aliases(aliases: list[ast.alias]) -> str:
    return ", ".join(
        f"{alias.name} as {alias.asname}" if alias.asname else alias.name
        for alias in aliases
    )


def _split_mixed_import(
    node: ast.Import, lazy_flags: list[bool], lines: list[str], newline: str
) -> list[str] | None:
    """Split ``node`` into an eager ``import`` line and a ``lazy import`` line.

    Returns ``None`` if other code shares the statement's lines, so a split is
    not safe. A trailing comment is kept on both lines (it can be a pragma).
    """
    assert node.end_lineno is not None
    assert node.end_col_offset is not None
    if _code_before(node, lines):
        return None
    last = lines[node.end_lineno - 1]
    body = last.rstrip("\r\n")
    ending = last[len(body) :]
    suffix = body.encode()[node.end_col_offset :].decode().strip()
    suffix = suffix.removeprefix(";").lstrip()
    if suffix and not suffix.startswith("#"):
        return None
    comment = f"  {suffix}" if suffix else ""

    first = lines[node.lineno - 1]
    indent = first[: len(first) - len(first.lstrip())]
    eager = [a for a, lazy in zip(node.names, lazy_flags, strict=True) if not lazy]
    lazy = [a for a, is_lazy in zip(node.names, lazy_flags, strict=True) if is_lazy]
    return [
        f"{indent}import {_format_aliases(eager)}{comment}{newline}",
        f"{indent}lazy import {_format_aliases(lazy)}{comment}{ending}",
    ]


def _rewrite_native_lazy_source(
    source: str, modules: list[str], *, strict_typing: bool = False
) -> str:
    """Rewrite ``source`` by adding ``lazy`` keyword to qualifying imports.

    Any existing ``__lazy_modules__`` assignments are removed. A top-level
    import statement gets a ``lazy `` prefix if all of its aliases map to
    packages in ``modules``. A plain ``import a, b`` where only some aliases
    qualify is split into an eager ``import`` line followed by a
    ``lazy import`` line. Statements that share a line with other code are
    skipped when the edit is not safe.
    """
    tree = ast.parse(source)
    assert isinstance(tree, ast.Module)
    newline = "\r\n" if "\r\n" in source else "\n"
    lines = list(source.splitlines(keepends=True))
    modules_set = set(modules)

    # (start, end, replacement) with 1-based inclusive line numbers.
    edits: list[tuple[int, int, list[str]]] = [
        (stmt.lineno, stmt.end_lineno or stmt.lineno, [])
        for stmt in tree.body
        if _is_lazy_modules_assignment(stmt)
    ]

    for node in collect_top_level_imports(tree):
        packages = _import_alias_packages(node, strict_typing=strict_typing)
        lazy_flags = [pkg in modules_set for pkg in packages]
        if not any(lazy_flags):
            continue
        if all(lazy_flags):
            if _code_before(node, lines):
                continue
            line = lines[node.lineno - 1]
            stripped = line.lstrip()
            indent = line[: len(line) - len(stripped)]
            edits.append((node.lineno, node.lineno, [f"{indent}lazy {stripped}"]))
        elif isinstance(node, ast.Import):
            replacement = _split_mixed_import(node, lazy_flags, lines, newline)
            if replacement is not None:
                assert node.end_lineno is not None
                edits.append((node.lineno, node.end_lineno, replacement))

    # Apply from the bottom up to keep earlier line indices stable.
    for start, end, replacement in sorted(edits, key=lambda e: e[0], reverse=True):
        lines[start - 1 : end] = replacement

    return "".join(lines)


def _rewrite_dynamic_lazy_source(source: str) -> str:
    """Rewrite ``source`` with a dynamic ``AllLazy`` object for ``__lazy_modules__``.

    The assignment is replaced (or inserted) with::

        class AllLazy:
            @staticmethod
            def __contains__(_: str) -> bool:
                return True


        __lazy_modules__ = AllLazy()

    Unlike the static modes, dynamic mode always writes the ``AllLazy`` block
    regardless of whether ``modules`` is non-empty — the caller has explicitly
    requested dynamic coverage.
    """
    tree = ast.parse(source)
    assert isinstance(tree, ast.Module)
    newline = "\r\n" if "\r\n" in source else "\n"
    lines = list(source.splitlines(keepends=True))

    _remove_native_lazy_prefixes(tree, lines)

    assignments = [stmt for stmt in tree.body if _is_lazy_modules_assignment(stmt)]

    alllazy_block = [
        f"class AllLazy:{newline}",
        f"    @staticmethod{newline}",
        f"    def __contains__(_: str) -> bool:{newline}",
        f"        return True{newline}",
        newline,
        newline,
        f"__lazy_modules__ = AllLazy(){newline}",
    ]

    if assignments:
        # Remove extra assignments from the end first (indices are stable going
        # backwards), then replace the first one with the AllLazy block.
        for stmt in reversed(assignments[1:]):
            del lines[stmt.lineno - 1 : stmt.end_lineno]

        first = assignments[0]
        lines[first.lineno - 1 : first.end_lineno] = alllazy_block
        return "".join(lines)

    insertion_line = _insertion_line_for_lazy_modules(tree, source)
    insertion_index = max(0, insertion_line - 1)

    block = _build_insertion_block(alllazy_block, newline, lines, insertion_index)

    lines[insertion_index:insertion_index] = block
    return "".join(lines)


def apply_lazy_modules(
    path: Path,
    modules: list[str],
    *,
    mode: str = "list",
    line_length: int = DEFAULT_LINE_LENGTH,
    strict_typing: bool = False,
) -> None:
    raw_bytes = path.read_bytes()
    encoding, _ = tokenize.detect_encoding(io.BytesIO(raw_bytes).readline)
    source = raw_bytes.decode(encoding)
    match mode:
        case "list":
            updated_source = _rewrite_lazy_modules_source(
                source, modules, forced_container="list", line_length=line_length
            )
        case "tuple":
            updated_source = _rewrite_lazy_modules_source(
                source, modules, forced_container="tuple", line_length=line_length
            )
        case "set":
            updated_source = _rewrite_lazy_modules_source(
                source, modules, forced_container="set", line_length=line_length
            )
        case "native":
            updated_source = _rewrite_native_lazy_source(
                source, modules, strict_typing=strict_typing
            )
        case "dynamic":
            updated_source = _rewrite_dynamic_lazy_source(source)
        case _:
            msg = f"unknown apply mode {mode!r}"
            raise ValueError(msg)
    if updated_source != source:
        path.write_text(updated_source, encoding=encoding, newline="")
