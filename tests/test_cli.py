from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from flake8_lazy.__main__ import main
from flake8_lazy._analysis import (
    collect_declared_lazy_modules,
    collect_recommended_lazy_modules,
)
from flake8_lazy._rewriter import apply_lazy_modules
from flake8_lazy.api import (
    _build_noqa_map,
    collect_errors_for_file,
    collect_recommended_lazy_modules_for_file,
)


def test_collect_errors_for_file(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import numpy\n", encoding="utf-8")

    errors = collect_errors_for_file(path)

    assert errors == [
        (
            1,
            0,
            "LZY102 module 'numpy' should be listed in __lazy_modules__",
        ),
    ]


def test_collect_errors_for_file_respects_encoding_cookie(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    source = '# coding: koi8-r\nmessage = "\u0442\u0435\u0441\u0442"\nimport numpy\n'
    path.write_bytes(source.encode("koi8-r"))

    errors = collect_errors_for_file(path)

    assert errors == [
        (
            3,
            0,
            "LZY102 module 'numpy' should be listed in __lazy_modules__",
        ),
    ]


def test_collect_errors_for_file_includes_path_in_decode_error(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    path.write_bytes(b"# coding: utf-8\n\xff\n")

    with pytest.raises(UnicodeDecodeError) as excinfo:
        collect_errors_for_file(path)

    if sys.version_info >= (3, 11):
        assert excinfo.value.__notes__ == [f"while reading {path}"]
    else:
        assert getattr(excinfo.value, "__notes__", None) is None


def test_main_outputs_lzy102_and_exits_nonzero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import numpy\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        main([str(path)])

    assert excinfo.value.code == 1

    output = capsys.readouterr().out
    assert (
        f"{path}:1:0: LZY102 module 'numpy' should be listed in __lazy_modules__"
        in output
    )


def test_collect_recommended_lazy_modules_sorts_and_filters() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["unused"]
import requests
import pathlib

HOME = pathlib.Path.home()
""",
    )

    assert collect_recommended_lazy_modules(tree) == ["requests"]


def test_collect_recommended_lazy_modules_for_file_skips_enclosing_packages(
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "a" / "b"
    package_dir.mkdir(parents=True)
    (tmp_path / "a" / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    path = package_dir / "c.py"
    path.write_text(
        "import a\nimport a.b\nimport requests\n",
        encoding="utf-8",
    )

    assert collect_recommended_lazy_modules_for_file(path) == ["requests"]


def test_collect_recommended_lazy_modules_for_repo_review_rich_children() -> None:
    path = Path(__file__).parent / "examples" / "repo_review" / "__main__.py.txt"

    recommended = collect_recommended_lazy_modules_for_file(path)

    assert "rich.console" in recommended
    assert "rich.markdown" in recommended
    assert "rich.syntax" in recommended
    assert "rich.terminal_theme" in recommended
    assert "rich.text" in recommended
    assert "rich.tree" in recommended
    assert "rich" not in recommended
    assert "rich.traceback" not in recommended


def test_collect_recommended_lazy_modules_includes_intermediate_parents() -> None:
    path = Path(__file__).parent / "examples" / "repo_review" / "_compat.py.txt"

    recommended = collect_recommended_lazy_modules_for_file(path)

    # importlib.abc is NOT recommended because it's guarded by
    # sys.version_info < (3, 11) which excludes Python 3.15+
    assert "importlib" in recommended
    assert "importlib.abc" not in recommended
    assert "importlib.resources" in recommended
    assert "importlib.resources.abc" in recommended


def test_collect_errors_for_file_skips_enclosing_package_diagnostics(
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "a" / "b"
    package_dir.mkdir(parents=True)
    (tmp_path / "a" / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    path = package_dir / "c.py"
    path.write_text(
        '__lazy_modules__ = ["a", "a.b"]\nimport a\nimport a.b\nimport requests\n',
        encoding="utf-8",
    )

    errors = collect_errors_for_file(path)

    assert errors == [
        (
            4,
            0,
            "LZY102 module 'requests' should be listed in __lazy_modules__",
        ),
        (
            1,
            20,
            "LZY402 module 'a' is an enclosing package for this file and "
            "should not be declared lazy",
        ),
        (
            1,
            25,
            "LZY402 module 'a.b' is an enclosing package for this file and "
            "should not be declared lazy",
        ),
    ]


def test_collect_errors_for_package_init_skips_enclosing_package_diagnostics(
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "a" / "b"
    package_dir.mkdir(parents=True)
    (tmp_path / "a" / "__init__.py").write_text("", encoding="utf-8")
    path = package_dir / "__init__.py"
    path.write_text(
        '__lazy_modules__ = ["a", "a.b"]\nimport a\nimport a.b\nimport pandas\n',
        encoding="utf-8",
    )

    errors = collect_errors_for_file(path)

    assert errors == [
        (
            4,
            0,
            "LZY102 module 'pandas' should be listed in __lazy_modules__",
        ),
        (
            1,
            20,
            "LZY402 module 'a' is an enclosing package for this file and "
            "should not be declared lazy",
        ),
        (
            1,
            25,
            "LZY402 module 'a.b' is an enclosing package for this file and "
            "should not be declared lazy",
        ),
    ]


def test_collect_declared_lazy_modules_returns_last_static_list() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = ["numpy"]
__lazy_modules__ = ["pandas", "numpy"]
""",
    )

    assert collect_declared_lazy_modules(tree) == ["pandas", "numpy"]


def test_collect_declared_lazy_modules_supports_relative_spec_parent_syntax() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = [f"{__spec__.parent}.subpackage"]
""",
    )

    assert collect_declared_lazy_modules(tree) == ['f"{__spec__.parent}.subpackage"']


def test_main_outputs_lazy_modules_format_and_exits_nonzero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import pandas\nimport numpy\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        main(["--format", "lazy-modules", str(path)])

    assert excinfo.value.code == 1

    captured = capsys.readouterr()
    assert captured.out == f'{path}: __lazy_modules__ = ["numpy", "pandas"]\n'
    assert captured.err == ""


def test_main_outputs_lazy_modules_format_for_relative_import(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("from .subpackage import helper\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        main(["--format", "lazy-modules", str(path)])

    assert excinfo.value.code == 1

    captured = capsys.readouterr()
    assert (
        captured.out
        == f'{path}: __lazy_modules__ = [f"{{__spec__.parent}}.subpackage"]\n'
    )
    assert captured.err == ""


def test_main_outputs_lazy_modules_format_for_clean_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text(
        '__lazy_modules__ = ["numpy"]\nimport numpy\n',
        encoding="utf-8",
    )

    main(["--format", "lazy-modules", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_main_outputs_lazy_modules_format_skips_empty_recommendation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import pathlib\nBASE = pathlib.Path.home()\n", encoding="utf-8")

    main(["--format", "lazy-modules", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_main_passes_when_file_is_configured(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text(
        '__lazy_modules__ = ["numpy"]\nimport numpy\n',
        encoding="utf-8",
    )

    main([str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_main_apply_replaces_existing_lazy_modules(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text(
        '__lazy_modules__ = ["unused"]\nimport numpy\n',
        encoding="utf-8",
    )

    main(["--apply=list", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert path.read_text(encoding="utf-8") == (
        '__lazy_modules__ = ["numpy"]\nimport numpy\n'
    )


def test_main_apply_inserts_after_comments_and_docstring(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text(
        "# SPDX-License-Identifier: BSD-3-Clause\n"
        '"""Module docs."""\n\n'
        "import pandas\n",
        encoding="utf-8",
    )

    main(["--apply=list", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert path.read_text(encoding="utf-8") == (
        '# SPDX-License-Identifier: BSD-3-Clause\n"""Module docs."""\n\n'
        '__lazy_modules__ = ["pandas"]\n\nimport pandas\n'
    )


def test_main_apply_inserts_after_future_annotations_import(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text(
        "from __future__ import annotations\n\nimport requests\n",
        encoding="utf-8",
    )

    main(["--apply=list", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert path.read_text(encoding="utf-8") == (
        "from __future__ import annotations\n"
        "\n"
        '__lazy_modules__ = ["requests"]\n'
        "\n"
        "import requests\n"
    )


def test_main_apply_inserts_blank_line_after_future_annotations_import_when_missing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text(
        "from __future__ import annotations\nimport requests\n",
        encoding="utf-8",
    )

    main(["--apply=list", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert path.read_text(encoding="utf-8") == (
        "from __future__ import annotations\n"
        "\n"
        '__lazy_modules__ = ["requests"]\n'
        "\n"
        "import requests\n"
    )


def test_apply_lazy_modules_writes_raw_newlines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "mod.py"
    path.write_bytes(b"import numpy\r\n")

    original_write_text = type(path).write_text
    captured_newline: str | None = None

    def recording_write_text(
        self: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        nonlocal captured_newline
        captured_newline = newline
        return original_write_text(
            self,
            data,
            encoding=encoding,
            errors=errors,
            newline=newline,
        )

    monkeypatch.setattr(type(path), "write_text", recording_write_text)

    apply_lazy_modules(path, ["numpy"])

    assert captured_newline == ""


def test_main_apply_removes_existing_lazy_modules_when_none_recommended(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    # A file with __lazy_modules__ but no module-level imports to recommend
    path.write_text(
        '__lazy_modules__ = ["numpy"]\n\ndef helper() -> None:\n    import numpy\n',
        encoding="utf-8",
    )

    main(["--apply=list", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert path.read_text(encoding="utf-8") == (
        "\ndef helper() -> None:\n    import numpy\n"
    )


def test_main_apply_leaves_file_unchanged_when_no_modules_and_no_existing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    original = "def helper() -> None:\n    import numpy\n"
    path.write_text(original, encoding="utf-8")

    main(["--apply=list", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert path.read_text(encoding="utf-8") == original


def test_main_apply_list_mode_explicit_flag(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    # Existing container is a tuple; --apply=list must force a list regardless.
    path.write_text(
        '__lazy_modules__ = ("unused",)\nimport numpy\n',
        encoding="utf-8",
    )

    main(["--apply=list", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert path.read_text(encoding="utf-8") == (
        '__lazy_modules__ = ["numpy"]\nimport numpy\n'
    )


def test_main_apply_set_mode_writes_set_literal(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import numpy\n", encoding="utf-8")

    main(["--apply=set", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert path.read_text(encoding="utf-8") == (
        '__lazy_modules__ = {"numpy"}\n\nimport numpy\n'
    )


def test_main_apply_set_mode_overrides_existing_list(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text(
        '__lazy_modules__ = ["unused"]\nimport numpy\n',
        encoding="utf-8",
    )

    main(["--apply=set", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert path.read_text(encoding="utf-8") == (
        '__lazy_modules__ = {"numpy"}\nimport numpy\n'
    )


def test_main_apply_set_mode_overrides_existing_tuple(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text(
        '__lazy_modules__ = ("numpy",)\nimport numpy\nimport pandas\n',
        encoding="utf-8",
    )

    main(["--apply=set", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert path.read_text(encoding="utf-8") == (
        '__lazy_modules__ = {"numpy", "pandas"}\nimport numpy\nimport pandas\n'
    )


def test_main_apply_set_mode_overrides_existing_correct_list(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Content is already correct but container type is list — must still convert.
    path = tmp_path / "mod.py"
    path.write_text(
        '__lazy_modules__ = ["numpy"]\nimport numpy\n',
        encoding="utf-8",
    )

    main(["--apply=set", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert path.read_text(encoding="utf-8") == (
        '__lazy_modules__ = {"numpy"}\nimport numpy\n'
    )


def test_main_apply_list_mode_overrides_existing_correct_set(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Content is already correct but container type is set — must still convert.
    path = tmp_path / "mod.py"
    path.write_text(
        '__lazy_modules__ = {"numpy"}\nimport numpy\n',
        encoding="utf-8",
    )

    main(["--apply=list", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert path.read_text(encoding="utf-8") == (
        '__lazy_modules__ = ["numpy"]\nimport numpy\n'
    )


@pytest.mark.skipif(
    sys.version_info < (3, 15),
    reason="Python 3.15 lazy import AST is required",
)
def test_main_apply_list_mode_converts_native_lazy_import(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("lazy import numpy\n", encoding="utf-8")

    main(["--apply=list", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert path.read_text(encoding="utf-8") == (
        '__lazy_modules__ = ["numpy"]\n\nimport numpy\n'
    )


@pytest.mark.skipif(
    sys.version_info < (3, 15),
    reason="Python 3.15 lazy import AST is required",
)
def test_main_apply_set_mode_converts_native_lazy_import(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("lazy import numpy\n", encoding="utf-8")

    main(["--apply=set", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert path.read_text(encoding="utf-8") == (
        '__lazy_modules__ = {"numpy"}\n\nimport numpy\n'
    )


@pytest.mark.skipif(
    sys.version_info < (3, 15),
    reason="Python 3.15 lazy import AST is required",
)
def test_main_apply_dynamic_mode_converts_native_lazy_import(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("lazy import numpy\n", encoding="utf-8")

    main(["--apply=dynamic", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert path.read_text(encoding="utf-8") == (
        "class AllLazy:\n"
        "    @staticmethod\n"
        "    def __contains__(_: str) -> bool:\n"
        "        return True\n"
        "\n"
        "\n"
        "__lazy_modules__ = AllLazy()\n"
        "\n"
        "import numpy\n"
    )


def test_main_apply_invalid_mode_exits(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import numpy\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        main(["--apply=bad", str(path)])

    assert excinfo.value.code == 2


def test_main_apply_native_adds_lazy_prefix_to_import(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import numpy\n", encoding="utf-8")

    main(["--apply=native", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert path.read_text(encoding="utf-8") == "lazy import numpy\n"


def test_main_apply_native_adds_lazy_prefix_to_from_import(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("from pathlib import Path\n", encoding="utf-8")

    main(["--apply=native", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert path.read_text(encoding="utf-8") == "lazy from pathlib import Path\n"


def test_main_apply_native_removes_lazy_modules_assignment(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text(
        '__lazy_modules__ = ["numpy"]\nimport numpy\n',
        encoding="utf-8",
    )

    main(["--apply=native", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert path.read_text(encoding="utf-8") == "lazy import numpy\n"


def test_main_apply_native_only_lazifies_recommended_imports(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    # pathlib is used at module level so it should NOT be lazified
    path.write_text(
        "import numpy\nimport pathlib\nBASE = pathlib.Path.home()\n",
        encoding="utf-8",
    )

    main(["--apply=native", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert path.read_text(encoding="utf-8") == (
        "lazy import numpy\nimport pathlib\nBASE = pathlib.Path.home()\n"
    )


def test_main_apply_native_handles_multiple_imports(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import numpy\nimport pandas\n", encoding="utf-8")

    main(["--apply=native", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert path.read_text(encoding="utf-8") == (
        "lazy import numpy\nlazy import pandas\n"
    )


def test_main_apply_native_removes_existing_lazy_modules_when_no_recommended(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text(
        '__lazy_modules__ = ["numpy"]\n\ndef helper() -> None:\n    import numpy\n',
        encoding="utf-8",
    )

    main(["--apply=native", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert path.read_text(encoding="utf-8") == (
        "\ndef helper() -> None:\n    import numpy\n"
    )


def test_build_noqa_map_bare_noqa() -> None:
    noqa_map = _build_noqa_map("import numpy  # noqa\n")
    assert noqa_map == {1: None}


def test_build_noqa_map_noqa_with_single_code() -> None:
    noqa_map = _build_noqa_map("import numpy  # noqa: LZY102\n")
    assert noqa_map == {1: {"LZY102"}}


def test_build_noqa_map_noqa_with_multiple_codes() -> None:
    noqa_map = _build_noqa_map("import numpy  # noqa: LZY101, LZY102\n")
    assert noqa_map == {1: {"LZY101", "LZY102"}}


def test_build_noqa_map_noqa_case_insensitive() -> None:
    noqa_map = _build_noqa_map("import numpy  # NOQA\n")
    assert noqa_map == {1: None}


def test_build_noqa_map_no_noqa() -> None:
    noqa_map = _build_noqa_map("import numpy\n")
    assert noqa_map == {}


def test_collect_errors_suppressed_by_bare_noqa(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import numpy  # noqa\n", encoding="utf-8")

    errors = collect_errors_for_file(path)

    assert errors == []


def test_collect_errors_suppressed_by_matching_code(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import numpy  # noqa: LZY102\n", encoding="utf-8")

    errors = collect_errors_for_file(path)

    assert errors == []


def test_collect_errors_not_suppressed_by_different_code(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import numpy  # noqa: LZY101\n", encoding="utf-8")

    errors = collect_errors_for_file(path)

    assert errors == [
        (1, 0, "LZY102 module 'numpy' should be listed in __lazy_modules__"),
    ]


def test_collect_errors_suppressed_by_one_of_multiple_codes(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import numpy  # noqa: LZY101, LZY102\n", encoding="utf-8")

    errors = collect_errors_for_file(path)

    assert errors == []


def test_collect_errors_noqa_only_suppresses_its_own_line(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import numpy  # noqa\nimport pandas\n", encoding="utf-8")

    errors = collect_errors_for_file(path)

    assert errors == [
        (2, 0, "LZY102 module 'pandas' should be listed in __lazy_modules__"),
    ]


def test_main_noqa_suppresses_output_and_exits_zero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import numpy  # noqa\n", encoding="utf-8")

    main([str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_main_noqa_with_code_suppresses_output_and_exits_zero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import numpy  # noqa: LZY102\n", encoding="utf-8")

    main([str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_main_apply_dynamic_inserts_alllazy_class(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import numpy\n", encoding="utf-8")

    main(["--apply=dynamic", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    result = path.read_text(encoding="utf-8")
    assert "class AllLazy:" in result
    assert "__contains__" in result
    assert "__lazy_modules__ = AllLazy()" in result
    assert "import numpy" in result


def test_main_apply_dynamic_replaces_existing_list(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text(
        '__lazy_modules__ = ["numpy"]\nimport numpy\n',
        encoding="utf-8",
    )

    main(["--apply=dynamic", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    result = path.read_text(encoding="utf-8")
    assert "__lazy_modules__ = AllLazy()" in result
    assert '["numpy"]' not in result


def test_main_apply_dynamic_is_noop_when_already_dynamic(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = (
        "class AllLazy:\n"
        "    @staticmethod\n"
        "    def __contains__(_: str) -> bool:\n"
        "        return True\n"
        "\n"
        "\n"
        "__lazy_modules__ = AllLazy()\n"
        "import numpy\n"
    )
    path = tmp_path / "mod.py"
    path.write_text(original, encoding="utf-8")

    main(["--apply=dynamic", str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert path.read_text(encoding="utf-8") == original


def test_main_apply_dynamic_produces_no_errors(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import numpy\n", encoding="utf-8")

    main(["--apply=dynamic", str(path)])
    # Re-run checker on the rewritten file — should produce no errors.
    errors = collect_errors_for_file(path)

    assert errors == []


def test_checker_produces_no_errors_for_dynamic_lazy_modules(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mod.py"
    path.write_text(
        "class AllLazy:\n"
        "    @staticmethod\n"
        "    def __contains__(_: str) -> bool:\n"
        "        return True\n"
        "\n"
        "\n"
        "__lazy_modules__ = AllLazy()\n"
        "import numpy\n"
        "import pandas\n",
        encoding="utf-8",
    )

    errors = collect_errors_for_file(path)

    assert errors == []


# ---------------------------------------------------------------------------
# import_preset tests
# ---------------------------------------------------------------------------


def test_collect_errors_for_file_preset_none_flags_always_imported(
    tmp_path: Path,
) -> None:
    """With preset=none, even always-imported stdlib modules are flagged."""
    path = tmp_path / "mod.py"
    path.write_text("import sys\n", encoding="utf-8")

    errors = collect_errors_for_file(path, import_preset="none")

    assert any("sys" in msg for _, _, msg in errors)


def test_collect_errors_for_file_preset_minimal_skips_always_imported(
    tmp_path: Path,
) -> None:
    """With preset=minimal (default), always-imported modules are not flagged."""
    path = tmp_path / "mod.py"
    path.write_text("import sys\n", encoding="utf-8")

    errors = collect_errors_for_file(path, import_preset="minimal")

    assert errors == []


def test_collect_errors_for_file_preset_default_skips_more_modules(
    tmp_path: Path,
) -> None:
    """With preset=default, site-startup modules like os are also not flagged."""
    path = tmp_path / "mod.py"
    path.write_text("import os\n", encoding="utf-8")

    errors_minimal = collect_errors_for_file(path, import_preset="minimal")
    errors_default = collect_errors_for_file(path, import_preset="default")

    assert any("os" in msg for _, _, msg in errors_minimal)
    assert errors_default == []


def test_collect_recommended_preset_none_includes_always_imported(
    tmp_path: Path,
) -> None:
    """With preset=none, always-imported modules appear in recommendations."""
    path = tmp_path / "mod.py"
    path.write_text("import sys\n", encoding="utf-8")

    mods = collect_recommended_lazy_modules_for_file(path, import_preset="none")

    assert "sys" in mods


def test_collect_recommended_preset_minimal_excludes_always_imported(
    tmp_path: Path,
) -> None:
    """With preset=minimal, always-imported modules are not recommended."""
    path = tmp_path / "mod.py"
    path.write_text("import sys\n", encoding="utf-8")

    mods = collect_recommended_lazy_modules_for_file(path, import_preset="minimal")

    assert "sys" not in mods


def test_main_import_preset_none_flags_always_imported(tmp_path: Path) -> None:
    """``--lazy-import-preset=none`` flags always-imported stdlib modules."""
    path = tmp_path / "mod.py"
    path.write_text("import sys\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="1"):
        main(["--lazy-import-preset=none", str(path)])


def test_main_import_preset_minimal_skips_always_imported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--lazy-import-preset=minimal suppresses errors for always-imported modules."""
    path = tmp_path / "mod.py"
    path.write_text("import sys\n", encoding="utf-8")

    main(["--lazy-import-preset=minimal", str(path)])  # should not raise

    captured = capsys.readouterr()
    assert captured.out == ""
