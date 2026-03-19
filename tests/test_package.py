from __future__ import annotations

import ast
import sys

import pytest

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

    imports = m.collect_top_level_imports(tree)

    assert len(imports) == 1
    assert isinstance(imports[0], ast.Import)
    assert imports[0].names[0].name == "os"


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


def test_checker_emits_lzy102_for_missing_lazy_packages() -> None:
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
    assert errors[0][2] == "LZY102 module 'numpy' should be listed in __lazy_modules__"


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

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    assert len(errors) == 1
    assert errors[0][2] == "LZY102 module 'numpy' should be listed in __lazy_modules__"


def test_checker_requires_explicit_nested_import_package() -> None:
    tree = ast.parse(
        """
import email.header
__lazy_modules__ = ["email"]
""",
    )

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    assert len(errors) == 2
    assert (
        errors[0][2]
        == "LZY101 stdlib module 'email.header' should be listed in __lazy_modules__"
    )
    assert (
        errors[1][2]
        == "LZY202 module 'email' is listed in __lazy_modules__ but never imported"
    )


def test_checker_emits_lzy101_for_missing_stdlib_module() -> None:
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
        == "LZY101 stdlib module 'zoneinfo' should be listed in __lazy_modules__"
    )


def test_checker_emits_lzy102_for_missing_third_party_module() -> None:
    tree = ast.parse(
        """
import numpy
""",
    )

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
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
    assert errors[0][2] == "LZY102 module '.local' should be listed in __lazy_modules__"


def test_checker_ignores_relative_package_only_import() -> None:
    tree = ast.parse(
        """
from . import helper
""",
    )

    checker = m.LazyImportChecker(tree=tree, filename="example.py")

    assert list(checker.run()) == []


def test_checker_emits_lzy201_for_unsorted_lazy_modules() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["zlib", "abc"]
""",
    )

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy201_errors = [e for e in errors if e[2].startswith("LZY201")]
    assert lzy201_errors == [
        (
            2,
            0,
            "LZY201 __lazy_modules__ should be sorted",
            m.LazyImportChecker,
        ),
    ]


def test_checker_does_not_emit_lzy201_for_sorted_lazy_modules() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["abc", "zlib"]
""",
    )

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
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

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
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

    checker = m.LazyImportChecker(tree=tree, filename="example.py")

    assert list(checker.run()) == []


def test_checker_emits_lzy202_for_annotated_assignment() -> None:
    tree = ast.parse(
        """
from typing import List
__lazy_modules__: List[str] = ["numpy"]
""",
    )

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy202_errors = [e for e in errors if e[2].startswith("LZY202")]
    assert len(lzy202_errors) == 1
    assert (
        lzy202_errors[0][2]
        == "LZY202 module 'numpy' is listed in __lazy_modules__ but never imported"
    )


def test_checker_emits_lzy203_for_duplicate_lazy_module() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["numpy", "numpy"]
import numpy
""",
    )

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy203_errors = [e for e in errors if e[2].startswith("LZY203")]
    assert lzy203_errors == [
        (
            2,
            0,
            "LZY203 module 'numpy' is duplicated in __lazy_modules__",
            m.LazyImportChecker,
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

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy203_messages = [e[2] for e in errors if e[2].startswith("LZY203")]
    assert lzy203_messages == [
        "LZY203 module 'numpy' is duplicated in __lazy_modules__",
        "LZY203 module 'pandas' is duplicated in __lazy_modules__",
    ]


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

    names = m.collect_strictly_top_level_names(tree)

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

    names = m.collect_strictly_top_level_names(tree)

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

    result = m.collect_unnecessary_lazy_imports(tree)

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

    result = m.collect_unnecessary_lazy_imports(tree)

    assert result == []


def test_checker_emits_lzy401_for_lazy_module_accessed_at_top_level() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["re"]
import re

REGEX = re.compile(".")
""",
    )

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
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

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy103_errors = [e for e in errors if e[2].startswith("LZY401")]
    assert lzy103_errors == []


def test_checker_does_not_emit_lzy401_for_lazy_module_used_only_in_function() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["re"]
import re

def func() -> None:
    REGEX = re.compile(".")
""",
    )

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
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

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
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

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
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

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy103_errors = [e for e in errors if e[2].startswith("LZY401")]
    assert len(lzy103_errors) == 1
    assert (
        lzy103_errors[0][2]
        == "LZY401 module 're' is declared lazy but accessed at the top level"
    )
