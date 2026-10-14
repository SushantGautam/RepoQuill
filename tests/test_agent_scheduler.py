"""Tests for the parallel agentic page scheduler (repoquill.agents.scheduler).

Uses a *final-answer* fake LLM client (returns a ChatResult with no tool
calls) so the real author loop + real tool registry + real subprocess
example execution are exercised without a live endpoint.
"""

from __future__ import annotations

import json
import os

import pytest

from repoquill.agents.contracts import (
    AgentBudget,
    ChatResult,
    PageTask,
    ToolContext,
)
from repoquill.agents.scheduler import (
    PageOutcome,
    run_agentic_generation,
    run_pages,
)


class FinalOnlyClient:
    """A fake tool-calling client that answers in one turn (no tool calls)."""

    def __init__(self, content_by_slug=None, fail_on=""):
        self.content_by_slug = content_by_slug or {}
        self.fail_on = fail_on
        self.calls = 0

    def chat_with_tools(self, messages, tools, tool_choice=None,
                        max_tokens=None, temperature=None, retries=5):
        self.calls += 1
        blob = json.dumps(messages)
        if self.fail_on and self.fail_on in blob:
            raise RuntimeError(f"endpoint 502 for {self.fail_on}")
        content = "## Page\n\nBody."
        for slug, c in self.content_by_slug.items():
            if f'"{slug}"' in blob or slug in blob:
                content = c
                break
        return ChatResult(content=content, tool_calls=[])


GOOD_PAGE = (
    "## Alpha\n\n"
    "The `Widget` class and `make_widget` helper.\n\n"
    "```python\n"
    "from alpha import make_widget\n"
    "w = make_widget('x')\n"
    "print(w.describe())\n"
    "```\n"
)


@pytest.fixture
def pkg(tmp_path):
    root = tmp_path / "root"
    alpha = root / "alpha"
    alpha.mkdir(parents=True)
    docs = root / "docs"
    docs.mkdir()
    (alpha / "__init__.py").write_text(
        "from .w import Widget, make_widget\n"
        "__all__ = ['Widget', 'make_widget']\n", encoding="utf-8")
    (alpha / "w.py").write_text(
        "class Widget:\n"
        "    def __init__(self, name):\n"
        "        self.name = name\n"
        "    def describe(self):\n"
        "        return 'widget:' + self.name\n\n"
        "def make_widget(name):\n"
        "    return Widget(name)\n", encoding="utf-8")
    ctx = ToolContext(repo_root=str(root), pkg_path=str(alpha),
                      docs_dir=str(docs))
    return {"root": str(root), "ctx": ctx, "docs": str(docs)}


def _task(slug, docs):
    return PageTask(slug=slug, title=slug.title(),
                    coverage_checklist=["Widget", "make_widget"],
                    out_path=os.path.join(docs, f"{slug}.md"))


def test_run_pages_parallel_and_isolation(pkg):
    docs = pkg["docs"]
    tasks = [_task("alpha", docs), _task("bad", docs), _task("gamma", docs)]
    client = FinalOnlyClient(
        content_by_slug={"alpha": GOOD_PAGE, "gamma": GOOD_PAGE},
        fail_on="bad")
    outcomes = run_pages(tasks, pkg["ctx"], client, max_parallel=3)
    assert len(outcomes) == 3
    by = {o.task.slug: o for o in outcomes}
    assert by["alpha"].ok is True
    assert by["gamma"].ok is True
    assert by["bad"].ok is False
    assert "502" in by["bad"].author.error
    # The good pages were written despite the middle one failing.
    assert os.path.isfile(os.path.join(docs, "alpha.md"))
    assert os.path.isfile(os.path.join(docs, "gamma.md"))


def test_run_pages_sequential(pkg):
    docs = pkg["docs"]
    tasks = [_task("alpha", docs)]
    outcomes = run_pages(tasks, pkg["ctx"], FinalOnlyClient(), max_parallel=1)
    assert outcomes[0].ok is True


def test_run_pages_verify_each_passes(pkg):
    docs = pkg["docs"]
    tasks = [_task("alpha", docs)]
    outcomes = run_pages(tasks, pkg["ctx"],
                         FinalOnlyClient(content_by_slug={"alpha": GOOD_PAGE}),
                         max_parallel=1, verify_each=True,
                         coverage_threshold=0.6)
    assert outcomes[0].ok is True
    assert outcomes[0].verification is not None
    assert outcomes[0].verification.passed is True
    assert outcomes[0].verification.coverage.ratio == 1.0


def test_run_pages_verify_each_coverage_failure(pkg):
    docs = pkg["docs"]
    # Page mentions only Widget, omits make_widget -> low coverage.
    sparse = "## Alpha\n\n`Widget` is a thing.\n"
    outcomes = run_pages(tasks=[_task("alpha", docs)], ctx=pkg["ctx"],
                         client=FinalOnlyClient(content_by_slug={"alpha": sparse}),
                         max_parallel=1, verify_each=True,
                         coverage_threshold=0.9)
    assert outcomes[0].author.ok is True
    assert outcomes[0].verification.passed is False
    assert outcomes[0].ok is False
    assert "make_widget" in outcomes[0].verification.coverage.missing


def test_empty_tasks(pkg):
    assert run_pages([], pkg["ctx"], FinalOnlyClient()) == []


class FakeCfg:
    def __init__(self, root, pkg, out):
        self.root = root
        self.pkg_path = pkg
        self.out_guides = out


def test_run_agentic_generation_records_state(pkg, tmp_path):
    from repoquill.config import AgenticConfig

    cfg = FakeCfg(pkg["root"], pkg["ctx"].pkg_path, pkg["docs"])
    pages = [
        {"slug": "alpha", "title": "Alpha", "source_files": [], "description": ""},
        {"slug": "bad", "title": "Bad", "source_files": [], "description": ""},
    ]
    ag = AgenticConfig(enabled=True, max_parallel_pages=2, execute_examples=True)
    client = FinalOnlyClient(content_by_slug={"alpha": GOOD_PAGE}, fail_on="bad")
    generated = run_agentic_generation(
        pages, cfg, client, ag,
        old_hashes={}, new_hashes={}, force_slugs={"alpha", "bad"})
    assert generated == ["alpha"]
    # alpha recorded ok, bad recorded failed (retry-safe).
    alpha_page = next(p for p in pages if p["slug"] == "alpha")
    bad_page = next(p for p in pages if p["slug"] == "bad")
    assert alpha_page.get("status") == "ok"
    assert bad_page.get("status") == "failed"
    assert os.path.isfile(os.path.join(pkg["docs"], "alpha.md"))


def test_run_agentic_generation_skips_unchanged(pkg):
    from repoquill.config import AgenticConfig

    cfg = FakeCfg(pkg["root"], pkg["ctx"].pkg_path, pkg["docs"])
    # A page that is already verified and unchanged -> skipped (not regenerated).
    existing = os.path.join(pkg["docs"], "alpha.md")
    with open(existing, "w", encoding="utf-8") as fh:
        fh.write(GOOD_PAGE)
    pages = [{"slug": "alpha", "title": "Alpha", "source_files": [],
              "description": "", "status": "ok",
              "verified_file_hashes": {}, "content_sha256": _sha(existing)}]
    ag = AgenticConfig(enabled=True, max_parallel_pages=2)
    client = FinalOnlyClient(content_by_slug={"alpha": "SHOULD NOT RUN"})
    generated = run_agentic_generation(
        pages, cfg, client, ag,
        old_hashes={}, new_hashes={})
    assert generated == []
    assert client.calls == 0


def _sha(path):
    import hashlib
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()
