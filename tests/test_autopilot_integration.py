"""End-to-end autopilot integration tests (CLI level, no network/LLM).

Covers the P0 acceptance criteria through the real ``cli.main`` path:

- a failed generation does NOT advance that page's state and is retried
  on the next run even when no source file changed;
- the deterministic quality gate blocks a "successful" generation whose
  content contains a bogus import (fail closed, nonzero exit);
- ``--no-llm`` still works and leaves plan state untouched.
"""

from __future__ import annotations

import json
import os
import textwrap

import pytest

from repoquill import cli


def _make_repo(tmp_path):
    """Tiny generic package (not domain-specific)."""
    pkg = tmp_path / "datefmt"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        '"""datefmt: date formatting helpers."""\n'
        "from datefmt.parser import parse_date\n"
    )
    (pkg / "parser.py").write_text(
        "def parse_date(text):\n"
        '    """Parse an ISO date string."""\n'
        "    return text.strip()\n"
    )
    (pkg / "formatter.py").write_text(
        "def format_date(value, style='iso'):\n"
        '    """Format a date value."""\n'
        "    return value\n"
    )
    cfg_path = tmp_path / "repoquill.yml"
    cfg_path.write_text(textwrap.dedent(
        """
        project_name: datefmt
        package_dir: datefmt
        llm:
          provider: openai
          model: gpt-4o
        build:
          docs_dir: docs
        """
    ).lstrip())
    return tmp_path, cfg_path


PAGES = [
    {"slug": "alpha", "title": "Alpha", "description": "",
     "source_files": ["datefmt/parser.py"]},
    {"slug": "beta", "title": "Beta", "description": "",
     "source_files": ["datefmt/formatter.py"]},
]

GOOD_CONTENT = (
    "# Page\n\n```python\nfrom datefmt.parser import parse_date\n"
    "parse_date('2026-01-01')\n```\n"
)
BAD_IMPORT_CONTENT = (
    "# Page\n\n```python\nfrom datefmt import DoesNotExist\n"
    "DoesNotExist()\n```\n"
)


def _monkeypatch_generation(monkeypatch, beta_behavior):
    """Stub structure planning + page generation (no LLM, no network)."""
    monkeypatch.setattr(
        cli, "determine_structure", lambda cfg, client: [dict(p) for p in PAGES]
    )

    def fake_generate_page(page, source_files, client, cfg):
        if page["slug"] == "beta":
            return beta_behavior("beta")
        return GOOD_CONTENT

    # generate_all_pages resolves generate_page in the narrative module;
    # patch it there.
    from repoquill import narrative
    monkeypatch.setattr(narrative, "generate_page", fake_generate_page)
    monkeypatch.setattr(
        narrative, "determine_structure",
        lambda cfg, client: [dict(p) for p in PAGES],
    )


def _run(monkeypatch, tmp_path, beta_behavior, args=None):
    monkeypatch.chdir(tmp_path)
    _monkeypatch_generation(monkeypatch, beta_behavior)
    if args is None:
        args = ["generate", "--no-scaffold", "--config",
                str(tmp_path / "repoquill.yml")]
    return cli.main(args)


def test_failed_page_retries_next_run(monkeypatch, tmp_path):
    _, cfg_path = _make_repo(tmp_path)

    def beta_fail(_):
        raise RuntimeError("simulated LLM outage")

    rc1 = _run(monkeypatch, tmp_path, beta_fail)
    assert rc1 == 1, "failed generation must exit nonzero"

    plan = json.loads((tmp_path / "docs" / ".plan.json").read_text())
    by_slug = {p["slug"]: p for p in plan["pages"]}
    assert by_slug["beta"]["status"] == "failed"
    assert by_slug["alpha"]["status"] == "ok"
    # alpha's state advanced; beta's verified hashes must NOT have advanced
    assert by_slug["alpha"].get("verified_file_hashes")
    assert not by_slug["beta"].get("verified_file_hashes")

    # Next run, no source change: beta must be retried and succeed.
    rc2 = _run(monkeypatch, tmp_path, lambda _: GOOD_CONTENT)
    assert rc2 == 0
    plan2 = json.loads((tmp_path / "docs" / ".plan.json").read_text())
    by_slug2 = {p["slug"]: p for p in plan2["pages"]}
    assert by_slug2["beta"]["status"] == "ok"
    assert by_slug2["beta"].get("verified_file_hashes")


def test_gate_blocks_bad_import_and_retries(monkeypatch, tmp_path):
    _, cfg_path = _make_repo(tmp_path)

    # "Successful" generation, but beta's content invents an API.
    def beta_bad(_):
        return BAD_IMPORT_CONTENT

    rc1 = _run(monkeypatch, tmp_path, beta_bad)
    assert rc1 == 1, "gate failure must exit nonzero"

    plan = json.loads((tmp_path / "docs" / ".plan.json").read_text())
    by_slug = {p["slug"]: p for p in plan["pages"]}
    assert by_slug["beta"]["status"] == "failed"
    assert "quality gate" in (by_slug["beta"].get("error") or "")
    assert not by_slug["beta"].get("verified_file_hashes")
    assert by_slug["alpha"]["status"] == "ok"

    # Build must have been skipped: no site dir produced.
    assert not (tmp_path / "docs" / "site_repoquill").exists()

    # Repair is off by default; next run regenerates beta (now correct).
    rc2 = _run(monkeypatch, tmp_path, lambda _: GOOD_CONTENT)
    assert rc2 == 0


def test_gate_failure_without_llm_still_blocks(monkeypatch, tmp_path):
    """A pre-existing broken guide page blocks a --no-llm build too."""
    _, cfg_path = _make_repo(tmp_path)
    docs = tmp_path / "docs"
    guides = docs / "guides"
    guides.mkdir(parents=True)
    (guides / "old-broken.md").write_text(BAD_IMPORT_CONTENT)
    # Seed a plan that lists the broken page so --no-llm picks it up.
    (docs / ".plan.json").write_text(json.dumps({
        "pages": [
            {"slug": "old-broken", "title": "Old Broken",
             "description": "", "source_files": ["datefmt/parser.py"]},
        ],
        "file_hashes": {},
    }))

    rc = _run(monkeypatch, tmp_path, None,
              args=["generate", "--no-llm", "--config", str(cfg_path)])
    assert rc == 1, "gate failure must block even in --no-llm mode"


def test_no_llm_clean_run_passes(monkeypatch, tmp_path):
    _, cfg_path = _make_repo(tmp_path)
    rc = _run(monkeypatch, tmp_path, None,
              args=["generate", "--no-llm", "--config", str(cfg_path)])
    assert rc == 0
