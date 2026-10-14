"""Pi quality tests: deterministic fake-process behavior + launch security.

These tests pin the *process/runtime boundary* of the embedded Pi docs
engine (M0 contracts in ``repoquill/pi/contracts.py``) against
standalone fake-Pi scripts in ``tests/pi_fakes/`` — real subprocesses
speaking the Pi 1.2.0 JSONL RPC protocol on stdio. They run fully
offline and deterministically (no LLM, no network).

Coverage:
* happy path: settled run, staged file, sanitized tool trace, usage,
  version capture, source-path tracking;
* model error: a failed message stream must never yield a completed/
  verified page;
* hang: run deadline -> PiRunTimeoutError, child reaped;
* crash: unexpected exit -> PiProcessError with stderr diagnostics;
* fail-closed / last-good: a failed Pi run leaves existing docs and
  plan state byte-identical (backend level and scheduler level);
* security: secrets never reach the trace, the full SAFE_LAUNCH_FLAGS
  set is pinned at the process level, and the real pinned binary shows
  no builtin bash/write/edit tools active;
* no-op semantics: unchanged pages cost zero Pi prompt spawns.

The fake ``write_doc`` side effect honors the same env knobs
(``REPOQUILL_FAKE_STAGED_DIR`` / ``REPOQUILL_FAKE_SLUG``) that
``contracts.build_runtime_env`` propagates into the child from the test
process — the canonical env path, no backend internals assumed.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest

from repoquill.pi import contracts

try:
    from repoquill.pi.rpc import PiRpcBackend
except ImportError:  # RPC workstream may not have landed yet
    PiRpcBackend = None

pytestmark = pytest.mark.skipif(
    PiRpcBackend is None,
    reason="repoquill.pi.rpc (PiRpcBackend) not available yet",
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PI_FAKES = REPO_ROOT / "tests" / "pi_fakes"
MINIUTIL = REPO_ROOT / "fixtures" / "miniutil"

REAL_PI = os.path.join(
    contracts.DEFAULT_PI_CACHE_DIR, "node_modules", ".bin", "pi")
HAS_REAL_PI = os.path.isfile(REAL_PI)
HAS_NODE = bool(__import__("shutil").which("node"))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _fake(name):
    return str(PI_FAKES / ("fake_pi_%s.py" % name))


def _make_project(tmp_path, slug="demo-guide"):
    """A tiny fake project: one source file + staging + live docs."""
    root = tmp_path / "proj"
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "pkg" / "mod.py").write_text(
        "def greet(name):\n    return 'hi ' + name\n", encoding="utf-8")
    staged = root / "staging"
    staged.mkdir()
    docs = root / "docs" / "guides"
    docs.mkdir(parents=True)
    return root, staged, docs


def _make_task(root, staged, slug="demo-guide", timeout_s=30.0):
    return contracts.PiTask(
        slug=slug,
        title="Demo Guide",
        description="Document the demo package.",
        evidence="file tree: src/pkg/mod.py",
        source_root=str(root),
        staged_docs_dir=str(staged),
        provider="fakeprovider",
        model="fake-model",
        allow_example_exec=False,
        timeout_s=timeout_s,
        system_prompt="Docs-only authoring prompt.",
    )


def _make_backend(fake_script, tmp_path):
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir(exist_ok=True)
    return PiRpcBackend(
        pi_bin=fake_script,
        extension_path=str(PI_FAKES / "dummy_extension.ts"),
        agent_dir=str(agent_dir),
        startup_deadline_s=15.0,
    )


def _fake_env(monkeypatch, staged, slug="demo-guide"):
    """Point the fake's write_doc at the task's staging dir/slug."""
    monkeypatch.setenv("REPOQUILL_FAKE_STAGED_DIR", str(staged))
    monkeypatch.setenv("REPOQUILL_FAKE_SLUG", slug)
    monkeypatch.setenv("REPOQUILL_FAKE_READ_PATH", "src/pkg/mod.py")


def count_procs_matching(needle: str) -> int:
    """psutil-free /proc scan: processes whose cmdline contains *needle*."""
    if not sys.platform.startswith("linux"):
        return -1  # unsupported -> caller treats as pass
    n = 0
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        if needle.encode() in data:
            n += 1
    return n


# --------------------------------------------------------------------------- #
# 0. Pure-fake protocol self check (independent of the backend)
# --------------------------------------------------------------------------- #
def test_fake_pi_protocol_self_check(tmp_path, monkeypatch):
    """The fakes speak the documented JSONL protocol on their own."""
    root, staged, _ = _make_project(tmp_path)
    _fake_env(monkeypatch, staged)
    env = contracts.build_runtime_env()
    proc = subprocess.Popen(
        [_fake("happy"), "--mode", "rpc", "--no-session",
         "--provider", "fakeprovider", "--model", "fake-model"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=str(root), env=env,
    )
    try:
        proc.stdin.write(json.dumps(
            {"id": "gs1", "type": contracts.CMD_GET_STATE}).encode() + b"\n")
        proc.stdin.flush()
        rec = json.loads(proc.stdout.readline())
        assert rec["type"] == "response" and rec["success"] is True
        proc.stdin.write(json.dumps(
            {"id": "p1", "type": contracts.CMD_PROMPT,
             "message": "write the page"}).encode() + b"\n")
        proc.stdin.flush()
        got = set()
        settled = False
        deadline = time.time() + 15
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            rec = json.loads(line.rstrip(b"\r\n"))
            got.add(rec.get("type"))
            if rec.get("type") == "agent_settled":
                settled = rec.get("aborted") is not True
                break
        assert settled
        assert contracts.EV_TOOL_START in got
        assert contracts.EV_TOOL_END in got
        assert contracts.EV_MSG_UPDATE in got
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)
    assert proc.returncode == 0
    page = staged / "demo-guide.md"
    assert page.is_file()
    assert "Documents the module." in page.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# 1. Happy path through PiRpcBackend
# --------------------------------------------------------------------------- #
def test_happy_run_full_result(tmp_path, monkeypatch):
    root, staged, _ = _make_project(tmp_path)
    _fake_env(monkeypatch, staged)
    backend = _make_backend(_fake("happy"), tmp_path)
    task = _make_task(root, staged)

    result = backend.run(task)

    # Delta note: PiRunResult has no `settled` field (M0 contract);
    # "settled" is implied by completed=True and aborted=False.
    assert result.ok is True
    assert result.completed is True
    assert result.aborted is False
    assert result.output_path == task.expected_output_path
    assert os.path.isfile(task.expected_output_path)
    assert os.path.realpath(result.output_path) == os.path.realpath(
        task.expected_output_path)

    names = [tc.name for tc in result.tool_calls]
    assert len(result.tool_calls) >= 2
    assert set(names) <= set(contracts.DOC_TOOL_ALLOWLIST)
    assert "read_file" in names and "write_doc" in names
    assert all(tc.is_error is False for tc in result.tool_calls)
    assert all(tc.tool_call_id for tc in result.tool_calls)
    assert result.tool_trace  # log-safe trace lines exist

    assert result.usage.total_tokens > 0
    assert result.pi_version == "1.2.0"
    assert result.model == "fake-model"
    assert result.elapsed_s > 0
    assert result.source_paths_read, (
        "read_file path should be tracked as a source path")
    assert result.errors == []


# --------------------------------------------------------------------------- #
# 2. Model error: nothing verified
# --------------------------------------------------------------------------- #
def test_model_error_never_yields_verified_page(tmp_path, monkeypatch):
    root, staged, _ = _make_project(tmp_path)
    _fake_env(monkeypatch, staged)
    backend = _make_backend(_fake("model_error"), tmp_path)
    task = _make_task(root, staged)

    try:
        result = backend.run(task)
    except contracts.PiModelAuthError:
        return  # acceptable: hard failure surfaced as an exception
    assert result is not None
    assert result.completed is False
    assert result.ok is False
    # No staged file exists or is treated as the output.
    assert not os.path.isfile(task.expected_output_path)
    assert result.errors, "model failure must be recorded in errors"
    assert any("502" in e for e in result.errors)


# --------------------------------------------------------------------------- #
# 3. Hang: run deadline, child reaped
# --------------------------------------------------------------------------- #
def test_hang_times_out_and_child_reaped(tmp_path, monkeypatch):
    root, staged, _ = _make_project(tmp_path)
    _fake_env(monkeypatch, staged)
    backend = _make_backend(_fake("hang"), tmp_path)
    task = _make_task(root, staged, timeout_s=2.5)

    started = time.time()
    with pytest.raises(contracts.PiRunTimeoutError):
        backend.run(task)
    elapsed = time.time() - started
    # Deadline must actually be honored (give slack for shutdown).
    assert elapsed < 60

    # Give any cleanup a moment, then no lingering fake process may exist.
    deadline = time.time() + 3
    while time.time() < deadline:
        if count_procs_matching("fake_pi_hang.py") == 0:
            break
        time.sleep(0.2)
    assert count_procs_matching("fake_pi_hang.py") == 0, (
        "hanging Pi child was not reaped")
    # And of course no page was produced.
    assert not os.path.isfile(task.expected_output_path)


# --------------------------------------------------------------------------- #
# 4. Crash: PiProcessError with stderr diagnostics
# --------------------------------------------------------------------------- #
def test_crash_raises_process_error_with_stderr(tmp_path, monkeypatch):
    root, staged, _ = _make_project(tmp_path)
    _fake_env(monkeypatch, staged)
    backend = _make_backend(_fake("crash"), tmp_path)
    task = _make_task(root, staged)

    with pytest.raises(contracts.PiProcessError) as excinfo:
        backend.run(task)
    message = str(excinfo.value)
    assert message, "PiProcessError must carry diagnostics"
    # The fake wrote "fake pi: simulated hard crash (exit 3)" to stderr.
    assert "crash" in message
    assert not os.path.isfile(task.expected_output_path)


# --------------------------------------------------------------------------- #
# 5. Fail-closed / last-good
# --------------------------------------------------------------------------- #
def test_fail_closed_last_good_backend_level(tmp_path, monkeypatch):
    """A failed Pi run leaves existing docs and plan state untouched.

    Backend level: ``run`` raises (crash fake) and never writes into the
    live docs tree — only the per-task staging dir is ever writable, and
    the copy from staging into docs is the scheduler's job, gated on an
    independent verification pass. If a future contract adds publish
    semantics to the backend itself, tighten this test.
    """
    root, staged, docs = _make_project(tmp_path, slug="broken-page")
    good = docs / "good.md"
    good.write_text("# Good\n\nlast-known-good content\n", encoding="utf-8")
    marker = tmp_path / "marker.txt"
    marker.write_text("do not touch\n", encoding="utf-8")
    plan = docs.parent / ".plan.json"
    plan.write_text(json.dumps({"pages": [{"slug": "good",
                                           "status": "ok"}]}),
                    encoding="utf-8")
    good_before = good.read_bytes()
    plan_before = plan.read_bytes()
    marker_before = marker.read_bytes()

    _fake_env(monkeypatch, staged, slug="broken-page")
    backend = _make_backend(_fake("crash"), tmp_path)
    task = _make_task(root, staged, slug="broken-page")

    with pytest.raises(contracts.PiError):
        backend.run(task)

    assert good.read_bytes() == good_before, "last-good doc was modified"
    assert plan.read_bytes() == plan_before, "plan state was advanced"
    assert marker.read_bytes() == marker_before
    assert not (docs / "broken-page.md").exists()
    # The crash fake never reaches write_doc; staging holds no page.
    assert list(staged.iterdir()) == []


def _miniutil_cfg(tmp_path):
    llm = types.SimpleNamespace(
        provider="fake", model="fake-model",
        base_url="http://127.0.0.1:1/v1",
        api_key_env="REPOQUILL_FAKE_KEY",
        agentic=types.SimpleNamespace(
            example_timeout=30.0, max_file_chars=16000,
            coverage_threshold=0.6))
    return types.SimpleNamespace(
        root=str(MINIUTIL),
        pkg_path=str(MINIUTIL / "miniutil"),
        out_guides=str(tmp_path / "guides"),
        llm=llm,
        raw={},
    )


def test_fail_closed_scheduler_run_pi_generation(tmp_path, monkeypatch):
    """Scheduler level: a crashed Pi page fails closed; retryable state."""
    from repoquill.agents.scheduler import run_pi_generation

    guides = tmp_path / "guides"
    guides.mkdir()
    good = guides / "good.md"
    good.write_text("# Good\n\nexisting published page\n", encoding="utf-8")
    good_before = good.read_bytes()
    cfg = _miniutil_cfg(tmp_path)
    assert cfg.out_guides == str(guides)

    page = {
        "slug": "textkit-guide",
        "title": "TextKit",
        "description": "",
        "source_files": ["miniutil/textkit.py"],
    }

    # Point the scheduler's binary discovery at the crash fake.
    monkeypatch.setenv(contracts.PI_BIN_ENV, _fake("crash"))
    monkeypatch.setenv("REPOQUILL_FAKE_KEY", "dummy")

    generated = run_pi_generation([page], cfg,
                                  old_hashes={}, new_hashes={})

    assert generated == [], "a crashed Pi page must not be generated"
    assert good.read_bytes() == good_before, "last-good doc was modified"
    # The failed page is recorded for retry, and no verified fingerprints
    # were advanced for it.
    assert page.get("status") == "failed"
    assert page.get("verified_file_hashes") is None
    assert page.get("content_sha256") is None
    assert not (guides / "textkit-guide.md").exists()
    # No new files appeared in the live docs tree.
    assert [p.name for p in guides.iterdir()] == ["good.md"]


# --------------------------------------------------------------------------- #
# 6. Security
# --------------------------------------------------------------------------- #
def test_secret_never_reaches_trace(tmp_path, monkeypatch):
    """A tool arg echoing an env secret must be redacted in the trace."""
    secret = "hunter2"
    monkeypatch.setenv("REPOQUILL_TEST_SECRET", secret)
    root, staged, _ = _make_project(tmp_path)
    _fake_env(monkeypatch, staged)
    backend = _make_backend(_fake("secret"), tmp_path)
    task = _make_task(root, staged)

    result = backend.run(task)
    assert result.ok is True, "the run itself should succeed"

    dumped = json.dumps(result.to_dict())
    assert secret not in dumped, "secret leaked into PiRunResult.to_dict()"
    assert secret not in "\n".join(result.tool_trace)
    # The redaction kept the call itself (only the value is replaced).
    read = [tc for tc in result.tool_calls if tc.name == "read_file"]
    assert read and "api_key" in read[0].args
    assert read[0].args["api_key"] != secret


def test_launch_args_contain_full_safe_flags(tmp_path, monkeypatch):
    """Pins the no-builtin-bash/write/edit guarantee at the process level."""
    argv_file = tmp_path / "argv.json"
    monkeypatch.setenv("REPOQUILL_FAKE_ARGV_FILE", str(argv_file))
    root, staged, _ = _make_project(tmp_path)
    _fake_env(monkeypatch, staged)
    backend = _make_backend(_fake("argv_dump"), tmp_path)
    task = _make_task(root, staged)

    result = backend.run(task)
    assert result.ok is True

    argv = json.loads(argv_file.read_text(encoding="utf-8"))
    assert argv[0].endswith("fake_pi_argv_dump.py")
    missing = [flag for flag in contracts.SAFE_LAUNCH_FLAGS
               if flag not in argv]
    assert not missing, "missing SAFE_LAUNCH_FLAGS in launch argv: %s" % missing
    # The vetted extension is explicitly loaded (not discovered).
    assert "--extension" in argv
    assert argv[argv.index("--extension") + 1] == str(
        PI_FAKES / "dummy_extension.ts")


def test_fake_get_state_reports_no_dangerous_tools(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    monkeypatch.setenv("REPOQUILL_FAKE_STATE_FILE", str(state_file))
    root, staged, _ = _make_project(tmp_path)
    _fake_env(monkeypatch, staged)
    backend = _make_backend(_fake("report_tools"), tmp_path)
    task = _make_task(root, staged)

    result = backend.run(task)
    assert result.ok is True
    data = json.loads(state_file.read_text(encoding="utf-8"))
    tools = data.get("tools")
    assert tools, "fake get_state should report the active tool set"
    assert set(tools) <= set(contracts.DOC_TOOL_ALLOWLIST)
    assert not (set(tools) & set(contracts.DENY_BUILTIN_TOOLS))


@pytest.mark.skipif(not (HAS_REAL_PI and HAS_NODE),
                    reason="pinned pi binary or node not available")
def test_real_pi_safe_flags_no_builtin_tools(tmp_path):
    """Real pinned pi + SAFE_LAUNCH_FLAGS: no builtin bash/write/edit.

    Drives the REAL binary (bypassing PiRpcBackend on purpose so this
    proof holds even if the RPC module is unavailable) with the vetted
    probe extension and a local mock model. Asserts that every tool that
    EXECUTED is an allowlisted extension tool and none from the
    hard-denylist was ever active.
    """
    from tests.pi_fakes.mock_model_server import MockModelServer

    if not MINIUTIL.is_dir():
        pytest.skip("miniutil fixture missing")
    staged = tmp_path / "staged"
    staged.mkdir()
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    provider = "localprobe"

    def script(messages):
        n = sum(1 for m in messages if m.get("role") == "tool")
        if n == 0:
            return ({"role": "assistant", "content": None,
                     "tool_calls": [{"id": "c1", "type": "function",
                                     "function": {"name": "list_files",
                                                  "arguments": "{}"}}]},
                    "tool_calls")
        if n == 1:
            return ({"role": "assistant", "content": None,
                     "tool_calls": [{"id": "c2", "type": "function",
                                     "function": {
                                         "name": "read_file",
                                         "arguments": json.dumps(
                                             {"path": "miniutil/textkit.py"})
                                         }}]},
                    "tool_calls")
        if n == 2:
            return ({"role": "assistant", "content": None,
                     "tool_calls": [{"id": "c3", "type": "function",
                                     "function": {
                                         "name": "write_doc",
                                         "arguments": json.dumps(
                                             {"slug": "probe",
                                              "content": "## Probe\n\n"
                                                         "`slugify` "
                                                         "documented.\n"})
                                         }}]},
                    "tool_calls")
        return ({"role": "assistant", "content": "Page written."}, "stop")

    with MockModelServer(script, log_path=str(tmp_path / "req.log")) as srv:
        (agent_dir / "models.json").write_text(json.dumps({
            "providers": {
                provider: {
                    "baseUrl": srv.base_url,
                    "api": "openai-completions",
                    "apiKey": "$PROBE_KEY",
                    "models": [{"id": "probe-model",
                                "contextWindow": 32768,
                                "maxTokens": 8192}],
                }
            }
        }), encoding="utf-8")

        env = contracts.build_runtime_env(agent_dir=str(agent_dir))
        env["PROBE_KEY"] = "dummy"
        env["REPOQUILL_FAKE_STAGED_DIR"] = str(staged)
        cmd = [
            REAL_PI, *contracts.SAFE_LAUNCH_FLAGS,
            "--extension", str(PI_FAKES / "probe_extension.ts"),
            "--provider", provider,
            "--model", "%s/probe-model" % provider,
            "--thinking", "off",
            "--system-prompt", "Docs-only. Use the provided tools.",
        ]
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(MINIUTIL), env=env,
        )
        tool_names = []
        settled = False
        try:
            def send(obj):
                proc.stdin.write(json.dumps(obj).encode() + b"\n")
                proc.stdin.flush()

            send({"id": "gs1", "type": contracts.CMD_GET_STATE})
            send({"id": "p1", "type": contracts.CMD_PROMPT,
                  "message": "Write the probe page (slug: probe)."})
            deadline = time.time() + 90
            while time.time() < deadline:
                line = proc.stdout.readline()
                if not line:
                    break
                rec = json.loads(line.rstrip(b"\r\n"))
                rtype = rec.get("type")
                if rtype == contracts.EV_TOOL_START:
                    tool_names.append(rec.get("toolName"))
                if rtype == contracts.EV_AGENT_SETTLED:
                    settled = rec.get("aborted") is not True
                    break
            assert settled, "real pi run did not settle"
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)

        # THE assertion: no hard-denied builtin ever executed, and
        # everything that ran is in the docs allowlist.
        assert tool_names, "expected at least one executed tool"
        assert not (set(tool_names) & set(contracts.DENY_BUILTIN_TOOLS)), (
            "dangerous builtin tool executed: %s" % tool_names)
        assert set(tool_names) <= set(contracts.DOC_TOOL_ALLOWLIST)
        assert (staged / "probe.md").is_file()


# --------------------------------------------------------------------------- #
# 7. No-op semantics
# --------------------------------------------------------------------------- #
def test_noop_pages_spawn_zero_pi_processes(tmp_path, monkeypatch):
    """Unchanged pages must cost zero Pi prompt spawns.

    The scheduler's ``run_pi_generation`` skip logic (page_needs_regeneration
    + manifest state) decides before any Pi process is constructed; the
    counter fake counts accepted ``prompt`` commands, so a no-op run must
    never create the counter file.
    """
    from repoquill.agents.scheduler import run_pi_generation

    guides = tmp_path / "guides"
    guides.mkdir()
    out = guides / "alpha.md"
    out.write_text("# Alpha\n\nunchanged page\n", encoding="utf-8")
    content_sha = hashlib.sha256(out.read_bytes()).hexdigest()

    page = {
        "slug": "alpha",
        "title": "Alpha",
        "description": "",
        "source_files": ["miniutil/textkit.py"],
        "status": "ok",
        "content_sha256": content_sha,
        "verified_file_hashes": {"miniutil/textkit.py": "h1"},
    }
    cfg = _miniutil_cfg(tmp_path)
    assert cfg.out_guides == str(guides)

    counter = tmp_path / "spawn-counter"
    monkeypatch.setenv(contracts.PI_BIN_ENV, _fake("counter"))
    monkeypatch.setenv("REPOQUILL_FAKE_COUNTER_FILE", str(counter))
    monkeypatch.setenv("REPOQUILL_FAKE_KEY", "dummy")

    generated = run_pi_generation(
        [page], cfg,
        old_hashes={"miniutil/textkit.py": "h1"},
        new_hashes={"miniutil/textkit.py": "h1"})

    assert generated == []
    assert not counter.exists(), (
        "unchanged page triggered a Pi prompt spawn")
    assert out.read_text(encoding="utf-8") == "# Alpha\n\nunchanged page\n"


# --------------------------------------------------------------------------- #
# Real-binary sanity (independent of the backend)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not (HAS_REAL_PI and HAS_NODE),
                    reason="pinned pi binary or node not available")
def test_real_pi_probe_reports_pinned_version(tmp_path):
    """PiRpcBackend.probe() handshakes the real binary with safe flags."""
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    backend = PiRpcBackend(pi_bin=REAL_PI, agent_dir=str(agent_dir))
    probe = backend.probe(startup_deadline_s=30.0)
    assert probe.pi_version == contracts.PI_PINNED_VERSION
    assert isinstance(probe.state, dict)
