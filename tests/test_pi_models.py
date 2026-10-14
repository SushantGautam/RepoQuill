"""Offline tests for repoquill.pi.models (ephemeral Pi agent config).

No network access: live_probe is never called here.
"""

import json
import os

import pytest

from repoquill.pi import contracts, models


class _LLMCfg:
    """Minimal stand-in for repoquill.config.LLMConfig (duck-typed)."""

    def __init__(self, **kw):
        self.provider = kw.get("provider", "openai")
        self.model = kw.get("model", "gpt-4o")
        self.base_url = kw.get("base_url", "https://simulachat.sushant.info.np/v1")
        self.api_key_env = kw.get("api_key_env", "OPENAI_API_KEY")


def _read_models_json(agent_dir):
    with open(os.path.join(agent_dir, "models.json"), encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- #
# resolve_endpoint
# --------------------------------------------------------------------------- #
def test_resolve_endpoint_happy_path():
    cfg = _LLMCfg()
    assert models.resolve_endpoint(cfg) == (
        "https://simulachat.sushant.info.np/v1",
        "gpt-4o",
        "OPENAI_API_KEY",
    )


def test_resolve_endpoint_missing_base_url_actionable():
    cfg = _LLMCfg(base_url=None)
    with pytest.raises(ValueError) as exc:
        models.resolve_endpoint(cfg)
    assert "base_url" in str(exc.value)
    assert "Pi" in str(exc.value)


def test_resolve_endpoint_missing_model_actionable():
    cfg = _LLMCfg(model="")
    with pytest.raises(ValueError) as exc:
        models.resolve_endpoint(cfg)
    assert "model" in str(exc.value)


def test_resolve_endpoint_missing_api_key_env_actionable():
    cfg = _LLMCfg(api_key_env="")
    with pytest.raises(ValueError) as exc:
        models.resolve_endpoint(cfg)
    assert "api_key_env" in str(exc.value)


# --------------------------------------------------------------------------- #
# provider_slug / model_pattern
# --------------------------------------------------------------------------- #
def test_provider_slug_deterministic_and_stable():
    url = "https://simulachat.sushant.info.np/v1"
    assert models.provider_slug(url) == "simulachat-sushant-info-np"
    # Same host, different scheme/port/path -> same slug.
    assert models.provider_slug("http://simulachat.sushant.info.np:8443/foo") == (
        models.provider_slug(url)
    )
    # Case-insensitive host.
    assert models.provider_slug("HTTPS://SIMULACHAT.SUSHANT.INFO.NP/v1") == (
        models.provider_slug(url)
    )


def test_provider_slug_collision_sanity_two_urls():
    slug_a = models.provider_slug("http://a:11434/v1")
    slug_b = models.provider_slug("http://b:11434/v1")
    assert slug_a == "a"
    assert slug_b == "b"
    assert slug_a != slug_b
    # Underscored hosts are squashed to the same hyphen form (documented:
    # non-alphanumerics all collapse to '-').
    assert models.provider_slug("http://foo_bar") == "foo-bar"
    assert models.provider_slug("http://foo-bar") == "foo-bar"


def test_model_pattern_format():
    cfg = _LLMCfg(model="qwen3-coder:32b")
    assert models.model_pattern(cfg) == (
        "simulachat-sushant-info-np/qwen3-coder:32b"
    )
    # Matches what build_launch_args would receive as --model.
    pattern = models.model_pattern(cfg)
    assert "/" in pattern and pattern.count("/") >= 1


# --------------------------------------------------------------------------- #
# build_ephemeral_agent_dir
# --------------------------------------------------------------------------- #
def test_models_json_exact_shape(tmp_path):
    dest = str(tmp_path / "agent")
    cfg = _LLMCfg(model="qwen3-27b")
    got = models.build_ephemeral_agent_dir(
        cfg, dest=dest, context_window=40960, max_tokens=16384, reasoning=True
    )
    assert got == dest
    data = _read_models_json(dest)

    assert set(data.keys()) == {"providers"}
    slug = "simulachat-sushant-info-np"
    assert set(data["providers"].keys()) == {slug}
    provider = data["providers"][slug]
    assert provider["baseUrl"] == "https://simulachat.sushant.info.np/v1"
    assert provider["api"] == "openai-completions"
    assert provider["apiKey"] == "$OPENAI_API_KEY"
    assert provider["models"] == [
        {
            "id": "qwen3-27b",
            "contextWindow": 40960,
            "maxTokens": 16384,
            "reasoning": True,
        }
    ]


def test_models_json_defaults():
    dest = models.build_ephemeral_agent_dir(_LLMCfg(model="m-1"))
    try:
        data = _read_models_json(dest)
        provider = data["providers"]["simulachat-sushant-info-np"]
        assert provider["models"][0] == {
            "id": "m-1",
            "contextWindow": 32768,
            "maxTokens": 8192,
            "reasoning": False,
        }
        # mkdtemp(prefix=...) -> basename carries the prefix.
        assert os.path.basename(dest).startswith("repoquill-pi-")
    finally:
        models.cleanup(dest)


def test_api_key_is_env_reference_even_when_env_set(monkeypatch, tmp_path):
    secret = "sk-super-secret-value-123"
    monkeypatch.setenv("MY_TEST_KEY", secret)
    cfg = _LLMCfg(api_key_env="MY_TEST_KEY", model="m-1")
    dest = models.build_ephemeral_agent_dir(cfg, dest=str(tmp_path / "a"))
    raw = open(os.path.join(dest, "models.json"), encoding="utf-8").read()
    assert secret not in raw
    data = json.loads(raw)
    provider = list(data["providers"].values())[0]
    assert provider["apiKey"] == "$MY_TEST_KEY"


def test_invalid_api_key_env_rejected(tmp_path):
    cfg = _LLMCfg(api_key_env="1BAD-NAME")
    with pytest.raises(ValueError) as exc:
        models.build_ephemeral_agent_dir(cfg, dest=str(tmp_path / "x"))
    assert "1BAD-NAME" in str(exc.value)
    assert not os.path.exists(os.path.join(str(tmp_path), "x", "models.json"))


def test_build_rejects_missing_base_url_and_model(tmp_path):
    with pytest.raises(ValueError):
        models.build_ephemeral_agent_dir(_LLMCfg(base_url=None), dest=str(tmp_path / "a"))
    with pytest.raises(ValueError):
        models.build_ephemeral_agent_dir(_LLMCfg(model=""), dest=str(tmp_path / "b"))


def test_dest_honored_and_reusable(tmp_path):
    dest = str(tmp_path / "nested" / "agent")
    cfg = _LLMCfg(model="m-1")
    assert models.build_ephemeral_agent_dir(cfg, dest=dest) == dest
    # Reusing dest rewrites the file rather than failing.
    assert models.build_ephemeral_agent_dir(
        _LLMCfg(model="m-2"), dest=dest
    ) == dest
    data = _read_models_json(dest)
    assert list(data["providers"].values())[0]["models"][0]["id"] == "m-2"


# --------------------------------------------------------------------------- #
# agent_dir_env_value / cleanup / check_api_key_present
# --------------------------------------------------------------------------- #
def test_agent_dir_env_value():
    assert models.agent_dir_env_value("/some/dir") == {
        contracts.AGENT_DIR_ENV: "/some/dir"
    }
    assert contracts.AGENT_DIR_ENV == "PI_CODING_AGENT_DIR"


def test_cleanup_removes_dir(tmp_path):
    dest = models.build_ephemeral_agent_dir(_LLMCfg(model="m-1"), dest=str(tmp_path / "c"))
    assert os.path.isdir(dest)
    models.cleanup(dest)
    assert not os.path.exists(dest)
    # Idempotent / no-op on missing.
    models.cleanup(dest)
    models.cleanup(None)


def test_check_api_key_present(monkeypatch):
    monkeypatch.setenv("RQ_TEST_SET_KEY", "x")
    monkeypatch.delenv("RQ_TEST_UNSET_KEY", raising=False)
    assert models.check_api_key_present("RQ_TEST_SET_KEY") is True
    assert models.check_api_key_present("RQ_TEST_UNSET_KEY") is False
