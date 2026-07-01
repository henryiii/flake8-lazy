"""Shared option defaults and parsers for CLI and flake8 plugin entrypoints."""

from __future__ import annotations

DEFAULT_IMPORT_PRESET = "default"
IMPORT_PRESET_CHOICES = ("none", "minimal", "default")

FORMAT_CHOICES = ("flake8", "lazy-modules")
APPLY_CHOICES = ("list", "tuple", "set", "native", "dynamic")

DEFAULT_EXCLUDE_MODULES = ""

# When True, multi-level relative imports are rendered with a ``(__spec__.parent
# or "")`` guard so ``.rsplit`` type-checks under strict optional checking; when
# False (the default) the plainer ``__spec__.parent.rsplit(...)`` form is used.
DEFAULT_STRICT_TYPING = False


def parse_exclude_modules(raw: str | None) -> frozenset[str]:
    """Parse comma-separated module names from option text."""
    value = raw or ""
    return frozenset(module.strip() for module in value.split(",") if module.strip())
