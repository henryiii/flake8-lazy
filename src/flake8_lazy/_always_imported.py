"""Modules that Python always imports at startup.

These modules are unconditionally present in ``sys.modules`` before any user
code runs.  Declaring them in ``__lazy_modules__`` has no effect and is
therefore not recommended.

The list below was generated with ``scripts/list_always_imported.py`` using
CPython 3.15 on Unix.  Platform-specific names (e.g. ``posix`` on POSIX,
``nt`` on Windows) are included for both platforms so the set is useful on
all supported operating systems.
"""

from __future__ import annotations

# Generated with: python scripts/list_always_imported.py  (CPython 3.15, Linux)
ALWAYS_IMPORTED: frozenset[str] = frozenset(
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
