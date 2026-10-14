"""Tests for the Pi-run bounds added after the SimpleAudit baseline.

The baseline run (research/local/simpleaudit-pi-eval) showed 7/8 guide
pages dying at the 300s deadline with no write_doc, and one page whose
failure reason ("staged file missing") carried zero evidence of what
the agent actually did. These tests pin the general-purpose repairs:

* ``llm.agentic.timeout_s`` / ``max_tool_calls`` / ``context_window``
  are parsed from repoquill.yml with product defaults (900s / 400 /
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
    assert ag.max_tool_calls == 250
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
        tmp_path, monkeypatch):
    """Regression: timeout diagnostics embed 'total_tokens=502'-style
    numbers; the endpoint-retry classifier must only match the base
    error, so a timed-out page is NOT retried as a 5xx."""
    class TimeoutBackend(FakeSequenceBackend):
        def install(self, monkeypatch):
            super().install(monkeypatch)
            rpc = sys.modules["repoquill.pi.rpc"]
            inner = rpc.PiRpcBackend

            def run(self, task):
                fake.calls += 1
                raise pi_contracts.PiRunTimeoutError(
                    "pi did not reach agent_settled within 900.0s "
                    "[200 tool call(s), write_doc=no; total_tokens=502]")

            inner.run = run

    fake = TimeoutBackend([{"ok": True}])
    ok = _run(tmp_path, fake, monkeypatch)
    assert ok == []
    assert fake.calls == 1  # no endpoint retry


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


# --------------------------------------------------------------------------- #
# Transient endpoint failure predicate
# --------------------------------------------------------------------------- #
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
