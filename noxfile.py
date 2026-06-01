#!/usr/bin/env -S uv run --script

# /// script
# dependencies = ["nox>=2025.2.9"]
# ///

"""Nox runner."""

from __future__ import annotations

import shutil
import tarfile
import urllib.request
from pathlib import Path

import nox

DIR = Path(__file__).parent.resolve()
PROJECT = nox.project.load_toml()

nox.needs_version = ">=2025.2.9"
nox.options.default_venv_backend = "uv|virtualenv"


@nox.session
def lint(session: nox.Session) -> None:
    """Run the linter."""
    session.install("prek")
    session.run(
        "prek",
        "run",
        "--all-files",
        "--show-diff-on-failure",
        *session.posargs,
    )


@nox.session
def pylint(session: nox.Session) -> None:
    """Run Pylint."""
    # This needs to be installed into the package environment, and is slower
    # than a pre-commit check
    session.install("-e.", "pylint>=3.2")
    session.run("pylint", "flake8_lazy", *session.posargs)


@nox.session
def tests(session: nox.Session) -> None:
    """Run the unit and regular tests."""
    test_deps = nox.project.dependency_groups(PROJECT, "test")
    session.install("-e.", *test_deps)
    session.run("pytest", *session.posargs)


@nox.session(reuse_venv=True, default=False)
def docs(session: nox.Session) -> None:
    """Make or serve the docs. Pass --non-interactive to avoid serving."""
    doc_deps = nox.project.dependency_groups(PROJECT, "docs")
    session.install("-e.", *doc_deps)

    if session.interactive:
        session.run("zensical", "serve", *session.posargs)
    else:
        session.run("zensical", "build", "--clean", *session.posargs)


@nox.session(python="3.15.0b1", default=False)
def cpython(session: nox.Session) -> None:
    """Run flake8-lazy on the CPython 3.15.0b1 source tree."""
    cpython_dir = DIR / ".nox" / "cpython-3.15.0b1"
    if not cpython_dir.exists():
        tarball = DIR / ".nox" / "cpython-3.15.0b1.tgz"
        if not tarball.exists():
            session.log("Downloading CPython 3.15.0b1 source...")
            url = "https://www.python.org/ftp/python/3.15.0/Python-3.15.0b1.tgz"
            urllib.request.urlretrieve(url, tarball)  # noqa: S310
        session.log("Extracting CPython source...")
        with tarfile.open(tarball, "r:gz") as tf:
            tf.extractall(path=DIR / ".nox", filter="data")
        extracted = DIR / ".nox" / "Python-3.15.0b1"
        extracted.rename(cpython_dir)

    session.install("-e.")
    # Exclude directories that contain intentionally broken/unparsable Python files.
    _skip = frozenset({"badsyntax", "tokenizedata", "syntax_warnings.py"})
    files = sorted(
        str(p) for p in cpython_dir.rglob("*.py") if not _skip.intersection(p.parts)
    )
    session.run(
        "flake8-lazy", "-j", "auto", *files, *session.posargs, success_codes=[0, 1]
    )


@nox.session
def selfcheck(session: nox.Session) -> None:
    """Run flake8 with --select=LZY on the project itself."""
    session.install("-e.", "flake8")
    session.run("flake8", "--select=LZY", "src/", *session.posargs)


@nox.session(default=False)
def bump(session: nox.Session) -> None:
    """Bump the version."""
    session.install("bump-my-version")
    session.run("bump-my-version", *session.posargs)


@nox.session(default=False)
def build(session: nox.Session) -> None:
    """Build an SDist and wheel."""
    build_path = DIR.joinpath("build")
    if build_path.exists():
        shutil.rmtree(build_path)

    session.install("build")
    session.run("python", "-m", "build")


if __name__ == "__main__":
    nox.main()
