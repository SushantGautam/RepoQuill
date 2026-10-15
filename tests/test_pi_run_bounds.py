"""Tests for the Pi-run bounds added after the SimpleAudit baseline.

The baseline run (research/local/simpleaudit-pi-eval) showed 7/8 guide
pages dying at the 300s deadline with no write_doc, and one page whose
failure reason ("staged file missing") carried zero evidence of what
the agent actually did. These tests pin the general-purpose repairs:

* ``llm.agentic.timeout_s`` / ``max_tool_calls`` / ``context_window``
  are parsed from repoquill.yml with product defaults (900s / 80 /
  32768);
* ``scheduler._pi_activity_summary`` turns a PiRunResult into an
  evidence-based one-liner (tool-call count, write_doc reached, peak
  tokens, redacted stderr tail);
* per-page FAILED lines in ``run_pi_generation`` carry that summary
  (both the non-ok path and the "staged file missing" path);
* a timeout whose message embeds token counts is NOT misread as a
  5xx/429 endpoint error (no spurious retry).

Deterministic: fake Pi backend modules, no network, no model.
"""

from __future__ import annotations

import os
import sys

from repoquill.agents import scheduler
from repoquill.agents.scheduler import _pi_activity_summary
from repoquill.config import load_config
from repoquill.pi import contracts as pi_contracts
from tests.test_pi_endpoint_retry import FakeSequenceBackend


def _make_repo(tmp_path):
    pkg = tmp_path / "datefmt"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "parser.py").write_text(
        "def parse_date(text):\n    return text.strip()\n")
    cfg_path = tmp_path / "repoquill.yml"
    cfg_path.write_text(
        "project_name: datefmt\n"
        "package_dir: datefmt\n"
        "llm:\n  provider: openai\n  model: gpt-4o\n")
    return cfg_path


PAGES = [
    {"slug": "alpha", "title": "Alpha", "description": "",
     "source_files": ["datefmt/parser.py"]},
]


def _run(tmp_path, fake, monkeypatch, capsys=None):
    fake.install(monkeypatch)
    cfg = load_config(str(_make_repo(tmp_path)))
    cfg.out_guides = str(tmp_path / "docs" / "guides")
    os.makedirs(cfg.out_guides, exist_ok=True)
    ok = scheduler.run_pi_generation(
        [dict(p) for p in PAGES], cfg,
        old_hashes={}, new_hashes={"datefmt/parser.py": "x"},
        force_slugs={"alpha"}, verify_each=False,
    )
    return ok


# --------------------------------------------------------------------------- #
# Config parsing
# --------------------------------------------------------------------------- #

def test_agentic_pi_bounds_defaults(tmp_path):
    cfg = load_config(str(_make_repo(tmp_path)))
    ag = cfg.llm.agentic
    assert ag.timeout_s == 900.0
    assert ag.max_tool_calls == 80
    assert ag.context_window == 32768
    assert ag.compaction_keep_recent_tokens == 60000


def test_agentic_pi_bounds_from_yaml(tmp_path):
    cfg_path = _make_repo(tmp_path)
    cfg_path.write_text(
        "project_name: datefmt\n"
        "package_dir: datefmt\n"
        "llm:\n"
        "  provider: openai\n"
        "  model: gpt-4o\n"
        "  agentic:\n"
        "    timeout_s: 1200\n"
        "    max_tool_calls: 150\n"
        "    context_window: 131072\n")
    cfg = load_config(str(cfg_path))
    ag = cfg.llm.agentic
    assert ag.timeout_s == 1200.0
    assert ag.max_tool_calls == 150
    assert ag.context_window == 131072


# --------------------------------------------------------------------------- #
# Activity summary (failure-reason evidence)
# --------------------------------------------------------------------------- #

def _result(**kw):
    base = dict(
        slug="alpha", completed=False, output_path=None,
        errors=[], model="fake",
        usage=pi_contracts.PiUsage(input_tokens=100, output_tokens=5),
    )
    base.update(kw)
    return pi_contracts.PiRunResult(**base)


def test_activity_summary_reports_calls_writedoc_and_stderr():
    r = _result(
        tool_calls=[
            pi_contracts.PiToolCall(tool_call_id="c1", name="search_code"),
            pi_contracts.PiToolCall(tool_call_id="c2", name="read_file"),
        ],
        stderr_tail="node: fetch failed (ECONNRESET)\n",
    )
    s = _pi_activity_summary(r)
    assert "2 tool call(s)" in s
    assert "write_doc=no" in s
    assert "stderr tail: node: fetch failed (ECONNRESET)" in s


def test_activity_summary_marks_successful_write_doc():
    r = _result(
        tool_calls=[
            pi_contracts.PiToolCall(tool_call_id="c1", name="read_file"),
            pi_contracts.PiToolCall(tool_call_id="c2", name="write_doc"),
        ],
    )
    s = _pi_activity_summary(r)
    assert "write_doc=yes" in s
    assert "stderr tail" not in s


def test_activity_summary_ignores_errored_write_doc():
    r = _result(tool_calls=[
        pi_contracts.PiToolCall(tool_call_id="c1", name="write_doc",
                                is_error=True),
    ])
    assert "write_doc=no" in _pi_activity_summary(r)


# --------------------------------------------------------------------------- #
# Scheduler failure-reason surfacing
# --------------------------------------------------------------------------- #

class ErrorDetailBackend(FakeSequenceBackend):
    """Non-ok result rich in diagnostics, like a real mid-run error."""

    def install(self, monkeypatch):
        super().install(monkeypatch)
        rpc = sys.modules["repoquill.pi.rpc"]
        inner = rpc.PiRpcBackend

        def run(self, task):
            return _result(
                slug=task.slug,
                errors=["message_end stopReason=error"],
                stderr_tail="node: fetch failed (ECONNRESET)",
                tool_calls=[
                    pi_contracts.PiToolCall(tool_call_id="c1",
                                            name="search_code"),
                ],
            )

        inner.run = run


class StaleStageOkBackend(FakeSequenceBackend):
    """Claims success but the staged file does not exist: exercises the
    'staged file missing after pi run' path (the SimpleAudit
    custom-judges failure mode)."""

    def install(self, monkeypatch):
        super().install(monkeypatch)
        rpc = sys.modules["repoquill.pi.rpc"]
        inner = rpc.PiRpcBackend

        def run(self, task):
            return _result(
                slug=task.slug, completed=True,
                output_path=task.expected_output_path,
                tool_calls=[
                    pi_contracts.PiToolCall(tool_call_id="c1",
                                            name="search_code"),
                    pi_contracts.PiToolCall(tool_call_id="c2",
                                            name="search_code"),
                ],
            )

        inner.run = run


def test_failed_page_line_carries_activity_evidence(tmp_path, monkeypatch,
                                                    capsys):
    ok = _run(tmp_path, ErrorDetailBackend([{"ok": False}]), monkeypatch)
    out = capsys.readouterr().out
    assert ok == []
    line = [l for l in out.splitlines() if "FAILED" in l][0]
    assert "stopReason=error" in line
    assert "1 tool call(s), write_doc=no" in line
    assert "stderr tail: node: fetch failed (ECONNRESET)" in line


def test_staged_file_missing_line_carries_activity_evidence(
        tmp_path, monkeypatch, capsys):
    ok = _run(tmp_path, StaleStageOkBackend([{"ok": True}]), monkeypatch)
    out = capsys.readouterr().out
    assert ok == []
    line = [l for l in out.splitlines() if "FAILED" in l][0]
    assert "staged file missing after pi run" in line
    assert "2 tool call(s), write_doc=no" in line
    assert not os.path.isfile(
        str(tmp_path / "docs" / "guides" / "alpha.md"))


def test_timeout_with_token_counts_is_not_an_endpoint_error(
        tmp_path, monkeypatch, capsys):
    """Regression: timeout diagnostics embed 'total_tokens=502'-style
    numbers; the endpoint-retry classifier must only match the base
    error, so a timed-out page is NOT retried as a 5xx. It IS retried
    as a deadline failure (fresh context + pre-loaded source excerpts
    — the 'consumed everything, no page' class)."""
    class TimeoutBackend(FakeSequenceBackend):
        def install(self, monkeypatch):
            super().install(monkeypatch)
            rpc = sys.modules["repoquill.pi.rpc"]
            inner = rpc.PiRpcBackend

            def run(self, task):
                fake.calls += 1
                fake.last_task = task
                raise pi_contracts.PiRunTimeoutError(
                    "pi did not reach agent_settled within 900.0s "
                    "[200 tool call(s), write_doc=no; total_tokens=502]")

            inner.run = run

    fake = TimeoutBackend([{"ok": True}])
    ok = _run(tmp_path, fake, monkeypatch)
    out = capsys.readouterr().out
    assert ok == []
    assert fake.calls == 2  # original + exactly one deadline retry
    assert "deadline hit without a page" in out
    assert "endpoint error" not in out
    # The retry's task prompt carries the pre-loaded source excerpt.
    assert "SOURCE EXCERPTS" in fake.last_task.evidence
    assert "def parse_date" in fake.last_task.evidence


def test_endpoint_error_still_retries_once(tmp_path, monkeypatch):
    """Sanity: a genuine 5xx in the base error still gets one retry."""
    fake = FakeSequenceBackend([
        {"ok": False, "errors": ["provider request failed: HTTP 502"]},
        {"ok": True},
    ])
    ok = _run(tmp_path, fake, monkeypatch)
    assert ok == ["alpha"]
    assert fake.calls == 2


def test_task_prompt_sets_exploration_budget(tmp_path):
    """The SimpleAudit probes showed agents over-exploring past 400 tool
    calls without writing; the task prompt now carries an explicit
    exploration budget and a write-doc obligation."""
    from repoquill.pi.rpc import build_task_prompt

    task = pi_contracts.PiTask(
        slug="s", title="T", description="d", evidence="e",
        source_root=str(tmp_path), staged_docs_dir=str(tmp_path / "s"),
        provider="p", model="m",
    )
    p = build_task_prompt(task)
    assert "hard budget" in p
    assert "15-20 tool" in p  # investigation budget (run-3 orbit evidence)
    assert "write_doc" in p
    assert "STOP" in p and "exploring and write the page" in p
    assert "do NOT re-read a file range" in p


class BudgetRetryBackend(FakeSequenceBackend):
    """First attempt: aborted on the tool-call budget (no file). Second:
    a normal successful run."""

    def install(self, monkeypatch):
        super().install(monkeypatch)
        rpc = sys.modules["repoquill.pi.rpc"]
        inner = rpc.PiRpcBackend
        outer = self

        def run(self, task):
            outer.calls += 1
            if outer.calls == 1:
                return _result(
                    slug=task.slug, completed=False, aborted=True,
                    errors=["tool-call budget of 250 exceeded — agent "
                            "aborted (it appears to be looping or "
                            "over-exploring)"])
            with open(task.expected_output_path, "w") as f:
                f.write("ok\n")
            return _result(slug=task.slug, completed=True,
                           output_path=task.expected_output_path)

        inner.run = run


def test_budget_exhausted_page_retried_once(tmp_path, monkeypatch,
                                            capsys):
    fake = BudgetRetryBackend([{"ok": False}, {"ok": True}])
    ok = _run(tmp_path, fake, monkeypatch)
    out = capsys.readouterr().out
    assert ok == ["alpha"]
    assert fake.calls == 2  # original + exactly one budget retry
    assert "one retry" in out


def test_budget_retry_failing_still_fails(tmp_path, monkeypatch):
    class AlwaysBudget(FakeSequenceBackend):
        def install(self, monkeypatch):
            super().install(monkeypatch)
            rpc = sys.modules["repoquill.pi.rpc"]
            inner = rpc.PiRpcBackend
            outer = self

            def run(self, task):
                outer.calls += 1
                return _result(
                    slug=task.slug, completed=False, aborted=True,
                    errors=["tool-call budget of 250 exceeded — agent "
                            "aborted (it appears to be looping or "
                            "over-exploring)"])

            inner.run = run

    fake = AlwaysBudget([{"ok": False}])
    ok = _run(tmp_path, fake, monkeypatch)
    assert ok == []
    assert fake.calls == 2  # no unbounded retry loop
    assert not os.path.isfile(
        str(tmp_path / "docs" / "guides" / "alpha.md"))


class OrbitRetryBackend(FakeSequenceBackend):
    """First attempt: aborted by the repeat-call orbit breaker (no file).
    Second: a normal successful run."""

    def install(self, monkeypatch):
        super().install(monkeypatch)
        rpc = sys.modules["repoquill.pi.rpc"]
        inner = rpc.PiRpcBackend
        outer = self

        def run(self, task):
            outer.calls += 1
            if outer.calls == 1:
                return _result(
                    slug=task.slug, completed=False, aborted=True,
                    errors=["repeated tool call aborted: the identical "
                            "call (read_file {\"path\": \"x.py\"}) was "
                            "issued 6 times — the agent is orbiting; "
                            "write the page with what has been gathered"])
            with open(task.expected_output_path, "w") as f:
                f.write("ok\n")
            return _result(slug=task.slug, completed=True,
                           output_path=task.expected_output_path)

        inner.run = run


def test_orbit_page_retried_once(tmp_path, monkeypatch, capsys):
    """Regression: an orbit-breaker abort (identical tool call repeated
    ``max_repeat_calls`` times) used to fall through with NO retry, so the
    page was dropped. It now gets one fresh-context retry with source
    excerpts pre-loaded (so the retry needs fewer calls and is less likely
    to re-loop on the same read)."""
    fake = OrbitRetryBackend([{"ok": False}, {"ok": True}])
    ok = _run(tmp_path, fake, monkeypatch)
    out = capsys.readouterr().out
    assert ok == ["alpha"]
    assert fake.calls == 2  # original + exactly one over-exploration retry
    assert "over-explored/orbiting" in out


def test_verification_failure_retries_with_feedback(tmp_path, monkeypatch,
                                                    capsys):
    """A draft that fails independent verification is re-authored ONCE with
    the specific findings fed back into the task, and the corrected
    (passing) page is published. Without feedback, a fresh-context retry
    would re-hallucinate the same symbol (measured on installation)."""
    from types import SimpleNamespace
    import repoquill.agents.verify as agent_verify

    class TwoRunBackend(FakeSequenceBackend):
        def install(self, monkeypatch):
            super().install(monkeypatch)
            rpc = sys.modules["repoquill.pi.rpc"]
            inner = rpc.PiRpcBackend
            outer = self

            def run(self, task):
                outer.calls += 1
                # The feedback retry's task carries the specific findings.
                if outer.calls == 2:
                    assert "FAILED INDEPENDENT VERIFICATION" in task.evidence
                    assert "do NOT reference it" in task.evidence
                with open(task.expected_output_path, "w") as f:
                    f.write(f"attempt {outer.calls}\n")
                return _result(slug=task.slug, completed=True,
                               output_path=task.expected_output_path)

            inner.run = run

    vres_calls = {"n": 0}

    def fake_verify_page_file(slug, staged, task, ctx, **kw):
        vres_calls["n"] += 1
        passed = vres_calls["n"] >= 2
        return SimpleNamespace(
            passed=passed,
            summary=("1 symbol finding; references nonexistent class "
                     "'MissingApiKeyError' (severity: high)")
            if not passed else "coverage 1/1; 0 findings")

    monkeypatch.setattr(agent_verify, "verify_page_file",
                        fake_verify_page_file)
    fake = TwoRunBackend([{"ok": True}, {"ok": True}])
    fake.install(monkeypatch)
    cfg = load_config(str(_make_repo(tmp_path)))
    cfg.llm.base_url = "http://127.0.0.1:9/v1"  # Pi needs an explicit endpoint
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")  # provider validation
    cfg.out_guides = str(tmp_path / "docs" / "guides")
    os.makedirs(cfg.out_guides, exist_ok=True)
    ok = scheduler.run_pi_generation(
        [dict(p) for p in PAGES], cfg,
        old_hashes={}, new_hashes={"datefmt/parser.py": "x"},
        force_slugs={"alpha"}, verify_each=True,
    )
    out = capsys.readouterr().out
    assert ok == ["alpha"]
    assert fake.calls == 2  # original + exactly one feedback retry
    assert vres_calls["n"] == 2
    assert "one retry with verification feedback" in out
    # The published page is the feedback retry's content, not the first.
    content = open(os.path.join(cfg.out_guides, "alpha.md")).read()
    assert content == "attempt 2\n"


def test_verification_feedback_retry_still_fails_bounded(tmp_path, monkeypatch,
                                                         capsys):
    """If the feedback retry ALSO fails verification, the page is dropped —
    exactly one feedback retry, no unbounded loop."""
    from types import SimpleNamespace
    import repoquill.agents.verify as agent_verify

    class AlwaysAuthor(FakeSequenceBackend):
        def install(self, monkeypatch):
            super().install(monkeypatch)
            rpc = sys.modules["repoquill.pi.rpc"]
            inner = rpc.PiRpcBackend
            outer = self

            def run(self, task):
                outer.calls += 1
                with open(task.expected_output_path, "w") as f:
                    f.write(f"attempt {outer.calls}\n")
                return _result(slug=task.slug, completed=True,
                               output_path=task.expected_output_path)

            inner.run = run

    def fake_verify_page_file(slug, staged, task, ctx, **kw):
        return SimpleNamespace(
            passed=False,
            summary="1 symbol finding; references nonexistent class 'X'")

    monkeypatch.setattr(agent_verify, "verify_page_file",
                        fake_verify_page_file)
    fake = AlwaysAuthor([{"ok": True}, {"ok": True}])
    fake.install(monkeypatch)
    cfg = load_config(str(_make_repo(tmp_path)))
    cfg.llm.base_url = "http://127.0.0.1:9/v1"  # Pi needs an explicit endpoint
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")  # provider validation
    cfg.out_guides = str(tmp_path / "docs" / "guides")
    os.makedirs(cfg.out_guides, exist_ok=True)
    ok = scheduler.run_pi_generation(
        [dict(p) for p in PAGES], cfg,
        old_hashes={}, new_hashes={"datefmt/parser.py": "x"},
        force_slugs={"alpha"}, verify_each=True,
    )
    assert ok == []
    assert fake.calls == 2  # original + exactly one feedback retry, no loop
    assert not os.path.isfile(
        str(tmp_path / "docs" / "guides" / "alpha.md"))


# --------------------------------------------------------------------------- #
# Transient endpoint failure predicate
# --------------------------------------------------------------------------- #
def test_over_exploration_predicate():
    from repoquill.agents.scheduler import _is_over_exploration_failure as t
    assert t(["tool-call budget of 250 exceeded — agent aborted"])
    assert t(["the agent is orbiting; write the page with what has been gathered"])
    assert t(["unrelated", "repeated tool call aborted ... orbiting"])
    # Endpoint / verification / deadline failures are NOT over-exploration.
    assert not t(["provider request failed: HTTP 502"])
    assert not t(["independent verification failed: 1 symbol finding"])
    assert not t(["did not reach agent_settled within 900.0s"])
    assert not t([])
    assert not t(None)


def _fake_result(tool_calls=(), total_tokens=0):
    from types import SimpleNamespace
    return SimpleNamespace(
        tool_calls=list(tool_calls),
        usage=SimpleNamespace(total_tokens=total_tokens),
    )


def test_transient_failure_status_codes():
    from repoquill.agents.scheduler import _is_transient_endpoint_failure as t
    assert t("request failed with HTTP 503")
    assert t("rate limited: 429 Too Many Requests")
    assert t("502 Bad Gateway")
    # Diagnostic numbers inside activity summaries must not match:
    assert not t("total_tokens=50342; 24 tool call(s)")
    assert not t("staged file missing (write_doc 42 calls)")


def test_transient_failure_stopreason_with_zero_consumption():
    from repoquill.agents.scheduler import _is_transient_endpoint_failure as t
    # Measured: transient proxy 401 surfaces as a bare stopReason=error
    # with nothing consumed -> retry.
    assert t("message_end stopReason=error",
             _fake_result(tool_calls=(), total_tokens=0))
    # ...but the same error after real work was done -> NOT retried
    # (a fresh attempt would double the consumed spend).
    assert not t("message_end stopReason=error",
                 _fake_result(tool_calls=["x"], total_tokens=0))
    assert not t("message_end stopReason=error",
                 _fake_result(tool_calls=(), total_tokens=1234))
    # No result object -> only status codes qualify.
    assert not t("message_end stopReason=error")


# --------------------------------------------------------------------------- #
# P1.4 — upgraded retry: pre-loaded source excerpts
# --------------------------------------------------------------------------- #
def test_budget_retry_gets_preloaded_source_excerpts(tmp_path, monkeypatch,
                                                     capsys):
    """A budget-exhausted page is retried with the planned source files
    pre-loaded into the task prompt (the retry then needs far fewer
    tool calls); the FIRST attempt's prompt stays as before."""
    class BudgetRetry(FakeSequenceBackend):
        def install(self, monkeypatch):
            self.tasks = []
            super().install(monkeypatch)
            rpc = sys.modules["repoquill.pi.rpc"]
            inner = rpc.PiRpcBackend
            outer = self

            def run(self, task):
                outer.tasks.append(task)
                outer.calls += 1
                if outer.calls == 1:
                    return _result(
                        slug=task.slug, completed=False, aborted=True,
                        errors=["tool-call budget of 80 exceeded — "
                                "agent aborted (it appears to be looping "
                                "or over-exploring)"])
                with open(task.expected_output_path, "w") as f:
                    f.write("ok\n")
                return _result(slug=task.slug, completed=True,
                               output_path=task.expected_output_path)

            inner.run = run

    fake = BudgetRetry([{"ok": False}, {"ok": True}])
    ok = _run(tmp_path, fake, monkeypatch)
    out = capsys.readouterr().out
    assert ok == ["alpha"]
    assert fake.calls == 2
    assert len(fake.tasks) == 2
    first, second = fake.tasks
    assert "SOURCE EXCERPTS" not in first.evidence
    assert "SOURCE EXCERPTS" in second.evidence
    assert "def parse_date" in second.evidence  # actual source inlined
    assert "datefmt/parser.py" in second.evidence
    assert "pre-loaded source excerpts" in out
    # The retry task otherwise mirrors the first (same budget/deadline).
    assert second.max_tool_calls == first.max_tool_calls
    assert second.timeout_s == first.timeout_s


def test_source_excerpts_text_reads_planned_files(tmp_path):
    """The excerpt builder inlines the head of each planned file and
    skips missing ones; no files -> empty (prompt unchanged)."""
    from repoquill.agents.scheduler import _source_excerpts_text
    pkg = tmp_path / "datefmt"
    pkg.mkdir()
    (pkg / "parser.py").write_text("def parse_date(text):\n"
                                   "    return text.strip()\n")
    from repoquill.agents.contracts import PageTask
    from repoquill.agents.evidence import build_evidence_pack
    task = PageTask(slug="alpha", title="Alpha", description="",
                    source_hints=["datefmt/parser.py"],
                    out_path=str(tmp_path / "o.md"))
    pack = build_evidence_pack(task, str(pkg), str(tmp_path))
    text = _source_excerpts_text(task, pack, "datefmt", str(tmp_path),
                                 str(pkg))
    assert "### datefmt/parser.py" in text
    assert "def parse_date" in text
    # No planned files anywhere -> empty (prompt stays unchanged).
    from repoquill.agents.contracts import EvidencePack
    task2 = PageTask(slug="beta", title="Beta", description="",
                     out_path=str(tmp_path / "o.md"))
    pack2 = EvidencePack()  # no candidate files, no hints
    assert _source_excerpts_text(task2, pack2, "datefmt", str(tmp_path),
                                 str(pkg)) == ""


def test_deadline_exhaustion_predicate():
    from repoquill.agents.scheduler import _is_deadline_exhaustion as d
    assert d("pi did not reach agent_settled within 900.0s "
             "[241 tool call(s), write_doc=no]")
    # Startup timeout (no authoring progress implied) is NOT this.
    assert not d("timed out waiting for the Pi RPC stream")
    assert not d("provider request failed: HTTP 502")
    assert not d(None)


# --------------------------------------------------------------------------- #
# P3 — authoring system prompt hardening
# --------------------------------------------------------------------------- #
def test_pi_system_prompt_hardened(tmp_path):
    from repoquill.agents.scheduler import build_pi_system_prompt
    p = build_pi_system_prompt(
        title="T", description="d", staged_path="/s/t.md",
        siblings=[("other-page", "Other Page")])
    # Verify-against-source (the baseline's 3 factual errors).
    assert "VERIFY every API reference against the source" in p
    assert "exact parameter names" in p
    assert "do not state it" in p
    # Runnable-as-displayed examples.
    assert "RUNNABLE AS DISPLAYED" in p
    assert "asyncio.run" in p
    # Offline / no-API-key section.
    assert "Offline usage (no API key)" in p
    # Navigation: Where to go next + concrete sibling list + link
    # convention.
    assert "Where to go next" in p
    assert "SIBLING PAGES" in p
    # Sibling links are page-relative (<slug>.md), never guides/<slug>.md
    # (a page in docs/guides/ resolves guides/<slug>.md to a 404).
    assert "page-relative links of the form `<slug>.md`" in p
    assert "NOT `guides/quickstart.md`" in p
    assert "'other-page' (Other Page)" in p
    # One canonical page per topic.
    assert "Do not duplicate another page's primary topic" in p
    # The existing contract is preserved.
    assert "/s/t.md" in p
    assert "write_doc" in p


def test_pi_system_prompt_without_siblings_is_safe(tmp_path):
    from repoquill.agents.scheduler import build_pi_system_prompt
    p = build_pi_system_prompt(title="T", description="",
                               staged_path="/s/t.md")
    assert "SIBLING PAGES" not in p
    assert "Where to go next" in p
