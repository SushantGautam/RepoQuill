"""Retry/backoff behavior for the LLM client."""
from __future__ import annotations

from repoquill.llm import _retry_wait


class _FakeResponse:
    def __init__(self, headers):
        self.headers = headers


class _FakeError(Exception):
    pass


def _error(headers=None):
    err = _FakeError("boom")
    if headers is not None:
        err.response = _FakeResponse(headers)
    return err


def test_base_backoff_is_30s_doubling():
    assert _retry_wait(0, _error()) == 30.0
    assert _retry_wait(1, _error()) == 60.0
    assert _retry_wait(2, _error()) == 120.0


def test_retry_after_header_is_honored_when_longer():
    # Cloudflare 502 pattern: origin asks for 60s backoff.
    err = _error({"retry-after": "60"})
    assert _retry_wait(0, err) == 60.0
    # A shorter retry-after does not reduce the base backoff.
    assert _retry_wait(1, err) == 60.0


def test_invalid_retry_after_ignored():
    err = _error({"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})
    assert _retry_wait(0, err) == 30.0


def test_error_without_response_uses_base_backoff():
    assert _retry_wait(3, _error()) == 240.0


def test_chat_defaults_to_five_retries():
    import inspect

    from repoquill.llm import LLMClient

    sig = inspect.signature(LLMClient.chat)
    assert sig.parameters["retries"].default == 5
