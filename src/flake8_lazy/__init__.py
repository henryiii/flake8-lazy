"""Copyright (c) 2026 Henry Schreiner. All rights reserved.

flake8-lazy: Detect imports that can be lazy
"""

from __future__ import annotations

import importlib.metadata

from .analysis import (
    collect_declared_lazy_modules,
    collect_duplicate_lazy_modules,
    collect_enclosing_lazy_modules,
    collect_invalid_lazy_module_names,
    collect_late_lazy_module_assignments,
    collect_lazy_imports_in_suppress_blocks,
    collect_lazy_packages,
    collect_missing_lazy_modules,
    collect_mixed_lazy_eager_imports,
    collect_recommended_lazy_modules,
    collect_redundant_lazy_declarations,
    collect_side_effect_only_import_packages,
    collect_unnecessary_lazy_imports,
    collect_unsorted_lazy_modules,
    collect_unused_lazy_modules,
)
from .api import (
    collect_declared_lazy_modules_for_file,
    collect_errors_for_file,
    collect_recommended_lazy_modules_for_file,
)
from .checker import LazyImportChecker
from .visitors import (
    collect_non_lazy_imports,
    collect_strictly_top_level_names,
    collect_top_level_imports,
)

__version__ = importlib.metadata.version("flake8-lazy")

__all__ = [
    "LazyImportChecker",
    "__version__",
    "collect_declared_lazy_modules",
    "collect_declared_lazy_modules_for_file",
    "collect_duplicate_lazy_modules",
    "collect_enclosing_lazy_modules",
    "collect_errors_for_file",
    "collect_invalid_lazy_module_names",
    "collect_late_lazy_module_assignments",
    "collect_lazy_imports_in_suppress_blocks",
    "collect_lazy_packages",
    "collect_missing_lazy_modules",
    "collect_mixed_lazy_eager_imports",
    "collect_non_lazy_imports",
    "collect_recommended_lazy_modules",
    "collect_recommended_lazy_modules_for_file",
    "collect_redundant_lazy_declarations",
    "collect_side_effect_only_import_packages",
    "collect_strictly_top_level_names",
    "collect_top_level_imports",
    "collect_unnecessary_lazy_imports",
    "collect_unsorted_lazy_modules",
    "collect_unused_lazy_modules",
]


def __dir__() -> list[str]:
    return __all__
