from __future__ import annotations

import importlib.metadata

import flake8_lazy as m


def test_version():
    assert importlib.metadata.version("flake8_lazy") == m.__version__
