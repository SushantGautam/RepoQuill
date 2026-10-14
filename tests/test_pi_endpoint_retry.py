"""Regression tests: per-page endpoint-error (5xx/429) retry in
run_pi_generation.

A page whose Pi run fails with a 5xx/429-class provider error is
retried exactly once; other failures are not retried; a retry that
fails is recorded as a failure (no infinite retries).
"""

from __future__ import annotations

import os
import shutil
import sys
import types

from repoquill.agents import scheduler
from repoquill.config import load_config
from repoquill.pi import contracts as pi_contracts


def _make_repo(tmp_path):
    pkg = tmp_path / "datefmt"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(
        "from datefmt.parser import parse_date\n")
    (pkg / "parser.py").write_text(
        "def parse_date(text):\n"
        "    return text.strip()\n")
    cfg_path = tmp_path / "repoquill.yml"
    cfg_path.write_text(
        "project_name: datefmt\n"
        "package_dir: datefmt\n"
        "documentation:\n  engine: pi\n"
        "llm:\n  provider: openai\n  model: gpt-4o\n"
        "build:\n  docs_dir: docs\n")
    return cfg_path


PAGES = [
    {"slug": "alpha", "title": "Alpha", "description": "",
     "source_files": ["datefmt/parser.py"]},
]

GOOD_CONTENT = "`parse_date` parses an ISO date string.\n"


class FakeSequenceBackend:
    """PiRpcBackend fake: each run() pops the next scripted outcome."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.last_task = None

    def install(self, monkeypatch):
        pi_pkg = __import__("repoquill.pi", fromlist=["pi"])
        bootstrap = types.ModuleType("repoquill.pi.bootstrap")
        bootstrap.find_pi = lambda: "/fake/pi"

        models = types.ModuleType("repoquill.pi.models")

        def build_ephemeral_agent_dir(llm_cfg, *a, **k):
            d = os.path.join("/tmp", "repoquill-fake-agent-retry")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "models.json"), "w") as f:
                f.write("{}")
            return d

        models.build_ephemeral_agent_dir = build_ephemeral_agent_dir
        models.model_pattern = lambda llm_cfg, *a, **k: "fake-model"
        models.cleanup = lambda path, *a, **k: shutil.rmtree(
            path, ignore_errors=True)

        rpc = types.ModuleType("repoquill.pi.rpc")
        fake = self

        class PiRpcBackend:
            def __init__(self, pi_bin, extension_path, agent_dir=None,
                         extra_env=None):
                pass

            def run(self, task):
                fake.last_task = task
                idx = min(fake.calls, len(fake.outcomes) - 1)
                fake.calls += 1
                outcome = fake.outcomes[idx]
                if outcome["ok"]:
                    with open(task.expected_output_path, "w") as f:
                        f.write(outcome.get("content", GOOD_CONTENT))
                    return pi_contracts.PiRunResult(
                        slug=task.slug, completed=True,
                        output_path=task.expected_output_path,
                        model="fake-model")
                return pi_contracts.PiRunResult(
                    slug=task.slug, completed=False, output_path=None,
                    errors=list(outcome.get("errors", [])),
                    model="fake-model")

        rpc.PiRpcBackend = PiRpcBackend

        bridge = types.ModuleType("repoquill.pi.bridge")

        class PiBridgeServer:
            def __init__(self, *args, **kwargs):
                self.socket_path = "/tmp/repoquill-fake-bridge-retry.sock"

            def start(self):
                pass

            def close(self):
                pass

        bridge.PiBridgeServer = PiBridgeServer

        for name, mod in [("bootstrap", bootstrap), ("models", models),
                          ("rpc", rpc), ("bridge", bridge)]:
            monkeypatch.setitem(sys.modules, f"repoquill.pi.{name}", mod)
            monkeypatch.setattr(pi_pkg, name, mod, raising=False)


def _run(tmp_path, fake, monkeypatch):
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


def test_endpoint_error_retried_once_and_recovers(tmp_path, monkeypatch,
                                                   capsys):
    fake = FakeSequenceBackend([
        {"ok": False,
         "errors": ["provider request failed: HTTP 502 Bad Gateway"]},
        {"ok": True},
    ])
    ok = _run(tmp_path, fake, monkeypatch)
    assert ok == ["alpha"]
    assert fake.calls == 2
    assert "one retry" in capsys.readouterr().out


def test_persistent_endpoint_error_fails_after_single_retry(
        tmp_path, monkeypatch):
    fake = FakeSequenceBackend([
        {"ok": False, "errors": ["provider request failed: HTTP 429"]},
        {"ok": False, "errors": ["provider request failed: HTTP 503"]},
    ])
    ok = _run(tmp_path, fake, monkeypatch)
    assert ok == []
    assert fake.calls == 2  # original + exactly one retry


def test_non_endpoint_error_is_not_retried(tmp_path, monkeypatch):
    fake = FakeSequenceBackend([
        {"ok": False, "errors": ["agent crashed: exit 1"]},
        {"ok": True},  # must never be reached
    ])
    ok = _run(tmp_path, fake, monkeypatch)
    assert ok == []
    assert fake.calls == 1


def test_failed_run_never_publishes_a_stale_staged_file(tmp_path,
                                                         monkeypatch):
    """Regression: an incomplete run (agent settled but no write_doc)
    must be reported as a failure, even though a stale file exists in
    the shared staging dir — the failure return must not fall through
    to the publish path."""
    class StaleStageBackend(FakeSequenceBackend):
        def install(self, monkeypatch):
            super().install(monkeypatch)
            rpc = sys.modules["repoquill.pi.rpc"]
            inner = rpc.PiRpcBackend

            def run(self, task):
                # Simulate a stale staged file left by a previous
                # attempt: present in the shared staging dir, but this
                # run did not complete.
                os.makedirs(os.path.dirname(task.expected_output_path),
                            exist_ok=True)
                with open(task.expected_output_path, "w") as f:
                    f.write("# Stale content from a prior attempt\n")
                return pi_contracts.PiRunResult(
                    slug=task.slug, completed=False, output_path=None,
                    errors=["agent settled without writing the page"],
                    model="fake-model")

            inner.run = run

    StaleStageBackend([
        {"ok": False,
         "errors": ["agent settled without writing the page"]},
    ]).install(monkeypatch)
    cfg = load_config(str(_make_repo(tmp_path)))
    cfg.out_guides = str(tmp_path / "docs" / "guides")
    os.makedirs(cfg.out_guides, exist_ok=True)
    ok = scheduler.run_pi_generation(
        [dict(p) for p in PAGES], cfg,
        old_hashes={}, new_hashes={"datefmt/parser.py": "x"},
        force_slugs={"alpha"}, verify_each=False,
    )
    assert ok == []
    assert not os.path.isfile(
        str(tmp_path / "docs" / "guides" / "alpha.md"))


def test_pi_timeout_s_from_agentic_config(tmp_path, monkeypatch):
    """llm.agentic.timeout_s overrides the 300s Pi per-page deadline."""
    fake = FakeSequenceBackend([{"ok": True}])
    fake.install(monkeypatch)
    cfg = load_config(str(_make_repo(tmp_path)))
    cfg.out_guides = str(tmp_path / "docs" / "guides")
    os.makedirs(cfg.out_guides, exist_ok=True)
    cfg.raw.setdefault("llm", {})["agentic"] = {"timeout_s": 600}
    scheduler.run_pi_generation(
        [dict(p) for p in PAGES], cfg,
        old_hashes={}, new_hashes={"datefmt/parser.py": "x"},
        force_slugs={"alpha"}, verify_each=False,
    )
    assert fake.last_task is not None
    assert fake.last_task.timeout_s == 600.0


def test_pi_timeout_s_defaults_to_900(tmp_path, monkeypatch):
    """Product default: 900s per-page Pi deadline. The SimpleAudit
    baseline showed real-repo pages routinely need far more than the
    old 300s on remote endpoints (7 of 8 pages hit the old deadline
    with no write_doc ever reached)."""
    fake = FakeSequenceBackend([{"ok": True}])
    fake.install(monkeypatch)
    cfg = load_config(str(_make_repo(tmp_path)))
    cfg.out_guides = str(tmp_path / "docs" / "guides")
    os.makedirs(cfg.out_guides, exist_ok=True)
    scheduler.run_pi_generation(
        [dict(p) for p in PAGES], cfg,
        old_hashes={}, new_hashes={"datefmt/parser.py": "x"},
        force_slugs={"alpha"}, verify_each=False,
    )
    assert fake.last_task.timeout_s == 900.0


def test_pi_max_tool_calls_default_and_override(tmp_path, monkeypatch):
    """llm.agentic.max_tool_calls (loop guard) is plumbed to the PiTask;
    default 250, 0 disables the budget."""
    fake = FakeSequenceBackend([{"ok": True}])
    fake.install(monkeypatch)
    cfg = load_config(str(_make_repo(tmp_path)))
    cfg.out_guides = str(tmp_path / "docs" / "guides")
    os.makedirs(cfg.out_guides, exist_ok=True)
    scheduler.run_pi_generation(
        [dict(p) for p in PAGES], cfg,
        old_hashes={}, new_hashes={"datefmt/parser.py": "x"},
        force_slugs={"alpha"}, verify_each=False,
    )
    assert fake.last_task.max_tool_calls == 250

    fake2 = FakeSequenceBackend([{"ok": True}])
    fake2.install(monkeypatch)
    cfg.raw.setdefault("llm", {})["agentic"] = {"max_tool_calls": 0}
    scheduler.run_pi_generation(
        [dict(p) for p in PAGES], cfg,
        old_hashes={}, new_hashes={"datefmt/parser.py": "x"},
        force_slugs={"alpha"}, verify_each=False,
    )
    assert fake2.last_task.max_tool_calls == 0


def test_pi_context_window_plumbed_to_agent_dir(tmp_path, monkeypatch):
    """llm.agentic.context_window is declared in the ephemeral models.json
    so Pi compacts at the endpoint's REAL window, not a guessed 32768."""
    seen = {}

    fake = FakeSequenceBackend([{"ok": True}])
    fake.install(monkeypatch)
    models = sys.modules["repoquill.pi.models"]
    original_build = models.build_ephemeral_agent_dir

    def capturing_build(llm_cfg, *a, **k):
        seen["kwargs"] = k
        return original_build(llm_cfg, *a, **k)

    monkeypatch.setattr(models, "build_ephemeral_agent_dir", capturing_build)
    cfg = load_config(str(_make_repo(tmp_path)))
    cfg.out_guides = str(tmp_path / "docs" / "guides")
    os.makedirs(cfg.out_guides, exist_ok=True)
    cfg.raw.setdefault("llm", {})["agentic"] = {
        "context_window": 131072,
        "compaction_keep_recent_tokens": 90000,
    }
    scheduler.run_pi_generation(
        [dict(p) for p in PAGES], cfg,
        old_hashes={}, new_hashes={"datefmt/parser.py": "x"},
        force_slugs={"alpha"}, verify_each=False,
    )
    assert seen["kwargs"].get("context_window") == 131072
    assert seen["kwargs"].get("compaction_keep_recent_tokens") == 90000


def test_pi_max_repeat_calls_plumbed_to_task(tmp_path, monkeypatch):
    """llm.agentic.max_repeat_calls reaches the PiTask (orbit guard):
    default 6, and an explicit yml value is honoured."""
    from repoquill.config import load_config

    fake = FakeSequenceBackend([{"ok": True}])
    fake.install(monkeypatch)
    cfg = load_config(str(_make_repo(tmp_path)))
    cfg.out_guides = str(tmp_path / "docs" / "guides")
    os.makedirs(cfg.out_guides, exist_ok=True)
    scheduler.run_pi_generation(
        [dict(p) for p in PAGES], cfg,
        old_hashes={}, new_hashes={"datefmt/parser.py": "x"},
        force_slugs={"alpha"}, verify_each=False,
    )
    assert fake.last_task.max_repeat_calls == 6  # default
    cfg.raw.setdefault("llm", {})["agentic"] = {"max_repeat_calls": 4}
    scheduler.run_pi_generation(
        [dict(p) for p in PAGES], cfg,
        old_hashes={}, new_hashes={"datefmt/parser.py": "x"},
        force_slugs={"alpha"}, verify_each=False,
    )
    assert fake.last_task.max_repeat_calls == 4
