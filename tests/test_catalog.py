"""Tests for the LiteLLM-derived provider catalog and auth helpers."""

from __future__ import annotations

import pytest

from repoquill.cli import (
    _LOCAL_PROVIDERS,
    _OAUTH_PROVIDERS,
    _needs_api_key,
    _pick_default_model,
    _provider_api_key_env,
)


def test_catalog_has_openai():
    from repoquill.cli import _litellm_catalog

    catalog = _litellm_catalog()
    assert "openai" in catalog
    assert catalog["openai"]["default"]
    assert isinstance(catalog["openai"]["models"], list)
    assert len(catalog["openai"]["models"]) > 0


def test_catalog_has_anthropic():
    from repoquill.cli import _litellm_catalog

    catalog = _litellm_catalog()
    assert "anthropic" in catalog
    assert catalog["anthropic"]["default"]


def test_catalog_models_are_unprefixed():
    """Model names in the catalog should not carry the provider prefix."""
    from repoquill.cli import _litellm_catalog

    catalog = _litellm_catalog()
    for model in catalog.get("anthropic", {}).get("models", []):
        assert not model.startswith("anthropic/"), f"model still prefixed: {model}"


def test_pick_default_model_prefers_short():
    models = ["gpt-4o-2024-05-13", "gpt-4o", "ft:gpt-3.5-turbo", "gpt-4"]
    assert _pick_default_model(models) == "gpt-4"


def test_pick_default_model_empty():
    assert _pick_default_model([]) == ""


def test_provider_api_key_env_convention():
    assert _provider_api_key_env("openai") == "OPENAI_API_KEY"
    assert _provider_api_key_env("anthropic") == "ANTHROPIC_API_KEY"
    assert _provider_api_key_env("together_ai") == "TOGETHER_AI_API_KEY"
    assert _provider_api_key_env("groq") == "GROQ_API_KEY"


def test_needs_api_key_standard():
    assert _needs_api_key("openai") is True
    assert _needs_api_key("anthropic") is True
    assert _needs_api_key("groq") is True


def test_needs_api_key_local():
    for p in _LOCAL_PROVIDERS:
        assert _needs_api_key(p) is False


def test_needs_api_key_oauth():
    for p in _OAUTH_PROVIDERS:
        assert _needs_api_key(p) is False


def test_github_copilot_is_oauth():
    assert "github_copilot" in _OAUTH_PROVIDERS


def test_ollama_is_local():
    assert "ollama" in _LOCAL_PROVIDERS
