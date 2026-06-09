"""Shared option defaults and parsers for CLI and flake8 plugin entrypoints."""

from __future__ import annotations

DEFAULT_IMPORT_PRESET = "default"
IMPORT_PRESET_CHOICES = ("none", "minimal", "default")

FORMAT_CHOICES = ("flake8", "lazy-modules")
APPLY_CHOICES = ("list", "set", "tuple", "native", "dynamic")

DEFAULT_EXCLUDE_MODULES = ""


def parse_exclude_modules(raw: str | None) -> frozenset[str]:
    """Parse comma-separated module names from option text."""
    value = raw or ""
    return frozenset(module.strip() for module in value.split(",") if module.strip())
