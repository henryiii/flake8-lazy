# flake8-lazy development

## Purpose

This is a flake8 plugin and standalone runner to help users with lazy imports
defined in [PEP 810](https://peps.python.org/pep-0810/). Using either a list
`__lazy_modules__` of full import names or the new `lazy` soft keyword when
importing, modules are marked to be loaded later.

## Project layout

Some key files:

- `pyproject.toml`: Most configuration
- `docs/index.md`: Documentation
- `zensical.toml`: Docs configuration
- `.pre-commit-config.yaml`: `prek` (pre-commit) configuration
- `src/flake8_lazy/`: Core package code
- `src/flake8_lazy/__init__.py`: Public plugin and runner entry points
- `src/flake8_lazy/checker.py`: Main flake8 checker implementation
- `src/flake8_lazy/_analysis.py`: Import analysis logic
- `src/flake8_lazy/api.py`: Public types and helper APIs
- `src/flake8_lazy/_visitors.py`: AST visitor implementations
- `src/flake8_lazy/_rewriter.py`: Source rewriting helpers for `--apply`
- `src/flake8_lazy/__main__.py`: Standalone CLI entry point
- `tests/test_package.py`: Package-level behavior tests
- `tests/test_cli.py`: CLI behavior tests

## Dev environment

The CLI tools `uv`, `prek`, and `nox` should be pre-installed as Python tools.

- `uv sync` (along with all the run commands) will ensure a `.venv` folder with
  an environment is created and populated.
- `uv run <command>` is a good way to run things like `pytest`. It will
  automatically make the `.venv` folder if it doesn't exist yet.
- `prek -a` will check the formatting and style.
- `nox -s pylint` will run pylint, a little slower (few seconds) but can report
  issues the faster checks can't.
- Docs are build with `nox -s docs --non-interactive`, and uses Zensical, a new
  tool that is very, very similar to mkdocs.
- You can run this on itself with `nox -s selfcheck`, which should be done if
  imports change.

## Testing instructions

- `uv run pytest` is a good way to run tests. Args can be easily added, like for
  a specific test.
- You can request a Python 3.15 alpha with `uv run --python 3.15 pytest`,
  remember it is "sticky", the `.venv` will be made with 3.15.
- Always add/update tests.
- Run `prek -a` to fixup style and look for linting issues.
- When running `prek -a` or `nox -s pylint`, the linting rules are _very_
  strict, so adding a local or global skip for a troublesome rule is fine if it
  makes the code better.

## Working on code

- Update the `README.md` and `docs/index.md` if rules or options change.
- Code is Python 3.10+, modern coding practices (like pattern matching)
  encouraged.
- Readability is important. Feel free to comment blocks and docstrings to
  explain what is happening.
- This is still a new project, feel free to refactor or change things to improve
  it.

## PR instructions

- Titles follow Conventional Commits (like `feat: ...`)
- Always run `prek -a` and `nox -s pylint` before committing.
