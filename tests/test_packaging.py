"""Packaging regression: the built wheel must include every subpackage.

Guard for the bug where the explicit setuptools ``packages`` list omitted
``repoquill.pi``, so the Pi engine (and its bundled ``extension.ts``) were
silently dropped from any wheel build (``uvx`` / ``pip install`` / PyPI) even
though it worked fine from source (``uv run``). These are static checks — no
wheel is built — so they run fast in CI.
"""
from __future__ import annotations

import os
import tomllib

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PKG_ROOT = os.path.join(_REPO_ROOT, "repoquill")


def _pyproject() -> dict:
    with open(os.path.join(_REPO_ROOT, "pyproject.toml"), "rb") as fh:
        return tomllib.load(fh)


def _subpackages() -> set:
    """Every ``repoquill/**`` directory that is a Python package (has __init__)."""
    found = {"repoquill"}
    for dirpath, dirnames, _ in os.walk(_PKG_ROOT):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        if dirpath != _PKG_ROOT and os.path.exists(
            os.path.join(dirpath, "__init__.py")
        ):
            found.add(os.path.relpath(dirpath, _REPO_ROOT).replace(os.sep, "."))
    return found


def test_all_subpackages_are_shipped():
    """Every subpackage dir with an __init__.py must be declared in packages."""
    declared = set(_pyproject()["tool"]["setuptools"]["packages"])
    missing = _subpackages() - declared
    assert not missing, (
        "These subpackages have an __init__.py but are NOT in the pyproject "
        "[tool.setuptools] packages list, so they are dropped from the built "
        f"wheel: {sorted(missing)}"
    )


def test_pi_extension_shipped_in_package_data():
    """The Pi runtime's extension.ts must be included as package data."""
    data = _pyproject()["tool"]["setuptools"].get("package-data", {})
    patterns = [p for globs in data.values() for p in globs]
    assert any("extension.ts" in p for p in patterns), (
        "repoquill/pi/extension.ts is not covered by "
        "[tool.setuptools.package-data]; the Pi engine would fail at runtime "
        "in an installed build (No file: extension.ts)."
    )
    assert os.path.exists(os.path.join(_PKG_ROOT, "pi", "extension.ts")), (
        "repoquill/pi/extension.ts is missing from the source tree."
    )
