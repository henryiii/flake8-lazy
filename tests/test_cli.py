from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

import flake8_lazy as m

if TYPE_CHECKING:
    from pathlib import Path


def test_collect_errors_for_file(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import numpy\n", encoding="utf-8")

    errors = m.collect_errors_for_file(path)

    assert errors == [
        (
            1,
            0,
            "LZY002 module 'numpy' should be listed in __lazy_modules__",
        ),
    ]


def test_collect_errors_for_file_includes_path_in_decode_error(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    path.write_bytes(b"\xff")

    with pytest.raises(UnicodeDecodeError) as excinfo:
        m.collect_errors_for_file(path)

    if sys.version_info >= (3, 11):
        assert excinfo.value.__notes__ == [f"while reading {path}"]
    else:
        assert getattr(excinfo.value, "__notes__", None) is None


def test_main_outputs_lzy001_and_exits_nonzero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text("import numpy\n", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        m.main([str(path)])

    assert excinfo.value.code == 1

    output = capsys.readouterr().out
    assert (
        f"{path}:1:0: LZY002 module 'numpy' should be listed in __lazy_modules__"
        in output
    )


def test_main_passes_when_file_is_configured(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "mod.py"
    path.write_text(
        '__lazy_modules__ = ["numpy"]\nimport numpy\n',
        encoding="utf-8",
    )

    m.main([str(path)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
