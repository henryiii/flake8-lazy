from __future__ import annotations

__lazy_modules__ = ["argparse", "pathlib", "sys"]

import argparse
import ast
import io
import sys
import tokenize
from pathlib import Path

from . import (
    __version__,
    collect_declared_lazy_modules_for_file,
    collect_errors_for_file,
    collect_recommended_lazy_modules_for_file,
)


def _format_lazy_modules(path: Path, modules: list[str]) -> str:
    joined_modules = ", ".join(
        module
        if module.startswith('f"{__spec__.parent') and module.endswith('"')
        else f'"{module}"'
        for module in modules
    )
    return f"{path}: __lazy_modules__ = [{joined_modules}]"


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
            isinstance(target, ast.Name) and target.id == "__lazy_modules__"
            for target in targets
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

    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        future_end_line = max(future_end_line, body[0].end_lineno or body[0].lineno)
        index = 1

    while index < len(body):
        statement = body[index]
        if isinstance(statement, ast.ImportFrom) and statement.module == "__future__":
            future_end_line = max(
                future_end_line,
                statement.end_lineno or statement.lineno,
            )
            index += 1
            continue
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


def _apply_lazy_modules(path: Path, modules: list[str]) -> None:
    raw_bytes = path.read_bytes()
    encoding, _ = tokenize.detect_encoding(io.BytesIO(raw_bytes).readline)
    source = raw_bytes.decode(encoding)
    updated_source = _rewrite_lazy_modules_source(source, modules)
    path.write_text(updated_source, encoding=encoding)


def main(argv: list[str] | None = None) -> None:
    """Run flake8-lazy checks directly from the command line."""
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--format",
        choices=("flake8", "lazy-modules"),
        default="flake8",
        help="output style for results",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="rewrite files to use the recommended __lazy_modules__ declaration",
    )
    namespace = parser.parse_args(list(argv) if argv is not None else None)

    found_errors = False
    for path in namespace.files:
        try:
            recommended_modules = collect_recommended_lazy_modules_for_file(path)
            declared_modules = collect_declared_lazy_modules_for_file(path)
            if namespace.apply and declared_modules != recommended_modules:
                _apply_lazy_modules(path, recommended_modules)
                recommended_modules = collect_recommended_lazy_modules_for_file(path)
                declared_modules = collect_declared_lazy_modules_for_file(path)
            errors = collect_errors_for_file(path)
        except OSError as exc:
            sys.stderr.write(f"{path}:0:0: LZY000 failed to read file ({exc})\n")
            found_errors = True
            continue
        except SyntaxError as exc:
            lineno = exc.lineno if exc.lineno is not None else 0
            col_offset = (exc.offset - 1) if exc.offset is not None else 0
            sys.stderr.write(
                f"{path}:{lineno}:{col_offset}: LZY000 failed to parse Python file\n",
            )
            found_errors = True
            continue

        if (
            namespace.format == "lazy-modules"
            and recommended_modules
            and declared_modules != recommended_modules
        ):
            sys.stdout.write(f"{_format_lazy_modules(path, recommended_modules)}\n")

        for lineno, col_offset, message in errors:
            if namespace.format == "flake8":
                sys.stdout.write(f"{path}:{lineno}:{col_offset}: {message}\n")
            found_errors = True

    if found_errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
