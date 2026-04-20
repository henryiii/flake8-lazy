# flake8-lazy development

## Purpose

flake8 plugin and standalone runner for lazy imports (PEP 810). Detects imports
that can be moved to `__lazy_modules__` or declared with the `lazy` soft keyword
(Python 3.15+).

## Project layout

- `src/flake8_lazy/__init__.py`: Plugin entry point (`LazyImportChecker`) and
  public API
- `src/flake8_lazy/__main__.py`: Standalone CLI entry point
- `src/flake8_lazy/checker.py`: Main flake8 checker
- `src/flake8_lazy/_analysis.py`: Import analysis logic
- `src/flake8_lazy/_visitors.py`: AST visitors
- `src/flake8_lazy/_rewriter.py`: `--apply` source rewriting
- `tests/test_package.py`: Package/rule tests
- `tests/test_cli.py`: CLI tests

## Dev commands

- `uv sync` — populate `.venv` (also happens implicitly on first `uv run`)
- `uv run pytest` — run tests (add `-k` or paths as needed)
- `prek -a` — run all pre-commit hooks with auto-fix (ruff, mypy, codespell,
  etc.)
- `nox -s pylint` — run pylint (slower, stricter; ok to add skip for false
  positives)
- `nox -s selfcheck` — run `flake8 --select=LZY src/`; **do this if imports
  change**
- `nox -s docs --non-interactive` — build docs (uses Zensical, similar to
  mkdocs)

## Testing

- pytest minversion 9.0; config lives in `pyproject.toml`
- `uv run --python 3.15 pytest` requests a 3.15 alpha; it is **sticky**
  (rewrites `.venv` to 3.15)
- Always run `prek -a` and `nox -s pylint` before committing

## Code conventions

- Python 3.10+; modern features (pattern matching, etc.) are fine
- Update `README.md` and `docs/index.md` if rules or CLI options change
- PR titles follow Conventional Commits (`feat: ...`)
- Always make sure `prek -a` runs and passes.
