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
__lazy_modules__ = ["os"]
import os

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

    assert m.collect_non_lazy_imports(tree) == ["dataclass"]


def test_collect_non_lazy_imports_detects_class_base_usage() -> None:
    tree = ast.parse(
        """
import ast
import pathlib


class Visitor(ast.NodeVisitor):
    path: pathlib.Path
""",
    )

    assert m.collect_non_lazy_imports(tree) == ["ast"]


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
__lazy_modules__ = ["pandas"]
import numpy
import pandas as pd
from sklearn import metrics

value = metrics
""",
    )

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
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
    result = m.collect_side_effect_only_import_packages(tree)

    assert result == {"logging.config"}


def test_collect_side_effect_only_import_ignored_when_bound_name_used() -> None:
    tree = ast.parse(
        """
import logging.config

logging.basicConfig()
""",
    )

    # `logging` is loaded via attribute access, so the import is NOT side-effect-only.
    result = m.collect_side_effect_only_import_packages(tree)

    assert result == set()


def test_collect_side_effect_only_import_ignored_when_aliased() -> None:
    tree = ast.parse(
        """
import logging.config as lc
""",
    )

    # `as lc` means the caller intends to use the binding explicitly.
    result = m.collect_side_effect_only_import_packages(tree)

    assert result == set()


def test_checker_ignores_side_effect_only_import_for_lzy101() -> None:
    tree = ast.parse(
        """
import email.header
""",
    )

    # email.header is a stdlib dotted import and email is never used
    # — treat it as a side-effect import and emit no LZY101 error.
    checker = m.LazyImportChecker(tree=tree, filename="example.py")

    assert list(checker.run()) == []


def test_checker_ignores_side_effect_only_import_for_lzy102() -> None:
    tree = ast.parse(
        """
import pkg.plugin
""",
    )

    # pkg.plugin is a dotted import whose bound name pkg is never used.
    checker = m.LazyImportChecker(tree=tree, filename="example.py")

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
    checker = m.LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy10x_errors = [e for e in errors if e[2].startswith(("LZY101", "LZY102"))]
    assert len(lzy10x_errors) == 1
    assert (
        lzy10x_errors[0][2]
        == "LZY101 stdlib module 'email.header' should be listed in __lazy_modules__"
    )


def test_checker_still_flags_aliased_dotted_import_when_unused() -> None:
    tree = ast.parse(
        """
import email.header as eh
""",
    )

    # The `as` alias signals intentional use of the binding; not side-effect-only.
    checker = m.LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy10x_errors = [e for e in errors if e[2].startswith(("LZY101", "LZY102"))]
    assert len(lzy10x_errors) == 1
    assert (
        lzy10x_errors[0][2]
        == "LZY101 stdlib module 'email.header' should be listed in __lazy_modules__"
    )


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
__lazy_modules__ = ["email"]
import email.header

def process() -> None:
    msg = email.header.decode_header("=?utf-8?b?dGVzdA==?=")
""",
    )

    # email IS used (in a function), so the import is not side-effect-only;
    # both LZY101 and LZY202 fire.
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


def test_checker_emits_lzy204_when_named_module_imported_before_assignment() -> None:
    tree = ast.parse(
        """
import numpy
__lazy_modules__ = ["numpy"]
""",
    )

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy204_errors = [e for e in errors if e[2].startswith("LZY204")]
    assert lzy204_errors == [
        (
            3,
            0,
            "LZY204 __lazy_modules__ should be assigned "
            "before importing modules it names",
            m.LazyImportChecker,
        ),
    ]


def test_checker_does_not_emit_lzy204_when_lazy_modules_precedes_imports() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["numpy"]
import numpy
""",
    )

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
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

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
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

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy204_errors = [e for e in errors if e[2].startswith("LZY204")]
    assert lzy204_errors == []


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

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
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

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
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

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
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

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
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

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
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

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
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

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
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

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
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

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
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

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
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

    checker = m.LazyImportChecker(tree=tree, filename="example.py")
    errors = list(checker.run())

    lzy303_errors = [e for e in errors if e[2].startswith("LZY303")]
    assert len(lzy303_errors) == 1
    assert (
        lzy303_errors[0][2]
        == "LZY303 module 'numpy' is imported both eagerly and lazily"
    )
