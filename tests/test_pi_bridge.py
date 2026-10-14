"""Tests for the Pi tool bridge (repoquill/pi/bridge.py + extension.ts).

Covers the wire envelope, defense-in-depth path policy (including symlink
traversal), the run_example opt-in gate, response size caps, timeout
handling, and — when the pinned Pi binary is available — that the real
Pi runtime loads ``extension.ts`` cleanly in ``--mode rpc`` without a
model (get_state smoke test).
"""

from __future__ import annotations

import json
import os
import select
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path

import pytest

from repoquill.agents.contracts import ToolResult
from repoquill.agents.tools import RepoQuillTools
from repoquill.pi import contracts as pi_contracts
from repoquill.pi.bridge import PiBridgeServer

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_MINIUTIL = REPO_ROOT / "fixtures" / "miniutil"
EXTENSION_TS = REPO_ROOT / "repoquill" / "pi" / "extension.ts"
SLUG = "getting-started"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
class BridgeClient:
    """Minimal line-oriented envelope client for the bridge socket."""

    def __init__(self, socket_path: str):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(socket_path)
        self.buf = b""

    def _read_line(self) -> bytes:
        while b"\n" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("bridge closed the connection")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return line

    def call(self, tool: str, args=None, rid: str = "t1") -> dict:
        env = {"v": 1, "id": rid, "tool": tool, "args": args or {}}
        self.sock.sendall(json.dumps(env).encode() + b"\n")
        return json.loads(self._read_line().decode())

    def raw(self, data: bytes) -> dict:
        self.sock.sendall(data)
        return json.loads(self._read_line().decode())

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _copy_fixture(tmp_path: Path) -> Path:
    dest = tmp_path / "repo"
    shutil.copytree(
        FIXTURE_MINIUTIL, dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return dest


def _make_tools(repo_root: Path, staging: Path,
                execute_examples: bool = False) -> RepoQuillTools:
    from repoquill.agents.contracts import ToolContext

    return RepoQuillTools(ToolContext(
        repo_root=str(repo_root),
        pkg_path=str(repo_root / "miniutil"),
        docs_dir=str(staging),
        execute_examples=execute_examples,
        example_timeout=30.0,
    ))


def _start_bridge(tmp_path: Path, repo_root: Path, *,
                  execute_examples: bool = False, **kw) -> PiBridgeServer:
    staging = tmp_path / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    tools = _make_tools(repo_root, staging, execute_examples)
    return PiBridgeServer(
        tools,
        source_root=str(repo_root),
        staging_docs_dir=str(staging),
        slug=SLUG,
        allow_example_exec=execute_examples,
        socket_dir=str(tmp_path / "sock"),
        **kw,
    )


@pytest.fixture
def repo(tmp_path):
    return _copy_fixture(tmp_path)


@pytest.fixture
def bridge(tmp_path, repo):
    server = _start_bridge(tmp_path, repo)
    server.start()
    yield server
    server.stop()


@pytest.fixture
def bridge_exec(tmp_path, repo):
    server = _start_bridge(tmp_path, repo, execute_examples=True)
    server.start()
    yield server
    server.stop()


# --------------------------------------------------------------------------- #
# Envelope round-trips
# --------------------------------------------------------------------------- #
def test_list_files_roundtrip(bridge):
    with BridgeClient(bridge.socket_path) as client:
        resp = client.call("list_files")
    assert resp["v"] == 1 and resp["id"] == "t1" and resp["ok"] is True
    files = resp["data"]["files"]
    assert "miniutil/textkit.py" in files
    assert resp["data"]["count"] == len(files)


def test_read_file_roundtrip(bridge):
    with BridgeClient(bridge.socket_path) as client:
        resp = client.call("read_file",
                           {"path": "miniutil/textkit.py"}, rid="r2")
    assert resp["id"] == "r2" and resp["ok"] is True
    assert "def slugify" in resp["data"]["content"]
    assert resp["data"]["path"] == "miniutil/textkit.py"


def test_search_code_roundtrip(bridge):
    with BridgeClient(bridge.socket_path) as client:
        resp = client.call("search_code", {"pattern": "slugify"})
    assert resp["ok"] is True
    assert resp["data"]["count"] >= 1
    assert any("textkit.py" in r for r in resp["data"]["results"])


def test_write_doc_correct_slug(bridge, tmp_path):
    with BridgeClient(bridge.socket_path) as client:
        resp = client.call("write_doc",
                           {"slug": SLUG, "content": "# Hi\n"})
    assert resp["ok"] is True, resp
    written = tmp_path / "staging" / f"{SLUG}.md"
    assert written.read_text(encoding="utf-8") == "# Hi\n"
    # `.md` suffix on the slug is normalized to the same target page.
    with BridgeClient(bridge.socket_path) as client:
        resp = client.call("write_doc",
                           {"slug": f"{SLUG}.md", "content": "v2"})
    assert resp["ok"] is True
    assert written.read_text(encoding="utf-8") == "v2"


# --------------------------------------------------------------------------- #
# write_doc policy
# --------------------------------------------------------------------------- #
def test_write_doc_other_slug_refused(bridge):
    with BridgeClient(bridge.socket_path) as client:
        resp = client.call("write_doc", {"slug": "other-page",
                                         "content": "x"})
    assert resp["ok"] is False
    assert "task" in resp["error"] or "slug" in resp["error"].lower()


def test_write_doc_outside_staging_refused(bridge, tmp_path):
    with BridgeClient(bridge.socket_path) as client:
        for bad in ("../evil", "../../etc/cron.d/x", "a/b", ".."):
            resp = client.call("write_doc", {"slug": bad, "content": "x"})
            assert resp["ok"] is False, (bad, resp)
    assert not (tmp_path / "evil.md").exists()
    assert not (tmp_path.parent / "etc").exists()


# --------------------------------------------------------------------------- #
# Read path escapes (defense in depth, incl. symlinks)
# --------------------------------------------------------------------------- #
def test_read_path_escape_refused(bridge):
    with BridgeClient(bridge.socket_path) as client:
        for bad in ("../outside.py", "/etc/passwd", "~/secret.txt",
                    "miniutil/../../outside.py"):
            resp = client.call("read_file", {"path": bad})
            assert resp["ok"] is False, (bad, resp)
            assert "error" in resp


def test_read_symlink_escape_refused(bridge, tmp_path):
    secret = tmp_path / "secret_outside.txt"
    secret.write_text("TOP SECRET\n", encoding="utf-8")
    repo = Path(bridge._repo_root)  # the copied fixture
    (repo / "leak.py").symlink_to(secret)
    (repo / "leakdir").symlink_to(tmp_path)

    with BridgeClient(bridge.socket_path) as client:
        assert client.call("read_file",
                           {"path": "leak.py"})["ok"] is False
        assert client.call("read_file",
                           {"path": "leakdir/secret_outside.txt"})[
            "ok"] is False
        assert client.call("list_files", {"path": "leakdir"})[
            "ok"] is False
        # non-escaping paths keep working
        assert client.call("read_file",
                           {"path": "miniutil/textkit.py"})["ok"] is True


# --------------------------------------------------------------------------- #
# run_example gate
# --------------------------------------------------------------------------- #
def test_run_example_disabled_refused(bridge):
    with BridgeClient(bridge.socket_path) as client:
        resp = client.call("run_example", {"code": "print(1)"})
    assert resp["ok"] is False
    assert resp["error"] == "example execution disabled"


def test_run_example_non_string_code_refused(bridge_exec):
    with BridgeClient(bridge_exec.socket_path) as client:
        resp = client.call("run_example", {"code": [1, 2]})
    assert resp["ok"] is False


def test_run_example_enabled_runs(bridge_exec):
    code = (
        "from miniutil.textkit import slugify\n"
        "print(slugify('Hello, World!'))\n"
    )
    with BridgeClient(bridge_exec.socket_path) as client:
        resp = client.call("run_example", {"code": code})
    assert resp["ok"] is True, resp
    assert resp["data"]["ok"] is True
    assert "hello-world" in resp["data"]["stdout"]
    assert resp["data"]["timed_out"] is False


def test_run_example_imports_from_source_root(bridge_exec):
    """The child's path setup must let the example import the documented
    package from its package root (``from miniutil import slugify``)."""
    code = (
        "from miniutil import slugify\n"
        "print(slugify('Hello, World!'))\n"
    )
    with BridgeClient(bridge_exec.socket_path) as client:
        resp = client.call("run_example", {"code": code})
    assert resp["ok"] is True, resp
    assert resp["data"]["ok"] is True
    assert resp["data"]["stdout"].strip() == "hello-world"


def test_run_example_pkg_discovery_without_tools(tmp_path, repo):
    """The scheduler builds the bridge with only source_root +
    staging_docs_dir (no tools, no explicit pkg_path). Package imports in
    run_example must still work via single-package discovery."""
    staging = tmp_path / "staging"
    staging.mkdir()
    server = PiBridgeServer(
        source_root=str(repo), staging_docs_dir=str(staging),
        slug=SLUG, allow_example_exec=True,
        socket_dir=str(tmp_path / "sock-disc"))
    server.start()
    try:
        with BridgeClient(server.socket_path) as client:
            resp = client.call(
                "run_example",
                {"code": ("from miniutil import slugify\n"
                          "print(slugify('Hello, World!'))\n")})
    finally:
        server.stop()
    assert resp["ok"] is True, resp
    assert resp["data"]["ok"] is True, resp
    assert resp["data"]["stdout"].strip() == "hello-world"


def test_run_example_env_stripped(bridge_exec, monkeypatch):
    """The child env is an allowlist: no parent credentials may leak."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-never-leak")
    monkeypatch.setenv("REPOQUILL_LIVE_KEY", "sk-test-never-leak-2")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test-never-leak")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp-test-never-leak")
    code = "import os\nprint(sorted(os.environ))\n"
    with BridgeClient(bridge_exec.socket_path) as client:
        resp = client.call("run_example", {"code": code})
    assert resp["ok"] is True, resp
    child_keys = eval(resp["data"]["stdout"].strip())  # safe: plain str list
    for secret in ("OPENAI_API_KEY", "REPOQUILL_LIVE_KEY",
                   "ANTHROPIC_API_KEY", "GITHUB_TOKEN"):
        assert secret not in child_keys, (secret, child_keys)
    # Allowlist, not denylist: only PATH/HOME/PYTHONPATH survive.
    # (LC_CTYPE may be ADDED by the child interpreter's own locale init;
    # it is not inherited from the parent.)
    assert set(child_keys) - {"LC_CTYPE"} <= \
        {"PATH", "HOME", "PYTHONPATH"}, child_keys


def test_run_example_timeout_kills_process_tree(bridge_exec):
    """A hanging example — including processes IT spawns — must be
    hard-killed when the wall-clock limit is hit."""
    code = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen(\n"
        "    [sys.executable, '-c', 'import time; time.sleep(300)'])\n"
        "print('child-pid', child.pid)\n"
        "sys.stdout.flush()\n"
        "time.sleep(30)\n"
    )
    with BridgeClient(bridge_exec.socket_path) as client:
        start = time.monotonic()
        resp = client.call("run_example", {"code": code, "timeout": 2})
        elapsed = time.monotonic() - start
    assert resp["ok"] is True, resp  # the bridge answered
    data = resp["data"]
    assert data["ok"] is False
    assert data["timed_out"] is True
    assert data["returncode"] is None
    assert "wall-clock" in data["stderr"]
    assert elapsed < 15.0, f"timeout kill took too long: {elapsed:.1f}s"
    # The example's own child (same process group) must be dead too.
    child_pid = int(data["stdout"].strip().split()[-1])
    deadline = time.monotonic() + 10.0
    while True:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            return  # gone
        if time.monotonic() >= deadline:
            os.kill(child_pid, signal.SIGKILL)  # cleanup, then fail
            pytest.fail(f"child pid {child_pid} survived the timeout kill")
        time.sleep(0.2)


def test_run_example_output_capped(bridge_exec):
    """stdout/stderr are tail-capped (4000 chars) and the whole envelope
    stays under the bridge size cap."""
    code = (
        "import sys\n"
        "sys.stdout.write('A' * 10000)\n"
        "sys.stderr.write('B' * 10000)\n"
    )
    with BridgeClient(bridge_exec.socket_path) as client:
        resp = client.call("run_example", {"code": code})
    assert resp["ok"] is True, resp
    data = resp["data"]
    assert data["ok"] is True
    assert data["returncode"] == 0
    assert data["stdout"] == "A" * 4000
    assert data["stderr"] == "B" * 4000
    assert len(json.dumps(resp).encode()) <= 256 * 1024


# --------------------------------------------------------------------------- #
# Envelope protocol errors
# --------------------------------------------------------------------------- #
def test_malformed_envelope(bridge):
    with BridgeClient(bridge.socket_path) as client:
        assert client.raw(b"not json at all\n")["ok"] is False
        assert client.raw(b"[1, 2, 3]\n")["ok"] is False
        bad_version = json.dumps(
            {"v": 2, "id": "x", "tool": "list_files", "args": {}}
        ).encode() + b"\n"
        resp = client.raw(bad_version)
        assert resp["ok"] is False
        assert "version" in resp["error"]
        no_tool = json.dumps({"v": 1, "id": "y", "args": {}}).encode() + b"\n"
        assert client.raw(no_tool)["ok"] is False


def test_unknown_tool_refused(bridge):
    with BridgeClient(bridge.socket_path) as client:
        for tool in ("bash", "list_docs", "read_doc", "apply_patch"):
            resp = client.call(tool, {"x": 1})
            assert resp["ok"] is False, tool
            assert "unknown tool" in resp["error"]


# --------------------------------------------------------------------------- #
# Bounds: size cap + timeout
# --------------------------------------------------------------------------- #
class _FakeTools:
    """ToolRegistry-shaped stand-in for bound-specific tests."""

    def __init__(self, repo_root: str, data=None, sleep_s: float = 0.0):
        self.ctx = type("C", (), {"repo_root": repo_root,
                                  "docs_dir": repo_root})()
        self._data = data or {}
        self._sleep_s = sleep_s
        self.calls: list = []

    def schemas(self):
        return []

    def names(self):
        return list(self._data)

    def execute(self, name, arguments):
        self.calls.append(name)
        if name == "search_code" and self._sleep_s:
            time.sleep(self._sleep_s)
        if name in self._data:
            return ToolResult(name, True, self._data[name])
        return ToolResult(name, False, None, f"unknown tool: {name!r}")


def test_oversized_response_truncated(bridge, tmp_path, repo):
    big = "x" * (400 * 1024)
    fake = _FakeTools(str(repo), {"read_file": {"content": big}})
    server = PiBridgeServer(
        fake, source_root=str(repo),
        staging_docs_dir=str(tmp_path / "staging2"), slug=SLUG,
        socket_dir=str(tmp_path / "sock-big"))
    server.start()
    try:
        with BridgeClient(server.socket_path) as client:
            raw = json.dumps({"v": 1, "id": "b1", "tool": "read_file",
                              "args": {"path": "miniutil/textkit.py"}})
            client.sock.sendall(raw.encode() + b"\n")
            line = client._read_line()
    finally:
        server.stop()
    assert len(line) <= 256 * 1024 + 16
    resp = json.loads(line)
    assert resp["ok"] is True
    assert resp["data"]["_truncated"] is True
    assert len(resp["data"]["content"]) < len(big)


def test_request_timeout_and_recovery(tmp_path, repo):
    slow = _FakeTools(str(repo), {"search_code": {"results": []},
                                  "list_files": {"files": ["a.py"],
                                                 "count": 1,
                                                 "truncated": False}},
                      sleep_s=2.5)
    server = PiBridgeServer(
        slow, source_root=str(repo),
        staging_docs_dir=str(tmp_path / "staging3"), slug=SLUG,
        socket_dir=str(tmp_path / "sock-slow"), request_timeout_s=0.5)
    server.start()
    try:
        with BridgeClient(server.socket_path) as client:
            start = time.monotonic()
            resp = client.call("search_code", {"pattern": "x"})
            elapsed = time.monotonic() - start
            assert resp["ok"] is False
            assert "timed out" in resp["error"]
            assert elapsed < 2.0  # clean failure, not a hang
            # The straggler must finish before the next tool starts; the
            # bridge must still answer afterwards.
            resp2 = client.call("list_files")
            assert resp2["ok"] is True
            assert resp2["data"]["files"] == ["a.py"]
            assert slow.calls == ["search_code", "list_files"]
    finally:
        server.stop()


# --------------------------------------------------------------------------- #
# Real Pi binary: extension must load cleanly (no model required)
# --------------------------------------------------------------------------- #
def _find_pi_bin():
    candidates = [os.environ.get("REPOQUILL_PI_BIN", ""),
                  os.path.join(pi_contracts.DEFAULT_PI_CACHE_DIR,
                               "node_modules", ".bin", "pi")]
    for cand in candidates:
        if cand and os.access(cand, os.X_OK):
            return cand
    return None


_PI_BIN = _find_pi_bin()


@pytest.mark.skipif(_PI_BIN is None,
                    reason="pinned pi binary not installed locally")
def test_real_pi_loads_extension_and_get_state(tmp_path):
    env = dict(os.environ, PI_OFFLINE="1", PI_SKIP_VERSION_CHECK="1")
    cmd = [
        _PI_BIN,
        "--mode", "rpc",
        "--no-session",
        "--no-builtin-tools",
        "--no-extensions",
        "--extension", str(EXTENSION_TS),
        "--no-mcp",
        "--no-skills",
        "--no-prompt-templates",
        "--no-context-files",
        "--no-approve",
        "--offline",
    ]
    proc = subprocess.Popen(
        cmd, cwd=str(tmp_path), env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(b'{"id":"s1","type":"get_state"}\n')
    proc.stdin.flush()

    deadline = time.monotonic() + 90.0
    response = None
    lines = []
    try:
        while time.monotonic() < deadline:
            rlist, _, _ = select.select([proc.stdout], [], [], 1.0)
            if rlist:
                line = proc.stdout.readline()
                if not line:
                    break
                lines.append(line)
                if b"extension_error" in line:
                    break
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if (msg.get("type") == "response"
                        and msg.get("command") == "get_state"):
                    response = msg
                    break
            elif proc.poll() is not None:
                # drain whatever is left
                rest = proc.stdout.read()
                lines.extend(rest.splitlines())
                break
    finally:
        if proc.poll() is None:
            try:
                proc.stdin.close()
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    assert response is not None, f"no get_state response: {lines!r}"
    assert response.get("success") is True, response
    assert not any(b"extension_error" in ln for ln in lines)
    assert proc.returncode == 0, (
        proc.stderr.read().decode(errors="replace")[:2000])

# --------------------------------------------------------------------------- #
# Exact-repeat (dedupe) handling
# --------------------------------------------------------------------------- #
def test_identical_reread_is_answered_with_memo(bridge):
    """The measured failure mode: proxy models re-issuing the SAME
    read_file/search_code 10-190x and burning the tool budget. The
    bridge must answer exact repeats with a short deterministic memo
    (no information loss: the payload is already in the model's
    conversation), and real calls must still return full data."""
    args = {"path": "miniutil/textkit.py"}
    with BridgeClient(bridge.socket_path) as client:
        first = client.call("read_file", args, rid="a1")
        second = client.call("read_file", args, rid="a2")
        third = client.call("read_file", args, rid="a3")
        varied = client.call("read_file", dict(args, start_line=2),
                             rid="a4")
        # search_code repeats are deduped too.
        s1 = client.call("search_code", {"pattern": "split"}, rid="a5")
        s2 = client.call("search_code", {"pattern": "split"}, rid="a6")
    assert first["ok"] and not first["data"].get("deduplicated")
    assert "content" in first["data"]
    assert second["ok"] and second["data"]["deduplicated"] is True
    assert "already made this exact tool call" in second["data"]["note"]
    # The memo is short compared with the full read payload.
    assert len(json.dumps(second["data"])) < len(json.dumps(first["data"]))
    # Repeat counter increments; the head points at the original result.
    assert "2 time(s)" in third["data"]["note"]
    # The head is a JSON dump of the original payload, so it names the
    # file (quotes escaped).
    assert "miniutil/textkit.py" in second["data"]["previous_result_head"]
    # Different args are a different call: full data again.
    assert varied["ok"] and "content" in varied["data"]
    assert not varied["data"].get("deduplicated")
    # search_code: first real, second memo.
    assert s1["ok"] and not s1["data"].get("deduplicated")
    assert s2["data"]["deduplicated"] is True


def test_write_doc_is_never_deduped(bridge, repo):
    """Rewriting a draft page is legitimate work: write_doc calls must
    always execute, however many times."""
    payload = {"slug": "getting-started", "content": "# Draft v1\n"}
    with BridgeClient(bridge.socket_path) as client:
        r1 = client.call("write_doc", payload, rid="w1")
        r2 = client.call("write_doc", payload, rid="w2")
    assert r1["ok"] and r2["ok"]
    assert not r1["data"].get("deduplicated")
    assert not r2["data"].get("deduplicated")
    staged = bridge._staging + "/getting-started.md"
    assert os.path.exists(staged)


def test_repeated_identical_call_becomes_error(bridge):
    """After 5 identical calls the bridge stops answering with a memo
    (the model keeps orbiting) and returns an ERROR telling it to stop
    and write. The 2nd-4th calls still get the short memo."""
    args = {"path": "miniutil/textkit.py"}
    with BridgeClient(bridge.socket_path) as client:
        r1 = client.call("read_file", args, rid="r1")
        r2 = client.call("read_file", args, rid="r2")
        r3 = client.call("read_file", args, rid="r3")
        r4 = client.call("read_file", args, rid="r4")
        r5 = client.call("read_file", args, rid="r5")
    assert r1["ok"] and not r1["data"].get("deduplicated")
    for r in (r2, r3, r4):
        assert r["ok"] and r["data"]["deduplicated"] is True
    assert r5["ok"] is False
    assert "STOP exploring" in r5["error"]
    assert "write_doc" in r5["error"]
