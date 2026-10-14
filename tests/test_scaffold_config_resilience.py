"""Regression tests for LLM config scaffolding resilience (cli._scaffold_config).

A truncated/malformed LLM scaffold response must not crash `repoquill
generate`; it must degrade to the default (unscaffolded) paths. The
scaffold prompt must also request enough output tokens to survive large
repositories (historically truncated at max_tokens=1024).
"""

from __future__ import annotations

import json

from repoquill import cli
from repoquill.config import load_config


def _make_repo(tmp_path):
    pkg = tmp_path / "datefmt"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(
        "from datefmt.parser import parse_date\n")
    (pkg / "parser.py").write_text(
        "def parse_date(text):\n    return text.strip()\n")
    cfg_path = tmp_path / "repoquill.yml"
    cfg_path.write_text(
        "project_name: datefmt\n"
        "package_dir: datefmt\n"
        "documentation:\n  engine: pi\n"
        "llm:\n  provider: openai\n  model: gpt-4o\n"
        "build:\n  docs_dir: docs\n")
    return cfg_path


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.last_kwargs = None

    def chat(self, messages, **kwargs):
        self.last_kwargs = kwargs
        return self.response


def test_malformed_scaffold_response_does_not_crash(tmp_path, capsys):
    cfg = load_config(str(_make_repo(tmp_path)))
    truncated = '{"narrative_sections": [{"title": "Core", "slugs": ["a"'
    # (deliberately truncated mid-JSON, as a 1024-token cap produces)
    client = FakeClient(truncated)
    updated = cli._scaffold_config(cfg, client)
    assert updated is False
    out = capsys.readouterr().out
    assert "scaffolding skipped" in out
    # Config file untouched.
    assert "narrative_sections" not in \
        (tmp_path / "repoquill.yml").read_text()


def test_valid_scaffold_response_updates_config(tmp_path):
    cfg = load_config(str(_make_repo(tmp_path)))
    payload = json.dumps({
        "narrative_sections": [
            {"title": "Core", "slugs": ["parse-date-guide"]}],
        "reference_sections": [
            {"title": "Core", "modules": ["datefmt.parser"]}],
        "index": {"tagline": "A date formatting library.",
                  "quick_start": {"install": "pip install datefmt"}},
    })
    client = FakeClient(payload)
    updated = cli._scaffold_config(cfg, client)
    assert updated is True
    text = (tmp_path / "repoquill.yml").read_text()
    assert "narrative_sections" in text
    assert "reference_sections" in text
    assert "tagline" in text


def test_scaffold_requests_sufficient_output_tokens(tmp_path):
    cfg = load_config(str(_make_repo(tmp_path)))
    truncated = '{"narrative_sections": ['
    client = FakeClient(truncated)
    cli._scaffold_config(cfg, client)
    assert client.last_kwargs["max_tokens"] >= 4096
