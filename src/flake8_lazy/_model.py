"""Data model produced by the single-pass module analysis.

These dataclasses are the boundary between Phase 1 (``_collect.build_module_info``
walks the AST exactly once) and Phase 2 (the pure ``_analysis`` checks read only
this model — no further AST traversal).  They hold plain data only, so a
``ModuleInfo`` is trivially picklable and cheap to pass between functions.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ImportInfo:
    """A single module-scope import binding (one per statement-and-alias)."""

    package: str | None
    """Resolved package, including the ``f"{__spec__.parent}.x"`` relative form."""

    bound_name: str
    is_aliased: bool
    is_from_import: bool
    """True for ``from a import b``; False for ``import a.b``."""

    is_lazy: bool
    """True when declared with the native ``lazy`` keyword (Python 3.15+)."""

    is_guarded: bool
    """True when imported in a region blocked from lazy recommendation
    (``TYPE_CHECKING`` or a ``sys.version_info`` guard excluding 3.15+)."""

    runtime_visible: bool
    """True unless the import lives in a ``TYPE_CHECKING`` if-body (which never
    executes at runtime and is excluded from the top-level import list)."""

    lineno: int
    col_offset: int


@dataclass(frozen=True, slots=True)
class LazyAssignment:
    """A static ``__lazy_modules__ = [...]`` assignment with its location."""

    modules: list[str]
    lineno: int
    col_offset: int


@dataclass(frozen=True, slots=True)
class ModuleInfo:
    """Everything the lazy-import checks need, collected in one AST pass."""

    imports: tuple[ImportInfo, ...]
    """Module-scope imports in source order; ``*`` imports are skipped."""

    static_lazy_assignments: tuple[LazyAssignment, ...]
    lazy_module_entries: tuple[tuple[str, int, int], ...]
    """Per-element ``(module, lineno, col_offset)`` in source order."""

    suppress_lazy_imports: tuple[tuple[str, int, int], ...]
    """``(module, lineno, col_offset)`` for native ``lazy`` imports that are
    direct children of a top-level ``suppress(ImportError)`` block (LZY301)."""

    declared_lazy_modules: list[str] | None
    """Modules of the last static ``__lazy_modules__`` assignment, if any."""

    has_dynamic_lazy_modules: bool
    """True if any ``__lazy_modules__`` value is a non-static (dynamic) object."""

    late_lazy_module_locations: tuple[tuple[int, int], ...]
    """Locations of ``__lazy_modules__`` assignments that follow an import of a
    module they name (LZY204)."""

    runtime_names: frozenset[str]
    runtime_attribute_paths: frozenset[str]
    strict_names: frozenset[str]
    strict_attribute_paths: frozenset[str]
    all_loaded_names: frozenset[str]
    type_checking_guard_names: frozenset[str]
    guarded_packages: frozenset[str]
    side_effect_only_packages: frozenset[str]
    enclosing_packages: frozenset[str] = field(default_factory=frozenset)

    @property
    def lazy_packages(self) -> set[str]:
        """Statically-declared ``__lazy_modules__`` values (last assignment)."""
        return set(self.declared_lazy_modules or ())
