"""Read flake8-lazy configuration from TOML.

The standalone ``flake8-lazy`` CLI discovers the nearest ``pyproject.toml`` by
walking up from the current working directory and reads its
``[tool.flake8-lazy.standalone]`` table. The values become argparse defaults, so
explicit command-line flags always win over the config file.

A file can also set per-file options in a ``[tool.flake8-lazy]`` table inside
its PEP 723 ``# /// script`` block. These override all other settings.
"""

from __future__ import annotations

__lazy_modules__ = [
    "tomli",
    "tomllib",
    f"{__spec__.parent}._options",
]

import re
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, NoReturn, TypeGuard

from ._options import (
    APPLY_CHOICES,
    FORMAT_CHOICES,
    IMPORT_PRESET_CHOICES,
    parse_exclude_modules,
)

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "ConfigError",
    "ScriptConfigError",
    "ScriptSettings",
    "find_config_file",
    "load_script_settings",
    "load_standalone_defaults",
]

# From the PEP 723 reference implementation.
_SCRIPT_RE = re.compile(
    r"(?m)^# /// (?P<type>[a-zA-Z0-9-]+)$\s(?P<content>(^#(| .*)$\s)+)^# ///$"
)

_STANDALONE_KEYS = (
    "format",
    "lazy-import-preset",
    "lazy-exclude-modules",
    "apply",
    "line-length",
    "jobs",
    "strict-typing",
)
_SCRIPT_KEYS = (
    "lazy-import-preset",
    "lazy-exclude-modules",
    "line-length",
    "strict-typing",
)


class ConfigError(Exception):
    """Raised when a config table is unreadable or invalid."""


class ScriptConfigError(ConfigError):
    """Raised when a script block's ``[tool.flake8-lazy]`` table is invalid."""

    def __init__(self, message: str, lineno: int) -> None:
        super().__init__(message, lineno)
        self.message = message
        self.lineno = lineno

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class ScriptSettings:
    """Per-file overrides from a script block; ``None`` means not set."""

    import_preset: str | None = None
    exclude_modules: frozenset[str] | None = None
    strict_typing: bool | None = None
    line_length: int | None = None


def load_script_settings(source: str) -> ScriptSettings:
    """Return the ``[tool.flake8-lazy]`` settings from a PEP 723 script block.

    Raises :class:`ScriptConfigError` with the block's line number on any problem.
    """
    if "# /// script" not in source:
        return ScriptSettings()
    matches = [m for m in _SCRIPT_RE.finditer(source) if m["type"] == "script"]
    if not matches:
        return ScriptSettings()
    lineno = source.count("\n", 0, matches[0].start()) + 1
    if len(matches) > 1:
        msg = "multiple script blocks found"
        raise ScriptConfigError(msg, lineno)

    content = "".join(
        line[2:] if line.startswith("# ") else line[1:]
        for line in matches[0]["content"].splitlines(keepends=True)
    )
    try:
        tool = tomllib.loads(content).get("tool", {})
    except tomllib.TOMLDecodeError as exc:
        msg = f"invalid [tool.flake8-lazy] in script block: failed to parse: {exc}"
        raise ScriptConfigError(msg, lineno) from exc
    if not isinstance(tool, dict):
        msg = "invalid script block: [tool] must be a table"
        raise ScriptConfigError(msg, lineno)
    try:
        return _script_settings(tool.get("flake8-lazy", {}))
    except ConfigError as exc:
        msg = f"invalid [tool.flake8-lazy] in script block: {exc}"
        raise ScriptConfigError(msg, lineno) from exc


def _script_settings(table: object) -> ScriptSettings:
    if not isinstance(table, dict):
        msg = "[tool.flake8-lazy] must be a table"
        raise ConfigError(msg)
    import_preset = exclude_modules = strict_typing = line_length = None
    for key, value in table.items():
        match key:
            case "lazy-import-preset":
                import_preset = _choice(key, value, IMPORT_PRESET_CHOICES)
            case "lazy-exclude-modules":
                exclude_modules = parse_exclude_modules(_module_list(key, value))
            case "strict-typing":
                strict_typing = _bool(key, value)
            case "line-length":
                line_length = _non_negative_int(key, value)
            case _:
                _unknown_key(key, _SCRIPT_KEYS, "[tool.flake8-lazy]")
    return ScriptSettings(
        import_preset=import_preset,
        exclude_modules=exclude_modules,
        strict_typing=strict_typing,
        line_length=line_length,
    )


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
        match key:
            case "format":
                defaults["format"] = _choice(key, value, FORMAT_CHOICES)
            case "lazy-import-preset":
                defaults["import_preset"] = _choice(key, value, IMPORT_PRESET_CHOICES)
            case "lazy-exclude-modules":
                defaults["exclude_modules"] = _module_list(key, value)
            case "apply":
                defaults["apply"] = _choice(key, value, APPLY_CHOICES)
            case "line-length":
                defaults["line_length"] = _non_negative_int(key, value)
            case "jobs":
                defaults["jobs"] = _jobs(key, value)
            case "strict-typing":
                defaults["strict_typing"] = _bool(key, value)
            case _:
                _unknown_key(key, _STANDALONE_KEYS, "[tool.flake8-lazy.standalone]")
    return defaults


def _unknown_key(key: str, allowed: tuple[str, ...], name: str) -> NoReturn:
    msg = f"unknown key {key!r} in {name}; valid keys are {', '.join(allowed)}"
    raise ConfigError(msg)


def _choice(key: str, value: object, choices: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in choices:
        joined = ", ".join(choices)
        msg = f"{key!r} must be one of: {joined}"
        raise ConfigError(msg)
    return value


def _module_list(key: str, value: object) -> str:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        # Pyrefly needs this, mypy is smart enough without it
        typed_list: list[str] = value
        return ",".join(typed_list)
    msg = f"{key!r} must be a list of strings"
    raise ConfigError(msg)


def _bool(key: str, value: object) -> bool:
    if not isinstance(value, bool):
        msg = f"{key!r} must be a boolean"
        raise ConfigError(msg)
    return value


def _non_negative_int(key: str, value: object) -> int:
    if not _is_int(value) or value < 0:
        msg = f"{key!r} must be a non-negative integer"
        raise ConfigError(msg)
    return value


def _jobs(key: str, value: object) -> int:
    if _is_int(value) and value > 0:
        return value
    # Omit the key entirely for automatic parallelism.
    msg = f"{key!r} must be a positive integer"
    raise ConfigError(msg)


def _is_int(value: object) -> TypeGuard[int]:
    # bool is a subclass of int but is never a valid numeric option here.
    return isinstance(value, int) and not isinstance(value, bool)
