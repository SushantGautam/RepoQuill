"""End-to-end agentic documentation engine tests.

The flagship test proves the working end-to-end example required of the
engine: a documentation agent, driven by a scripted tool-calling LLM,

1. discovers the repository layout and the authoritative API surface via
   tool calls (``list_files`` / ``inspect_api`` / ``inspect_tests``);
2. runs a code example that FAILS, observes the failure, and re-runs a
   repaired example that PASSES (real isolated subprocess execution);
3. writes a full-coverage page via ``write_doc``;
4. passes INDEPENDENT verification (semantic coverage + executed example +
   import/symbol checks) — the verifier is a separate module the author
   never calls.

It runs against the unrelated ``fixtures/miniutil`` repository (not
SimpleAudit) to demonstrate cross-repo generality.
"""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

import pytest

from repoquill.agents.author import run_page_agent
from repoquill.agents.contracts import (
    AgentBudget,
    ChatResult,
    PageTask,
    ToolCall,
    ToolContext,
)
from repoquill.agents.tools import RepoQuillTools
from repoquill.agents.verify import verify_page_file

REPO_ROOT = Path(__file__).resolve().parent.parent
MINIUTIL = REPO_ROOT / "fixtures" / "miniutil"

SLUG = "getting-started"

# A first attempt that hallucinates a method (Counter has `total`, not `sum`).
BUGGY_EXAMPLE = (
    "from miniutil import Counter\n"
    "c = Counter([1, 2])\n"
    "print(c.sum())\n"
)
# The repaired, real example.
FIXED_EXAMPLE = (
    "from miniutil import Counter\n"
    "c = Counter([1, 2])\n"
    "c.add(3)\n"
    "print(c.total())\n"
)

PAGE = """## Getting Started

MiniUtil is a tiny text and math toolkit. Its public API has four parts:

- `TextStats` — compute statistics about a string (`word_count`, `longest_word`).
- `slugify` — convert a phrase into a URL-friendly slug.
- `Counter` — accumulate values and compute their running `total`.
- `moving_average` — a sliding-window average over a sequence.

### A verified example

```python
from miniutil import Counter

c = Counter([1, 2])
c.add(3)
print(c.total())
```

`Counter([1, 2])` starts with 1 and 2; after `add(3)`, `total()` is `6`.

### Other helpers

`TextStats("hello world").word_count()` is `2`. `slugify("Hello World")`
produces `"hello-world"`. `moving_average([1, 2, 3, 4], 2)` yields
`[1.5, 2.5, 3.5]`.
"""


class ScriptedAuthorClient:
    """A fake tool-calling LLM that plays the full discover-run-repair-write
    sequence, reacting to the *actual* result of the failing example."""

    def __init__(self):
        self.state = "list"
        self.calls = 0

    def _tool(self, name, args):
        self.calls += 1
        return ChatResult(content=None, tool_calls=[
            ToolCall(id=f"c{self.calls}", name=name, arguments=args)])

    def _final(self, content):
        self.calls += 1
        return ChatResult(content=content, tool_calls=[])

    def chat_with_tools(self, messages, tools, tool_choice=None,
                        max_tokens=None, temperature=None, retries=5):
        last_tool = None
        for m in reversed(messages):
            if m.get("role") == "tool":
                last_tool = m
                break
        if self.state == "list":
            self.state = "api"
            return self._tool("list_files", {})
        if self.state == "api":
            self.state = "tests"
            return self._tool("inspect_api", {})
        if self.state == "tests":
            self.state = "run_buggy"
            return self._tool("inspect_tests", {})
        if self.state == "run_buggy":
            self.state = "decide"
            return self._tool("run_example", {"code": BUGGY_EXAMPLE})
        if self.state == "decide":
            failed = (last_tool is not None
                      and '"ok": false' in last_tool.get("content", ""))
            if failed:
                # React to the real failure: repair and re-run.
                self.state = "write"
                return self._tool("run_example", {"code": FIXED_EXAMPLE})
            self.state = "write"
            return self._tool("write_doc",
                              {"slug": SLUG, "content": PAGE})
        if self.state == "write":
            self.state = "final"
            return self._tool("write_doc", {"slug": SLUG, "content": PAGE})
        # "final" / "done"
        return self._final("Page written.")


def test_agentic_engine_end_to_end(tmp_path):
    assert MINIUTIL.is_dir(), "miniutil fixture is required for this test"
    docs = str(tmp_path / "docs")
    ctx = ToolContext(
        repo_root=str(MINIUTIL),
        pkg_path=str(MINIUTIL / "miniutil"),
        docs_dir=docs,
        execute_examples=True,
    )
    task = PageTask(
        slug=SLUG,
        title="Getting Started",
        description="Intro to miniutil",
        source_hints=["miniutil/textkit.py", "miniutil/calc.py"],
        coverage_checklist=["TextStats", "slugify", "Counter",
                            "moving_average"],
        out_path=os.path.join(docs, f"{SLUG}.md"),
    )
    registry = RepoQuillTools(ctx)
    client = ScriptedAuthorClient()
    result = run_page_agent(task, ctx, registry, client,
                            budget=AgentBudget(max_steps=15,
                                               max_llm_calls=15))
    # The agent finished and persisted a page.
    assert result.ok is True, result.error
    assert result.wrote_doc is True
    assert os.path.isfile(task.out_path)

    # It genuinely used the tools to discover the repo, API and tests.
    tool_names = [t.get("name") for t in result.transcript
                  if t.get("role") == "tool"]
    for expected in ("list_files", "inspect_api", "inspect_tests",
                     "run_example", "write_doc"):
        assert expected in tool_names, (
            f"agent did not call {expected}; saw {tool_names}")
    # It ran the example more than once (a failing attempt + a repaired one).
    assert tool_names.count("run_example") >= 2
    # The first run_example failed, a later one succeeded (repair happened).
    run_results = [t for t in result.transcript
                   if t.get("role") == "tool" and t.get("name") == "run_example"]
    saw_failure = any('"ok": false' in (t.get("summary") or "")
                      for t in run_results)
    saw_success = any('"ok": true' in (t.get("summary") or "")
                      and "returncode" in (t.get("summary") or "")
                      for t in run_results)
    assert saw_failure, "expected the agent to observe a failing example"
    assert saw_success, "expected a later passing example run"

    # The final page documents all four expected symbols.
    for sym in ("TextStats", "slugify", "Counter", "moving_average"):
        assert sym in result.content

    # Independent verification (separate from the author) must pass.
    vres = verify_page_file(task.slug, task.out_path, task, ctx,
                            run_examples=True, coverage_threshold=0.6)
    assert vres.passed is True, vres.as_dict()
    assert vres.coverage.ratio == 1.0
    assert vres.examples_ok is True
    assert vres.symbol_findings == []
    assert vres.import_findings == []


def test_agentic_engine_outage_does_not_publish(tmp_path):
    """A sustained LLM outage yields ok=False and no published page."""
    docs = str(tmp_path / "docs")
    ctx = ToolContext(
        repo_root=str(MINIUTIL),
        pkg_path=str(MINIUTIL / "miniutil"),
        docs_dir=docs,
    )
    task = PageTask(slug=SLUG, title="Getting Started",
                    out_path=os.path.join(docs, f"{SLUG}.md"))

    class OutageClient:
        def chat_with_tools(self, *a, **k):
            raise RuntimeError("LLM request failed: 502")

    result = run_page_agent(task, ctx, RepoQuillTools(ctx), OutageClient(),
                            budget=AgentBudget(max_steps=5, max_llm_calls=5))
    assert result.ok is False
    assert "502" in (result.error or "")
    assert not os.path.isfile(task.out_path)


def _make_datefmt(tmp_path):
    pkg = tmp_path / "datefmt"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        "from datefmt.parser import parse_date\n")
    (pkg / "parser.py").write_text(
        "def parse_date(text):\n    return text.strip()\n")
    (tmp_path / "repoquill.yml").write_text(textwrap.dedent(
        """
        project_name: datefmt
        package_dir: datefmt
        llm:
          provider: openai
          model: gpt-4o
          agentic:
            enabled: true
        build:
          docs_dir: docs
        """
    ).lstrip())
    return tmp_path


def test_cli_agentic_wiring(monkeypatch, tmp_path):
    """`repoquill generate --agentic` routes through the engine end-to-end."""
    from repoquill import cli

    _make_datefmt(tmp_path)
    pages = [
        {"slug": "alpha", "title": "Alpha", "description": "",
         "source_files": ["datefmt/parser.py"]},
    ]
    good = (
        "## Alpha\n\n`parse_date` parses an ISO date string.\n\n"
        "```python\nfrom datefmt.parser import parse_date\n"
        "print(parse_date(' 2026-01-01 '))\n```\n"
    )

    class FinalClient:
        def __init__(self):
            self.calls = 0

        def chat_with_tools(self, messages, tools, **k):
            self.calls += 1
            return ChatResult(content=good, tool_calls=[])

    monkeypatch.setattr(cli, "_make_agentic_client",
                        lambda cfg: FinalClient())
    monkeypatch.setattr(cli, "determine_structure",
                        lambda cfg, client: [dict(p) for p in pages])

    monkeypatch.chdir(tmp_path)
    rc = cli.main(["generate", "--agentic", "--no-scaffold",
                   "--config", str(tmp_path / "repoquill.yml")])
    assert rc == 0
    page = tmp_path / "docs" / "guides" / "alpha.md"
    assert page.exists()
    assert "parse_date" in page.read_text()
    plan = json.loads((tmp_path / "docs" / ".plan.json").read_text())
    by_slug = {p["slug"]: p for p in plan["pages"]}
    assert by_slug["alpha"]["status"] == "ok"


def test_cli_no_agentic_uses_legacy(monkeypatch, tmp_path):
    """Without --agentic (and agentic disabled), the legacy path is used."""
    from repoquill import cli
    from repoquill import narrative

    _make_datefmt(tmp_path)
    # Disable agentic for this config.
    cfg_file = tmp_path / "repoquill.yml"
    cfg_file.write_text(textwrap.dedent(
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
    pages = [{"slug": "alpha", "title": "Alpha", "description": "",
              "source_files": ["datefmt/parser.py"]}]
    good = "## Alpha\n\n`parse_date` parses a date.\n"

    legacy_called = {"n": 0}

    def fake_generate_page(page, source_files, client, cfg):
        legacy_called["n"] += 1
        return good

    monkeypatch.setattr(cli, "determine_structure",
                        lambda cfg, client: [dict(p) for p in pages])
    monkeypatch.setattr(narrative, "generate_page", fake_generate_page)

    monkeypatch.chdir(tmp_path)
    rc = cli.main(["generate", "--no-scaffold",
                   "--config", str(cfg_file)])
    assert rc == 0
    assert legacy_called["n"] == 1, "legacy generate_page should be used"
