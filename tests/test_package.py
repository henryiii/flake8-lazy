from __future__ import annotations

import ast
import sys
from typing import TYPE_CHECKING

import pytest

from flake8_lazy import LazyImportChecker
from flake8_lazy._always_imported import (
    ALWAYS_IMPORTED_DEFAULT,
    ALWAYS_IMPORTED_MINIMAL,
)
from flake8_lazy._analysis import (
    collect_broken_lazy_modules,
    collect_missing_lazy_modules,
    collect_non_lazy_imports,
    collect_recommended_lazy_modules,
    collect_unnecessary_lazy_imports,
)
from flake8_lazy._ast_helpers import format_module_literal
from flake8_lazy._collect import build_module_info, collect_top_level_imports

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ("module", "quote", "expected"),
    [
        ("numpy", '"', '"numpy"'),
        ("numpy", "'", "'numpy'"),
        ('f"{__spec__.parent}.sub"', '"', 'f"{__spec__.parent}.sub"'),
        ('f"{__spec__.parent}.sub"', "'", "f'{__spec__.parent}.sub'"),
        # Multi-level: the guarded rsplit's quotes must not reuse the outer quote
        # (GH-78), otherwise the f-string is a syntax error on Python < 3.12.
        (
            'f"{(__spec__.parent or "").rsplit(".", 1)[0]}.sub"',
            '"',
            "f\"{(__spec__.parent or '').rsplit('.', 1)[0]}.sub\"",
        ),
        (
            'f"{(__spec__.parent or "").rsplit(".", 1)[0]}.sub"',
            "'",
            'f\'{(__spec__.parent or "").rsplit(".", 1)[0]}.sub\'',
        ),
    ],
)
def test_format_module_literal_quotes(module: str, quote: str, expected: str) -> None:
    rendered = format_module_literal(module, quote)
    assert rendered == expected
    # Every rendering must be a valid string/f-string literal everywhere.
    ast.parse(rendered)


def test_collect_top_level_imports() -> None:
    tree = ast.parse(
        """
import os
from pathlib import Path

if True:
    import typing

def func() -> None:
    import json

class Example:
    import collections
""",
    )

    imports = collect_top_level_imports(tree)

    assert len(imports) == 3
    assert isinstance(imports[0], ast.Import)
    assert isinstance(imports[1], ast.ImportFrom)
    assert isinstance(imports[2], ast.Import)


@pytest.mark.skipif(
    sys.version_info < (3, 15),
    reason="Python 3.15 lazy import AST is required",
)
def test_collect_top_level_imports_ignores_lazy_imports() -> None:
    tree = ast.parse(
        """
import os
lazy import json
lazy from pathlib import Path
""",
    )

    imports = collect_top_level_imports(tree)

    assert len(imports) == 1
    assert isinstance(imports[0], ast.Import)
    assert imports[0].names[0].name == "os"


def test_checker_collects_top_level_imports_without_errors() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["os"]
import os

def func() -> None:
    import json
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")

    assert list(checker.run()) == []


def test_collect_non_lazy_imports_ignores_annotation_and_class_usage() -> None:
    tree = ast.parse(
        """
import os
import sys
from pathlib import Path

value = os.name
typed: Path

class C:
    inner = sys.platform
""",
    )

    assert collect_non_lazy_imports(build_module_info(tree)) == ["os"]


def test_collect_non_lazy_imports_handles_aliases_and_from_imports() -> None:
    tree = ast.parse(
        """
import numpy.linalg as la
from pathlib import Path as P
import typing

vector = la.norm([1, 2, 3])
path = P(".")

def fn() -> None:
    reveal = typing.Any
""",
    )

    assert collect_non_lazy_imports(build_module_info(tree)) == ["la", "P"]


def test_recommended_includes_import_from_submodule() -> None:
    tree = ast.parse(
        """
import cibuildwheel
import cibuildwheel.util
from cibuildwheel.logger import log

def fn() -> None:
    cibuildwheel.util.do_something()
    log("Hello")
""",
    )

    assert collect_recommended_lazy_modules(build_module_info(tree)) == [
        "cibuildwheel",
        "cibuildwheel.logger",
        "cibuildwheel.util",
    ]


def test_recommended_excludes_dotted_import_used_at_top_level() -> None:
    tree = ast.parse(
        """
import importlib.metadata

__version__ = importlib.metadata.version("flake8-lazy")
""",
    )

    assert collect_recommended_lazy_modules(build_module_info(tree)) == []


def test_collect_non_lazy_imports_detects_class_decorator_usage() -> None:
    tree = ast.parse(
        """
from dataclasses import dataclass
import pathlib


@dataclass
class Item:
    path: pathlib.Path
""",
    )

    assert collect_non_lazy_imports(build_module_info(tree)) == ["dataclass"]


def test_collect_non_lazy_imports_detects_class_base_usage() -> None:
    tree = ast.parse(
        """
import ast
import pathlib


class Visitor(ast.NodeVisitor):
    path: pathlib.Path
""",
    )

    assert collect_non_lazy_imports(build_module_info(tree)) == ["ast"]


def test_collect_lazy_packages() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["numpy", "pandas"]
""",
    )

    assert build_module_info(tree).lazy_packages == {"numpy", "pandas"}


def test_checker_emits_lzy102_for_missing_lazy_packages() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["pandas"]
import numpy
import pandas as pd
from sklearn import metrics

value = metrics
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    assert len(errors) == 1
    assert errors[0][2] == "LZY102 module 'numpy' should be listed in __lazy_modules__"


def test_collect_side_effect_only_import_packages_basic() -> None:
    tree = ast.parse(
        """
import logging.config
import os
""",
    )

    # logging.config is a dotted unaliased import and logging is never loaded;
    # os is a plain import so it is not side-effect-only.
    result = build_module_info(tree).side_effect_only_packages

    assert result == {"logging.config"}


def test_collect_side_effect_only_import_ignored_when_bound_name_used() -> None:
    tree = ast.parse(
        """
import logging.config

logging.basicConfig()
""",
    )

    # `logging` is loaded via attribute access, so the import is NOT side-effect-only.
    result = build_module_info(tree).side_effect_only_packages

    assert result == set()


def test_collect_side_effect_only_import_ignored_when_aliased() -> None:
    tree = ast.parse(
        """
import logging.config as lc
""",
    )

    # `as lc` means the caller intends to use the binding explicitly.
    result = build_module_info(tree).side_effect_only_packages

    assert result == set()


def test_checker_ignores_side_effect_only_import_for_lzy101() -> None:
    tree = ast.parse(
        """
import email.header
""",
    )

    # email.header is a stdlib dotted import and email is never used
    # — treat it as a side-effect import and emit no LZY101 error.
    checker = LazyImportChecker(tree=tree, filename="example.py")

    assert list(checker.run()) == []


def test_checker_ignores_side_effect_only_import_for_lzy102() -> None:
    tree = ast.parse(
        """
import pkg.plugin
""",
    )

    # pkg.plugin is a dotted import whose bound name pkg is never used.
    checker = LazyImportChecker(tree=tree, filename="example.py")

    lzy10x_errors = [e for e in checker.run() if e[2].startswith(("LZY101", "LZY102"))]
    assert lzy10x_errors == []


def test_checker_still_flags_dotted_import_when_bound_name_is_used() -> None:
    tree = ast.parse(
        """
import email.header

def process() -> None:
    msg = email.header.decode_header("=?utf-8?b?dGVzdA==?=")
""",
    )

    # `email` is used inside a function, so it is not side-effect-only
    # (it IS in all loaded names) and should still be flagged as LZY101.
    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy10x_errors = [e for e in errors if e[2].startswith(("LZY101", "LZY102"))]
    assert len(lzy10x_errors) == 2
    assert (
        lzy10x_errors[0][2]
        == "LZY101 stdlib module 'email.header' should be listed in __lazy_modules__"
    )
    assert (
        lzy10x_errors[1][2]
        == "LZY101 stdlib module 'email' should be listed in __lazy_modules__"
    )


def test_checker_still_flags_aliased_dotted_import_when_unused() -> None:
    tree = ast.parse(
        """
import email.header as eh
""",
    )

    # The `as` alias signals intentional use of the binding; not side-effect-only.
    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy10x_errors = [e for e in errors if e[2].startswith(("LZY101", "LZY102"))]
    assert len(lzy10x_errors) == 2
    assert (
        lzy10x_errors[0][2]
        == "LZY101 stdlib module 'email.header' should be listed in __lazy_modules__"
    )
    assert (
        lzy10x_errors[1][2]
        == "LZY101 stdlib module 'email' should be listed in __lazy_modules__"
    )


def test_checker_ignores_future_import() -> None:
    tree = ast.parse(
        """
from __future__ import annotations
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")

    assert list(checker.run()) == []


def test_checker_ignores_typing_type_checking_block() -> None:
    tree = ast.parse(
        """
import typing
import numpy

if typing.TYPE_CHECKING:
    reveal = numpy
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    assert len(errors) == 1
    assert errors[0][2] == "LZY102 module 'numpy' should be listed in __lazy_modules__"


def test_checker_ignores_name_type_checking_block() -> None:
    tree = ast.parse(
        """
from typing import TYPE_CHECKING
import numpy

if TYPE_CHECKING:
    reveal = numpy
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    assert len(errors) == 1
    assert errors[0][2] == "LZY102 module 'numpy' should be listed in __lazy_modules__"


def test_checker_ignores_sys_version_info_less_than_314_guard() -> None:
    """Imports guarded by sys.version_info < (3, 14) are ignored.

    They exclude Python 3.15+.
    """
    tree = ast.parse(
        """
import sys

if sys.version_info < (3, 14):
    from importlib.abc import Traversable
else:
    from importlib.resources.abc import Traversable
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    # Only importlib.resources and its submodules should be recommended.
    # importlib.abc should NOT be recommended (guarded if-block excludes 3.15)
    error_msgs = [e[2] for e in errors]
    assert not any("importlib.abc" in msg for msg in error_msgs)
    assert any("importlib.resources" in msg for msg in error_msgs)


def test_checker_includes_sys_version_info_less_than_316_guard() -> None:
    """Imports guarded by sys.version_info < (3, 16) are included.

    They allow Python 3.15.
    """
    tree = ast.parse(
        """
import sys

if sys.version_info < (3, 16):
    import numpy
else:
    import pandas
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    # Both numpy and pandas should be recommended as they both execute in 3.15
    assert len(errors) == 2
    assert any("numpy" in e[2] for e in errors)
    assert any("pandas" in e[2] for e in errors)


def test_checker_includes_sys_version_info_gte_314_guard() -> None:
    """Imports guarded by sys.version_info >= (3, 14) are included.

    They allow Python 3.15.
    """
    tree = ast.parse(
        """
import sys

if sys.version_info >= (3, 14):
    import numpy
else:
    import pandas
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    # Both numpy and pandas should be recommended
    assert len(errors) == 2
    assert any("numpy" in e[2] for e in errors)
    assert any("pandas" in e[2] for e in errors)


def test_checker_ignores_sys_version_info_gte_316_guard() -> None:
    """Imports guarded by sys.version_info >= (3, 16) are ignored.

    They exclude Python 3.15.
    """
    tree = ast.parse(
        """
import sys

if sys.version_info >= (3, 16):
    import numpy
else:
    import pandas
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    # Only pandas should be recommended; numpy is guarded by version
    # check that excludes 3.15
    assert len(errors) == 1
    assert "pandas" in errors[0][2]


def test_checker_requires_explicit_nested_import_package() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["email"]
import email.header

def process() -> None:
    msg = email.header.decode_header("=?utf-8?b?dGVzdA==?=")
""",
    )

    # A child import satisfies the parent package entry in __lazy_modules__.
    # Only the nested module still needs its own lazy declaration.
    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    assert len(errors) == 1
    assert (
        errors[0][2]
        == "LZY101 stdlib module 'email.header' should be listed in __lazy_modules__"
    )


def test_checker_emits_lzy101_for_missing_stdlib_module() -> None:
    tree = ast.parse(
        """
import zoneinfo
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    assert len(errors) == 1
    assert (
        errors[0][2]
        == "LZY101 stdlib module 'zoneinfo' should be listed in __lazy_modules__"
    )


def test_checker_emits_lzy102_for_missing_third_party_module() -> None:
    tree = ast.parse(
        """
import numpy
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    assert len(errors) == 1
    assert errors[0][2] == "LZY102 module 'numpy' should be listed in __lazy_modules__"


def test_checker_does_not_flag_typing_when_used_for_guard_and_annotations() -> None:
    tree = ast.parse(
        """
from typing import Any
import typing

if typing.TYPE_CHECKING:
    import numpy

def fn(x: Any) -> Any:
    return x
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")

    assert list(checker.run()) == []


def test_checker_typing_mixed_any_and_typevar_repro() -> None:
    tree_without_lazy = ast.parse(
        """
from typing import Any, TypeVar

_TProjectBuilder = TypeVar("_TProjectBuilder")

def fn(x: Any) -> Any:
    return x
""",
    )
    checker_without_lazy = LazyImportChecker(
        tree=tree_without_lazy,
        filename="example.py",
    )
    messages_without_lazy = [error[2] for error in checker_without_lazy.run()]

    assert (
        "LZY101 stdlib module 'typing' should be listed in __lazy_modules__"
        not in messages_without_lazy
    )

    tree_with_lazy = ast.parse(
        """
__lazy_modules__ = ["typing"]
from typing import Any, TypeVar

_TProjectBuilder = TypeVar("_TProjectBuilder")

def fn(x: Any) -> Any:
    return x
""",
    )
    checker_with_lazy = LazyImportChecker(tree=tree_with_lazy, filename="example.py")
    messages_with_lazy = [error[2] for error in checker_with_lazy.run()]

    assert (
        "LZY401 module 'typing' is declared lazy but accessed at the top level"
        in messages_with_lazy
    )


def test_checker_uses_spec_parent_syntax_for_relative_import_message() -> None:
    tree = ast.parse(
        """
from .local import helper
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    assert len(errors) == 1
    assert (
        errors[0][2] == "LZY102 module 'f\"{__spec__.parent}.local\"'"
        " should be listed in __lazy_modules__"
    )


def test_checker_ignores_relative_package_only_import() -> None:
    tree = ast.parse(
        """
from . import helper
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")

    assert list(checker.run()) == []


def test_checker_emits_lzy201_for_unsorted_lazy_modules() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["zlib", "abc"]
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy201_errors = [e for e in errors if e[2].startswith("LZY201")]
    assert lzy201_errors == [
        (
            2,
            0,
            "LZY201 __lazy_modules__ should be sorted",
            LazyImportChecker,
        ),
    ]


def test_checker_does_not_emit_lzy201_for_sorted_lazy_modules() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["abc", "zlib"]
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy201_errors = [e for e in errors if e[2].startswith("LZY201")]
    assert lzy201_errors == []


def test_checker_emits_lzy202_for_unused_lazy_module() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["numpy", "pandas"]
import numpy
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    assert len(errors) == 1
    assert (
        errors[0][2]
        == "LZY202 module 'pandas' is listed in __lazy_modules__ but never imported"
    )


def test_checker_does_not_emit_lzy202_when_all_lazy_modules_are_imported() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["numpy", "pandas"]
import numpy
import pandas
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")

    assert list(checker.run()) == []


def test_checker_does_not_emit_lzy202_when_child_module_is_imported() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["packaging"]
import packaging.version
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy202_errors = [e for e in errors if e[2].startswith("LZY202")]
    assert lzy202_errors == []


def test_checker_emits_lzy202_for_annotated_assignment() -> None:
    tree = ast.parse(
        """
from typing import List
__lazy_modules__: List[str] = ["numpy"]
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy202_errors = [e for e in errors if e[2].startswith("LZY202")]
    assert len(lzy202_errors) == 1
    assert (
        lzy202_errors[0][2]
        == "LZY202 module 'numpy' is listed in __lazy_modules__ but never imported"
    )


@pytest.mark.parametrize(
    "container",
    [
        '["numpy"]',
        '("numpy",)',
        '{"numpy"}',
        'list(["numpy"])',
        'list(("numpy",))',
        'tuple(["numpy"])',
        'tuple(("numpy",))',
        'set(["numpy"])',
        'set(("numpy",))',
        'set({"numpy"})',
        'frozenset(["numpy"])',
        'frozenset(("numpy",))',
        'frozenset({"numpy"})',
    ],
)
def test_checker_recognises_all_lazy_modules_container_forms(container: str) -> None:
    tree = ast.parse(
        f"""
__lazy_modules__ = {container}
import numpy
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    assert not any(e[2].startswith("LZY102") for e in errors), (
        f"LZY102 unexpectedly raised for container {container!r}"
    )

    tree = ast.parse(
        """
__lazy_modules__ = ["numpy", "numpy"]
import numpy
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy203_errors = [e for e in errors if e[2].startswith("LZY203")]
    assert lzy203_errors == [
        (
            2,
            0,
            "LZY203 module 'numpy' is duplicated in __lazy_modules__",
            LazyImportChecker,
        ),
    ]


def test_checker_emits_lzy203_once_per_duplicated_module() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["numpy", "numpy", "numpy", "pandas", "pandas"]
import numpy
import pandas
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy203_messages = [e[2] for e in errors if e[2].startswith("LZY203")]
    assert lzy203_messages == [
        "LZY203 module 'numpy' is duplicated in __lazy_modules__",
        "LZY203 module 'pandas' is duplicated in __lazy_modules__",
    ]


def test_checker_emits_lzy204_when_named_module_imported_before_assignment() -> None:
    tree = ast.parse(
        """
import numpy
__lazy_modules__ = ["numpy"]
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy204_errors = [e for e in errors if e[2].startswith("LZY204")]
    assert lzy204_errors == [
        (
            3,
            0,
            "LZY204 __lazy_modules__ should be assigned "
            "before importing modules it names",
            LazyImportChecker,
        ),
    ]


def test_checker_does_not_emit_lzy204_when_lazy_modules_precedes_imports() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["numpy"]
import numpy
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy204_errors = [e for e in errors if e[2].startswith("LZY204")]
    assert lzy204_errors == []


def test_checker_does_not_emit_lzy204_for_future_import_before_lazy_modules() -> None:
    tree = ast.parse(
        """
from __future__ import annotations
__lazy_modules__ = ["numpy"]
import numpy
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy204_errors = [e for e in errors if e[2].startswith("LZY204")]
    assert lzy204_errors == []


def test_checker_does_not_emit_lzy204_for_unrelated_import_before_assignment() -> None:
    tree = ast.parse(
        """
import os
__lazy_modules__ = ["numpy"]
import numpy
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy204_errors = [e for e in errors if e[2].startswith("LZY204")]
    assert lzy204_errors == []


def test_checker_emits_lzy205_for_relative_name_in_lazy_modules() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = [".local"]
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy205_errors = [e for e in errors if e[2].startswith("LZY205")]
    assert lzy205_errors == [
        (
            2,
            20,
            "LZY205 module '.local' in __lazy_modules__ must be absolute",
            LazyImportChecker,
        ),
    ]


def test_checker_does_not_emit_lzy205_for_spec_parent_relative_form() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = [f"{__spec__.parent}.local"]
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy205_errors = [e for e in errors if e[2].startswith("LZY205")]
    assert lzy205_errors == []


def test_checker_emits_lzy206_for_broken_module() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["concurrent.futures"]
import concurrent.futures
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy206_errors = [e for e in errors if e[2].startswith("LZY206")]
    assert lzy206_errors == [
        (
            2,
            20,
            "LZY206 module 'concurrent.futures' is listed in"
            " __lazy_modules__ but is broken under lazy imports",
            LazyImportChecker,
        ),
    ]


def test_checker_emits_lzy206_for_parent_of_broken_module() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["concurrent"]
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy206_errors = [e for e in errors if e[2].startswith("LZY206")]
    assert lzy206_errors == [
        (
            2,
            20,
            "LZY206 module 'concurrent' is listed in"
            " __lazy_modules__ but is broken under lazy imports",
            LazyImportChecker,
        ),
    ]


def test_checker_does_not_emit_lzy206_for_non_broken_module() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["numpy"]
import numpy
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy206_errors = [e for e in errors if e[2].startswith("LZY206")]
    assert lzy206_errors == []


def test_collect_broken_lazy_modules_basic() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["concurrent.futures", "numpy", "concurrent"]
""",
    )

    result = collect_broken_lazy_modules(build_module_info(tree))
    assert result == [
        ("concurrent.futures", 2, 20),
        ("concurrent", 2, 51),
    ]


def test_collect_broken_lazy_modules_empty() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["numpy", "pandas"]
""",
    )

    result = collect_broken_lazy_modules(build_module_info(tree))
    assert result == []


def test_collect_broken_lazy_modules_custom_set() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["foo.bar", "numpy"]
""",
    )

    result = collect_broken_lazy_modules(
        build_module_info(tree), broken=frozenset({"foo.bar"})
    )
    assert result == [("foo.bar", 2, 20)]


def test_collect_strictly_top_level_names_excludes_conditional_blocks() -> None:
    tree = ast.parse(
        """
import re
import os

REGEX = re.compile(".")

if condition:
    x = os.path.join("a", "b")
""",
    )

    names = build_module_info(tree).strict_names

    assert "re" in names
    assert "os" not in names


def test_collect_strictly_top_level_names_excludes_for_while_with_try() -> None:
    tree = ast.parse(
        """
import a
import b
import c
import d

for item in a.items():
    pass

while b.running():
    pass

with c.context():
    pass

try:
    d.connect()
except Exception:
    pass
""",
    )

    names = build_module_info(tree).strict_names

    assert "a" not in names
    assert "b" not in names
    assert "c" not in names
    assert "d" not in names


def test_collect_unnecessary_lazy_imports_basic() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["re"]
import re

REGEX = re.compile(".")
""",
    )

    result = collect_unnecessary_lazy_imports(build_module_info(tree))

    assert len(result) == 1
    assert result[0][0] == "re"


def test_collect_unnecessary_lazy_imports_not_flagged_in_if_block() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["re"]
import re

if __name__ == "__main__":
    REGEX = re.compile(".")
""",
    )

    result = collect_unnecessary_lazy_imports(build_module_info(tree))

    assert result == []


def test_collect_unnecessary_lazy_imports_ignores_unaliased_dotted_root_usage() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["rich.console"]
import rich.console

rich.traceback.install(suppress=[rich], show_locals=False, width=None)
""",
    )

    result = collect_unnecessary_lazy_imports(build_module_info(tree))

    assert result == []


def test_collect_unnecessary_lazy_imports_flags_dotted_package_top_level() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["importlib.metadata"]
import importlib.metadata

__version__ = importlib.metadata.version("flake8-lazy")
""",
    )

    result = collect_unnecessary_lazy_imports(build_module_info(tree))

    assert result == [("importlib.metadata", 3, 0)]


def test_collect_unnecessary_lazy_imports_ignores_enclosing_packages(
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "a" / "b"
    package_dir.mkdir(parents=True)
    (tmp_path / "a" / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    path = package_dir / "c.py"
    source = '__lazy_modules__ = ["a", "a.b"]\nimport a\nimport a.b\n'
    path.write_text(source, encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    result = collect_unnecessary_lazy_imports(build_module_info(tree))

    assert result == []


def test_checker_emits_lzy401_for_lazy_module_accessed_at_top_level() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["re"]
import re

REGEX = re.compile(".")
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy103_errors = [e for e in errors if e[2].startswith("LZY401")]
    assert len(lzy103_errors) == 1
    assert (
        lzy103_errors[0][2]
        == "LZY401 module 're' is declared lazy but accessed at the top level"
    )


def test_checker_does_not_emit_lzy401_for_lazy_module_used_only_in_if_block() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["re"]
import re

if __name__ == "__main__":
    REGEX = re.compile(".")
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy103_errors = [e for e in errors if e[2].startswith("LZY401")]
    assert lzy103_errors == []


def test_checker_does_not_emit_lzy401_for_unaliased_dotted_root_usage() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["rich.console"]
import rich.console

rich.traceback.install(suppress=[rich], show_locals=False, width=None)
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy401_errors = [e for e in errors if e[2].startswith("LZY401")]
    assert lzy401_errors == []


def test_checker_emits_lzy401_for_dotted_package_used_at_top_level() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["importlib.metadata"]
import importlib.metadata

__version__ = importlib.metadata.version("flake8-lazy")
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy401_errors = [e for e in errors if e[2].startswith("LZY401")]
    assert len(lzy401_errors) == 1
    assert (
        lzy401_errors[0][2] == "LZY401 module 'importlib.metadata' is declared lazy"
        " but accessed at the top level"
    )


def test_checker_emits_lzy402_for_enclosing_packages_declared_lazy(
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "a" / "b"
    package_dir.mkdir(parents=True)
    (tmp_path / "a" / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    path = package_dir / "c.py"
    source = '__lazy_modules__ = ["a", "a.b"]\nimport a\nimport a.b\n'
    path.write_text(source, encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    checker = LazyImportChecker(tree=tree, filename=str(path))
    errors = list(checker.run())

    lzy402_errors = [e for e in errors if e[2].startswith("LZY402")]
    assert len(lzy402_errors) == 2
    assert (
        lzy402_errors[0][2]
        == "LZY402 module 'a' is an enclosing package for this file and "
        "should not be declared lazy"
    )
    assert (
        lzy402_errors[1][2]
        == "LZY402 module 'a.b' is an enclosing package for this file and "
        "should not be declared lazy"
    )


@pytest.mark.skipif(
    sys.version_info < (3, 15),
    reason="Python 3.15 lazy import AST is required",
)
def test_checker_emits_lzy402_for_enclosing_packages_with_native_lazy_import(
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "a" / "b"
    package_dir.mkdir(parents=True)
    (tmp_path / "a" / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    path = package_dir / "c.py"
    source = "lazy import a\nlazy import a.b\n"
    path.write_text(source, encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    checker = LazyImportChecker(tree=tree, filename=str(path))
    errors = list(checker.run())

    lzy402_errors = [e for e in errors if e[2].startswith("LZY402")]
    assert len(lzy402_errors) == 2
    assert (
        lzy402_errors[0][2]
        == "LZY402 module 'a' is an enclosing package for this file and "
        "should not be declared lazy"
    )
    assert (
        lzy402_errors[1][2]
        == "LZY402 module 'a.b' is an enclosing package for this file and "
        "should not be declared lazy"
    )


def test_checker_does_not_emit_lzy401_for_lazy_module_used_only_in_function() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["re"]
import re

def func() -> None:
    REGEX = re.compile(".")
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy103_errors = [e for e in errors if e[2].startswith("LZY401")]
    assert lzy103_errors == []


def test_checker_emits_lzy401_for_aliased_lazy_import_accessed_at_top_level() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["re"]
import re as regex

REGEX = regex.compile(".")
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy103_errors = [e for e in errors if e[2].startswith("LZY401")]
    assert len(lzy103_errors) == 1
    assert (
        lzy103_errors[0][2]
        == "LZY401 module 're' is declared lazy but accessed at the top level"
    )


def test_checker_emits_lzy401_for_lazy_from_import_accessed_at_top_level() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["re"]
from re import compile

REGEX = compile(".")
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy103_errors = [e for e in errors if e[2].startswith("LZY401")]
    assert len(lzy103_errors) == 1
    assert (
        lzy103_errors[0][2]
        == "LZY401 module 're' is declared lazy but accessed at the top level"
    )


@pytest.mark.skipif(
    sys.version_info < (3, 15),
    reason="Python 3.15 lazy import AST is required",
)
def test_checker_emits_lzy401_for_native_lazy_import_accessed_at_top_level() -> None:
    tree = ast.parse(
        """
lazy import re

REGEX = re.compile(".")
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy103_errors = [e for e in errors if e[2].startswith("LZY401")]
    assert len(lzy103_errors) == 1
    assert (
        lzy103_errors[0][2]
        == "LZY401 module 're' is declared lazy but accessed at the top level"
    )


# ---------------------------------------------------------------------------
# LZY301: lazy import inside suppress(ImportError) is misleading
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    sys.version_info < (3, 15),
    reason="Python 3.15 lazy import AST is required",
)
def test_checker_emits_lzy301_for_lazy_import_in_suppress_block() -> None:
    tree = ast.parse(
        """
from contextlib import suppress

with suppress(ImportError):
    lazy import numpy
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy301_errors = [e for e in errors if e[2].startswith("LZY301")]
    assert len(lzy301_errors) == 1
    assert (
        lzy301_errors[0][2]
        == "LZY301 lazy import 'numpy' inside suppress(ImportError) is misleading"
    )


@pytest.mark.skipif(
    sys.version_info < (3, 15),
    reason="Python 3.15 lazy import AST is required",
)
def test_checker_emits_lzy301_for_contextlib_suppress_qualified() -> None:
    tree = ast.parse(
        """
import contextlib

with contextlib.suppress(ImportError):
    lazy import numpy
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy301_errors = [e for e in errors if e[2].startswith("LZY301")]
    assert len(lzy301_errors) == 1
    assert (
        lzy301_errors[0][2]
        == "LZY301 lazy import 'numpy' inside suppress(ImportError) is misleading"
    )


@pytest.mark.skipif(
    sys.version_info < (3, 15),
    reason="Python 3.15 lazy import AST is required",
)
def test_checker_emits_lzy301_for_module_not_found_error() -> None:
    tree = ast.parse(
        """
from contextlib import suppress

with suppress(ModuleNotFoundError):
    lazy import numpy
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy301_errors = [e for e in errors if e[2].startswith("LZY301")]
    assert len(lzy301_errors) == 1
    assert (
        lzy301_errors[0][2]
        == "LZY301 lazy import 'numpy' inside suppress(ImportError) is misleading"
    )


@pytest.mark.skipif(
    sys.version_info < (3, 15),
    reason="Python 3.15 lazy import AST is required",
)
def test_checker_does_not_emit_lzy301_for_eager_import_in_suppress_block() -> None:
    tree = ast.parse(
        """
from contextlib import suppress

with suppress(ImportError):
    import numpy
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy301_errors = [e for e in errors if e[2].startswith("LZY301")]
    assert lzy301_errors == []


@pytest.mark.skipif(
    sys.version_info < (3, 15),
    reason="Python 3.15 lazy import AST is required",
)
def test_checker_emits_lzy301_for_lazy_from_import_in_suppress_block() -> None:
    tree = ast.parse(
        """
from contextlib import suppress

with suppress(ImportError):
    lazy from numpy import linalg
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy301_errors = [e for e in errors if e[2].startswith("LZY301")]
    assert len(lzy301_errors) == 1
    assert (
        lzy301_errors[0][2]
        == "LZY301 lazy import 'numpy' inside suppress(ImportError) is misleading"
    )


# ---------------------------------------------------------------------------
# LZY302: module declared lazy by both 'lazy' keyword and __lazy_modules__
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    sys.version_info < (3, 15),
    reason="Python 3.15 lazy import AST is required",
)
def test_checker_emits_lzy302_for_redundant_lazy_declaration() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["numpy"]

lazy import numpy
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy302_errors = [e for e in errors if e[2].startswith("LZY302")]
    assert len(lzy302_errors) == 1
    assert (
        lzy302_errors[0][2] == "LZY302 module 'numpy' is declared lazy"
        " by both 'lazy' keyword and __lazy_modules__"
    )


@pytest.mark.skipif(
    sys.version_info < (3, 15),
    reason="Python 3.15 lazy import AST is required",
)
def test_checker_does_not_emit_lzy302_when_no_overlap() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["pandas"]

lazy import numpy
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy302_errors = [e for e in errors if e[2].startswith("LZY302")]
    assert lzy302_errors == []


@pytest.mark.skipif(
    sys.version_info < (3, 15),
    reason="Python 3.15 lazy import AST is required",
)
def test_checker_emits_lzy302_for_redundant_lazy_from_import() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["numpy"]

lazy from numpy import linalg
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy302_errors = [e for e in errors if e[2].startswith("LZY302")]
    assert len(lzy302_errors) == 1
    assert (
        lzy302_errors[0][2] == "LZY302 module 'numpy' is declared lazy"
        " by both 'lazy' keyword and __lazy_modules__"
    )


# ---------------------------------------------------------------------------
# LZY303: module imported both eagerly and lazily
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    sys.version_info < (3, 15),
    reason="Python 3.15 lazy import AST is required",
)
def test_checker_emits_lzy303_for_mixed_eager_and_lazy_import() -> None:
    tree = ast.parse(
        """
import numpy
lazy import numpy
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy303_errors = [e for e in errors if e[2].startswith("LZY303")]
    assert len(lzy303_errors) == 1
    assert (
        lzy303_errors[0][2]
        == "LZY303 module 'numpy' is imported both eagerly and lazily"
    )


@pytest.mark.skipif(
    sys.version_info < (3, 15),
    reason="Python 3.15 lazy import AST is required",
)
def test_checker_does_not_emit_lzy303_for_lazy_only_import() -> None:
    tree = ast.parse(
        """
lazy import numpy
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy303_errors = [e for e in errors if e[2].startswith("LZY303")]
    assert lzy303_errors == []


@pytest.mark.skipif(
    sys.version_info < (3, 15),
    reason="Python 3.15 lazy import AST is required",
)
def test_checker_emits_lzy303_for_mixed_from_imports() -> None:
    tree = ast.parse(
        """
from numpy import linalg
lazy from numpy import random
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy303_errors = [e for e in errors if e[2].startswith("LZY303")]
    assert len(lzy303_errors) == 1
    assert (
        lzy303_errors[0][2]
        == "LZY303 module 'numpy' is imported both eagerly and lazily"
    )


def test_has_dynamic_lazy_modules_false_for_list() -> None:
    tree = ast.parse('__lazy_modules__ = ["numpy"]\nimport numpy\n')
    assert not build_module_info(tree).has_dynamic_lazy_modules


def test_has_dynamic_lazy_modules_false_when_absent() -> None:
    tree = ast.parse("import numpy\n")
    assert not build_module_info(tree).has_dynamic_lazy_modules


def test_has_dynamic_lazy_modules_true_for_call() -> None:
    tree = ast.parse("__lazy_modules__ = AllLazy()\nimport numpy\n")
    assert build_module_info(tree).has_dynamic_lazy_modules


def test_has_dynamic_lazy_modules_true_for_name() -> None:
    tree = ast.parse("__lazy_modules__ = SOME_CONSTANT\nimport numpy\n")
    assert build_module_info(tree).has_dynamic_lazy_modules


def test_checker_suppresses_lzy102_for_dynamic_lazy_modules() -> None:
    tree = ast.parse(
        "__lazy_modules__ = AllLazy()\nimport numpy\nimport pandas\n",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy10x = [e for e in errors if e[2].startswith(("LZY101", "LZY102"))]
    assert lzy10x == []


def test_checker_suppresses_lzy2xx_for_dynamic_lazy_modules() -> None:
    tree = ast.parse(
        '__lazy_modules__ = AllLazy()\n__lazy_modules__ = ["numpy"]\nimport numpy\n',
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy2xx = [e for e in errors if e[2].startswith("LZY2")]
    assert lzy2xx == []


def test_checker_does_not_flag_always_imported_module_lzy101() -> None:
    # 'sys' and 'time' are in ALWAYS_IMPORTED_DEFAULT; they should never be
    # recommended as lazy imports regardless of how they are used.
    tree = ast.parse(
        """
import sys
import time

def fn() -> None:
    sys.exit(0)
    time.sleep(1)
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy10x = [e for e in errors if e[2].startswith(("LZY101", "LZY102"))]
    assert lzy10x == []


def test_collect_recommended_excludes_always_imported_modules() -> None:
    tree = ast.parse(
        """
import sys
import time
import numpy
""",
    )

    info = build_module_info(tree)

    # With the default preset, sys and time are excluded; only numpy is recommended.
    recommended_default = collect_recommended_lazy_modules(
        info, always_imported=ALWAYS_IMPORTED_DEFAULT
    )
    assert "sys" not in recommended_default
    assert "time" not in recommended_default
    assert "numpy" in recommended_default

    # With no filtering (empty frozenset), sys and time are also candidates.
    recommended_none = collect_recommended_lazy_modules(
        info, always_imported=frozenset()
    )
    assert "sys" in recommended_none
    assert "time" in recommended_none
    assert "numpy" in recommended_none

    # With minimal preset, sys and time are also excluded.
    recommended_minimal = collect_recommended_lazy_modules(
        info, always_imported=ALWAYS_IMPORTED_MINIMAL
    )
    assert "sys" not in recommended_minimal
    assert "time" not in recommended_minimal


def test_always_imported_default_includes_os_path() -> None:
    assert "os.path" in ALWAYS_IMPORTED_DEFAULT


def test_collect_recommended_lazy_modules_skips_blocked_parent_packages() -> None:
    tree = ast.parse(
        """
import os.path

def fn() -> None:
    os.path.join("a", "b")
""",
    )

    assert collect_recommended_lazy_modules(
        build_module_info(tree),
        always_imported=frozenset({"os"}),
    ) == ["os.path"]


def test_collect_recommended_lazy_modules_excludes_try_block_imports() -> None:
    tree = ast.parse(
        """
import rich

try:
    import numpy
except ImportError:
    numpy = None
""",
    )

    # ``numpy`` lives in a try/except block, where it can never be made lazy.
    assert collect_recommended_lazy_modules(build_module_info(tree)) == ["rich"]


def test_collect_missing_lazy_modules_excludes_try_block_imports() -> None:
    tree = ast.parse(
        """
try:
    from ._version import version as __version__
except ImportError:
    __version__ = None
""",
    )

    assert collect_missing_lazy_modules(build_module_info(tree)) == []


def test_checker_does_not_flag_os_path_lzy10x() -> None:
    tree = ast.parse("import os.path\n")

    checker = LazyImportChecker(tree=tree, filename="example.py")
    lzy10x_errors = [e for e in checker.run() if e[2].startswith(("LZY101", "LZY102"))]

    assert lzy10x_errors == []


# ---------------------------------------------------------------------------
# exclude_modules tests
# ---------------------------------------------------------------------------


def test_checker_run_exclude_modules_excludes_module() -> None:
    """Modules in exclude_modules are not flagged as missing from __lazy_modules__."""
    tree = ast.parse("import numpy\n")

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors_without = checker.run(exclude_modules=frozenset())
    errors_with = checker.run(exclude_modules=frozenset({"numpy"}))

    assert any("numpy" in e[2] for e in errors_without)
    assert not any("numpy" in e[2] for e in errors_with)


def test_checker_run_exclude_modules_does_not_affect_other_modules() -> None:
    """Other modules are still flagged even when exclude_modules is set."""
    tree = ast.parse("import numpy\nimport pandas\n")

    checker = LazyImportChecker(tree=tree, filename="example.py")
    errors = checker.run(exclude_modules=frozenset({"numpy"}))

    modules = [e[2] for e in errors]
    assert not any("numpy" in m for m in modules)
    assert any("pandas" in m for m in modules)


# ---------------------------------------------------------------------------
# Regression tests pinning behaviour the single-pass collector must preserve.
# These cover currently-untested edge cases where scope/conditional nesting
# changes which statements a check considers.
# ---------------------------------------------------------------------------


def test_checker_does_not_emit_lzy204_for_import_inside_top_level_if() -> None:
    # The import is nested in a top-level ``if`` (not a direct module-body
    # statement), so it does not count toward late-assignment detection.
    tree = ast.parse(
        """
if True:
    import numpy
__lazy_modules__ = ["numpy"]
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    lzy204 = [e for e in checker.run() if e[2].startswith("LZY204")]
    assert lzy204 == []


def test_checker_does_not_emit_lzy401_for_lazy_module_used_only_in_if_test() -> None:
    # A name used only inside an ``if`` test expression is not a strict
    # top-level use, so the lazy import is not flagged as unnecessary.
    tree = ast.parse(
        """
__lazy_modules__ = ["re"]
import re

if re.match("a", "b"):
    pass
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    lzy401 = [e for e in checker.run() if e[2].startswith("LZY401")]
    assert lzy401 == []


@pytest.mark.skipif(
    sys.version_info < (3, 15),
    reason="Python 3.15 lazy import AST is required",
)
def test_checker_does_not_emit_lzy301_for_lazy_import_in_nested_suppress() -> None:
    # Only ``lazy`` imports that are direct children of a top-level
    # ``suppress(ImportError)`` block are flagged; a suppress nested inside an
    # ``if`` is not scanned.
    tree = ast.parse(
        """
from contextlib import suppress

if True:
    with suppress(ImportError):
        lazy import numpy
""",
    )

    checker = LazyImportChecker(tree=tree, filename="example.py")
    lzy301 = [e for e in checker.run() if e[2].startswith("LZY301")]
    assert lzy301 == []
