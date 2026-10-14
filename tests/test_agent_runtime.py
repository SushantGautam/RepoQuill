"""Tests for :mod:`repoquill.agents` — the bounded docs-only repair runtime.

No real LLM, no network: LLM paths use a duck-typed :class:`FakeClient`
whose ``.chat`` matches :meth:`repoquill.llm.LLMClient.chat`'s call
signature (``messages, max_tokens, temperature, retries`` → str).
"""

from __future__ import annotations

import os

import pytest

from repoquill.agents import (
    RepairBudget,
    diagnose_page,
    repair_page,
    repair_pages,
)
from repoquill.agents import repair as repair_module
from repoquill.verify import build_index


# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------

PKG_CORE = '''\
class Auditor:
    def __init__(self, provider, model):
        self.provider = provider
        self.model = model

    @property
    def results(self):
        return []

    def run(self, target):
        return 1
'''

# Page with deterministic problems only: a missing required kwarg and a
# property called as a method.  check_page finds nothing wrong here — the
# surgical fixes must catch it without any LLM.
DETERMINISTIC_PAGE = (
    "# Usage\n\n"
    "```python\n"
    "from pkglib import Auditor\n"
    "a = Auditor(provider=\"ollama\")\n"
    "r = a.results()\n"
    "```\n"
)

# Page whose only problem is invented symbols.
GHOST_PAGE = (
    "# Ghost\n\n"
    "The `GhostClassifier` class scores documents.\n\n"
    "```python\n"
    "from pkglib.ghost import GhostClassifier\n"
    "g = GhostClassifier()\n"
    "```\n"
)

# A fully clean candidate that uses only real package symbols.
AUDITOR_PAGE = (
    "# Auditor\n\n"
    "The `Auditor` class scores documents.\n\n"
    "```python\n"
    "from pkglib import Auditor\n"
    "a = Auditor(provider=\"ollama\", model=\"m\")\n"
    "```\n"
)

# A candidate that invents ANOTHER nonexistent symbol.
EVIL_PAGE = (
    "# Ghost\n\n"
    "The `EvilWizard` class scores documents.\n\n"
    "```python\n"
    "from pkglib.ghost import GhostClassifier\n"
    "g = GhostClassifier()\n"
    "```\n"
)


def _make_pkg(root):
    pkg = root / "pkglib"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text(PKG_CORE, encoding="utf-8")
    return str(pkg)


class FakeClient:
    """Duck-typed stand-in for LLMClient; never touches the network."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0
        self.last_messages = None

    def chat(self, messages, max_tokens=None, temperature=None,
             retries=3) -> str:
        self.calls += 1
        self.last_messages = messages
        if self.calls <= len(self.responses):
            return self.responses[self.calls - 1]
        return self.responses[-1]


class _Gate:
    def __init__(self, passed):
        self.passed = passed


@pytest.fixture
def env(tmp_path):
    pkg = _make_pkg(tmp_path)
    guides = tmp_path / "guides"
    guides.mkdir()
    return tmp_path, pkg, guides


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

def test_budget_defaults_and_accounting():
    b = RepairBudget()
    assert b.max_iterations == 2
    assert b.max_llm_calls == 2
    assert b.max_chars_per_page == 200_000
    assert b.iterations_remaining == 2
    assert b.llm_calls_remaining == 2
    assert not b.exhausted

    assert b.fits("x" * 200_000)
    assert not b.fits("x" * 200_001)

    b.consume_iteration()
    assert b.consume_llm_call() is True
    assert b.iterations_remaining == 1
    assert b.llm_calls_remaining == 1
    assert not b.exhausted

    b.consume_iteration()
    assert b.iterations_remaining == 0
    assert b.exhausted
    assert b.can_start_iteration() is False
    b.consume_iteration()  # no-op at the cap
    assert b.iterations_remaining == 0


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def test_diagnose_page_flags_invented_symbols(env):
    _, pkg, guides = env
    page = guides / "ghost.md"
    page.write_text(GHOST_PAGE, encoding="utf-8")
    idx = build_index(pkg)
    idx.pkg_name = "pkglib"
    findings = diagnose_page(str(page), idx)
    assert {f["symbol"] for f in findings} >= {"GhostClassifier"}

    clean = guides / "clean.md"
    clean.write_text(AUDITOR_PAGE, encoding="utf-8")
    assert diagnose_page(str(clean), idx) == []


# ---------------------------------------------------------------------------
# Deterministic repair (no LLM)
# ---------------------------------------------------------------------------

def test_deterministic_fix_without_llm(env):
    _, pkg, guides = env
    page = guides / "usage.md"
    page.write_text(DETERMINISTIC_PAGE, encoding="utf-8")
    client = FakeClient([])  # would raise if ever called

    result = repair_page(str(page), pkg, client=client)

    assert result.fixed is True
    assert result.status == "fixed"
    assert result.attempts == 0
    assert result.llm_calls == 0
    assert client.calls == 0
    assert result.diagnostics_before == []
    assert result.diagnostics_after == []

    text = page.read_text(encoding="utf-8")
    assert "a.results\n" in text          # property parens stripped
    assert "model is required" in text    # missing kwarg documented
    assert "a.results()" not in text

    # as_dict round-trips the public fields
    d = result.as_dict()
    assert d["status"] == "fixed" and d["page_path"] == str(page)
    assert d["llm_calls"] == 0


def test_clean_page_is_clean(env):
    _, pkg, guides = env
    page = guides / "clean.md"
    page.write_text(AUDITOR_PAGE, encoding="utf-8")
    result = repair_page(str(page), pkg)
    assert result.status == "clean"
    assert result.fixed is False
    assert page.read_text(encoding="utf-8") == AUDITOR_PAGE


# ---------------------------------------------------------------------------
# LLM repair (fake client only)
# ---------------------------------------------------------------------------

def test_llm_fixes_invented_symbol(env):
    _, pkg, guides = env
    page = guides / "ghost.md"
    page.write_text(GHOST_PAGE, encoding="utf-8")
    client = FakeClient([AUDITOR_PAGE])

    result = repair_page(str(page), pkg, client=client)

    assert result.fixed is True
    assert result.status == "fixed"
    assert result.llm_calls == 1
    assert client.calls == 1
    assert result.diagnostics_after == []
    assert len(result.diagnostics_before) >= 1
    text = page.read_text(encoding="utf-8")
    assert "Auditor" in text and "GhostClassifier" not in text


def test_evidence_guard_rejects_invented_symbol(env):
    _, pkg, guides = env
    page = guides / "ghost.md"
    page.write_text(GHOST_PAGE, encoding="utf-8")
    client = FakeClient([EVIL_PAGE, EVIL_PAGE])

    result = repair_page(str(page), pkg, client=client)

    assert result.fixed is False
    assert result.status == "budget-exhausted"
    assert "invent" in result.notes
    # Original content preserved — never a worse page.
    assert page.read_text(encoding="utf-8") == GHOST_PAGE


def test_repeated_broken_candidate_exhausts_budget(env):
    _, pkg, guides = env
    page = guides / "ghost.md"
    page.write_text(GHOST_PAGE, encoding="utf-8")
    budget = RepairBudget(max_iterations=3, max_llm_calls=5)
    client = FakeClient([EVIL_PAGE] * 3)

    result = repair_page(str(page), pkg, client=client, budget=budget)

    assert result.fixed is False
    assert result.status == "budget-exhausted"
    assert result.llm_calls == 3 == budget.max_iterations
    assert result.attempts == 3
    assert client.calls == 3  # bounded: no infinite loop
    assert page.read_text(encoding="utf-8") == GHOST_PAGE


def test_validator_gate_rejects_then_accepts(env):
    _, pkg, guides = env
    page = guides / "ghost.md"
    page.write_text(GHOST_PAGE, encoding="utf-8")

    # Failing gate: candidate is clean per diagnostics but the gate vetoes.
    client = FakeClient([AUDITOR_PAGE, AUDITOR_PAGE])
    result = repair_page(str(page), pkg, client=client,
                         validator=lambda p: _Gate(False))
    assert result.fixed is False
    assert result.status == "budget-exhausted"
    assert "validator" in result.notes
    assert page.read_text(encoding="utf-8") == GHOST_PAGE

    # Passing gate: the same candidate is accepted.
    page.write_text(GHOST_PAGE, encoding="utf-8")
    client2 = FakeClient([AUDITOR_PAGE])
    result2 = repair_page(str(page), pkg, client=client2,
                          validator=lambda p: _Gate(True))
    assert result2.fixed is True
    assert result2.status == "fixed"
    assert result2.llm_calls == 1


# ---------------------------------------------------------------------------
# Safety invariants
# ---------------------------------------------------------------------------

def test_source_package_untouched(env):
    _, pkg, guides = env
    page = guides / "usage.md"
    page.write_text(DETERMINISTIC_PAGE, encoding="utf-8")

    pkg_files = list((env[0] / "pkglib").rglob("*.py"))
    before = {p.name: (p.read_bytes(), os.stat(p).st_mtime_ns)
              for p in pkg_files}

    repair_page(str(page), pkg)

    after = {p.name: (p.read_bytes(), os.stat(p).st_mtime_ns)
             for p in pkg_files}
    assert before == after


def test_no_client_deterministic_insufficient(env):
    _, pkg, guides = env
    page = guides / "ghost.md"
    page.write_text(GHOST_PAGE, encoding="utf-8")

    result = repair_page(str(page), pkg)  # no client

    assert result.fixed is False
    assert result.status == "no-evidence"
    assert result.llm_calls == 0
    # No fabricated changes: the page is exactly as it was.
    assert page.read_text(encoding="utf-8") == GHOST_PAGE


def test_module_is_shell_and_network_free():
    import inspect

    src = inspect.getsource(repair_module)
    for bad in ("os.system", "subprocess", "socket", "urllib", "requests",
                "http", "eval("):
        assert bad not in src, f"repair.py must not use {bad!r}"


# ---------------------------------------------------------------------------
# Batch isolation
# ---------------------------------------------------------------------------

def test_batch_isolation(env, monkeypatch):
    _, pkg, guides = env
    (guides / "ok.md").write_text(DETERMINISTIC_PAGE, encoding="utf-8")
    (guides / "boom.md").write_text(
        "# BOOM\n\nThe `GhostClassifier` class.\n", encoding="utf-8")

    orig = repair_module._diagnose_text

    def flaky(text, idx):
        if "BOOM" in text:
            raise RuntimeError("boom")
        return orig(text, idx)

    monkeypatch.setattr(repair_module, "_diagnose_text", flaky)

    results = repair_pages(str(guides), pkg, slugs=["ok.md", "boom.md"])

    by_name = {os.path.basename(r.page_path): r for r in results}
    assert set(by_name) == {"ok.md", "boom.md"}
    assert by_name["ok.md"].status == "fixed"
    assert by_name["boom.md"].status == "error"
    assert by_name["boom.md"].fixed is False


def test_batch_default_slugs_and_result_dicts(env):
    _, pkg, guides = env
    (guides / "a.md").write_text(AUDITOR_PAGE, encoding="utf-8")
    (guides / "b.md").write_text(DETERMINISTIC_PAGE, encoding="utf-8")

    results = repair_pages(str(guides), pkg)
    assert len(results) == 2
    statuses = {os.path.basename(r.page_path): r.status for r in results}
    assert statuses == {"a.md": "clean", "b.md": "fixed"}
    for r in results:
        d = r.as_dict()
        assert isinstance(d, dict) and d["page_path"]
