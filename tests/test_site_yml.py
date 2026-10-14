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

It also pins the P2/P5 site-assembly behavior:
- index.md / llms.txt / llms-full.txt / nav only link pages that were
  actually generated (missing pages are marked, never dead-linked);
- the nav preserves configured section order and per-section page order.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

from repoquill.site import (
    build_index_md,
    build_llms_full_txt,
    build_llms_txt,
    build_mkdocs_yml,
    build_nav,
)


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


# ---------------------------------------------------------------------------
# P2: link integrity — site assembly must never link missing pages
# ---------------------------------------------------------------------------

PAGE_SLUGS = ["quickstart", "installation", "auditing", "reporting"]


def _site_cfg(tmp_path):
    """Config with two narrative sections over four planned pages."""
    docs = tmp_path / "docs"
    (docs / "guides").mkdir(parents=True)
    (docs / "reference").mkdir()
    sections = [
        {"title": "Getting Started",
         "slugs": ["quickstart", "installation"]},
        {"title": "Core Concepts",
         "slugs": ["auditing", "reporting"]},
    ]
    pages = [
        {"slug": s, "title": s.capitalize(), "description": f"{s} page"}
        for s in PAGE_SLUGS
    ]
    cfg = SimpleNamespace(
        project_name="TestProj",
        site_name="TestSite",
        site={"description": "A test site."},
        site_url="https://example.com/docs",
        repo_url="https://example.com/repo",
        index={"tagline": "Test tagline."},
        site_src=str(docs),
        out_guides=str(docs / "guides"),
        ref_dir=str(docs / "reference"),
        narrative_sections=sections,
        raw={},
        pkg_path=str(tmp_path / "pkg"),
    )
    return cfg, pages


def _write_guides(tmp_path, slugs):
    guides = tmp_path / "docs" / "guides"
    for s in slugs:
        (guides / f"{s}.md").write_text(f"# {s.capitalize()}\n\ncontent {s}\n")


def test_index_md_links_only_pages_on_disk(tmp_path):
    cfg, pages = _site_cfg(tmp_path)
    _write_guides(tmp_path, ["quickstart", "auditing"])
    build_index_md(cfg, pages, [])
    index = open(os.path.join(cfg.site_src, "index.md")).read()
    # Generated pages are linked.
    assert "[Quickstart](guides/quickstart.md)" in index
    # Missing pages: no dead link, marked as unavailable.
    assert "(guides/installation.md)" not in index
    assert "(guides/reporting.md)" not in index
    assert "Installation (not yet available)" in index
    assert "Reporting (not yet available)" in index


def test_index_md_generated_set_overrides_disk(tmp_path):
    """An explicit generated set excludes pages whose stale file remains."""
    cfg, pages = _site_cfg(tmp_path)
    _write_guides(tmp_path, PAGE_SLUGS)
    build_index_md(cfg, pages, [], generated={"quickstart", "auditing"})
    index = open(os.path.join(cfg.site_src, "index.md")).read()
    assert "[Installation](guides/installation.md)" not in index
    assert "Installation (not yet available)" in index
    assert "[Auditing](guides/auditing.md)" in index


def test_llms_txt_marks_unavailable_pages(tmp_path):
    cfg, pages = _site_cfg(tmp_path)
    build_llms_txt(cfg, pages, [], generated={"quickstart"})
    txt = open(os.path.join(cfg.site_src, "llms.txt")).read()
    assert "[Quickstart](https://example.com/docs/guides/quickstart/)" in txt
    assert "guides/installation/" not in txt
    assert "Installation (NOT AVAILABLE" in txt
    assert "Reporting (NOT AVAILABLE" in txt


def test_llms_full_excludes_unavailable_pages(tmp_path):
    cfg, pages = _site_cfg(tmp_path)
    guides = tmp_path / "docs" / "guides"
    for s in PAGE_SLUGS:
        (guides / f"{s}.md").write_text(f"# {s}\n\nMARKER_{s}\n")
    build_llms_full_txt(cfg, pages, [], generated={"quickstart", "installation"})
    txt = open(os.path.join(cfg.site_src, "llms-full.txt")).read()
    assert "MARKER_quickstart" in txt
    assert "MARKER_installation" in txt
    assert "MARKER_auditing" not in txt
    assert "MARKER_reporting" not in txt


def test_nav_omits_unavailable_pages(tmp_path):
    cfg, pages = _site_cfg(tmp_path)
    nav = build_nav(cfg, pages, [], generated={"quickstart"})
    # Single available page: section flattens to a direct link.
    assert nav == ["index.md", ["Guides", ["guides/quickstart.md"]]]
    flat = str(nav)
    assert "installation" not in flat
    assert "auditing" not in flat
    assert "reporting" not in flat


# ---------------------------------------------------------------------------
# P5: nav reading order follows config order, never alphabetical
# ---------------------------------------------------------------------------

def test_nav_preserves_section_and_page_order(tmp_path):
    """Section order and per-section page order must follow the config."""
    cfg, pages = _site_cfg(tmp_path)
    # Deliberately non-alphabetical at BOTH levels: section titles and
    # the slug order within each section.
    cfg.narrative_sections = [
        {"title": "Deploying", "slugs": ["reporting", "installation"]},
        {"title": "Beginning", "slugs": ["auditing", "quickstart"]},
    ]
    _write_guides(tmp_path, PAGE_SLUGS)
    nav = build_nav(cfg, pages, [])
    assert nav[0] == "index.md"
    guides = nav[1]
    assert guides[0] == "Guides"
    # Sections in configured order (Deploying before Beginning), pages in
    # configured slug order — not alphabetical.
    assert guides[1] == [
        ["Deploying", ["guides/reporting.md", "guides/installation.md"]],
        ["Beginning", ["guides/auditing.md", "guides/quickstart.md"]],
    ]
