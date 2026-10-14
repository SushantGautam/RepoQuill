"""Discovery, provisioning and diagnostics for the pinned Pi coding agent.

RepoQuill expects the ``pi`` binary at a pinned, auditable version
(``PI_PINNED_VERSION`` from :mod:`repoquill.pi.contracts`). This module
provides:

* :func:`find_pi` / :func:`find_node` — passive discovery (never installs).
* :func:`ensure_pi` — discovery plus an *opt-in* pinned install into the
  RepoQuill app cache (``DEFAULT_PI_CACHE_DIR``). It never installs globally
  and never installs ``@latest``; the exact npm command is a constant built
  from the pinned package spec, so it is reviewable.
* :func:`doctor` — a structured readiness report for ``repoquill doctor``.

Security notes
--------------
* Every subprocess call uses an argument list (no shell), an explicit
  timeout, and captured (trimmed) output; nothing from a candidate binary's
  output is ever executed.
* No secrets are ever printed: only environment variable *names* appear in
  messages.
* The ``--no-llm`` code path never touches this module, so a Python-only
  user needs neither Node nor Pi.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from repoquill.pi.contracts import (
    DEFAULT_PI_CACHE_DIR,
    PI_BIN_ENV,
    PI_PACKAGE,
    PI_PINNED_VERSION,
    PiNotInstalledError,
)

#: Default deadline for the managed ``npm install`` step.
NPM_INSTALL_TIMEOUT = 600.0

__all__ = [
    "NPM_INSTALL_TIMEOUT",
    "PiInstallation",
    "doctor",
    "ensure_pi",
    "find_node",
    "find_pi",
]


@dataclass
class PiInstallation:
    """A discovered ``pi`` binary.

    ``source`` is one of ``"env"`` (``REPOQUILL_PI_BIN``), ``"path"`` (found
    on PATH) or ``"cache"`` (the RepoQuill app-cache install). ``cache_dir``
    is only set for the cache source.

    Pin handling: :func:`find_pi` prefers a candidate whose reported version
    equals ``PI_PINNED_VERSION``. If *no* candidate matches the pin but at
    least one works, the first working candidate is still returned (callers
    decide whether to accept it); the mismatch is recorded by the returned
    ``version`` — callers detect it with ``installation.version !=
    PI_PINNED_VERSION`` and report it (see :func:`ensure_pi`, :func:`doctor`).
    """

    binary: str
    version: str
    source: str
    cache_dir: Optional[str] = None


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #

def _cache_bin_path() -> str:
    return os.path.join(DEFAULT_PI_CACHE_DIR, "node_modules", ".bin", "pi")


def _install_command() -> str:
    """The exact pinned install command (auditable, one line)."""
    return (
        f"mkdir -p {DEFAULT_PI_CACHE_DIR} && cd {DEFAULT_PI_CACHE_DIR} && "
        f"npm install --no-audit --no-fund {PI_PACKAGE}@{PI_PINNED_VERSION}"
    )


def _env_override_help() -> str:
    return f"export {PI_BIN_ENV}=/path/to/pi"


def _not_installed_message() -> str:
    return (
        f"Pi coding agent {PI_PACKAGE}@{PI_PINNED_VERSION} was not found "
        f"(checked ${PI_BIN_ENV}, PATH, {_cache_bin_path()}).\n"
        "To install the pinned version into the RepoQuill app cache:\n"
        f"  {_install_command()}\n"
        "Or point at an existing pi binary:\n"
        f"  {_env_override_help()}"
    )


def _probe_version(binary: str, *, timeout: float) -> Optional[str]:
    """Run ``<binary> --version``; return the first token of its output.

    Returns ``None`` when the binary is missing, non-executable, exits
    non-zero, times out, or prints nothing recognizable. Never raises.
    """
    try:
        proc = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    text = " ".join((proc.stdout or "").split())
    if not text:
        text = " ".join((proc.stderr or "").split())
    if not text:
        return None
    return text.split()[0]


def _check_model(cfg: Any) -> Tuple[Dict[str, Any], List[str]]:
    """Validate a duck-typed llm config (provider/model/base_url/api_key_env)."""
    if cfg is None:
        return (
            {
                "ok": False,
                "base_url": None,
                "api_key_env": None,
                "api_key_present": False,
                "note": (
                    "No model configuration supplied; run `repoquill doctor` "
                    "from a project root (with repoquill.yml) to check the "
                    "model endpoint."
                ),
            },
            [
                "No LLM config found — run `repoquill doctor` from the "
                "project root (where repoquill.yml sets llm.base_url + "
                "llm.api_key_env), or pass --config PATH."
            ],
        )
    base_url = getattr(cfg, "base_url", None) or None
    api_key_env = getattr(cfg, "api_key_env", None) or None
    key_present = bool(api_key_env) and bool(os.environ.get(api_key_env))
    ok = bool(base_url) and bool(api_key_env) and key_present

    recommendations: List[str] = []
    if not base_url:
        note = (
            "llm.base_url is not set — point it at your OpenAI-compatible "
            "endpoint in repoquill.yml."
        )
        recommendations.append(
            "Set llm.base_url (and llm.model) in repoquill.yml to your "
            "OpenAI-compatible endpoint."
        )
    elif not api_key_env:
        note = (
            "llm.api_key_env is not set — name the environment variable "
            "that holds the API key."
        )
        recommendations.append(
            "Set llm.api_key_env in repoquill.yml to the environment "
            "variable holding your API key."
        )
    elif not key_present:
        note = f"Environment variable {api_key_env} is not set or is empty."
        recommendations.append(f"export {api_key_env}=<your-api-key>")
    else:
        note = "Model configuration complete."
    return (
        {
            "ok": ok,
            "base_url": base_url,
            "api_key_env": api_key_env,
            "api_key_present": key_present,
            "note": note,
        },
        recommendations,
    )


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def find_pi(*, timeout: float = 10.0) -> Optional[PiInstallation]:
    """Locate the ``pi`` binary; never installs, never raises.

    Discovery order: (1) ``REPOQUILL_PI_BIN`` if set (source ``"env"``),
    (2) ``pi`` on PATH (source ``"path"``), (3) the app-cache install
    ``DEFAULT_PI_CACHE_DIR/node_modules/.bin/pi`` (source ``"cache"``).
    Each candidate is verified by running ``pi --version`` (argument list,
    timeout, captured output).

    A candidate whose version equals ``PI_PINNED_VERSION`` wins immediately.
    If none matches the pin, the *first* working candidate is returned so
    callers can decide and report the mismatch (see
    :class:`PiInstallation`). Returns ``None`` when nothing works.
    """
    candidates: List[Tuple[str, str, Optional[str]]] = []
    env_bin = os.environ.get(PI_BIN_ENV, "").strip()
    if env_bin:
        candidates.append((env_bin, "env", None))
    path_bin = shutil.which("pi")
    if path_bin:
        candidates.append((path_bin, "path", None))
    candidates.append((_cache_bin_path(), "cache", DEFAULT_PI_CACHE_DIR))

    seen = set()
    fallback: Optional[PiInstallation] = None
    for binary, source, cache_dir in candidates:
        key = os.path.abspath(binary)
        if key in seen:
            continue
        seen.add(key)
        version = _probe_version(binary, timeout=timeout)
        if version is None:
            continue
        installation = PiInstallation(
            binary=binary,
            version=version,
            source=source,
            cache_dir=cache_dir,
        )
        if version == PI_PINNED_VERSION:
            return installation
        if fallback is None:
            fallback = installation
    return fallback


def find_node(*, timeout: float = 10.0) -> Optional[str]:
    """Return ``node --version`` (e.g. ``v24.21.0``) or ``None`` if absent."""
    node = shutil.which("node")
    if node is None:
        return None
    return _probe_version(node, timeout=timeout)


def ensure_pi(
    install: bool = False,
    *,
    timeout: float = NPM_INSTALL_TIMEOUT,
) -> PiInstallation:
    """Return a working ``pi`` installation, optionally provisioning one.

    With ``install=False`` (default) this is pure discovery and raises
    :class:`PiNotInstalledError` with both self-service options when Pi is
    missing. With ``install=True`` it requires Node, creates the app-cache
    dir if needed, writes a minimal ``package.json`` when absent, then runs
    the exact pinned command::

        npm install --no-audit --no-fund @earendil-works/pi-coding-agent@1.2.0

    in the cache dir (never global, never ``@latest``) and re-discovers.
    Any failure raises :class:`PiNotInstalledError` naming the failing step
    and the remediation.
    """
    found = find_pi()
    if found is not None:
        return found

    if not install:
        raise PiNotInstalledError(_not_installed_message())

    if find_node() is None:
        raise PiNotInstalledError(
            "Node.js is required to install the Pi coding agent, but `node` "
            "was not found on a PATH where `node --version` succeeds. "
            "Install Node.js from https://nodejs.org/ (or your OS package "
            "manager), then re-run. Without Node, Pi cannot be installed."
        )

    cache_dir = DEFAULT_PI_CACHE_DIR
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except OSError as exc:
        raise PiNotInstalledError(
            f"Failed at step 'create cache dir {cache_dir}': {exc}. "
            f"Or point at an existing binary: {_env_override_help()}"
        )

    pkg_json = os.path.join(cache_dir, "package.json")
    if not os.path.exists(pkg_json):
        try:
            with open(pkg_json, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "name": "repoquill-pi-cache",
                        "private": True,
                        "version": "0.0.0",
                    },
                    fh,
                    indent=2,
                )
                fh.write("\n")
        except OSError as exc:
            raise PiNotInstalledError(
                f"Failed at step 'write {pkg_json}': {exc}. "
                f"Or point at an existing binary: {_env_override_help()}"
            )

    npm = shutil.which("npm")
    if npm is None:
        raise PiNotInstalledError(
            "Node.js was found but `npm` is not on PATH. Reinstall Node.js "
            f"from https://nodejs.org/ (npm ships with it), or use: "
            f"{_env_override_help()}"
        )

    spec = f"{PI_PACKAGE}@{PI_PINNED_VERSION}"
    argv = [npm, "install", "--no-audit", "--no-fund", spec]
    try:
        proc = subprocess.run(
            argv,
            cwd=cache_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise PiNotInstalledError(
            f"Failed at step 'npm install {spec}' in {cache_dir}: timed out "
            f"after {timeout:.0f}s. Retry with a working network, or "
            f"install manually: {_install_command()}"
        )
    except OSError as exc:
        raise PiNotInstalledError(
            f"Failed at step 'npm install {spec}' in {cache_dir}: {exc}. "
            f"Install manually: {_install_command()}"
        )

    if proc.returncode != 0:
        err = " ".join((proc.stderr or proc.stdout or "").split())[:500]
        raise PiNotInstalledError(
            f"Failed at step 'npm install {spec}' in {cache_dir} "
            f"(exit {proc.returncode}): {err or 'no error output'}. "
            f"Retry, or install manually: {_install_command()}"
        )

    found = find_pi()
    if found is None:
        raise PiNotInstalledError(
            "npm install reported success, but the pi binary was not found "
            f"at {_cache_bin_path()}. Inspect {cache_dir} for a partial "
            f"install, or point at an existing binary: {_env_override_help()}"
        )
    return found


def doctor(*, check_model_cfg: Any = None) -> Dict[str, Any]:
    """Structured readiness report (for ``repoquill doctor``).

    ``check_model_cfg`` is an optional duck-typed llm config exposing
    ``provider``/``model``/``base_url``/``api_key_env``. ``ready`` is True
    only when Node works, a pi binary works, its version matches the pin,
    AND the model is reachable (base_url + api_key_env set and the key
    present); every shortfall produces a concrete, command-level
    recommendation.
    """
    node_version = find_node()
    node_ok = node_version is not None

    installation = find_pi()
    pi_ok = installation is not None
    version_matches = (
        installation.version == PI_PINNED_VERSION if installation else None
    )

    model, model_recs = _check_model(check_model_cfg)
    recommendations = list(model_recs)
    if not node_ok:
        recommendations.append(
            "Install Node.js (https://nodejs.org/ or your OS package "
            "manager) so `node --version` succeeds; Node is required to "
            "run or install Pi."
        )
    if not pi_ok:
        recommendations.append(
            f"Install the pinned Pi into the app cache: {_install_command()}"
        )
        recommendations.append(
            f"… or point at an existing binary: {_env_override_help()}"
        )
    elif version_matches is False:
        recommendations.append(
            f"pi {installation.version} found, but the pinned version is "
            f"{PI_PINNED_VERSION}. Reinstall it: {_install_command()} — or "
            f"point at a {PI_PINNED_VERSION} binary: {_env_override_help()}"
        )

    return {
        "node": {"ok": node_ok, "version": node_version},
        "pi": {
            "ok": pi_ok,
            "binary": installation.binary if installation else None,
            "version": installation.version if installation else None,
            "pinned": PI_PINNED_VERSION,
            "version_matches": version_matches,
            "source": installation.source if installation else None,
        },
        "cache_dir": DEFAULT_PI_CACHE_DIR,
        "cache_install_present": os.path.exists(_cache_bin_path()),
        "model": model,
        "ready": bool(node_ok and pi_ok and version_matches
                      and model.get("ok", False)),
        "recommendations": recommendations,
    }
