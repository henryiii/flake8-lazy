---
icon: lucide/terminal
---

# CLI mode

You can also run the checker directly:

```bash
flake8-lazy path/to/file.py
# or
uvx flake8-lazy path/to/file.py
```

By default, output is flake8-like:

```text
path/to/file.py:1:0: LZY102 module 'numpy' should be listed in __lazy_modules__
```

For a copy-pasteable recommendation, use the alternate format:

```bash
flake8-lazy --format lazy-modules path/to/file.py
```

```text
path/to/file.py: __lazy_modules__ = ["numpy"]
```

This prints the sorted `__lazy_modules__` value the checker recommends for each
file when it differs from the file's current static `__lazy_modules__`
declaration, while keeping the same exit-status behavior.

## Auto-apply with `--apply`

To rewrite files in place with the recommended declaration, use `--apply=list`:

```bash
flake8-lazy --apply=list path/to/file.py another_file.py
```

`--apply` replaces an existing top-level `__lazy_modules__` assignment when
present. If there is no assignment yet, one is inserted near the top of the file
after leading comments/docstrings (and after `from __future__ import ...` lines,
to keep valid Python syntax).

The available modes are:

| Mode      | Output                                                                |
| --------- | --------------------------------------------------------------------- |
| `list`    | `__lazy_modules__ = ["a", "b"]`                                       |
| `set`     | `__lazy_modules__ = {"a", "b"}` (slower construct, faster membership) |
| `native`  | `lazy import a` / `lazy from b import ...` (3.15+)                    |
| `dynamic` | `AllLazy` class that always returns `True` for `in`                   |

### Dynamic mode

The `dynamic` mode inserts:

```python
class AllLazy:
    @staticmethod
    def __contains__(_: str) -> bool:
        return True


__lazy_modules__ = AllLazy()
```

This is the shortest way to declare every import as lazy without enumerating
them. It is idempotent: running `--apply=dynamic` on a file that already has a
dynamic `__lazy_modules__` is a no-op.

### Line length

For the `list` and `set` modes, if the single-line assignment would exceed the
line length (`--line-length`, default `88`, matching black/ruff), it is written
one module per line with a trailing comma, black/ruff style:

```python
__lazy_modules__ = [
    "long_package_name_one",
    "long_package_name_two",
    "long_package_name_three",
]
```

The trailing comma is a "magic trailing comma", so black and ruff keep the
exploded form instead of collapsing it. This means `--apply` output does not
need to be reformatted afterwards. Pass `--line-length=0` to disable splitting
and always write the assignment on a single line.

The command exits with status `1` if any diagnostics are produced.

## Use with pre-commit / prek

The standalone runner is also available as a
[pre-commit](https://pre-commit.com) / [prek](https://prek.j178.dev) hook, which
installs and runs it for you. Add it to your `.pre-commit-config.yaml`:

```yaml
- repo: https://github.com/henryiii/flake8-lazy
  rev: v0.8.0
  hooks:
    - id: flake8-lazy
```

The hook runs on staged Python files and reports diagnostics by default. Any of
the CLI options above can be passed through `args`. For example, to auto-apply
the recommended `__lazy_modules__` declaration on commit:

```yaml
- repo: https://github.com/henryiii/flake8-lazy
  rev: v0.8.0
  hooks:
    - id: flake8-lazy
      args: [--apply=list]
```

When `--apply` rewrites a file, pre-commit reports the hook as failed and leaves
the changes in your working tree for review, just like other auto-fixing hooks
(black, ruff, etc.). Re-stage the files and re-run the commit to accept them.

## Configuring always-imported modules with `--lazy-import-preset`

Some modules are always loaded before any user code runs (e.g. `sys`, `time`).
Declaring such modules in `__lazy_modules__` has no effect, so flake8-lazy skips
them from its recommendations by default. You can control which set of modules
is excluded via `--lazy-import-preset`:

| Preset    | Modules excluded from recommendations                                                   |
| --------- | --------------------------------------------------------------------------------------- |
| `default` | Modules imported during a normal Python startup (includes `os`, `site`, etc.). Default. |
| `minimal` | Modules imported when Python starts in isolated mode (`-IS`).                           |
| `none`    | No exclusions — all imported modules are candidates.                                    |

```bash
# Use the smaller isolated-startup set
flake8-lazy --lazy-import-preset=minimal path/to/file.py

# Recommend lazy imports for every module, even always-imported ones
flake8-lazy --lazy-import-preset=none path/to/file.py
```

When using flake8 directly, set the option in your `.flake8` or `setup.cfg`:

```ini
[flake8]
lazy-import-preset = default
```

## Excluding specific modules with `--lazy-exclude-modules`

To exclude individual modules from lazy-import recommendations — for example,
modules that your project always imports at startup, or that must stay eager for
correctness — use `--lazy-exclude-modules` with a comma-separated list:

```bash
flake8-lazy --lazy-exclude-modules=numpy,pandas path/to/file.py
```

Modules listed here are treated as always-imported and will not be flagged
(LZY101/LZY102) or included in `--format lazy-modules` recommendations.

When using flake8 directly, add the option to your `.flake8` or `setup.cfg`:

```ini
[flake8]
lazy-exclude-modules = numpy,pandas
```
