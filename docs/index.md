---
icon: lucide/rocket
---

# Get started

flake8-lazy helps keep import-time overhead low by detecting imports that can be
declared as lazy in `__lazy_modules__`. For this package itself,
`flake8-lazy --help` runs roughly twice as fast when using Python 3.15's new
lazy import system (following [PEP 810](https://peps.python.org/pep-0810/)).

Error messages will mention `__lazy_modules__`, but the `lazy` keyword is
supported too.

## Installation

```bash
python -m pip install flake8-lazy
```

Usually you would include this in some sort of dependency-group in your project,
e.g. `dev` or `lint`. There's also a standalone runner. If you use uv or pipx,
you can run it from anywhere without installation:

```bash
uvx flake8-lazy <filenames>
# OR
pipx run flake8-lazy <filenames>
```

## Run through flake8

```bash
flake8 your_package
```

The plugin is auto-discovered by flake8 via entry points.

## Run through pre-commit

flake8-lazy ships a [pre-commit](https://pre-commit.com) hook, so you can run
the standalone checker without installing it into your environment. Add it to
your `.pre-commit-config.yaml`:

```yaml
- repo: https://github.com/henryiii/flake8-lazy
  rev: v0.8.1
  hooks:
    - id: flake8-lazy
```

By default the hook only reports diagnostics. To have it rewrite files in place,
pass `--apply`:

```yaml
- repo: https://github.com/henryiii/flake8-lazy
  rev: v0.8.1
  hooks:
    - id: flake8-lazy
      args: [--apply=list]
```

## Next steps

- [Rule reference](rules.md) — all LZY error codes
- [Examples](examples.md) — common patterns and diagnostics
- [CLI mode](cli.md) — standalone runner and `--apply` auto-fix
- [How it works](how-it-works.md) — detection logic and lazy-capable imports

## Acknowledgements

[GitHub Copilot](https://github.com/features/copilot) in VS Code was used to
help develop this package. The
[Scientific Python Development Guide](https://learn.scientific-python.org/development/)
template was used as a starting point.
