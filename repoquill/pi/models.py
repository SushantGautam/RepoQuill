"""Ephemeral Pi agent-directory configuration for OpenAI-compatible endpoints.

RepoQuill points a documentation Pi run at the same provider a normal
RepoQuill run would (RepoQuill's ``LLMConfig``: ``provider`` / ``model`` /
``base_url`` / ``api_key_env``). Pi resolves custom providers from a
``models.json`` file inside its *agent directory* (``<agent-dir>/models.json``;
see the pinned Pi 1.2.0 docs, ``models.md`` / ``configuration.md``). This
module builds a throwaway agent directory per run so no user-global Pi config
is touched and no secret is ever written to disk: ``apiKey`` is always a
``$NAME`` / ``${NAME}`` environment reference that Pi expands at request time.

Compatibility caveats (IMPORTANT, verified against the pinned pi-ai 1.2.0
source, ``dist/api/openai-completions.js``)
-------------------------------------------
* ``api: "openai-completions"`` in models.json is the correct api value for
  OpenAI-compatible endpoints (confirmed against the installed Pi 1.2.0
  ``docs/models.md``).
* For *agentic* documentation runs (where the model must call the vetted
  bridge tools), the endpoint must support **native ``tool_calls``** in the
  OpenAI completions schema. Qwen models served by vLLM/SGLang generally do;
  some proxies or older deployments return tool calls as text or reject the
  ``tools`` parameter outright.
* Pi ALWAYS sends ``stream: true`` with
  ``stream_options: {"include_usage": true}`` on
  ``POST <baseUrl>/chat/completions`` — the endpoint MUST support OpenAI SSE
  streaming for agentic use. This is the main compatibility risk for
  SimulaChat/Qwen gateways that advertise ``/chat/completions`` but implement
  non-streaming or vendor-specific streaming.
* Token caps: Pi sends ``params.max_tokens`` (the compat field) or
  ``max_completion_tokens``; if absent it falls back to ``model.maxTokens``
  from models.json. So the generated ``maxTokens`` should be generous
  (>= 8192) and ``contextWindow`` sane (>= 32768) to avoid premature
  compaction/clamping — these are the defaults of
  :func:`build_ephemeral_agent_dir`.

Use :func:`live_probe` (explicit, manual) to confirm a given endpoint before
relying on it — RepoQuill never probes automatically and never falls back
silently: an endpoint without tool-call support simply fails the page and
must be diagnosed.

The ``llm_cfg`` argument is duck-typed: any object with ``provider``,
``model``, ``base_url`` and ``api_key_env`` attributes (e.g.
``repoquill.config.LLMConfig``) works; no heavy imports are made.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from . import contracts

#: ``$NAME`` / ``${NAME}`` environment reference: must be a valid shell-ish
#: identifier so models.json can interpolate it and the spawner can export it.
_ENV_REF_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# --------------------------------------------------------------------------- #
# Endpoint resolution
# --------------------------------------------------------------------------- #
def resolve_endpoint(llm_cfg: Any) -> Tuple[str, str, str]:
    """Resolve ``(base_url, model_id, api_key_env)`` from an LLM config.

    Pi custom providers require an explicit endpoint, so a missing
    ``base_url`` is an error here even though the legacy LiteLLM path allows
    it (LiteLLM can infer one from ``provider``).
    """
    base_url = (getattr(llm_cfg, "base_url", None) or "").strip()
    model_id = (getattr(llm_cfg, "model", None) or "").strip()
    api_key_env = (getattr(llm_cfg, "api_key_env", None) or "").strip()

    if not base_url:
        raise ValueError(
            "Pi custom providers need an explicit LLM base_url "
            "(set repoquill.llm.base_url, e.g. the /v1 endpoint of your "
            "OpenAI-compatible server); unlike the legacy LiteLLM path, Pi "
            "cannot infer an endpoint from the provider name."
        )
    if not model_id:
        raise ValueError(
            "LLM model id is missing (set repoquill.llm.model); Pi needs an "
            "exact model id advertised by the endpoint."
        )
    if not api_key_env:
        raise ValueError(
            "LLM api_key_env is missing (set repoquill.llm.api_key_env); Pi "
            "resolves the API key from that environment variable at request "
            "time, so the variable name must be configured."
        )
    return base_url, model_id, api_key_env


def validate_api_key_env(api_key_env: str) -> None:
    """Raise ``ValueError`` unless the name is a valid ``$NAME`` reference."""
    if not _ENV_REF_RE.match(api_key_env or ""):
        raise ValueError(
            f"api_key_env {api_key_env!r} is not a valid environment variable "
            "name (must match ^[A-Za-z_][A-Za-z0-9_]*$); models.json only "
            "accepts $NAME / ${NAME} references."
        )


def check_api_key_present(api_key_env: str) -> bool:
    """Diagnostics helper: is the key currently set in the environment?"""
    return bool(os.environ.get(api_key_env))


# --------------------------------------------------------------------------- #
# Provider slug
# --------------------------------------------------------------------------- #
def provider_slug(base_url: str) -> str:
    """Stable provider slug derived from the endpoint's URL host.

    Deterministic mapping: take the hostname (port ignored — two services on
    the same host with different ports share a slug, which is fine because
    Pi provider names are just keys and the baseUrl disambiguates), lowercase
    it, replace every non-alphanumeric run with a single ``-``, and strip
    leading/trailing ``-``. Example: ``https://simulachat.sushant.info.np/v1``
    → ``simulachat-sushant-info-np``. An unparseable URL falls back to a slug
    of the whole string so two distinct strings always collide only if they
    are equal after normalization.
    """
    host = ""
    try:
        host = (urlparse(base_url).hostname or "").strip().lower()
    except ValueError:
        host = ""
    if not host:
        host = base_url.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", host)
    return slug.strip("-")


def model_pattern(llm_cfg: Any) -> str:
    """``"<provider_slug>/<model_id>"`` — the pattern for Pi CLI ``--model``
    and ``PiTask.model``."""
    base_url, model_id, _ = resolve_endpoint(llm_cfg)
    return f"{provider_slug(base_url)}/{model_id}"


# --------------------------------------------------------------------------- #
# Ephemeral agent directory
# --------------------------------------------------------------------------- #
def build_ephemeral_agent_dir(
    llm_cfg: Any,
    dest: Optional[str] = None,
    context_window: int = 32768,
    max_tokens: int = 8192,
    reasoning: bool = False,
) -> str:
    """Create a per-run Pi agent directory containing a ``models.json``.

    If ``dest`` is given it is used (created if missing); otherwise a temp
    directory with prefix ``repoquill-pi-`` is created. The returned path is
    meant to be exported as ``contracts.AGENT_DIR_ENV`` (see
    :func:`agent_dir_env_value`) and removed with :func:`cleanup` when the
    run finishes.

    ``apiKey`` is always written as ``$<API_KEY_ENV>`` — never a literal
    secret. Whether the variable is currently set does not matter here; Pi
    resolves it at request time in the child process environment.
    """
    base_url, model_id, api_key_env = resolve_endpoint(llm_cfg)
    validate_api_key_env(api_key_env)

    if dest is not None:
        os.makedirs(dest, exist_ok=True)
    else:
        dest = tempfile.mkdtemp(prefix="repoquill-pi-")

    slug = provider_slug(base_url)
    models_json = {
        "providers": {
            slug: {
                "baseUrl": base_url,
                "api": "openai-completions",
                "apiKey": f"${api_key_env}",
                "models": [
                    {
                        "id": model_id,
                        "contextWindow": int(context_window),
                        "maxTokens": int(max_tokens),
                        "reasoning": bool(reasoning),
                    }
                ],
            }
        }
    }
    path = os.path.join(dest, "models.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(models_json, fh, indent=2)
        fh.write("\n")
    return dest


def agent_dir_env_value(path: str) -> Dict[str, str]:
    """Env mapping for the spawner pointing Pi at the ephemeral agent dir."""
    return {contracts.AGENT_DIR_ENV: path}


def cleanup(path: Optional[str]) -> None:
    """Remove an ephemeral agent directory (ignores missing dirs)."""
    if path:
        shutil.rmtree(path, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Optional live probe (explicit-only, not wired into the CLI)
# --------------------------------------------------------------------------- #
def live_probe(llm_cfg: Any, timeout_s: float = 30.0) -> Dict[str, Any]:
    """POST one tiny ``/chat/completions`` request with one fake tool.

    Returns a structured dict::

        {"ok": bool, "tool_call_supported": Optional[bool],
         "status": Optional[int], "error": str, "raw": Any}

    ``tool_call_supported`` is ``True`` only when the response contains a
    structured ``tool_calls`` entry (native OpenAI-style tool calling), which
    is the prerequisite for agentic documentation runs. HTTP errors are
    captured, not raised. This is deliberately NOT called anywhere in the
    automated pipeline — invoke it manually (e.g.
    ``python -c "from repoquill.pi import models; ...; models.live_probe(cfg)"``)
    to characterize an endpoint. Uses stdlib urllib only.

    Caveat: Pi itself always requests SSE streaming
    (``stream: true`` + ``stream_options.include_usage``), which this
    non-streaming probe does not exercise; a passing probe confirms
    tool-call support only, not streaming support.
    """
    base_url, model_id, api_key_env = resolve_endpoint(llm_cfg)
    validate_api_key_env(api_key_env)

    api_key = os.environ.get(api_key_env, "")
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"

    body = json.dumps({
        "model": model_id,
        "max_tokens": 16,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Call the ping tool with reason='probe' and nothing else."
                ),
            }
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "ping",
                    "description": "Acknowledge the probe.",
                    "parameters": {
                        "type": "object",
                        "properties": {"reason": {"type": "string"}},
                        "required": ["reason"],
                    },
                },
            }
        ],
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            status = response.getcode()
            raw = json.loads(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", "replace")[:2000]
        return {
            "ok": False,
            "tool_call_supported": None,
            "status": exc.code,
            "error": f"HTTP {exc.code}: {payload}",
            "raw": None,
        }
    except Exception as exc:  # network/timeout/JSON errors: report, don't raise
        return {
            "ok": False,
            "tool_call_supported": None,
            "status": None,
            "error": f"{type(exc).__name__}: {exc}",
            "raw": None,
        }

    tool_call_supported = False
    try:
        message = (raw or {}).get("choices", [{}])[0].get("message", {})
        tool_calls = message.get("tool_calls") or []
        tool_call_supported = any(
            (tc.get("function") or {}).get("name") for tc in tool_calls
        )
    except (IndexError, AttributeError, TypeError):
        tool_call_supported = False

    return {
        "ok": True,
        "tool_call_supported": tool_call_supported,
        "status": status,
        "error": "",
        "raw": raw,
    }


__all__ = [
    "resolve_endpoint",
    "validate_api_key_env",
    "check_api_key_present",
    "provider_slug",
    "model_pattern",
    "build_ephemeral_agent_dir",
    "agent_dir_env_value",
    "cleanup",
    "live_probe",
]
