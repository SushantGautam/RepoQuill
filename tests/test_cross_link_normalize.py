"""Cross-guide link normalization (repoquill.site.cross_link_guides).

A page in docs/guides/ must link to sibling guides with page-relative
``<slug>.md`` links. The ``guides/<slug>.md`` form (valid from index.md,
which sits one level up) 404s from a guide page because it resolves to
``docs/guides/guides/<slug>.md``. ``cross_link_guides`` normalizes the
agent-emitted ``guides/<slug>.md`` links back to their page-relative form.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

from repoquill.site import cross_link_guides

PAGES = [
    {"slug": "quickstart", "title": "Quickstart", "description": "q"},
    {"slug": "installation", "title": "Installation", "description": "i"},
]


def _cfg(tmp_path):
    docs = tmp_path / "docs"
    (docs / "guides").mkdir(parents=True)
    (docs / "reference").mkdir()
    sections = [
        {"title": "Getting Started", "slugs": ["quickstart", "installation"]}
    ]
    return SimpleNamespace(
        project_name="T", site_name="T", site={"description": "d"},
        site_url="https://x.com", repo_url="https://x.com/r",
        index={"tagline": "t"}, site_src=str(docs),
        out_guides=str(docs / "guides"), ref_dir=str(docs / "reference"),
        narrative_sections=sections, raw={}, pkg_path=str(tmp_path / "pkg"),
    )


def _write(cfg, slug, body):
    with open(os.path.join(cfg.out_guides, f"{slug}.md"), "w") as fh:
        fh.write(body)


def _read(cfg, slug):
    with open(os.path.join(cfg.out_guides, f"{slug}.md")) as fh:
        return fh.read()


def test_guides_prefix_sibling_link_normalized(tmp_path):
    cfg = _cfg(tmp_path)
    _write(cfg, "quickstart", "# Quickstart\n\nbody\n")
    _write(cfg, "installation",
           "# Installation\n\n"
           "Continue with the [Quickstart](guides/quickstart.md).\n\n"
           "## Where to go next\n- [Quickstart](guides/quickstart.md)\n")
    cross_link_guides(cfg, PAGES)
    content = _read(cfg, "installation")
    assert "](guides/quickstart.md)" not in content
    assert "](quickstart.md)" in content


def test_page_relative_sibling_link_untouched(tmp_path):
    cfg = _cfg(tmp_path)
    _write(cfg, "quickstart", "# Quickstart\n\nbody\n")
    _write(cfg, "installation",
           "# Installation\n\nSee [Quickstart](quickstart.md).\n")
    cross_link_guides(cfg, PAGES)
    content = _read(cfg, "installation")
    assert "](guides/quickstart.md)" not in content
    assert "](quickstart.md)" in content
