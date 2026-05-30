"""Read standalone-runner defaults from ``[tool.flake8-lazy.standalone]``.

The standalone ``flake8-lazy`` CLI discovers the nearest ``pyproject.toml`` by
walking up from the current working directory and reads its
``[tool.flake8-lazy.standalone]`` table. The values become argparse defaults, so
explicit command-line flags always win over the config file.
"""

from __future__ import annotations

__lazy_modules__ = [
    f"{__spec__.parent}._options",
    "tomli",
    "tomllib",
]

import sys
from typing import TYPE_CHECKING, TypeGuard

from ._options import APPLY_CHOICES, FORMAT_CHOICES, IMPORT_PRESET_CHOICES

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["ConfigError", "find_config_file", "load_standalone_defaults"]


class ConfigError(Exception):
    """Raised when the standalone config table is unreadable or invalid."""


def find_config_file(start: Path) -> Path | None:
    """Return the nearest ``pyproject.toml`` at or above ``start``."""
    for directory in (start, *start.parents):
        candidate = directory / "pyproject.toml"
        if candidate.is_file():
            return candidate
    return None


def load_standalone_defaults(start: Path) -> dict[str, object]:
    """Return normalized argparse defaults from the nearest ``pyproject.toml``.

    Returns an empty dict when no config file or no ``standalone`` table exists.
    Keys are argparse ``dest`` names; values are normalized to the final types
    the CLI namespace expects. Raises :class:`ConfigError` on any problem.
    """
    path = find_config_file(start)
    if path is None:
        return {}
    try:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
    except OSError as exc:
        msg = f"failed to read {path}: {exc}"
        raise ConfigError(msg) from exc
    except tomllib.TOMLDecodeError as exc:
        msg = f"failed to parse {path}: {exc}"
        raise ConfigError(msg) from exc

    table = data.get("tool", {}).get("flake8-lazy", {}).get("standalone", {})
    if not table:
        return {}
    if not isinstance(table, dict):
        msg = f"{path}: [tool.flake8-lazy.standalone] must be a table"
        raise ConfigError(msg)

    try:
        return _normalize(table)
    except ConfigError as exc:
        msg = f"{path}: {exc}"
        raise ConfigError(msg) from exc


def _normalize(table: dict[str, object]) -> dict[str, object]:
    defaults: dict[str, object] = {}
    for key, value in table.items():
        norm = key.replace("-", "_")
        match norm:
            case "format":
                defaults["format"] = _choice(key, value, FORMAT_CHOICES)
            case "lazy_import_preset":
                defaults["import_preset"] = _choice(key, value, IMPORT_PRESET_CHOICES)
            case "lazy_exclude_modules":
                defaults["exclude_modules"] = _module_list(key, value)
            case "apply":
                defaults["apply"] = _choice(key, value, APPLY_CHOICES)
            case "line_length":
                defaults["line_length"] = _non_negative_int(key, value)
            case "jobs":
                defaults["jobs"] = _jobs(key, value)
            case _:
                msg = (
                    f"unknown key {key!r} in [tool.flake8-lazy.standalone]; "
                    "valid keys are format, lazy-import-preset, "
                    "lazy-exclude-modules, apply, line-length, jobs"
                )
                raise ConfigError(msg)
    return defaults


def _choice(key: str, value: object, choices: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in choices:
        joined = ", ".join(choices)
        msg = f"{key!r} must be one of: {joined}"
        raise ConfigError(msg)
    return value


def _module_list(key: str, value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return ",".join(value)
    msg = f"{key!r} must be a string or a list of strings"
    raise ConfigError(msg)


def _non_negative_int(key: str, value: object) -> int:
    if not _is_int(value) or value < 0:
        msg = f"{key!r} must be a non-negative integer"
        raise ConfigError(msg)
    return value


def _jobs(key: str, value: object) -> int:
    if isinstance(value, str) and value.lower() == "auto":
        return 0
    if _is_int(value) and value > 0:
        return value
    msg = f"{key!r} must be a positive integer or 'auto'"
    raise ConfigError(msg)


def _is_int(value: object) -> TypeGuard[int]:
    # bool is a subclass of int but is never a valid numeric option here.
    return isinstance(value, int) and not isinstance(value, bool)
