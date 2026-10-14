"""Regression tests for the REPOQUILL_MAX_PAGES budget guard.

The LLM planner's page proposal must be trimmed to the first N pages
(planner's own ordering) when REPOQUILL_MAX_PAGES is set, and left
untouched otherwise.
"""

import json
from types import SimpleNamespace

from repoquill.narrative import determine_structure


def _cfg(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("ALPHA = 1\n")
    return SimpleNamespace(
        pkg_path=str(pkg),
        root=str(tmp_path),
        narrative_sections=[],
        llm=SimpleNamespace(plan_temperature=0.1),
    )


def _fake_client(n_pages):
    payload = json.dumps([
        {"title": f"Page {i}", "slug": f"page-{i}",
         "description": f"desc {i}", "source_files": ["pkg/__init__.py"]}
        for i in range(n_pages)
    ])
    return SimpleNamespace(chat=lambda msgs, **kw: payload)


def test_max_pages_trims_to_first_n_in_planner_order(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("REPOQUILL_MAX_PAGES", "3")
    pages = determine_structure(_cfg(tmp_path), _fake_client(7))
    assert len(pages) == 3
    assert [p["slug"] for p in pages] == ["page-0", "page-1", "page-2"]
    out = capsys.readouterr().out
    assert "Trimmed slugs" in out
    assert "page-3" in out and "page-6" in out


def test_max_pages_unset_leaves_plan_untouched(tmp_path, monkeypatch):
    monkeypatch.delenv("REPOQUILL_MAX_PAGES", raising=False)
    pages = determine_structure(_cfg(tmp_path), _fake_client(7))
    assert len(pages) == 7


def test_max_pages_above_count_is_noop(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("REPOQUILL_MAX_PAGES", "10")
    pages = determine_structure(_cfg(tmp_path), _fake_client(7))
    assert len(pages) == 7
    assert "Trimmed" not in capsys.readouterr().out


def test_max_pages_applies_to_config_sections_path(tmp_path, monkeypatch,
                                                   capsys):
    """The budget cap also trims slugs from LLM-scaffolded
    narrative_sections (fixed page list), in list order."""
    monkeypatch.setenv("REPOQUILL_MAX_PAGES", "3")
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("ALPHA = 1\n")
    cfg = SimpleNamespace(
        pkg_path=str(pkg),
        root=str(tmp_path),
        narrative_sections=[
            {"title": "Section A",
             "slugs": [f"slug-{i}" for i in range(6)]},
        ],
        llm=SimpleNamespace(plan_temperature=0.1),
    )
    client = SimpleNamespace(chat=lambda msgs, **kw: json.dumps([
        {"slug": s, "source_files": ["pkg/__init__.py"],
         "description": "d"} for s in
        [f"slug-{i}" for i in range(6)]
    ]))
    pages = determine_structure(cfg, client)
    assert [p["slug"] for p in pages] == ["slug-0", "slug-1", "slug-2"]
    assert "Trimmed slugs" in capsys.readouterr().out


def test_max_pages_invalid_value_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("REPOQUILL_MAX_PAGES", "not-a-number")
    pages = determine_structure(_cfg(tmp_path), _fake_client(7))
    assert len(pages) == 7


def test_max_pages_zero_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("REPOQUILL_MAX_PAGES", "0")
    pages = determine_structure(_cfg(tmp_path), _fake_client(7))
    assert len(pages) == 7
