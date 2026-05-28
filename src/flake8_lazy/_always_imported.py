"""Modules that Python imports at startup under specific configurations.

Declaring these modules in ``__lazy_modules__`` has no effect because they are
already present in ``sys.modules`` before user code runs, so they are skipped
from lazy-import recommendations.

Two preset sets are provided, corresponding to different Python startup modes:

* ``ALWAYS_IMPORTED_MINIMAL`` — modules present when Python starts in isolated
  + no-site mode (``python -IS``).  A small core set: ``sys``, ``time``,
  ``codecs``, etc.
* ``ALWAYS_IMPORTED_DEFAULT`` — modules present during a normal Python startup
  (``python -I``, with site initialisation).  Includes ``os``, ``os.path``,
  ``abc``, ``site``, and more.

The sets were generated with ``scripts/list_always_imported.py`` using
CPython 3.15 on Unix.  Platform-specific names (e.g. ``posix`` on POSIX,
``nt`` on Windows) are included for both platforms.
"""

from __future__ import annotations

# Generated with: uv run --python 3.15 python scripts/list_always_imported.py -S
# (CPython 3.15, Linux) — python -IS startup modules.
ALWAYS_IMPORTED_MINIMAL: frozenset[str] = frozenset(
    {
        "builtins",
        "codecs",
        "encodings",
        "encodings.aliases",
        "encodings.utf_8",
        "marshal",
        "nt",  # Windows equivalent of posix
        "posix",  # POSIX (Linux/macOS) low-level OS interface
        "sys",
        "sys.monitoring",
        "time",
        "zipimport",
    }
)

# Generated with: uv run --python 3.15 python scripts/list_always_imported.py
# (CPython 3.15, Linux) — modules present on normal Python startup (including site).
ALWAYS_IMPORTED_DEFAULT: frozenset[str] = frozenset(
    {
        "abc",
        "builtins",
        "codecs",
        "encodings",
        "encodings.aliases",
        "encodings.utf_8",
        "encodings.utf_8_sig",
        "errno",
        "genericpath",
        "marshal",
        "nt",  # Windows
        "ntpath",  # Windows
        "os",
        "os.path",
        "posix",  # POSIX (Linux/macOS)
        "posixpath",  # POSIX (Linux/macOS)
        "site",
        "stat",
        "sys",
        "sys.monitoring",
        "time",
        "zipimport",
    }
)

# Map of preset name → frozenset of always-imported module names.
IMPORT_PRESETS: dict[str, frozenset[str]] = {
    "none": frozenset(),
    "minimal": ALWAYS_IMPORTED_MINIMAL,
    "default": ALWAYS_IMPORTED_DEFAULT,
}
