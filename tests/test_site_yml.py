"""Tests for build_mkdocs_yml — E1: auto-configure mkdocstrings + md extensions.

These tests pin the behavior established by experiment E1:
- when the config has no mkdocstrings plugin, one is auto-inserted with
  the package path injected (so reference pages render instead of showing
  literal ":::" text);
- markdown extensions get a working default set when absent;
- output_dir mode places mkdocs.yml in the PARENT of site_src (mkdocs
  rejects docs_dir == the config file's own directory) and rewrites a
  relative site_dir to an absolute sibling path (mkdocs rejects a
  site_dir inside docs_dir).
"""

from __future__ import annotations

import os
from types import SimpleNamespace

from repoquill.site import build_mkdocs_yml


def _cfg(tmp_path, output_dir=None, plugins=None, md_exts=None):
    raw = {}
    if output_dir:
        raw["output_dir"] = output_dir
        site_src = str(tmp_path / output_dir)
    else:
        site_src = str(tmp_path / "docs")
    return SimpleNamespace(
        site_name="TestSite",
        site={},
        site_url="",
        repo_url="",
        repo_name="",
        theme={},
        plugins=plugins or [],
        markdown_extensions=md_exts or [],
        raw=raw,
        root=str(tmp_path / "src"),
        site_src=site_src,
        config_dir=str(tmp_path),
        build={"docs_dir": "docs", "site_dir": "site_repoquill"},
    )


def test_auto_inserts_mkdocstrings_plugin(tmp_path):
    cfg = _cfg(tmp_path)
    build_mkdocs_yml(cfg, nav=[{"title": "Home", "file": "index.md"}])
    yml = open(os.path.join(str(tmp_path), "mkdocs.yml")).read()
    assert "mkdocstrings" in yml
    # The package path must be injected so handlers can resolve the source.
    assert cfg.root in yml
    # A search plugin is also added (material's search is expected).
    assert "search" in yml


def test_keeps_user_mkdocstrings_plugin(tmp_path):
    user_plugin = [{"mkdocstrings": {"handlers": {"python": {"options": {"show_source": True}}}}}]
    cfg = _cfg(tmp_path, plugins=user_plugin)
    build_mkdocs_yml(cfg, nav=[{"title": "Home", "file": "index.md"}])
    yml = open(os.path.join(str(tmp_path), "mkdocs.yml")).read()
    assert "show_source: true" in yml
    assert cfg.root in yml


def test_default_markdown_extensions(tmp_path):
    cfg = _cfg(tmp_path)
    build_mkdocs_yml(cfg, nav=[{"title": "Home", "file": "index.md"}])
    yml = open(os.path.join(str(tmp_path), "mkdocs.yml")).read()
    assert "admonition" in yml
    assert "tables" in yml
    assert "toc" in yml


def test_user_markdown_extensions_preserved(tmp_path):
    cfg = _cfg(tmp_path, md_exts=["pymdownx.emoji"])
    build_mkdocs_yml(cfg, nav=[{"title": "Home", "file": "index.md"}])
    yml = open(os.path.join(str(tmp_path), "mkdocs.yml")).read()
    assert "pymdownx.emoji" in yml
    # Defaults are NOT added on top of an explicit user list.
    assert "admonition" not in yml


def test_output_dir_layout(tmp_path):
    # mkdocs.yml must land in the PARENT of site_src, with docs_dir set to
    # the basename of site_src.
    cfg = _cfg(tmp_path, output_dir="site")
    build_mkdocs_yml(cfg, nav=[{"title": "Home", "file": "index.md"}])
    parent = str(tmp_path)
    yml_path = os.path.join(parent, "mkdocs.yml")
    assert os.path.exists(yml_path), "mkdocs.yml must be in parent of site_src"
    yml = open(yml_path).read()
    assert "docs_dir: site" in yml
    # site_dir must be an absolute path OUTSIDE docs_dir.
    expected_site = os.path.join(parent, "site_repoquill")
    assert f"site_dir: {expected_site}" in yml


def test_non_output_dir_layout_unchanged(tmp_path):
    cfg = _cfg(tmp_path)
    build_mkdocs_yml(cfg, nav=[{"title": "Home", "file": "index.md"}])
    yml_path = os.path.join(str(tmp_path), "mkdocs.yml")
    assert os.path.exists(yml_path)
    yml = open(yml_path).read()
    assert "docs_dir: docs" in yml
    assert "site_dir: site_repoquill" in yml
