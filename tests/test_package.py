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

def func() -> None:
    import json
""",
    )

    checker = m.LazyImportChecker(tree=tree, filename="example.py")

    assert list(checker.run()) == []
