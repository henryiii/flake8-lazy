from __future__ import annotations

import ast

import flake8_lazy as m


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

    imports = m.collect_top_level_imports(tree)

    assert len(imports) == 3
    assert isinstance(imports[0], ast.Import)
    assert isinstance(imports[1], ast.ImportFrom)
    assert isinstance(imports[2], ast.Import)


def test_checker_collects_top_level_imports_without_errors() -> None:
    tree = ast.parse(
        """
import os
__lazy_modules__ = ["os"]

def func() -> None:
    import json
""",
    )

    checker = m.LazyImportChecker(tree=tree, filename="example.py")

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

    assert m.collect_non_lazy_imports(tree) == ["os"]


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

    assert m.collect_non_lazy_imports(tree) == ["la", "P"]


def test_collect_lazy_packages() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["numpy", "pandas"]
""",
    )

    assert m.collect_lazy_packages(tree) == {"numpy", "pandas"}


def test_checker_emits_lzy001_for_missing_lazy_packages() -> None:
    tree = ast.parse(
        """
import numpy
import pandas as pd
from sklearn import metrics

value = metrics
__lazy_modules__ = ["pandas"]
""",
    )

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    assert len(errors) == 1
    assert errors[0][2] == "LZY002 module 'numpy' should be listed in __lazy_modules__"


def test_checker_ignores_future_import() -> None:
    tree = ast.parse(
        """
from __future__ import annotations
""",
    )

    checker = m.LazyImportChecker(tree=tree, filename="example.py")

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

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    assert len(errors) == 1
    assert errors[0][2] == "LZY002 module 'numpy' should be listed in __lazy_modules__"


def test_checker_ignores_name_type_checking_block() -> None:
    tree = ast.parse(
        """
from typing import TYPE_CHECKING
import numpy

if TYPE_CHECKING:
    reveal = numpy
""",
    )

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    assert len(errors) == 1
    assert errors[0][2] == "LZY002 module 'numpy' should be listed in __lazy_modules__"


def test_checker_requires_explicit_nested_import_package() -> None:
    tree = ast.parse(
        """
import email.header
__lazy_modules__ = ["email"]
""",
    )

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    assert len(errors) == 1
    assert (
        errors[0][2]
        == "LZY001 stdlib module 'email.header' should be listed in __lazy_modules__"
    )


def test_checker_emits_lzy001_for_missing_stdlib_module() -> None:
    tree = ast.parse(
        """
import zoneinfo
""",
    )

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    assert len(errors) == 1
    assert (
        errors[0][2]
        == "LZY001 stdlib module 'zoneinfo' should be listed in __lazy_modules__"
    )


def test_checker_emits_lzy002_for_missing_third_party_module() -> None:
    tree = ast.parse(
        """
import numpy
""",
    )

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    assert len(errors) == 1
    assert errors[0][2] == "LZY002 module 'numpy' should be listed in __lazy_modules__"


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

    checker = m.LazyImportChecker(tree=tree, filename="example.py")

    assert list(checker.run()) == []


def test_checker_preserves_relative_import_prefix_in_message() -> None:
    tree = ast.parse(
        """
from .local import helper
""",
    )

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    assert len(errors) == 1
    assert errors[0][2] == "LZY002 module '.local' should be listed in __lazy_modules__"
