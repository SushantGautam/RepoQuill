"""Tests for pinned Pi discovery / provisioning / doctor (pi.bootstrap).

Deterministic: fake ``pi``/``node`` shell executables in ``tmp_path``, PATH
manipulated via monkeypatch, and ``subprocess.run`` mocked wherever npm or
state-changing binaries would be involved. No real npm, no network, no
global installs.
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

import repoquill.pi.bootstrap as bs
from repoquill.pi.bootstrap import (
    PiInstallation,
    doctor,
    ensure_pi,
    find_node,
    find_pi,
)
from repoquill.pi.contracts import (
    PI_BIN_ENV,
    PI_PACKAGE,
    PI_PINNED_VERSION,
    PiNotInstalledError,
)

PIN = PI_PINNED_VERSION  # "1.2.0"
SPEC = f"{PI_PACKAGE}@{PIN}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bin(directory, name, version, exit_code=0):
    """Create an executable shell script that prints ``version`` to
    ``--version`` (exit code configurable)."""
    path = os.path.join(str(directory), name)
    if version is None:
        body = f"#!/bin/sh\nexit {exit_code}\n"
    else:
        body = (
            "#!/bin/sh\n"
            f'if [ "$1" = "--version" ]; then echo {version}; fi\n'
            f"exit {exit_code}\n"
        )
    with open(path, "w") as fh:
        fh.write(body)
    os.chmod(path, 0o755)
    return path


def _empty_path_dir(tmp_path):
    d = tmp_path / "emptybin"
    d.mkdir()
    return str(d)


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    """No pi/node visible on PATH, no env override, cache redirected to a
    non-existent tmp dir."""
    monkeypatch.setenv("PATH", _empty_path_dir(tmp_path))
    monkeypatch.delenv(PI_BIN_ENV, raising=False)
    monkeypatch.setattr(bs, "DEFAULT_PI_CACHE_DIR", str(tmp_path / "nocache"))
    return tmp_path


class Cfg:
    """Duck-typed llm config."""

    def __init__(self, **kwargs):
        for key in ("provider", "model", "base_url", "api_key_env"):
            setattr(self, key, kwargs.get(key))


# ---------------------------------------------------------------------------
# find_pi
# ---------------------------------------------------------------------------

def test_find_pi_env_override_wins(tmp_path, monkeypatch):
    env_bin = _make_bin(tmp_path, "pi-env", PIN)
    monkeypatch.setenv(PI_BIN_ENV, env_bin)
    monkeypatch.setenv("PATH", _empty_path_dir(tmp_path))
    monkeypatch.setattr(bs, "DEFAULT_PI_CACHE_DIR", str(tmp_path / "nocache"))

    inst = find_pi()
    assert inst is not None
    assert inst.source == "env"
    assert inst.binary == env_bin
    assert inst.version == PIN
    assert inst.cache_dir is None


def test_find_pi_on_path(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _make_bin(bindir, "pi", PIN)
    monkeypatch.delenv(PI_BIN_ENV, raising=False)
    monkeypatch.setenv("PATH", str(bindir))
    monkeypatch.setattr(bs, "DEFAULT_PI_CACHE_DIR", str(tmp_path / "nocache"))

    inst = find_pi()
    assert inst is not None
    assert inst.source == "path"
    assert os.path.basename(inst.binary) == "pi"
    assert inst.version == PIN


def test_find_pi_cache_fallback(tmp_path, monkeypatch):
    cache = tmp_path / "pi-cache"
    (cache / "node_modules" / ".bin").mkdir(parents=True)
    _make_bin(cache / "node_modules" / ".bin", "pi", PIN)
    monkeypatch.delenv(PI_BIN_ENV, raising=False)
    monkeypatch.setenv("PATH", _empty_path_dir(tmp_path))
    monkeypatch.setattr(bs, "DEFAULT_PI_CACHE_DIR", str(cache))

    inst = find_pi()
    assert inst is not None
    assert inst.source == "cache"
    assert inst.version == PIN
    assert inst.cache_dir == str(cache)


def test_find_pi_prefers_pinned_version_over_earlier_candidates(
    tmp_path, monkeypatch
):
    """Env candidate reports a wrong version; PATH candidate is pinned →
    the pinned one wins."""
    env_bin = _make_bin(tmp_path, "pi-old", "0.9.0")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _make_bin(bindir, "pi", PIN)
    monkeypatch.setenv(PI_BIN_ENV, env_bin)
    monkeypatch.setenv("PATH", str(bindir))
    monkeypatch.setattr(bs, "DEFAULT_PI_CACHE_DIR", str(tmp_path / "nocache"))

    inst = find_pi()
    assert inst.source == "path"
    assert inst.version == PIN


def test_find_pi_returns_unpinned_candidate_when_no_pin_match(
    tmp_path, monkeypatch
):
    """No candidate matches the pin → the first working candidate is
    still returned (callers record/reject the mismatch)."""
    env_bin = _make_bin(tmp_path, "pi-old", "0.9.0")
    monkeypatch.setenv(PI_BIN_ENV, env_bin)
    monkeypatch.setenv("PATH", _empty_path_dir(tmp_path))
    monkeypatch.setattr(bs, "DEFAULT_PI_CACHE_DIR", str(tmp_path / "nocache"))

    inst = find_pi()
    assert inst is not None
    assert inst.source == "env"
    assert inst.version == "0.9.0"
    assert inst.version != PIN  # mismatch is recorded in .version


def test_find_pi_not_found_returns_none(isolated_env):
    assert find_pi() is None


def test_find_pi_broken_cache_binary_returns_none(tmp_path, monkeypatch):
    cache = tmp_path / "pi-cache"
    (cache / "node_modules" / ".bin").mkdir(parents=True)
    _make_bin(cache / "node_modules" / ".bin", "pi", None, exit_code=1)
    monkeypatch.delenv(PI_BIN_ENV, raising=False)
    monkeypatch.setenv("PATH", _empty_path_dir(tmp_path))
    monkeypatch.setattr(bs, "DEFAULT_PI_CACHE_DIR", str(cache))

    assert find_pi() is None


def test_find_pi_env_path_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv(PI_BIN_ENV, str(tmp_path / "does-not-exist"))
    monkeypatch.setenv("PATH", _empty_path_dir(tmp_path))
    monkeypatch.setattr(bs, "DEFAULT_PI_CACHE_DIR", str(tmp_path / "nocache"))

    assert find_pi() is None


# ---------------------------------------------------------------------------
# find_node
# ---------------------------------------------------------------------------

def test_find_node_reports_version(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _make_bin(bindir, "node", "v24.21.0")
    monkeypatch.setenv("PATH", str(bindir))

    assert find_node() == "v24.21.0"


def test_find_node_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", _empty_path_dir(tmp_path))

    assert find_node() is None


# ---------------------------------------------------------------------------
# ensure_pi
# ---------------------------------------------------------------------------

def test_ensure_pi_returns_existing(isolated_env, monkeypatch):
    bindir = isolated_env / "bin"
    bindir.mkdir()
    _make_bin(bindir, "pi", PIN)
    monkeypatch.setenv(PI_BIN_ENV, os.path.join(str(bindir), "pi"))

    inst = ensure_pi(install=False)
    assert isinstance(inst, PiInstallation)
    assert inst.version == PIN


def test_ensure_pi_missing_raises_with_both_options(isolated_env):
    with pytest.raises(PiNotInstalledError) as exc:
        ensure_pi(install=False)
    msg = str(exc.value)
    # (a) the exact pinned install command
    assert f"npm install --no-audit --no-fund {SPEC}" in msg
    assert "@latest" not in msg
    # (b) the env override
    assert f"export {PI_BIN_ENV}=/path/to/pi" in msg


def _install_fixture(monkeypatch, tmp_path):
    """PATH dir with fake node+npm, cache redirected; returns (cache, pi
    cache binary path). subprocess.run is NOT mocked here."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _make_bin(bindir, "node", "v24.21.0")
    npm = os.path.join(str(bindir), "npm")
    with open(npm, "w") as fh:
        fh.write("#!/bin/sh\nexit 0\n")
    os.chmod(npm, 0o755)
    monkeypatch.delenv(PI_BIN_ENV, raising=False)
    monkeypatch.setenv("PATH", str(bindir))
    cache = tmp_path / "pi-cache"
    monkeypatch.setattr(bs, "DEFAULT_PI_CACHE_DIR", str(cache))
    return cache


def test_ensure_pi_install_happy_path(monkeypatch, tmp_path):
    cache = _install_fixture(monkeypatch, tmp_path)
    cache_bin = str(cache / "node_modules" / ".bin" / "pi")
    state = {"installed": False}
    calls = []

    def fake_run(args, **kwargs):
        args = list(args)
        calls.append((args, kwargs))
        if "--version" in args:
            if os.path.basename(args[0]) == "node":
                return subprocess.CompletedProcess(args, 0, "v24.21.0\n", "")
            if state["installed"] and args[0] == cache_bin:
                return subprocess.CompletedProcess(args, 0, f"{PIN}\n", "")
            return subprocess.CompletedProcess(args, 1, "", "not installed\n")
        if "install" in args:
            state["installed"] = True
            return subprocess.CompletedProcess(
                args, 0, "added 1 package in 1s\n", ""
            )
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(bs.subprocess, "run", fake_run)

    inst = ensure_pi(install=True)

    # The exact pinned npm argv, in the cache dir, no @latest.
    installs = [c for c in calls if "install" in c[0]]
    assert len(installs) == 1
    argv, kwargs = installs[0]
    assert argv[1:] == ["install", "--no-audit", "--no-fund", SPEC]
    assert "@latest" not in " ".join(argv)
    assert kwargs.get("cwd") == str(cache)

    # Re-discovered the freshly installed cache binary.
    assert inst is not None
    assert inst.source == "cache"
    assert inst.version == PIN
    assert inst.binary == cache_bin
    assert inst.cache_dir == str(cache)

    # Minimal package.json was written into the cache dir.
    with open(os.path.join(str(cache), "package.json")) as fh:
        pkg = json.load(fh)
    assert pkg.get("private") is True


def test_ensure_pi_install_no_node_raises_with_hint(
    isolated_env, monkeypatch
):
    monkeypatch.setattr(
        bs.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "no\n"),
    )
    with pytest.raises(PiNotInstalledError) as exc:
        ensure_pi(install=True)
    msg = str(exc.value)
    assert "Node.js" in msg
    assert "node" in msg


def test_ensure_pi_install_npm_failure_names_step(
    isolated_env, monkeypatch
):
    bindir = isolated_env / "bin"
    bindir.mkdir()
    _make_bin(bindir, "node", "v24.21.0")
    npm = os.path.join(str(bindir), "npm")
    with open(npm, "w") as fh:
        fh.write("#!/bin/sh\nexit 0\n")
    os.chmod(npm, 0o755)
    monkeypatch.setenv("PATH", str(bindir))
    cache = isolated_env / "pi-cache"
    monkeypatch.setattr(bs, "DEFAULT_PI_CACHE_DIR", str(cache))

    def fake_run(args, **kwargs):
        args = list(args)
        if "--version" in args and os.path.basename(args[0]) == "node":
            return subprocess.CompletedProcess(args, 0, "v24.21.0\n", "")
        if "install" in args:
            return subprocess.CompletedProcess(
                args, 1, "", "npm ERR! network timeout\n"
            )
        return subprocess.CompletedProcess(args, 1, "", "")

    monkeypatch.setattr(bs.subprocess, "run", fake_run)

    with pytest.raises(PiNotInstalledError) as exc:
        ensure_pi(install=True)
    msg = str(exc.value)
    assert f"npm install {SPEC}" in msg
    assert str(cache) in msg
    assert "npm ERR! network timeout" in msg
    # Remediation is present and never suggests @latest.
    assert f"npm install --no-audit --no-fund {SPEC}" in msg
    assert "@latest" not in msg


def test_ensure_pi_install_success_but_binary_missing(
    isolated_env, monkeypatch
):
    """npm exits 0 but re-discovery finds nothing → still an error."""
    bindir = isolated_env / "bin"
    bindir.mkdir()
    _make_bin(bindir, "node", "v24.21.0")
    npm = os.path.join(str(bindir), "npm")
    with open(npm, "w") as fh:
        fh.write("#!/bin/sh\nexit 0\n")
    os.chmod(npm, 0o755)
    monkeypatch.setenv("PATH", str(bindir))
    cache = isolated_env / "pi-cache"
    monkeypatch.setattr(bs, "DEFAULT_PI_CACHE_DIR", str(cache))

    def fake_run(args, **kwargs):
        args = list(args)
        if "--version" in args and os.path.basename(args[0]) == "node":
            return subprocess.CompletedProcess(args, 0, "v24.21.0\n", "")
        if "install" in args:
            return subprocess.CompletedProcess(args, 0, "ok\n", "")
        return subprocess.CompletedProcess(args, 1, "", "")

    monkeypatch.setattr(bs.subprocess, "run", fake_run)

    with pytest.raises(PiNotInstalledError) as exc:
        ensure_pi(install=True)
    assert "pi binary was not found" in str(exc.value)


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------

def test_doctor_shape_when_pi_missing(isolated_env):
    doc = doctor()
    assert set(doc) == {
        "node", "pi", "cache_dir", "cache_install_present",
        "model", "ready", "recommendations",
    }
    assert set(doc["node"]) == {"ok", "version"}
    assert set(doc["pi"]) == {
        "ok", "binary", "version", "pinned", "version_matches", "source",
    }
    assert set(doc["model"]) == {
        "ok", "base_url", "api_key_env", "api_key_present", "note",
    }

    # With the isolated env, node and pi are both absent.
    assert doc["node"]["ok"] is False
    assert doc["node"]["version"] is None
    assert doc["pi"] == {
        "ok": False,
        "binary": None,
        "version": None,
        "pinned": PIN,
        "version_matches": None,
        "source": None,
    }
    assert doc["cache_dir"] == str(isolated_env / "nocache")
    assert doc["cache_install_present"] is False
    assert doc["model"]["ok"] is False
    assert doc["ready"] is False
    # Non-empty, concrete recommendations (both node and pi missing).
    assert len(doc["recommendations"]) >= 2
    joined = "\n".join(doc["recommendations"])
    assert f"npm install --no-audit --no-fund {SPEC}" in joined
    assert f"export {PI_BIN_ENV}=/path/to/pi" in joined
    assert "Node.js" in joined


def test_doctor_ready_with_pinned_pi(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _make_bin(bindir, "node", "v24.21.0")
    _make_bin(bindir, "pi", PIN)
    monkeypatch.delenv(PI_BIN_ENV, raising=False)
    monkeypatch.setenv("PATH", str(bindir))
    cache = tmp_path / "pi-cache"
    (cache / "node_modules" / ".bin").mkdir(parents=True)
    _make_bin(cache / "node_modules" / ".bin", "pi", PIN)
    monkeypatch.setattr(bs, "DEFAULT_PI_CACHE_DIR", str(cache))

    doc = doctor()
    assert doc["node"]["ok"] is True
    assert doc["node"]["version"] == "v24.21.0"
    assert doc["pi"]["ok"] is True
    assert doc["pi"]["version"] == PIN
    assert doc["pi"]["pinned"] == PIN
    assert doc["pi"]["version_matches"] is True
    assert doc["pi"]["source"] in ("path", "cache")
    assert doc["cache_install_present"] is True
    assert doc["ready"] is True
    # No node/pi/model failures → no runtime recommendations.
    assert doc["recommendations"] == []


def test_doctor_version_mismatch_not_ready(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _make_bin(bindir, "node", "v24.21.0")
    _make_bin(bindir, "pi", "0.9.0")
    monkeypatch.delenv(PI_BIN_ENV, raising=False)
    monkeypatch.setenv("PATH", str(bindir))
    monkeypatch.setattr(bs, "DEFAULT_PI_CACHE_DIR", str(tmp_path / "nocache"))

    doc = doctor()
    assert doc["pi"]["ok"] is True
    assert doc["pi"]["version_matches"] is False
    assert doc["ready"] is False
    joined = "\n".join(doc["recommendations"])
    assert PIN in joined
    assert SPEC in joined or f"{PI_BIN_ENV}" in joined


def test_doctor_model_cfg_missing_base_url(isolated_env):
    cfg = Cfg(provider="qwen", model="qwen3-max",
              base_url=None, api_key_env="FOO_API_KEY")
    doc = doctor(check_model_cfg=cfg)
    assert doc["model"]["ok"] is False
    assert doc["model"]["base_url"] is None
    assert "base_url" in doc["model"]["note"]
    assert any("llm.base_url" in r for r in doc["recommendations"])


def test_doctor_model_cfg_api_key_flip(isolated_env, monkeypatch):
    cfg = Cfg(provider="qwen", model="qwen3-max",
              base_url="https://api.example/v1", api_key_env="FOO_API_KEY")

    monkeypatch.delenv("FOO_API_KEY", raising=False)
    doc = doctor(check_model_cfg=cfg)
    assert doc["model"]["ok"] is False
    assert doc["model"]["api_key_present"] is False
    assert "FOO_API_KEY" in doc["model"]["note"]
    assert "export FOO_API_KEY" in "\n".join(doc["recommendations"])

    monkeypatch.setenv("FOO_API_KEY", "sk-test-secret")
    doc = doctor(check_model_cfg=cfg)
    assert doc["model"]["ok"] is True
    assert doc["model"]["api_key_present"] is True
    # The secret itself must never appear in the report.
    assert "sk-test-secret" not in json.dumps(doc)
