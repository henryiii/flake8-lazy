---
name: setup-lazy-imports
description: >-
  Set up flake8-lazy in a repository — add its pre-commit hook (defaulting to
  --apply=set), run it once to rewrite files with __lazy_modules__ declarations,
  then verify nothing broke by running the test suite and an import smoke check.
  Use this whenever the user wants to set up, add, enable, adopt, or apply lazy
  imports, PEP 810, __lazy_modules__, or flake8-lazy in a project; wants to
  "lazify" a codebase, make imports lazy, cut import-time overhead, or speed up
  CLI/app startup — even if they don't name the tool explicitly.
---

# Set up lazy imports (flake8-lazy)

## What this does and why

[flake8-lazy](https://github.com/henryiii/flake8-lazy) finds top-level imports
that are only used inside functions and can therefore be deferred. Declaring
them in `__lazy_modules__` (backward compatible with all Python versions, and
honored natively as lazy imports on 3.15+ / PEP 810) cuts import-time overhead —
often a large win for CLIs and apps where startup latency matters.

Your job is to make adoption a one-shot, safe operation: wire up the pre-commit
hook so the declarations stay correct over time, do the initial bulk rewrite,
and then prove the change is safe before handing it back. The rewrite is
mechanical but touches many files, so verification is the part that earns trust.

## Preconditions — check first

- **Git repo.** You need `git` for the bulk run (`git ls-files`) and to show a
  reviewable diff (`git diff`). If it isn't a git repo, tell the user and stop.
- **Note the starting state.** Run `git status --short`. If the tree is already
  dirty, say so — you want the final diff to be attributable to this tool, not
  mixed with unrelated edits. Don't commit or stash on the user's behalf unless
  they ask.
- **Python project.** Confirm there are `.py` files to act on.

## Step 1 — Determine the pinned version

Pre-commit hooks pin a `rev`. Fetch the latest release tag rather than guessing:

```bash
gh release view --repo henryiii/flake8-lazy --json tagName -q .tagName
```

If `gh` is unavailable, fall back to:

```bash
git ls-remote --tags --refs https://github.com/henryiii/flake8-lazy \
  | sed 's#.*/##' | sort -V | tail -1
```

Use that tag (e.g. `v0.8.3`) verbatim as the `rev`.

## Step 2 — Add the hook to `.pre-commit-config.yaml`

The default apply mode is **`set`** — `__lazy_modules__ = {"a", "b"}` — which is
slightly slower to build but faster for membership checks. Use `set` unless the
user asked for another mode (`list`, `tuple`, `native`, `dynamic`).

The block to add (match the indentation the file already uses — most configs put
`- repo:` at two spaces):

```yaml
- repo: https://github.com/henryiii/flake8-lazy
  rev: v0.8.3 # replace with the tag from Step 1
  hooks:
    - id: flake8-lazy
      files: ^src/
      args: [--apply=set, --strict-typing]
```

Handle the three cases:

- **No `.pre-commit-config.yaml`.** Create one with a `repos:` list containing
  just this block. Keep it minimal — don't invent unrelated hooks.
- **File exists, no flake8-lazy repo.** Append the block under `repos:`,
  matching the existing style. Edit the text directly rather than round-tripping
  through a YAML library, which would strip the file's comments and formatting.
- **flake8-lazy already present.** Update `rev` to the latest tag and make sure
  `args` includes `--apply=set` (or the user's chosen mode). Don't duplicate the
  repo block.

This should target the package files only (src or the package module).
`--strict-typing` is optional - it only matters if relative imports to outer
packages are being used.

## Step 3 — Run it once to rewrite files

Prefer the project's pre-commit runner so the run matches what will happen on
every future commit. Use `prek` (or `pre-commit`) and target just this hook:

```bash
prek run flake8-lazy --all-files    # or: pre-commit run flake8-lazy --all-files
```

**A non-zero exit here is expected, not a failure.** pre-commit reports the hook
as "Failed" whenever it modifies files — that's exactly what `--apply` does on a
codebase that had no lazy declarations yet. Judge success by the resulting
`git diff`, not the exit code. (Re-running until it passes is optional; the
point is the files are now rewritten.)

If neither `prek` nor `pre-commit` is installed, fall back to the standalone
runner over the tracked Python files (the CLI takes explicit files, not
directories):

```bash
uvx flake8-lazy --apply=set $(git ls-files '*.py')
```

Same note on exit status: `--apply` exits `1` when it finds/changes anything.

## Step 4 — Verify nothing broke

This is where you earn trust. Two checks:

1. **Import smoke check.** Import each top-level package so an obviously broken
   rewrite surfaces immediately. Find the package name(s) from `[project].name`
   / the `src/` layout / top-level packages, then:

   ```bash
   uv run --python 3.15 python -c "import your_package"   # or: python -c "import your_package"
   ```

2. **Test suite.** Run the project's normal test command — check `CLAUDE.md`,
   `README`, or `pyproject.toml` for how tests run. Common forms:

   ```bash
   uv run --python=3.15 pytest -q    # uv-managed projects or general projects
   nox -P 3.15 -s tests              # if the project uses nox
   ```

If tests or the import check fail, investigate before declaring success. The
likely culprits: a module that is actually used at module top level (flake8-lazy
flags these as `LZY401` rather than making them lazy, but a genuine failure
means something referenced a lazily-deferred name too early), or a conditional
import the tool couldn't prove safe. Report the failure with output; don't paper
over it.

## Step 5 — Report

Summarize concisely:

- The hook that was added/updated (repo + rev + args).
- What changed: `git diff --stat`, and the count of files that gained
  `__lazy_modules__`.
- Verification result: import check ✓/✗, tests ✓/✗ with the command used.
- Anything left for the user — e.g. remaining `LZY4xx` diagnostics the tool
  reported but did not auto-fix, or files it skipped.

Leave the changes unstaged so the user can review the diff themselves unless
they asked you to commit.

## Notes

- `--apply=set` only writes/updates the `__lazy_modules__` declaration; it never
  moves or deletes import statements. Imports the tool can't prove are
  deferrable are simply left out.
- The output is already black/ruff-compatible (magic trailing comma when a
  declaration is split across lines), so it won't fight a formatter.
- This hook is self-contained (`language: python` installs the runner), so you
  do **not** need to add flake8-lazy to the project's dependencies for the hook
  to work. Mention adding it to a `dev`/`lint` group only if the user wants to
  run it or the flake8 plugin outside pre-commit.
