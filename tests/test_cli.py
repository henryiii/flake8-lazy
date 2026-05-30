from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from flake8_lazy.__main__ import main
from flake8_lazy._analysis import collect_recommended_lazy_modules
from flake8_lazy._collect import build_module_info
from flake8_lazy._config import (
    ConfigError,
    find_config_file,
    load_standalone_defaults,
)
from flake8_lazy._rewriter import apply_lazy_modules
from flake8_lazy.api import (
    _build_noqa_map,
    _deduplicate_paths,
    _process_single_file,
    collect_errors_for_file,
    collect_recommended_lazy_modules_for_file,
)


def _assert_no_output(capsys: pytest.CaptureFixture[str]) -> None:
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def _run_main_and_assert_no_output(
    args: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    main(args)
    _assert_no_output(capsys)


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


@pytest.mark.skipif(
    sys.version_info < (3, 15),
    reason="Python 3.15 lazy import AST is required",
)
def test_process_single_file_native_mode_does_not_collect_native_fields(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("lazy import numpy\n", encoding="utf-8")

    _path, analysis = _process_single_file(
        path,
        import_preset="default",
        exclude_modules=frozenset(),
        apply_mode="native",
        include_errors=False,
    )

    assert analysis.has_native_lazy is False
    assert analysis.native_modules == []


def test_deduplicate_paths_tolerates_missing_paths(tmp_path: Path) -> None:
    missing = tmp_path / "missing.py"
    assert _deduplicate_paths([missing]) == [missing]


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

    assert collect_recommended_lazy_modules(build_module_info(tree)) == ["requests"]


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

    assert build_module_info(tree).declared_lazy_modules == ["pandas", "numpy"]


def test_collect_declared_lazy_modules_supports_relative_spec_parent_syntax() -> None:
    tree = ast.parse(
        """
__lazy_modules__ = [f"{__spec__.parent}.subpackage"]
""",
    )

    assert build_module_info(tree).declared_lazy_modules == [
        'f"{__spec__.parent}.subpackage"'
    ]


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

    _run_main_and_assert_no_output(["--format", "lazy-modules", str(path)], capsys)


def test_main_outputs_lazy_modules_format_skips_empty_recommendation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import pathlib\nBASE = pathlib.Path.home()\n", encoding="utf-8")

    _run_main_and_assert_no_output(["--format", "lazy-modules", str(path)], capsys)


def test_main_passes_when_file_is_configured(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text(
        '__lazy_modules__ = ["numpy"]\nimport numpy\n',
        encoding="utf-8",
    )

    _run_main_and_assert_no_output([str(path)], capsys)


def test_main_apply_replaces_existing_lazy_modules(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text(
        '__lazy_modules__ = ["unused"]\nimport numpy\n',
        encoding="utf-8",
    )

    _run_main_and_assert_no_output(["--apply=list", str(path)], capsys)
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

    _run_main_and_assert_no_output(["--apply=list", str(path)], capsys)
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

    _run_main_and_assert_no_output(["--apply=list", str(path)], capsys)
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

    _run_main_and_assert_no_output(["--apply=list", str(path)], capsys)
    assert path.read_text(encoding="utf-8") == (
        "from __future__ import annotations\n"
        "\n"
        '__lazy_modules__ = ["requests"]\n'
        "\n"
        "import requests\n"
    )


def test_apply_splits_long_assignment_multiline(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    imports = "".join(f"import long_package_name_{i}\n" for i in range(5))
    path.write_text(
        f"from __future__ import annotations\n\n{imports}", encoding="utf-8"
    )

    _run_main_and_assert_no_output(["--apply=list", str(path)], capsys)
    text = path.read_text(encoding="utf-8")
    assert "__lazy_modules__ = [\n" in text
    assert '    "long_package_name_0",\n' in text
    # Magic trailing comma on the final element keeps black/ruff from collapsing.
    assert '    "long_package_name_4",\n]\n' in text


def test_apply_keeps_short_assignment_single_line(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text(
        "from __future__ import annotations\n\nimport requests\n",
        encoding="utf-8",
    )

    _run_main_and_assert_no_output(["--apply=list", str(path)], capsys)
    assert '__lazy_modules__ = ["requests"]\n' in path.read_text(encoding="utf-8")


def test_apply_line_length_option_controls_split(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    imports = "".join(f"import pkg_{i}\n" for i in range(4))
    path.write_text(
        f"from __future__ import annotations\n\n{imports}", encoding="utf-8"
    )

    # A tiny line-length forces every assignment to be split.
    _run_main_and_assert_no_output(
        ["--apply=list", "--line-length=20", str(path)], capsys
    )
    assert "__lazy_modules__ = [\n" in path.read_text(encoding="utf-8")


def test_apply_line_length_zero_disables_split(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    imports = "".join(f"import long_package_name_{i}\n" for i in range(5))
    path.write_text(
        f"from __future__ import annotations\n\n{imports}", encoding="utf-8"
    )

    # A line length of 0 disables splitting, keeping the old single-line output.
    _run_main_and_assert_no_output(
        ["--apply=list", "--line-length=0", str(path)], capsys
    )
    text = path.read_text(encoding="utf-8")
    assert "__lazy_modules__ = [\n" not in text
    assert '"long_package_name_0", "long_package_name_1"' in text


def test_apply_invalid_line_length_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import requests\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        main(["--apply=list", "--line-length=-1", str(path)])
    assert "line-length must be a non-negative integer" in capsys.readouterr().err


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

    _run_main_and_assert_no_output(["--apply=list", str(path)], capsys)
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

    _run_main_and_assert_no_output(["--apply=list", str(path)], capsys)
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

    _run_main_and_assert_no_output(["--apply=list", str(path)], capsys)
    assert path.read_text(encoding="utf-8") == (
        '__lazy_modules__ = ["numpy"]\nimport numpy\n'
    )


def test_main_apply_set_mode_writes_set_literal(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import numpy\n", encoding="utf-8")

    _run_main_and_assert_no_output(["--apply=set", str(path)], capsys)
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

    _run_main_and_assert_no_output(["--apply=set", str(path)], capsys)
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

    _run_main_and_assert_no_output(["--apply=set", str(path)], capsys)
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

    _run_main_and_assert_no_output(["--apply=set", str(path)], capsys)
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

    _run_main_and_assert_no_output(["--apply=list", str(path)], capsys)
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

    _run_main_and_assert_no_output(["--apply=list", str(path)], capsys)
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

    _run_main_and_assert_no_output(["--apply=set", str(path)], capsys)
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

    _run_main_and_assert_no_output(["--apply=dynamic", str(path)], capsys)
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


def test_main_jobs_rejects_non_positive(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import numpy\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        main(["-j", "0", str(path)])

    assert excinfo.value.code == 2

    with pytest.raises(SystemExit) as excinfo:
        main(["-j", "-4", str(path)])

    assert excinfo.value.code == 2


def test_main_apply_native_adds_lazy_prefix_to_import(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import numpy\n", encoding="utf-8")

    _run_main_and_assert_no_output(["--apply=native", str(path)], capsys)
    assert path.read_text(encoding="utf-8") == "lazy import numpy\n"


def test_main_apply_native_adds_lazy_prefix_to_from_import(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("from pathlib import Path\n", encoding="utf-8")

    _run_main_and_assert_no_output(["--apply=native", str(path)], capsys)
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

    _run_main_and_assert_no_output(["--apply=native", str(path)], capsys)
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

    _run_main_and_assert_no_output(["--apply=native", str(path)], capsys)
    assert path.read_text(encoding="utf-8") == (
        "lazy import numpy\nimport pathlib\nBASE = pathlib.Path.home()\n"
    )


def test_main_apply_native_handles_multiple_imports(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import numpy\nimport pandas\n", encoding="utf-8")

    _run_main_and_assert_no_output(["--apply=native", str(path)], capsys)
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

    _run_main_and_assert_no_output(["--apply=native", str(path)], capsys)
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

    _run_main_and_assert_no_output([str(path)], capsys)


def test_main_noqa_with_code_suppresses_output_and_exits_zero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import numpy  # noqa: LZY102\n", encoding="utf-8")

    _run_main_and_assert_no_output([str(path)], capsys)


def test_main_apply_dynamic_inserts_alllazy_class(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import numpy\n", encoding="utf-8")

    _run_main_and_assert_no_output(["--apply=dynamic", str(path)], capsys)
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

    _run_main_and_assert_no_output(["--apply=dynamic", str(path)], capsys)
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

    _run_main_and_assert_no_output(["--apply=dynamic", str(path)], capsys)
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


def test_collect_errors_for_file_preset_default_skips_always_imported(
    tmp_path: Path,
) -> None:
    """With the default preset, always-imported modules are not flagged."""
    path = tmp_path / "mod.py"
    path.write_text("import sys\n", encoding="utf-8")

    errors = collect_errors_for_file(path)

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


def test_collect_recommended_preset_default_excludes_always_imported(
    tmp_path: Path,
) -> None:
    """With the default preset, always-imported modules are not recommended."""
    path = tmp_path / "mod.py"
    path.write_text("import sys\n", encoding="utf-8")

    mods = collect_recommended_lazy_modules_for_file(path)

    assert "sys" not in mods


def test_main_import_preset_none_flags_always_imported(tmp_path: Path) -> None:
    """``--lazy-import-preset=none`` flags always-imported stdlib modules."""
    path = tmp_path / "mod.py"
    path.write_text("import sys\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="1"):
        main(["--lazy-import-preset=none", str(path)])


def test_main_import_preset_default_skips_always_imported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--lazy-import-preset=default suppresses errors for always-imported modules."""
    path = tmp_path / "mod.py"
    path.write_text("import sys\n", encoding="utf-8")

    _run_main_and_assert_no_output([str(path)], capsys)


# ---------------------------------------------------------------------------
# exclude_modules tests
# ---------------------------------------------------------------------------


def test_collect_errors_exclude_modules_skips_listed_module(
    tmp_path: Path,
) -> None:
    """Modules in exclude_modules are not flagged even if they are importable."""
    path = tmp_path / "mod.py"
    path.write_text("import numpy\n", encoding="utf-8")

    errors_without = collect_errors_for_file(path)
    errors_with = collect_errors_for_file(path, exclude_modules=frozenset({"numpy"}))

    assert any("numpy" in msg for _, _, msg in errors_without)
    assert errors_with == []


def test_collect_recommended_exclude_modules_excludes_listed_module(
    tmp_path: Path,
) -> None:
    """Modules in exclude_modules are excluded from recommendations."""
    path = tmp_path / "mod.py"
    path.write_text("import numpy\nimport pandas\n", encoding="utf-8")

    mods_without = collect_recommended_lazy_modules_for_file(path)
    mods_with = collect_recommended_lazy_modules_for_file(
        path, exclude_modules=frozenset({"numpy"})
    )

    assert "numpy" in mods_without
    assert "numpy" not in mods_with
    assert "pandas" in mods_with


def test_main_exclude_modules_skips_listed_module(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--lazy-exclude-modules`` suppresses errors for listed modules."""
    path = tmp_path / "mod.py"
    path.write_text("import numpy\n", encoding="utf-8")

    _run_main_and_assert_no_output(["--lazy-exclude-modules=numpy", str(path)], capsys)


def test_main_exclude_modules_comma_separated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--lazy-exclude-modules`` accepts a comma-separated list."""
    path = tmp_path / "mod.py"
    path.write_text("import numpy\nimport pandas\n", encoding="utf-8")

    _run_main_and_assert_no_output(
        ["--lazy-exclude-modules=numpy,pandas", str(path)], capsys
    )


# ---------------------------------------------------------------------------
# config file ([tool.flake8-lazy.standalone]) tests
# ---------------------------------------------------------------------------


def _write_config(directory: Path, body: str) -> Path:
    config = directory / "pyproject.toml"
    config.write_text(f"[tool.flake8-lazy.standalone]\n{body}", encoding="utf-8")
    return config


def test_find_config_file_walks_up(tmp_path: Path) -> None:
    config = tmp_path / "pyproject.toml"
    config.write_text("", encoding="utf-8")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)

    assert find_config_file(nested) == config


def test_load_standalone_defaults_empty_without_table(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.other]\nfoo = "bar"\n', encoding="utf-8"
    )

    assert load_standalone_defaults(tmp_path) == {}


def test_load_standalone_defaults_normalizes_keys(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        'format = "lazy-modules"\n'
        'lazy-import-preset = "minimal"\n'
        'lazy-exclude-modules = ["numpy", "pandas"]\n'
        'apply = "list"\n'
        "line-length = 100\n"
        "jobs = 4\n",
    )

    assert load_standalone_defaults(tmp_path) == {
        "format": "lazy-modules",
        "import_preset": "minimal",
        "exclude_modules": "numpy,pandas",
        "apply": "list",
        "line_length": 100,
        "jobs": 4,
    }


def test_load_standalone_defaults_rejects_underscore_keys(tmp_path: Path) -> None:
    # Only the exact dash-form CLI flag names are accepted.
    _write_config(tmp_path, 'lazy_exclude_modules = "numpy"\n')

    with pytest.raises(ConfigError, match="unknown key 'lazy_exclude_modules'"):
        load_standalone_defaults(tmp_path)


def test_load_standalone_defaults_jobs_auto(tmp_path: Path) -> None:
    _write_config(tmp_path, 'jobs = "auto"\n')

    assert load_standalone_defaults(tmp_path) == {"jobs": 0}


def test_load_standalone_defaults_string_exclude_modules(tmp_path: Path) -> None:
    _write_config(tmp_path, 'lazy-exclude-modules = "numpy,pandas"\n')

    assert load_standalone_defaults(tmp_path) == {"exclude_modules": "numpy,pandas"}


def test_load_standalone_defaults_rejects_unknown_key(tmp_path: Path) -> None:
    _write_config(tmp_path, 'unknown = "x"\n')

    with pytest.raises(ConfigError, match="unknown key 'unknown'"):
        load_standalone_defaults(tmp_path)


def test_load_standalone_defaults_rejects_bad_choice(tmp_path: Path) -> None:
    _write_config(tmp_path, 'format = "nonsense"\n')

    with pytest.raises(ConfigError, match="'format' must be one of"):
        load_standalone_defaults(tmp_path)


def test_load_standalone_defaults_rejects_negative_line_length(tmp_path: Path) -> None:
    _write_config(tmp_path, "line-length = -1\n")

    with pytest.raises(ConfigError, match="non-negative integer"):
        load_standalone_defaults(tmp_path)


def test_load_standalone_defaults_rejects_bool_jobs(tmp_path: Path) -> None:
    _write_config(tmp_path, "jobs = true\n")

    with pytest.raises(ConfigError, match="positive integer or 'auto'"):
        load_standalone_defaults(tmp_path)


def test_load_standalone_defaults_rejects_malformed_toml(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("not = valid = toml", encoding="utf-8")

    with pytest.raises(ConfigError, match="failed to parse"):
        load_standalone_defaults(tmp_path)


def test_main_reads_exclude_modules_from_config(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path, 'lazy-exclude-modules = ["numpy"]\n')
    path = tmp_path / "mod.py"
    path.write_text("import numpy\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    _run_main_and_assert_no_output([str(path)], capsys)


def test_main_reads_import_preset_from_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path, 'lazy-import-preset = "none"\n')
    path = tmp_path / "mod.py"
    path.write_text("import sys\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit, match="1"):
        main([str(path)])


def test_main_cli_overrides_config(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Config would flag sys (preset none), but the CLI flag wins.
    _write_config(tmp_path, 'lazy-import-preset = "none"\n')
    path = tmp_path / "mod.py"
    path.write_text("import sys\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    _run_main_and_assert_no_output(["--lazy-import-preset=default", str(path)], capsys)


def test_main_reads_format_from_config(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path, 'format = "lazy-modules"\n')
    path = tmp_path / "mod.py"
    path.write_text("import numpy\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit, match="1"):
        main([str(path)])

    captured = capsys.readouterr()
    assert captured.out == f'{path}: __lazy_modules__ = ["numpy"]\n'


def test_main_reads_apply_from_config(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path, 'apply = "list"\n')
    path = tmp_path / "mod.py"
    path.write_text("import numpy\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    _run_main_and_assert_no_output([str(path)], capsys)
    assert path.read_text(encoding="utf-8") == (
        '__lazy_modules__ = ["numpy"]\n\nimport numpy\n'
    )


def test_main_invalid_config_exits_two(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_config(tmp_path, 'unknown = "x"\n')
    path = tmp_path / "mod.py"
    path.write_text("import numpy\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        main([str(path)])

    assert excinfo.value.code == 2
    assert "unknown key 'unknown'" in capsys.readouterr().err
