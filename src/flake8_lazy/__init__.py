"""Copyright (c) 2026 Henry Schreiner. All rights reserved.

flake8-lazy: Detect imports that can be lazy
"""

from __future__ import annotations

__lazy_modules__ = [f"{__spec__.parent}.checker"]

import importlib.metadata

from .checker import LazyImportChecker

__version__ = importlib.metadata.version("flake8-lazy")

__all__ = [
    "LazyImportChecker",
    "__version__",
]


def __dir__() -> list[str]:
    return __all__
