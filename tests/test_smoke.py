"""Smoke test: proves the package is installed and importable."""

import codetutor


def test_package_imports() -> None:
    assert codetutor.__version__ == "0.1.0"
