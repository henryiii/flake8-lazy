"""flake8 checker implementation."""

from __future__ import annotations

__lazy_modules__ = [
    f"{__spec__.parent}._always_imported",
    f"{__spec__.parent}._analysis",
    f"{__spec__.parent}._collect",
    f"{__spec__.parent}._options",
    "importlib",
    "importlib.metadata",
]

import importlib.metadata
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse
    import ast
    from typing import Protocol

    from ._model import ModuleInfo

    class _OptionManager(Protocol):
        """Minimal protocol for flake8's OptionManager."""

        def add_option(
            self,
            *args: str,
            parse_from_config: bool = ...,
            **kwargs: object,
        ) -> None: ...


from ._always_imported import IMPORT_PRESETS
from ._analysis import (
    collect_broken_lazy_modules,
    collect_duplicate_lazy_modules,
    collect_enclosing_lazy_modules,
    collect_invalid_lazy_module_names,
    collect_late_lazy_module_assignments,
    collect_lazy_imports_in_suppress_blocks,
    collect_missing_lazy_modules,
    collect_mixed_lazy_eager_imports,
    collect_redundant_lazy_declarations,
    collect_unnecessary_lazy_imports,
    collect_unsorted_lazy_modules,
    collect_unused_lazy_modules,
)
from ._collect import build_module_info
from ._options import (
    DEFAULT_EXCLUDE_MODULES,
    DEFAULT_IMPORT_PRESET,
    DEFAULT_STRICT_TYPING,
    parse_exclude_modules,
)

__all__ = ["ERROR_MESSAGES", "LazyImportChecker"]


ERROR_MESSAGES = {
    "LZY101": "stdlib module {module!r} should be listed in __lazy_modules__",
    "LZY102": "module {module!r} should be listed in __lazy_modules__",
    "LZY201": "__lazy_modules__ should be sorted",
    "LZY204": "__lazy_modules__ should be assigned before importing modules it names",
    "LZY202": "module {module!r} is listed in __lazy_modules__ but never imported",
    "LZY203": "module {module!r} is duplicated in __lazy_modules__",
    "LZY205": "module {module!r} in __lazy_modules__ must be absolute",
    "LZY206": (
        "module {module!r} is listed in __lazy_modules__"
        " but is broken under lazy imports"
    ),
    "LZY301": "lazy import {module!r} inside suppress(ImportError) is misleading",
    "LZY302": (
        "module {module!r} is declared lazy by both 'lazy' keyword and __lazy_modules__"
    ),
    "LZY303": "module {module!r} is imported both eagerly and lazily",
    "LZY401": "module {module!r} is declared lazy but accessed at the top level",
    "LZY402": (
        "module {module!r} is an enclosing package for this file "
        "and should not be declared lazy"
    ),
}


def _lazy_module_error_code(module: str) -> str:
    root_module = module.split(".", maxsplit=1)[0]
    if root_module in sys.stdlib_module_names:
        return "LZY101"
    return "LZY102"


def _missing_lazy_module_diagnostics(
    info: ModuleInfo, *, always_imported: frozenset[str]
) -> list[tuple[int, int, str]]:
    diagnostics: list[tuple[int, int, str]] = []
    for module, lineno, col_offset in collect_missing_lazy_modules(
        info, always_imported=always_imported
    ):
        code = _lazy_module_error_code(module)
        message = ERROR_MESSAGES[code].format(module=module)
        diagnostics.append((lineno, col_offset, f"{code} {message}"))
    return diagnostics


def _lazy_module_validation_diagnostics(
    info: ModuleInfo,
) -> list[tuple[int, int, str]]:
    if info.has_dynamic_lazy_modules:
        return []
    diagnostics: list[tuple[int, int, str]] = []
    for lineno, col_offset in collect_unsorted_lazy_modules(info):
        diagnostics.append((lineno, col_offset, f"LZY201 {ERROR_MESSAGES['LZY201']}"))
    for module, lineno, col_offset in collect_unused_lazy_modules(info):
        message = ERROR_MESSAGES["LZY202"].format(module=module)
        diagnostics.append((lineno, col_offset, f"LZY202 {message}"))
    for module, lineno, col_offset in collect_duplicate_lazy_modules(info):
        message = ERROR_MESSAGES["LZY203"].format(module=module)
        diagnostics.append((lineno, col_offset, f"LZY203 {message}"))
    for lineno, col_offset in collect_late_lazy_module_assignments(info):
        diagnostics.append((lineno, col_offset, f"LZY204 {ERROR_MESSAGES['LZY204']}"))
    for module, lineno, col_offset in collect_invalid_lazy_module_names(info):
        message = ERROR_MESSAGES["LZY205"].format(module=module)
        diagnostics.append((lineno, col_offset, f"LZY205 {message}"))
    for module, lineno, col_offset in collect_broken_lazy_modules(info):
        message = ERROR_MESSAGES["LZY206"].format(module=module)
        diagnostics.append((lineno, col_offset, f"LZY206 {message}"))
    return diagnostics


def _lazy_keyword_diagnostics(info: ModuleInfo) -> list[tuple[int, int, str]]:
    diagnostics: list[tuple[int, int, str]] = []
    for module, lineno, col_offset in collect_lazy_imports_in_suppress_blocks(info):
        message = ERROR_MESSAGES["LZY301"].format(module=module)
        diagnostics.append((lineno, col_offset, f"LZY301 {message}"))
    for module, lineno, col_offset in collect_redundant_lazy_declarations(info):
        message = ERROR_MESSAGES["LZY302"].format(module=module)
        diagnostics.append((lineno, col_offset, f"LZY302 {message}"))
    for module, lineno, col_offset in collect_mixed_lazy_eager_imports(info):
        message = ERROR_MESSAGES["LZY303"].format(module=module)
        diagnostics.append((lineno, col_offset, f"LZY303 {message}"))
    return diagnostics


def _semantic_lazy_diagnostics(info: ModuleInfo) -> list[tuple[int, int, str]]:
    diagnostics: list[tuple[int, int, str]] = []
    for module, lineno, col_offset in collect_unnecessary_lazy_imports(info):
        message = ERROR_MESSAGES["LZY401"].format(module=module)
        diagnostics.append((lineno, col_offset, f"LZY401 {message}"))
    for module, lineno, col_offset in collect_enclosing_lazy_modules(info):
        message = ERROR_MESSAGES["LZY402"].format(module=module)
        diagnostics.append((lineno, col_offset, f"LZY402 {message}"))
    return diagnostics


def build_diagnostics(
    info: ModuleInfo, *, always_imported: frozenset[str]
) -> list[tuple[int, int, str]]:
    """Return all ``(lineno, col_offset, "CODE message")`` diagnostics for ``info``."""
    diagnostics = _missing_lazy_module_diagnostics(
        info, always_imported=always_imported
    )
    diagnostics += _lazy_module_validation_diagnostics(info)
    diagnostics += _lazy_keyword_diagnostics(info)
    diagnostics += _semantic_lazy_diagnostics(info)
    return diagnostics


class LazyImportChecker:
    """flake8 checker for imports that can be made lazy."""

    name = "flake8-lazy"
    version = importlib.metadata.version("flake8-lazy")
    __slots__ = ("filename", "tree")

    # Class-level options, set by parse_options when running under flake8.
    import_preset: str = DEFAULT_IMPORT_PRESET
    exclude_modules: frozenset[str] = frozenset()
    strict_typing: bool = DEFAULT_STRICT_TYPING

    def __init__(self, tree: ast.AST, filename: str) -> None:
        self.tree = tree
        self.filename = filename

    @classmethod
    def add_options(cls, option_manager: _OptionManager) -> None:
        """Register lazy-import options with flake8's option manager."""
        option_manager.add_option(
            "--lazy-import-preset",
            default=DEFAULT_IMPORT_PRESET,
            parse_from_config=True,
            dest="lazy_import_preset",
            type=str,
            metavar="PRESET",
            help=(
                "Set of modules to treat as always-imported and skip from "
                "lazy-import recommendations. "
                "PRESET is one of: "
                "none (no filtering), "
                "default (normal python startup modules including site, default), "
                "minimal (python -IS startup modules). "
                "[%(default)s]"
            ),
        )
        option_manager.add_option(
            "--lazy-exclude-modules",
            default=DEFAULT_EXCLUDE_MODULES,
            parse_from_config=True,
            dest="lazy_exclude_modules",
            type=str,
            metavar="MODULES",
            help=(
                "Comma-separated list of module names to exclude from "
                "lazy-import recommendations. These modules are treated as "
                "always-imported and will not be flagged or recommended for "
                "lazy declarations. [%(default)s]"
            ),
        )
        option_manager.add_option(
            "--lazy-strict-typing",
            action="store_true",
            default=DEFAULT_STRICT_TYPING,
            parse_from_config=True,
            dest="lazy_strict_typing",
            help=(
                "Render multi-level relative imports in __lazy_modules__ with a "
                "'(__spec__.parent or \"\")' guard so they type-check under "
                "strict optional checking. [%(default)s]"
            ),
        )

    @classmethod
    def parse_options(
        cls,
        _option_manager: _OptionManager,
        options: argparse.Namespace,
        _args: list[str],
    ) -> None:
        """Read parsed flake8 options and store preset and non-lazy modules."""
        preset = options.lazy_import_preset
        if preset not in IMPORT_PRESETS:
            valid = ", ".join(sorted(IMPORT_PRESETS))
            msg = f"invalid --lazy-import-preset value {preset!r}; choose from: {valid}"
            raise ValueError(msg)
        cls.import_preset = preset
        cls.exclude_modules = parse_exclude_modules(options.lazy_exclude_modules)
        cls.strict_typing = bool(options.lazy_strict_typing)

    def run(
        self,
        *,
        always_imported: frozenset[str] | None = None,
        exclude_modules: frozenset[str] | None = None,
    ) -> list[tuple[int, int, str, type[LazyImportChecker]]]:
        if always_imported is None:
            always_imported = IMPORT_PRESETS[type(self).import_preset]
        if exclude_modules is None:
            exclude_modules = type(self).exclude_modules
        always_imported = always_imported | exclude_modules
        info = build_module_info(
            self.tree, self.filename, strict_typing=type(self).strict_typing
        )
        checker = type(self)
        return [
            (lineno, col_offset, message, checker)
            for lineno, col_offset, message in build_diagnostics(
                info, always_imported=always_imported
            )
        ]
