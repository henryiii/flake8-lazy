"""flake8 checker implementation."""

from __future__ import annotations

__lazy_modules__ = [
    f"{__spec__.parent}._always_imported",
    f"{__spec__.parent}._analysis",
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
    has_dynamic_lazy_modules,
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


class LazyImportChecker:
    """flake8 checker for imports that can be made lazy."""

    name = "flake8-lazy"
    version = importlib.metadata.version("flake8-lazy")
    __slots__ = ("filename", "tree")

    # Class-level options, set by parse_options when running under flake8.
    import_preset: str = "default"
    exclude_modules: frozenset[str] = frozenset()

    def __init__(self, tree: ast.AST, filename: str) -> None:
        self.tree = tree
        self.filename = filename

    @classmethod
    def add_options(cls, option_manager: _OptionManager) -> None:
        """Register lazy-import options with flake8's option manager."""
        option_manager.add_option(
            "--lazy-import-preset",
            default="default",
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
            default="",
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
        raw = options.lazy_exclude_modules or ""
        cls.exclude_modules = frozenset(m.strip() for m in raw.split(",") if m.strip())

    def _build_missing_lazy_module_errors(
        self,
        *,
        always_imported: frozenset[str],
    ) -> list[tuple[int, int, str, type[LazyImportChecker]]]:
        errors: list[tuple[int, int, str, type[LazyImportChecker]]] = []
        for module, lineno, col_offset in collect_missing_lazy_modules(
            self.tree,
            filename=self.filename,
            always_imported=always_imported,
        ):
            code = _lazy_module_error_code(module)
            message = ERROR_MESSAGES[code].format(module=module)
            errors.append((lineno, col_offset, f"{code} {message}", type(self)))
        return errors

    def _build_lazy_module_validation_errors(
        self,
    ) -> list[tuple[int, int, str, type[LazyImportChecker]]]:
        if has_dynamic_lazy_modules(self.tree):
            return []
        errors: list[tuple[int, int, str, type[LazyImportChecker]]] = []
        for lineno, col_offset in collect_unsorted_lazy_modules(self.tree):
            errors.append(
                (
                    lineno,
                    col_offset,
                    f"LZY201 {ERROR_MESSAGES['LZY201']}",
                    type(self),
                )
            )

        for module, lineno, col_offset in collect_unused_lazy_modules(
            self.tree,
            filename=self.filename,
        ):
            message = ERROR_MESSAGES["LZY202"].format(module=module)
            errors.append((lineno, col_offset, f"LZY202 {message}", type(self)))

        for module, lineno, col_offset in collect_duplicate_lazy_modules(self.tree):
            message = ERROR_MESSAGES["LZY203"].format(module=module)
            errors.append((lineno, col_offset, f"LZY203 {message}", type(self)))

        for lineno, col_offset in collect_late_lazy_module_assignments(self.tree):
            errors.append(
                (
                    lineno,
                    col_offset,
                    f"LZY204 {ERROR_MESSAGES['LZY204']}",
                    type(self),
                )
            )

        for module, lineno, col_offset in collect_invalid_lazy_module_names(self.tree):
            message = ERROR_MESSAGES["LZY205"].format(module=module)
            errors.append((lineno, col_offset, f"LZY205 {message}", type(self)))

        return errors

    def _build_lazy_keyword_errors(
        self,
    ) -> list[tuple[int, int, str, type[LazyImportChecker]]]:
        errors: list[tuple[int, int, str, type[LazyImportChecker]]] = []
        for module, lineno, col_offset in collect_lazy_imports_in_suppress_blocks(
            self.tree
        ):
            message = ERROR_MESSAGES["LZY301"].format(module=module)
            errors.append((lineno, col_offset, f"LZY301 {message}", type(self)))

        for module, lineno, col_offset in collect_redundant_lazy_declarations(
            self.tree
        ):
            message = ERROR_MESSAGES["LZY302"].format(module=module)
            errors.append((lineno, col_offset, f"LZY302 {message}", type(self)))

        for module, lineno, col_offset in collect_mixed_lazy_eager_imports(self.tree):
            message = ERROR_MESSAGES["LZY303"].format(module=module)
            errors.append((lineno, col_offset, f"LZY303 {message}", type(self)))

        return errors

    def _build_semantic_lazy_errors(
        self,
    ) -> list[tuple[int, int, str, type[LazyImportChecker]]]:
        errors: list[tuple[int, int, str, type[LazyImportChecker]]] = []
        for module, lineno, col_offset in collect_unnecessary_lazy_imports(self.tree):
            message = ERROR_MESSAGES["LZY401"].format(module=module)
            errors.append((lineno, col_offset, f"LZY401 {message}", type(self)))
        for module, lineno, col_offset in collect_enclosing_lazy_modules(
            self.tree,
            filename=self.filename,
        ):
            message = ERROR_MESSAGES["LZY402"].format(module=module)
            errors.append((lineno, col_offset, f"LZY402 {message}", type(self)))
        return errors

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
        errors: list[tuple[int, int, str, type[LazyImportChecker]]] = []
        errors.extend(
            self._build_missing_lazy_module_errors(always_imported=always_imported)
        )
        errors.extend(self._build_lazy_module_validation_errors())
        errors.extend(self._build_lazy_keyword_errors())
        errors.extend(self._build_semantic_lazy_errors())
        return errors
