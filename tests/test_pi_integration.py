"""Integration tests for the Pi-first engine wiring (M2).

Covers, without any Node/Pi/LLM dependency:

* engine resolution rules (fresh default, migration mapping, CLI
  overrides, --agentic/--no-agentic alias semantics);
* CLI routing: each --engine value calls exactly the right generator,
  and --no-llm never touches the Pi path;
* fail-closed behavior: a Pi startup failure exits nonzero and leaves
  the docs directory and plan file byte-identical (no silent fallback);
* run_pi_generation against a FAKE pi backend (injected via
  sys.modules): incremental skip, per-page isolation, independent
  verification before publish, agent-dir cleanup;
* the `repoquill doctor` subcommand.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import types

import pytest

from repoquill import cli
from repoquill.agents import scheduler
from repoquill.config import load_config, resolve_engine
from repoquill.pi import contracts as pi_contracts


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
def _make_repo(tmp_path, engine=None, agentic_enabled=False):
    """Tiny generic package + repoquill.yml (engine param optional)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    pkg = tmp_path / "datefmt"
    pkg.mkdir(parents=True, exist_ok=True)
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
    lines = ["project_name: datefmt", "package_dir: datefmt"]
    if engine is not None:
        lines += ["documentation:", f"  engine: {engine}"]
    lines += ["llm:", "  provider: openai", "  model: gpt-4o"]
    if agentic_enabled:
        lines += ["  agentic:", "    enabled: true"]
    lines += ["build:", "  docs_dir: docs"]
    cfg_path = tmp_path / "repoquill.yml"
    cfg_path.write_text("\n".join(lines) + "\n")
    return tmp_path, cfg_path


PAGES = [
    {"slug": "alpha", "title": "Alpha", "description": "",
     "source_files": ["datefmt/parser.py"]},
    {"slug": "beta", "title": "Beta", "description": "",
     "source_files": ["datefmt/formatter.py"]},
]

GOOD_CONTENT = (
    "## Alpha\n\n`parse_date` parses an ISO date string; "
    "`format_date` formats a date value.\n"
)
LOW_COVERAGE_CONTENT = "# Beta\n\nA generic page with no symbols.\n"


def _patch_planning(monkeypatch):
    """Stub structure planning (no LLM calls)."""
    monkeypatch.setattr(
        cli, "determine_structure",
        lambda cfg, client: [dict(p) for p in PAGES])


def _dir_digest(path):
    """Stable byte digest of a directory tree (paths relative)."""
    entries = []
    for root, _dirs, files in os.walk(path):
        for f in sorted(files):
            full = os.path.join(root, f)
            rel = os.path.relpath(full, path)
            with open(full, "rb") as fh:
                entries.append((rel, hashlib.sha256(fh.read()).hexdigest()))
    return sorted(entries)


# --------------------------------------------------------------------------- #
# Fake repoquill.pi modules (injected via sys.modules; tests skip nothing —
# the fake IS the backend; the real pi/* modules are never required)
# --------------------------------------------------------------------------- #
class FakePiModules:
    def __init__(self):
        self.backend_instances = []
        self.agent_dirs = []
        self.cleaned = []
        self.find_pi_result = "/fake/pi"
        self.find_pi_error = None
        # slug -> (content, error) mapping for the fake backend.
        self.behavior = {}
        self.default_content = GOOD_CONTENT
        self.doctor_result = None

    def install(self, monkeypatch):
        import repoquill.pi as pi_pkg

        bootstrap = types.ModuleType("repoquill.pi.bootstrap")

        def find_pi():
            if self.find_pi_error is not None:
                raise self.find_pi_error
            return self.find_pi_result

        bootstrap.find_pi = find_pi
        if self.doctor_result is not None:
            bootstrap.doctor = lambda *a, **k: self.doctor_result

        models = types.ModuleType("repoquill.pi.models")

        def build_ephemeral_agent_dir(llm_cfg, *a, **k):
            import tempfile
            d = tempfile.mkdtemp(prefix="repoquill-fake-agent-")
            self.agent_dirs.append(d)
            with open(os.path.join(d, "models.json"), "w") as f:
                f.write("{}")
            return d

        models.build_ephemeral_agent_dir = build_ephemeral_agent_dir
        models.model_pattern = lambda llm_cfg, *a, **k: "fake-model"

        def cleanup(path, *a, **k):
            self.cleaned.append(path)
            shutil.rmtree(path, ignore_errors=True)

        models.cleanup = cleanup

        rpc = types.ModuleType("repoquill.pi.rpc")
        fake = self  # closure

        class PiRpcBackend:
            def __init__(self, pi_bin, extension_path, agent_dir=None,
                         extra_env=None):
                fake.backend_instances.append(
                    (pi_bin, extension_path, agent_dir, extra_env))

            def run(self, task):
                content, error = fake.behavior.get(
                    task.slug, (fake.default_content, None))
                if error is not None:
                    raise error
                with open(task.expected_output_path, "w") as f:
                    f.write(content)
                return pi_contracts.PiRunResult(
                    slug=task.slug, completed=True,
                    output_path=task.expected_output_path,
                    model="fake-model")

        rpc.PiRpcBackend = PiRpcBackend

        bridge = types.ModuleType("repoquill.pi.bridge")

        class PiBridgeServer:
            def __init__(self, *args, **kwargs):
                self.socket_path = "/tmp/repoquill-fake-bridge.sock"

            def start(self):
                pass

            def close(self):
                pass

        bridge.PiBridgeServer = PiBridgeServer

        for name, mod in [("bootstrap", bootstrap), ("models", models),
                          ("rpc", rpc), ("bridge", bridge)]:
            monkeypatch.setitem(sys.modules, f"repoquill.pi.{name}", mod)
            monkeypatch.setattr(pi_pkg, name, mod, raising=False)


def _make_cfg(tmp_path):
    root, cfg_path = _make_repo(tmp_path, engine="pi")
    cfg = load_config(str(cfg_path))
    return cfg


# --------------------------------------------------------------------------- #
# Engine resolution
# --------------------------------------------------------------------------- #
def test_fresh_config_defaults_to_pi(tmp_path, capsys):
    _, cfg_path = _make_repo(tmp_path, engine="pi")
    cfg = load_config(str(cfg_path))
    assert cfg.documentation_engine == "pi"
    assert resolve_engine(cfg) == "pi"
    assert capsys.readouterr().out == ""


def test_missing_key_agentic_enabled_maps_to_python_agent(tmp_path, capsys):
    _, cfg_path = _make_repo(tmp_path, agentic_enabled=True)
    cfg = load_config(str(cfg_path))
    assert cfg.documentation_engine is None
    assert resolve_engine(cfg) == "python-agent"
    out = capsys.readouterr().out
    assert "llm.agentic.enabled maps to engine: python-agent" in out


def test_missing_key_no_agentic_defaults_legacy(tmp_path, capsys):
    _, cfg_path = _make_repo(tmp_path)
    cfg = load_config(str(cfg_path))
    assert cfg.documentation_engine is None
    assert resolve_engine(cfg) == "legacy"
    assert "maps to" not in capsys.readouterr().out


def test_cli_engine_overrides_config(tmp_path):
    _, cfg_path = _make_repo(tmp_path, engine="pi")
    cfg = load_config(str(cfg_path))
    assert resolve_engine(cfg, cli_engine="legacy") == "legacy"
    assert resolve_engine(cfg, cli_engine="python-agent") == "python-agent"

    # Legacy config (no key), explicit --engine pi upgrades.
    legacy_root, _ = _make_repo(tmp_path / "legacy")
    legacy_cfg = load_config(str(legacy_root / "repoquill.yml"))
    assert legacy_cfg.documentation_engine is None
    assert resolve_engine(legacy_cfg, cli_engine="pi") == "pi"


def test_agentic_flag_aliases_python_agent(tmp_path, capsys):
    _, cfg_path = _make_repo(tmp_path, engine="pi")
    cfg = load_config(str(cfg_path))
    assert resolve_engine(cfg, agentic_flag=True) == "python-agent"
    assert "deprecated alias" in capsys.readouterr().out


def test_no_agentic_only_downgrades_python_agent(tmp_path):
    _, cfg_path = _make_repo(tmp_path, agentic_enabled=True)
    cfg = load_config(str(cfg_path))
    # python-agent (via migration) downgraded to legacy.
    assert resolve_engine(cfg, agentic_flag=False) == "legacy"

    pi_cfg_root, _ = _make_repo(tmp_path / "pi", engine="pi")
    pi_cfg = load_config(str(pi_cfg_root / "repoquill.yml"))
    # pi is NOT affected by --no-agentic.
    assert resolve_engine(pi_cfg, agentic_flag=False) == "pi"

    legacy_root, _ = _make_repo(tmp_path / "legacy")
    legacy_cfg = load_config(str(legacy_root / "repoquill.yml"))
    # never upgrades legacy.
    assert resolve_engine(legacy_cfg, agentic_flag=False) == "legacy"


def test_engine_flag_wins_over_agentic(tmp_path, capsys):
    root, cfg_path = _make_repo(tmp_path)
    cfg = load_config(str(cfg_path))
    assert resolve_engine(cfg, cli_engine="pi", agentic_flag=True) == "pi"
    assert "--engine pi" in capsys.readouterr().out


def test_invalid_engine_rejected(tmp_path):
    root, cfg_path = _make_repo(tmp_path)
    text = (cfg_path.read_text().replace(
        "llm:", "documentation:\n  engine: bogus\nllm:", 1))
    cfg_path.write_text(text)
    with pytest.raises(ValueError, match="documentation.engine"):
        load_config(str(cfg_path))


def test_init_template_scaffolds_pi_engine(tmp_path):
    # The scaffolded template must always set documentation.engine: pi,
    # so every fresh config has the key (fresh-install default = Pi).
    assert "documentation:" in cli._CONFIG_TEMPLATE
    assert "engine: pi" in cli._CONFIG_TEMPLATE

    # The formatted template must round-trip through load_config.
    content = cli._CONFIG_TEMPLATE.format(
        project_name="demo", package_dir="demo",
        source_repo_block="", description="A demo.",
        repo_name="me/demo", site_owner="me", site_slug="demo",
        provider="openai", model="gpt-4o", base_url_line="",
        api_key_env_line="  api_key_env: OPENAI_API_KEY\n",
        reference_block="  - title: Core\n    modules: [demo]",
        index_block='  quick_start:\n    install: "pip install demo"',
    )
    (tmp_path / "repoquill.yml").write_text(content)
    cfg = load_config(str(tmp_path / "repoquill.yml"))
    assert cfg.documentation_engine == "pi"
    assert resolve_engine(cfg) == "pi"


# --------------------------------------------------------------------------- #
# CLI routing
# --------------------------------------------------------------------------- #
def _run_cli(monkeypatch, root, *extra):
    monkeypatch.chdir(root)
    args = ["generate", "--no-scaffold", "--config",
            str(root / "repoquill.yml"), *extra]
    return cli.main(args)


def test_engine_pi_routes_to_run_pi_generation(monkeypatch, tmp_path, capsys):
    root, _ = _make_repo(tmp_path, engine="pi")
    _patch_planning(monkeypatch)

    calls = {"pi": 0, "agent": 0, "legacy": 0}

    def fake_pi(pages, cfg, **kw):
        calls["pi"] += 1
        return [p["slug"] for p in pages]

    monkeypatch.setattr(scheduler, "run_pi_generation", fake_pi)
    monkeypatch.setattr(
        scheduler, "run_agentic_generation",
        lambda *a, **k: calls.__setitem__("agent", calls["agent"] + 1) or [])
    monkeypatch.setattr(
        cli, "generate_all_pages",
        lambda *a, **k: calls.__setitem__("legacy", calls["legacy"] + 1) or [])

    rc = _run_cli(monkeypatch, root)
    assert rc == 0
    assert calls == {"pi": 1, "agent": 0, "legacy": 0}
    assert "mode: pi" in capsys.readouterr().out


def test_engine_python_agent_routes(monkeypatch, tmp_path):
    root, _ = _make_repo(tmp_path, engine="python-agent")
    _patch_planning(monkeypatch)
    calls = {"pi": 0, "agent": 0, "legacy": 0}
    monkeypatch.setattr(
        scheduler, "run_pi_generation",
        lambda *a, **k: calls.__setitem__("pi", calls["pi"] + 1) or [])
    monkeypatch.setattr(
        scheduler, "run_agentic_generation",
        lambda *a, **k: calls.__setitem__("agent", calls["agent"] + 1) or [])
    monkeypatch.setattr(
        cli, "generate_all_pages",
        lambda *a, **k: calls.__setitem__("legacy", calls["legacy"] + 1) or [])

    rc = _run_cli(monkeypatch, root)
    assert rc == 0
    assert calls == {"pi": 0, "agent": 1, "legacy": 0}


def test_engine_legacy_routes(monkeypatch, tmp_path):
    root, _ = _make_repo(tmp_path, engine="legacy")
    _patch_planning(monkeypatch)
    calls = {"pi": 0, "agent": 0, "legacy": 0}
    monkeypatch.setattr(
        scheduler, "run_pi_generation",
        lambda *a, **k: calls.__setitem__("pi", calls["pi"] + 1) or [])
    monkeypatch.setattr(
        scheduler, "run_agentic_generation",
        lambda *a, **k: calls.__setitem__("agent", calls["agent"] + 1) or [])
    monkeypatch.setattr(
        cli, "generate_all_pages",
        lambda *a, **k: calls.__setitem__("legacy", calls["legacy"] + 1) or [])

    rc = _run_cli(monkeypatch, root)
    assert rc == 0
    assert calls == {"pi": 0, "agent": 0, "legacy": 1}


def test_agentic_flag_maps_to_python_agent(monkeypatch, tmp_path, capsys):
    # Fresh pi config + --agentic (no --engine) → python-agent.
    root, _ = _make_repo(tmp_path, engine="pi")
    _patch_planning(monkeypatch)
    calls = {"pi": 0, "agent": 0, "legacy": 0}
    monkeypatch.setattr(
        scheduler, "run_pi_generation",
        lambda *a, **k: calls.__setitem__("pi", calls["pi"] + 1) or [])
    monkeypatch.setattr(
        scheduler, "run_agentic_generation",
        lambda *a, **k: calls.__setitem__("agent", calls["agent"] + 1) or [])
    monkeypatch.setattr(
        cli, "generate_all_pages",
        lambda *a, **k: calls.__setitem__("legacy", calls["legacy"] + 1) or [])

    rc = _run_cli(monkeypatch, root, "--agentic")
    assert rc == 0
    assert calls == {"pi": 0, "agent": 1, "legacy": 0}
    assert "deprecated alias" in capsys.readouterr().out


def test_no_agentic_downgrades_python_agent(monkeypatch, tmp_path):
    root, _ = _make_repo(tmp_path, engine="python-agent")
    _patch_planning(monkeypatch)
    calls = {"pi": 0, "agent": 0, "legacy": 0}
    monkeypatch.setattr(
        scheduler, "run_pi_generation",
        lambda *a, **k: calls.__setitem__("pi", calls["pi"] + 1) or [])
    monkeypatch.setattr(
        scheduler, "run_agentic_generation",
        lambda *a, **k: calls.__setitem__("agent", calls["agent"] + 1) or [])
    monkeypatch.setattr(
        cli, "generate_all_pages",
        lambda *a, **k: calls.__setitem__("legacy", calls["legacy"] + 1) or [])

    rc = _run_cli(monkeypatch, root, "--no-agentic")
    assert rc == 0
    assert calls == {"pi": 0, "agent": 0, "legacy": 1}


def test_engine_flag_wins_over_agentic_flag(monkeypatch, tmp_path, capsys):
    root, _ = _make_repo(tmp_path)
    _patch_planning(monkeypatch)
    calls = {"pi": 0, "agent": 0, "legacy": 0}
    monkeypatch.setattr(
        scheduler, "run_pi_generation",
        lambda *a, **k: calls.__setitem__("pi", calls["pi"] + 1) or [])
    monkeypatch.setattr(
        scheduler, "run_agentic_generation",
        lambda *a, **k: calls.__setitem__("agent", calls["agent"] + 1) or [])
    monkeypatch.setattr(
        cli, "generate_all_pages",
        lambda *a, **k: calls.__setitem__("legacy", calls["legacy"] + 1) or [])

    rc = _run_cli(monkeypatch, root, "--agentic", "--engine", "pi")
    assert rc == 0
    assert calls == {"pi": 1, "agent": 0, "legacy": 0}
    out = capsys.readouterr().out
    assert "using --engine pi" in out


def test_no_llm_never_touches_pi(monkeypatch, tmp_path):
    """A real --no-llm run with find_pi exploding: pi is never imported
    into the execution path, and the run still succeeds (no Node needed)."""
    root, _ = _make_repo(tmp_path, engine="pi")
    fake = FakePiModules()
    fake.find_pi_error = pi_contracts.PiNotInstalledError("must never be called")
    fake.install(monkeypatch)

    def pi_sentinel(*a, **k):
        raise AssertionError("run_pi_generation must not run with --no-llm")

    monkeypatch.setattr(scheduler, "run_pi_generation", pi_sentinel)

    rc = _run_cli(monkeypatch, root, "--no-llm")
    assert rc == 0
    assert fake.backend_instances == []


def test_pi_not_installed_fail_closed(monkeypatch, tmp_path, capsys):
    """Pi startup failure: nonzero exit, docs dir + plan byte-identical."""
    root, _ = _make_repo(tmp_path, engine="pi")
    _patch_planning(monkeypatch)
    docs = root / "docs"
    guides = docs / "guides"
    guides.mkdir(parents=True)
    (guides / "alpha.md").write_text(GOOD_CONTENT)
    (guides / "beta.md").write_text(GOOD_CONTENT)
    (docs / ".plan.json").write_text(json.dumps({
        "pages": [dict(p) for p in PAGES],
        "file_hashes": {"datefmt/parser.py": "h1",
                        "datefmt/formatter.py": "h2"},
    }))
    # Baseline --no-llm run: creates the deterministic Layer-1 reference
    # files (which every run regenerates identically) so the digest below
    # compares a stable tree.
    rc0 = _run_cli(monkeypatch, root, "--no-llm")
    assert rc0 == 0
    before_docs = _dir_digest(str(docs))

    # Also make the real pi bootstrap fail, to prove the CLI never gets
    # past the generator even if the sentinel were bypassed.
    fake = FakePiModules()
    fake.find_pi_error = pi_contracts.PiNotInstalledError(
        "pi not installed (Node missing)")
    fake.install(monkeypatch)

    def boom(*a, **k):
        raise pi_contracts.PiNotInstalledError("pi not installed")

    monkeypatch.setattr(scheduler, "run_pi_generation", boom)

    rc = _run_cli(monkeypatch, root)
    assert rc == 1, "pi startup failure must exit nonzero"

    assert _dir_digest(str(docs)) == before_docs, \
        "docs dir must be byte-identical after a total pi failure"

    out = capsys.readouterr().out
    assert "pi engine failed" in out
    assert "repoquill doctor" in out
    assert "--engine python-agent" in out
    assert "--engine legacy" in out


# --------------------------------------------------------------------------- #
# run_pi_generation against a fake backend
# --------------------------------------------------------------------------- #
def _pi_env(tmp_path):
    """Repo + loaded config; returns (cfg, pages)."""
    root, _ = _make_repo(tmp_path, engine="pi")
    cfg = load_config(str(root / "repoquill.yml"))
    os.makedirs(cfg.out_guides, exist_ok=True)
    return cfg


def test_pi_unchanged_pages_cost_zero_spawns(monkeypatch, tmp_path):
    fake = FakePiModules()
    fake.install(monkeypatch)
    cfg = _pi_env(tmp_path)
    guides = cfg.out_guides
    with open(os.path.join(guides, "alpha.md"), "w") as f:
        f.write(GOOD_CONTENT)
    with open(os.path.join(guides, "beta.md"), "w") as f:
        f.write(GOOD_CONTENT)
    hashes = {"datefmt/parser.py": "h1", "datefmt/formatter.py": "h2"}
    pages = [dict(p) for p in PAGES]

    generated = scheduler.run_pi_generation(
        pages, cfg, old_hashes=hashes, new_hashes=hashes)

    assert generated == []
    assert fake.backend_instances == [], "unchanged pages must not spawn pi"
    # Agent dir was still cleaned up.
    assert len(fake.cleaned) == len(fake.agent_dirs)


def test_pi_changed_page_processed_and_recorded(monkeypatch, tmp_path):
    fake = FakePiModules()
    fake.install(monkeypatch)
    cfg = _pi_env(tmp_path)
    # alpha.md must exist for alpha to count as unchanged.
    with open(os.path.join(cfg.out_guides, "alpha.md"), "w") as f:
        f.write(GOOD_CONTENT)
    old = {"datefmt/parser.py": "h1", "datefmt/formatter.py": "h2"}
    new = {"datefmt/parser.py": "h1", "datefmt/formatter.py": "h2-CHANGED"}
    pages = [dict(p) for p in PAGES]

    generated = scheduler.run_pi_generation(
        pages, cfg, old_hashes=old, new_hashes=new)

    assert generated == ["beta"]
    assert len(fake.backend_instances) == 1
    out = os.path.join(cfg.out_guides, "beta.md")
    assert os.path.isfile(out)
    with open(out) as f:
        assert "A generic page" not in f.read()  # good content was staged
    by_slug = {p["slug"]: p for p in pages}
    assert by_slug["beta"].get("status") == "ok"
    assert by_slug["alpha"].get("status") != "failed"
    # No backend call for the unchanged page.
    assert fake.cleaned, "agent dir must be cleaned up"


def test_pi_failing_page_does_not_block_others(monkeypatch, tmp_path):
    fake = FakePiModules()
    fake.behavior["beta"] = (
        GOOD_CONTENT,
        pi_contracts.PiRunTimeoutError("did not settle in time"),
    )
    fake.install(monkeypatch)
    cfg = _pi_env(tmp_path)
    old = {"datefmt/parser.py": "a", "datefmt/formatter.py": "b"}
    new = {"datefmt/parser.py": "A", "datefmt/formatter.py": "B"}
    pages = [dict(p) for p in PAGES]

    generated = scheduler.run_pi_generation(
        pages, cfg, old_hashes=old, new_hashes=new)

    assert sorted(generated) == ["alpha"]
    by_slug = {p["slug"]: p for p in pages}
    assert by_slug["alpha"].get("status") == "ok"
    assert by_slug["beta"].get("status") == "failed"
    assert "did not settle" in (by_slug["beta"].get("error") or "")
    # The failed page was never published.
    assert not os.path.isfile(
        os.path.join(cfg.out_guides, "beta.md"))


def test_pi_verify_each_blocks_low_coverage(monkeypatch, tmp_path):
    fake = FakePiModules()
    fake.default_content = LOW_COVERAGE_CONTENT
    fake.install(monkeypatch)
    cfg = _pi_env(tmp_path)
    old = {"datefmt/parser.py": "a"}
    new = {"datefmt/parser.py": "A"}
    pages = [dict(PAGES[0])]

    generated = scheduler.run_pi_generation(
        pages, cfg, old_hashes=old, new_hashes=new, verify_each=True)

    assert generated == []
    assert pages[0].get("status") == "failed"
    assert "verification failed" in (pages[0].get("error") or "")
    assert not os.path.isfile(os.path.join(cfg.out_guides, "alpha.md"))

    # verify_each=False skips the independent check and publishes.
    pages2 = [dict(PAGES[0])]
    generated2 = scheduler.run_pi_generation(
        pages2, cfg, old_hashes=old, new_hashes=new, verify_each=False)
    assert generated2 == ["alpha"]
    assert os.path.isfile(os.path.join(cfg.out_guides, "alpha.md"))


def test_pi_not_installed_raises_before_any_work(monkeypatch, tmp_path):
    fake = FakePiModules()
    fake.find_pi_error = pi_contracts.PiNotInstalledError(
        "Node not found; install Node or run --no-llm")
    fake.install(monkeypatch)
    cfg = _pi_env(tmp_path)
    pages = [dict(p) for p in PAGES]

    with pytest.raises(pi_contracts.PiNotInstalledError):
        scheduler.run_pi_generation(pages, cfg)

    assert fake.backend_instances == []
    assert os.listdir(cfg.out_guides) == []


def test_pi_find_pi_none_raises_not_installed(monkeypatch, tmp_path):
    """Landed contract: find_pi() returns None (never raises) when the
    binary is missing → the scheduler must fail closed itself."""
    fake = FakePiModules()
    fake.find_pi_result = None
    fake.install(monkeypatch)
    cfg = _pi_env(tmp_path)

    with pytest.raises(pi_contracts.PiNotInstalledError,
                       match="npm install"):
        scheduler.run_pi_generation([dict(p) for p in PAGES], cfg)

    assert fake.backend_instances == []
    assert fake.agent_dirs == [], "agent dir must not be built before resolve"


def test_pi_find_pi_installation_object(monkeypatch, tmp_path):
    """Landed contract: find_pi() returns a PiInstallation-like object
    with .binary/.version; the scheduler unwraps the binary path."""
    fake = FakePiModules()

    class _Inst:
        binary = "/fake/pi"
        version = "1.2.0"
        source = "path"
        cache_dir = None

    fake.find_pi_result = _Inst()
    fake.install(monkeypatch)
    cfg = _pi_env(tmp_path)
    pages = [dict(PAGES[0])]

    generated = scheduler.run_pi_generation(
        pages, cfg,
        old_hashes={"datefmt/parser.py": "a"},
        new_hashes={"datefmt/parser.py": "A"},
        verify_each=False)

    assert generated == ["alpha"]
    assert fake.backend_instances[0][0] == "/fake/pi"


def test_pi_task_wire_format(monkeypatch, tmp_path):
    """The PiTask handed to the backend carries the documented fields."""
    fake = FakePiModules()
    fake.install(monkeypatch)
    captured = {}

    class CapturingBackend:
        def __init__(self, pi_bin, extension_path, agent_dir=None,
                     extra_env=None):
            fake.backend_instances.append(
                (pi_bin, extension_path, agent_dir, extra_env))

        def run(self, task):
            captured["task"] = task
            with open(task.expected_output_path, "w") as f:
                f.write(fake.default_content)
            return pi_contracts.PiRunResult(
                slug=task.slug, completed=True,
                output_path=task.expected_output_path,
                model="fake-model")

    sys.modules["repoquill.pi.rpc"].PiRpcBackend = CapturingBackend

    cfg = _pi_env(tmp_path)
    pages = [dict(PAGES[0])]
    scheduler.run_pi_generation(
        pages, cfg,
        old_hashes={"datefmt/parser.py": "a"},
        new_hashes={"datefmt/parser.py": "A"},
        verify_each=False)

    task = captured["task"]
    assert task.slug == "alpha"
    assert task.model == "fake-model"
    assert task.provider == "openai"
    assert task.expected_output_path.endswith("alpha.md")
    assert task.staged_docs_dir.endswith("/") is False
    assert "documentation author" in task.system_prompt.lower()
    assert "alpha.md" in task.system_prompt
    assert task.allow_example_exec is False


def test_pi_provider_slug_from_custom_model_pattern(monkeypatch, tmp_path):
    """Custom-endpoint providers must come from the model slug.

    Regression: sending the openai-compat name (``openai``) while the model
    is a custom ``slug/id`` pattern made Pi fail startup with
    "No API key found for openai" even though the ephemeral provider config
    was correct.
    """
    fake = FakePiModules()
    fake.install(monkeypatch)
    sys.modules["repoquill.pi.models"].model_pattern = (
        lambda llm_cfg, *a, **k: "simulachat-host-np/Qwen3.8")
    captured = {}

    class CapturingBackend:
        def __init__(self, pi_bin, extension_path, agent_dir=None,
                     extra_env=None):
            pass

        def run(self, task):
            captured["task"] = task
            with open(task.expected_output_path, "w") as f:
                f.write(fake.default_content)
            return pi_contracts.PiRunResult(
                slug=task.slug, completed=True,
                output_path=task.expected_output_path,
                model="fake-model")

    sys.modules["repoquill.pi.rpc"].PiRpcBackend = CapturingBackend

    cfg = _pi_env(tmp_path)
    pages = [dict(PAGES[0])]
    scheduler.run_pi_generation(
        pages, cfg,
        old_hashes={"datefmt/parser.py": "a"},
        new_hashes={"datefmt/parser.py": "A"},
        verify_each=False)

    assert captured["task"].model == "simulachat-host-np/Qwen3.8"
    assert captured["task"].provider == "simulachat-host-np"


def test_pi_bridge_socket_env_reaches_backend(monkeypatch, tmp_path):
    """The Pi child must receive THIS page's bridge socket via extra_env.

    Regression: the bridge socket was only reachable through os.environ
    (which the unit tests never set for the scheduler path), so real
    scheduler-driven Pi runs had tools that could not reach the bridge.
    """
    fake = FakePiModules()
    fake.install(monkeypatch)
    cfg = _pi_env(tmp_path)
    pages = [dict(PAGES[0])]

    scheduler.run_pi_generation(
        pages, cfg,
        old_hashes={"datefmt/parser.py": "a"},
        new_hashes={"datefmt/parser.py": "A"},
        verify_each=False)

    assert fake.backend_instances, "backend was never constructed"
    extra_env = fake.backend_instances[0][3]
    assert extra_env is not None
    assert extra_env[pi_contracts.BRIDGE_SOCKET_ENV] == (
        "/tmp/repoquill-fake-bridge.sock")
    assert extra_env["REPOQUILL_ALLOW_EXAMPLE_EXEC"] in ("0", "1")


# --------------------------------------------------------------------------- #
# doctor subcommand
# --------------------------------------------------------------------------- #
def test_doctor_command_prints_readiness(monkeypatch, capsys):
    fake = FakePiModules()
    fake.doctor_result = {
        "node": {"ok": True, "version": "20.0.0"},
        "pi": {"ok": False, "version": None},
        "model": {"ok": True, "provider": "openai"},
        "recommendations": ["Install Pi package", "Check model endpoint"],
    }
    fake.install(monkeypatch)

    rc = cli.main(["doctor"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "node:" in out
    assert "pi:" in out
    assert "20.0.0" in out
    assert "Install Pi package" in out
    assert "Check model endpoint" in out


def test_doctor_missing_pi_modules(monkeypatch, capsys):
    # A None entry makes `import repoquill.pi.bootstrap` raise ImportError.
    monkeypatch.setitem(sys.modules, "repoquill.pi.bootstrap", None)
    rc = cli.main(["doctor"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "not available" in out
    assert "--no-llm" in out


# --------------------------------------------------------------------------- #
# Help surface
# --------------------------------------------------------------------------- #
def test_generate_help_shows_engine(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["repoquill", "generate", "--help"])
    with pytest.raises(SystemExit):
        cli.main(["generate", "--help"])
    out = capsys.readouterr().out
    assert "--engine" in out
    assert "pi,python-agent,legacy" in out
