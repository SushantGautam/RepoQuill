"""Tests for the `repoquill init` LLM-config capture and file generation."""

from __future__ import annotations

import os
import textwrap

import pytest

from repoquill.cli import _cmd_init


class _Args:
    """Minimal argparse.Namespace stand-in for init."""

    def __init__(self, **kw):
        self.name = kw.get("name")
        self.package = kw.get("package")
        self.description = kw.get("description")
        self.provider = kw.get("provider")
        self.model = kw.get("model")
        self.trigger = kw.get("trigger")
        self.test = kw.get("test", False)
        self.force = kw.get("force", False)


@pytest.fixture
def pkg_dir(tmp_path, monkeypatch):
    """Create a minimal Python package and chdir into it."""
    monkeypatch.chdir(tmp_path)
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("# mypkg\n")
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "myproj"
            """
        )
    )
    return tmp_path


def test_init_openai_writes_api_key_env(pkg_dir, monkeypatch):
    # Non-interactive: accept defaults (openai / default model)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")
    rc = _cmd_init(_Args(provider="openai", model="gpt-4o"))
    assert rc == 0

    cfg_text = (pkg_dir / "repoquill.yml").read_text()
    assert "provider: openai" in cfg_text
    assert "model: gpt-4o" in cfg_text
    assert "api_key_env: OPENAI_API_KEY" in cfg_text

    wf_text = (pkg_dir / ".github" / "workflows" / "docs.yml").read_text()
    assert "api_key_env: OPENAI_API_KEY" in wf_text
    # Explicit secrets (not `secrets: inherit`)
    assert "secrets: inherit" not in wf_text
    assert "${{ secrets.LLM_API_KEY }}" in wf_text


def test_init_github_copilot_no_api_key_env(pkg_dir, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")
    rc = _cmd_init(_Args(provider="github_copilot", model="gpt-4o"))
    assert rc == 0

    cfg_text = (pkg_dir / "repoquill.yml").read_text()
    assert "provider: github_copilot" in cfg_text
    # api_key_env should be commented out, not set
    assert "api_key_env: OPENAI_API_KEY" not in cfg_text
    assert "not needed" in cfg_text


def test_init_ollama_no_api_key_env(pkg_dir, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")
    rc = _cmd_init(_Args(provider="ollama", model="llama3.1"))
    assert rc == 0

    cfg_text = (pkg_dir / "repoquill.yml").read_text()
    assert "provider: ollama" in cfg_text
    assert "api_key_env: " not in cfg_text.replace("  # api_key_env:", "")
    assert "local provider" in cfg_text


def test_init_anthropic_env_var(pkg_dir, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")
    rc = _cmd_init(_Args(provider="anthropic", model="claude-sonnet-4-5"))
    assert rc == 0

    cfg_text = (pkg_dir / "repoquill.yml").read_text()
    assert "api_key_env: ANTHROPIC_API_KEY" in cfg_text


def test_init_existing_config_shows_prompt(pkg_dir, monkeypatch):
    """Second init without --force shows existing config and keeps values."""
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")
    assert _cmd_init(_Args(provider="openai", model="gpt-4o")) == 0
    # Second run without --force: shows existing config, keeps all (default)
    assert _cmd_init(_Args(provider="openai", model="gpt-4o")) == 0
    # With --force it overwrites
    assert _cmd_init(_Args(provider="openai", model="gpt-4o", force=True)) == 0


def test_init_generated_config_loads(pkg_dir, monkeypatch):
    """The generated repoquill.yml must be loadable by load_config."""
    from repoquill.config import load_config

    monkeypatch.setattr("builtins.input", lambda *a, **k: "")
    _cmd_init(_Args(provider="github_copilot", model="gpt-4o"))
    cfg = load_config(str(pkg_dir / "repoquill.yml"))
    assert cfg.llm.provider == "github_copilot"
    assert cfg.llm.model == "gpt-4o"


# --- Workflow trigger modes ---


def _on_block(pkg_dir) -> str:
    """Return the on: block (up to the jobs: line) from the generated workflow."""
    wf = pkg_dir / ".github" / "workflows" / "docs.yml"
    text = wf.read_text()
    start = text.index("on:")
    end = text.index("jobs:")
    return text[start:end]


def test_init_trigger_manual_is_dormant(pkg_dir, monkeypatch):
    """manual (default) → only workflow_dispatch active, push commented out."""
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")
    _cmd_init(_Args(provider="openai", model="gpt-4o", trigger="manual"))
    block = _on_block(pkg_dir)
    assert "workflow_dispatch:" in block
    # push must be commented out (dormant) — no active push line
    assert "\n  push:" not in block
    assert "#   push:" in block


def test_init_trigger_push_main(pkg_dir, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")
    _cmd_init(_Args(provider="openai", model="gpt-4o", trigger="push_main"))
    block = _on_block(pkg_dir)
    assert "  push:" in block
    assert "branches: [main]" in block
    assert "workflow_dispatch:" in block


def test_init_trigger_push_all(pkg_dir, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")
    _cmd_init(_Args(provider="openai", model="gpt-4o", trigger="push_all"))
    block = _on_block(pkg_dir)
    assert "  push:" in block
    assert "  pull_request:" in block
    assert "workflow_dispatch:" in block


def test_init_trigger_release(pkg_dir, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")
    _cmd_init(_Args(provider="openai", model="gpt-4o", trigger="release"))
    block = _on_block(pkg_dir)
    assert "  push:" in block
    assert "tags:" in block
    assert "'v*'" in block
    assert "workflow_dispatch:" in block


def test_init_trigger_default_is_manual(pkg_dir, monkeypatch):
    """No --trigger flag → defaults to manual (dormant)."""
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")
    _cmd_init(_Args(provider="openai", model="gpt-4o"))
    block = _on_block(pkg_dir)
    assert "workflow_dispatch:" in block
    assert "\n  push:" not in block  # dormant
