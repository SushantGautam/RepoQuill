"""Deterministic tests for the Pi RPC backend against a FAKE pi process.

The fake pi is a small Python script written into the pytest tmp dir that
speaks the Pi v1.2.0 JSONL RPC protocol (LF-only framing, id-correlated
responses, scripted event streams). No network, no model.

One test (marked + skipped when absent) probes the real pinned binary at
``/home/susan/.cache/repoquill/pi/node_modules/.bin/pi`` -- ``get_state``
only, no model required.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time

import pytest

from repoquill.pi import contracts
from repoquill.pi.protocol import (
    decode_stream,
    encode_command,
    prompt_disposition,
    redact_secrets,
    sanitize_args,
    summarize_result,
)
from repoquill.pi.rpc import PiRpcBackend, build_task_prompt

REAL_PI_BIN = "/home/susan/.cache/repoquill/pi/node_modules/.bin/pi"

# --------------------------------------------------------------------------- #
# Fake pi process (raw source; \u escapes are interpreted by the fake)
# --------------------------------------------------------------------------- #

FAKE_PI_SOURCE = r'''
import json
import os
import sys
import time


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def usage(i, o, cr, cw, total):
    return {
        "input": i, "output": o, "cacheRead": cr, "cacheWrite": cw,
        "totalTokens": i + o + cr + cw,
        "cost": {"input": 0, "output": total, "cacheRead": 0,
                 "cacheWrite": 0, "total": total},
    }


def normal_sequence(stage_path):
    emit({"type": "agent_start"})
    emit({"type": "turn_start"})
    emit({"type": "message_start",
          "message": {"role": "assistant", "content": [], "stopReason": "pending"}})
    emit({"type": "message_update", "usage": usage(10, 2, 0, 0, 0.0001),
          "assistantMessageEvent": {"type": "text_delta", "contentIndex": 0,
                                    "delta": "Reading\u2028files"}})
    emit({"type": "tool_execution_start", "toolCallId": "call_read",
          "toolName": "read_file",
          "args": {"path": "src/app.py", "preview": "x" * 300,
                   "api_key": "sk-fakefakefake123456"}})
    emit({"type": "tool_execution_end", "toolCallId": "call_read",
          "toolName": "read_file",
          "result": {"content": [{"type": "text",
                                  "text": "def main():\n    return 42\n"}],
                     "details": {}},
          "isError": False, "durationMs": 12})
    emit({"type": "message_update", "usage": usage(40, 15, 5, 1, 0.0005),
          "assistantMessageEvent": {"type": "toolcall_end", "contentIndex": 0,
                                    "toolCall": {"id": "call_write",
                                                 "name": "write_doc"}}})
    if stage_path:
        with open(stage_path, "w") as f:
            f.write("# Fake page\n\nstaged by the fake pi\n")
    emit({"type": "tool_execution_start", "toolCallId": "call_write",
          "toolName": "write_doc",
          "args": {"path": stage_path or "out.md",
                   "content": "# Page\n\nBody"}})
    emit({"type": "tool_execution_end", "toolCallId": "call_write",
          "toolName": "write_doc",
          "result": {"content": [{"type": "text",
                                  "text": "wrote page (" + "y" * 350 + ")"}],
                     "details": {}},
          "isError": False, "durationMs": 3})
    emit({"type": "message_end",
          "message": {"role": "assistant", "stopReason": "stop"}})
    emit({"type": "turn_end", "message": {"role": "assistant"}, "toolResults": []})
    emit({"type": "agent_end", "messages": [], "willRetry": False})
    emit({"type": "agent_settled", "aborted": False})


def model_error_sequence(final_error, auth):
    emit({"type": "agent_start"})
    emit({"type": "turn_start"})
    emit({"type": "message_start",
          "message": {"role": "assistant", "content": [], "stopReason": "pending"}})
    emit({"type": "message_update", "usage": usage(5, 0, 0, 0, 0.0),
          "assistantMessageEvent": {"type": "error", "error": final_error}})
    emit({"type": "message_end",
          "message": {"role": "assistant", "stopReason": "error"}})
    emit({"type": "auto_retry_start", "attempt": 1, "maxAttempts": 3,
          "delayMs": 0, "errorMessage": final_error})
    emit({"type": "auto_retry_end", "success": False, "attempt": 1,
          "finalError": final_error})
    emit({"type": "agent_end", "messages": [], "willRetry": False})
    emit({"type": "agent_settled", "aborted": False})


def main():
    if "--version" in sys.argv:
        print("1.2.0")
        return 0
    mode = os.environ.get("REPOQUILL_FAKE_MODE", "normal")
    stage_path = os.environ.get("REPOQUILL_FAKE_STAGE_PATH")
    decoy = os.environ.get("REPOQUILL_FAKE_DECOY") == "1"
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
        except ValueError:
            emit({"type": "response", "command": "parse", "success": False,
                  "error": "bad command"})
            continue
        ctype = cmd.get("type")
        cid = cmd.get("id")
        if ctype == "get_state":
            if decoy:
                emit({"id": "stale-99", "type": "response",
                      "command": "get_state", "success": True,
                      "data": {"decoy": True}})
            emit({"id": cid, "type": "response", "command": "get_state",
                  "success": True,
                  "data": {"isStreaming": False, "sessionId": "fake",
                           "messageCount": 0}})
        elif ctype == "prompt":
            emit({"id": cid, "type": "response", "command": "prompt",
                  "success": True, "data": {"disposition": "started"}})
            if mode == "crash":
                emit({"type": "agent_start"})
                emit({"type": "message_start",
                      "message": {"role": "assistant", "content": []}})
                sys.stderr.write("crash: password=hunter22 "
                                 "token=sk-fakefakefake123456\nfatal: boom\n")
                sys.stderr.flush()
                return 3
            if mode == "hang":
                emit({"type": "agent_start"})
                for _ in sys.stdin:  # blocks until stdin is closed
                    pass
                return 0
            if mode == "malformed":
                sys.stdout.write('{"type":"agent_start", oops\n')
                sys.stdout.flush()
                normal_sequence(stage_path)
            elif mode == "model-error":
                model_error_sequence("Model not found: bogus/model", True)
            elif mode == "soft-error":
                model_error_sequence("upstream returned 500", False)
            else:
                normal_sequence(stage_path)
        elif ctype == "abort":
            emit({"id": cid, "type": "response", "command": "abort",
                  "success": True})
    return 0


sys.exit(main())
'''


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def fake_pi(tmp_path_factory) -> str:
    """Executable fake pi script (correct interpreter via shebang)."""
    base = tmp_path_factory.mktemp("fakepi")
    script = base / "fake_pi"
    script.write_text("#!" + sys.executable + "\n" + FAKE_PI_SOURCE)
    script.chmod(0o755)
    return str(script)


def run_fake(fake_pi: str, tmp_path, *, mode: str = "normal",
             write_stage: bool = True, decoy: bool = False,
             timeout_s: float = 30.0):
    env = dict(REPOQUILL_FAKE_MODE=mode)
    task = contracts.PiTask(
        slug="my-page",
        title="My Page",
        description="Explain the miniutil helper API.",
        evidence="miniutil.add(a, b) returns a + b.",
        source_root=str(tmp_path),
        staged_docs_dir=str(tmp_path / "staged"),
        provider="fake",
        model="fake-model",
        timeout_s=timeout_s,
        system_prompt="docs-only",
    )
    (tmp_path / "staged").mkdir(exist_ok=True)
    if write_stage:
        env["REPOQUILL_FAKE_STAGE_PATH"] = task.expected_output_path
    if decoy:
        env["REPOQUILL_FAKE_DECOY"] = "1"
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        backend = PiRpcBackend(fake_pi, extension_path=None,
                               startup_deadline_s=15.0)
        return backend.run(task)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# --------------------------------------------------------------------------- #
# Protocol framing
# --------------------------------------------------------------------------- #

def test_encode_command_is_single_jsonl_record():
    data = encode_command({"id": "r1", "type": "get_state"})
    assert data.endswith(b"\n")
    assert data.count(b"\n") == 1
    assert json.loads(data) == {"id": "r1", "type": "get_state"}


def test_encode_command_escapes_unicode_separators():
    # U+2028 in a command payload must be escaped, never raw on the wire.
    data = encode_command({"message": "a\u2028b"})
    assert b"\xe2\x80\xa8" not in data
    assert b"\\u2028" in data


def test_decode_stream_u2028_inside_string_does_not_break_framing():
    payload = (
        '{"type":"message_update","usage":null,"assistantMessageEvent":'
        '{"type":"text_delta","contentIndex":0,"delta":"A\u2028B"}}\n'
        '{"type":"agent_settled","aborted":false}\n'
    )
    records = list(decode_stream(io.BytesIO(payload.encode("utf-8"))))
    assert len(records) == 2
    assert records[0]["assistantMessageEvent"]["delta"] == "A\u2028B"
    assert records[1]["type"] == "agent_settled"


def test_decode_stream_strips_single_trailing_cr():
    data = b'{"a":1}\r\n{"b":2}\n'
    records = list(decode_stream(io.BytesIO(data)))
    assert records == [{"a": 1}, {"b": 2}]


def test_decode_stream_malformed_line_yields_parse_error_and_continues():
    data = b'{"ok":true}\nnot-json {\n{"after":true}\n'
    records = list(decode_stream(io.BytesIO(data)))
    assert records[0] == {"ok": True}
    assert records[1]["type"] == "response"
    assert records[1]["command"] == "parse"
    assert records[1]["success"] is False
    assert records[2] == {"after": True}


def test_decode_stream_final_unterminated_record():
    records = list(decode_stream(io.BytesIO(b'{"tail":1}')))
    assert records == [{"tail": 1}]


def test_prompt_disposition():
    assert prompt_disposition({"data": {"disposition": "handled"}}) == "handled"
    assert prompt_disposition({"data": {"disposition": "started"}}) == "started"
    assert prompt_disposition({"success": True}) == ""


# --------------------------------------------------------------------------- #
# Sanitization
# --------------------------------------------------------------------------- #

def test_sanitize_args_redacts_secrets_and_truncates():
    args = sanitize_args({
        "path": "src/app.py",
        "api_key": "sk-abcdef123456",
        "query": "z" * 500,
        "bearer": "Bearer abc.def.ghi",
        "count": 3,
        "headers": {"Authorization": "Bearer super-secret-token-123"},
    })
    assert args["path"] == "src/app.py"
    assert args["api_key"] == "***redacted***"
    assert len(args["query"]) == 200
    assert args["query"].endswith("\u2026")
    assert args["count"] == 3
    assert args["headers"]["Authorization"] == "***redacted***"
    assert "Bearer" in args["bearer"] or args["bearer"] == "***redacted***"
    # token-looking strings are redacted even under neutral keys
    assert sanitize_args({"preview": "x sk-fakefakefake123456 y"})["preview"] \
        == "***redacted***"


def test_summarize_result_one_line_and_capped():
    text = summarize_result(
        {"content": [{"type": "text", "text": "line1\nline2 " + "w" * 400}]})
    assert len(text) <= 300
    assert "\n" not in text
    assert text.endswith("\u2026")
    assert summarize_result(None) == ""
    assert "hunter22" not in redact_secrets("password=hunter22")


def test_redact_secrets():
    raw = "Error: api_key=abc123456 Authorization: Bearer xyz\nsk-abcdef123456"
    out = redact_secrets(raw)
    assert "abc123456" not in out
    assert "sk-abcdef123456" not in out
    assert "***" in out


# --------------------------------------------------------------------------- #
# Backend: run() against the fake
# --------------------------------------------------------------------------- #

def test_run_normal_completed_with_staged_file(fake_pi, tmp_path):
    result = run_fake(fake_pi, tmp_path, mode="normal", write_stage=True)
    assert result.completed is True
    assert result.ok is True
    assert result.aborted is False
    assert result.output_path == str(tmp_path / "staged" / "my-page.md")
    assert os.path.isfile(result.output_path)
    assert result.pi_version == "1.2.0"
    assert result.model == "fake-model"
    assert result.errors == []
    assert result.elapsed_s > 0


def test_run_completed_false_when_file_missing(fake_pi, tmp_path):
    result = run_fake(fake_pi, tmp_path, mode="normal", write_stage=False)
    assert result.completed is False
    assert result.ok is False
    assert result.output_path is None
    # the run itself was clean
    assert result.errors == []
    assert result.aborted is False


def test_run_id_correlation_ignores_decoy_response(fake_pi, tmp_path):
    result = run_fake(fake_pi, tmp_path, mode="normal", decoy=True)
    assert result.completed is True


def test_usage_aggregation_max_cumulative(fake_pi, tmp_path):
    result = run_fake(fake_pi, tmp_path, mode="normal")
    u = result.usage
    # two message_update records: (10,2,0.0001) then (40,15,0.0005); take max
    assert u.input_tokens == 40
    assert u.output_tokens == 15
    assert u.cache_read_tokens == 5
    assert u.cache_write_tokens == 1
    assert abs(u.cost - 0.0005) < 1e-12


def test_tool_trace_sanitized(fake_pi, tmp_path):
    result = run_fake(fake_pi, tmp_path, mode="normal")
    by_name = {tc.name: tc for tc in result.tool_calls}
    assert set(by_name) == {"read_file", "write_doc"}

    read = by_name["read_file"]
    assert read.tool_call_id == "call_read"
    assert read.is_error is False
    assert read.duration_ms == 12
    assert read.args["api_key"] == "***redacted***"
    assert len(read.args["preview"]) == 200
    assert read.result_summary == "def main(): return 42"

    write = by_name["write_doc"]
    assert write.tool_call_id == "call_write"
    assert write.duration_ms == 3
    assert len(write.result_summary) <= 300
    assert write.result_summary.endswith("\u2026")

    assert result.source_paths_read == ["src/app.py"]


def test_run_crash_raises_process_error_with_redacted_tail(fake_pi, tmp_path):
    with pytest.raises(contracts.PiProcessError) as exc_info:
        run_fake(fake_pi, tmp_path, mode="crash")
    msg = str(exc_info.value)
    assert "code 3" in msg
    assert "boom" in msg
    # secrets from stderr must be redacted in the surfaced tail
    assert "hunter22" not in msg
    assert "sk-fakefakefake123456" not in msg
    assert "***" in msg


def test_run_hang_raises_timeout(fake_pi, tmp_path):
    started = time.monotonic()
    with pytest.raises(contracts.PiRunTimeoutError):
        run_fake(fake_pi, tmp_path, mode="hang", timeout_s=2.0)
    assert time.monotonic() - started < 15


def test_run_malformed_line_is_tolerated(fake_pi, tmp_path):
    result = run_fake(fake_pi, tmp_path, mode="malformed")
    assert result.completed is True


def test_run_hard_model_error_raises_auth_error(fake_pi, tmp_path):
    with pytest.raises(contracts.PiModelAuthError) as exc_info:
        run_fake(fake_pi, tmp_path, mode="model-error")
    assert "Model not found" in str(exc_info.value)


def test_run_soft_model_error_completes_not_completed(fake_pi, tmp_path):
    result = run_fake(fake_pi, tmp_path, mode="soft-error")
    assert result.completed is False
    assert result.ok is False
    assert result.aborted is False
    assert any("upstream returned 500" in e for e in result.errors)
    assert any("stopReason=error" in e for e in result.errors)


def test_missing_binary_raises_not_installed(tmp_path):
    backend = PiRpcBackend("/nonexistent/pi-bin-xyz", extension_path=None)
    task = contracts.PiTask(
        slug="s", title="T", description="d", evidence="e",
        source_root=str(tmp_path), staged_docs_dir=str(tmp_path / "s"),
        provider="p", model="m",
    )
    with pytest.raises(contracts.PiNotInstalledError) as exc_info:
        backend.run(task)
    msg = str(exc_info.value)
    assert "npm install" in msg
    assert "@earendil-works/pi-coding-agent" in msg


def test_launch_args_use_contract_and_prune_empty_extension(fake_pi):
    backend = PiRpcBackend(fake_pi, extension_path=None)
    args = backend._launch_args("prov", "model", "sp")
    assert args[0] == fake_pi
    for flag in contracts.SAFE_LAUNCH_FLAGS:
        assert flag in args
    assert "--extension" not in args
    assert args[args.index("--provider") + 1] == "prov"
    assert args[args.index("--model") + 1] == "model"
    assert args[args.index("--system-prompt") + 1] == "sp"

    backend2 = PiRpcBackend(fake_pi, extension_path="/tmp/ext.ts")
    args2 = backend2._launch_args("prov", "model", "sp")
    assert args2[args2.index("--extension") + 1] == "/tmp/ext.ts"


def test_build_task_prompt_contents(tmp_path):
    task = contracts.PiTask(
        slug="my-page",
        title="My Page",
        description="Describe the helper.",
        evidence="EVIDENCE-XYZ",
        source_root=str(tmp_path),
        staged_docs_dir=str(tmp_path / "staged"),
        provider="p",
        model="m",
    )
    prompt = build_task_prompt(task)
    assert "Describe the helper." in prompt
    assert "EVIDENCE-XYZ" in prompt
    assert "my-page" in prompt
    assert "write_doc" in prompt
    assert task.expected_output_path in prompt
    assert "Do not attempt to execute example code." in prompt
    task2 = contracts.PiTask(
        slug="s", title="T", description="d", evidence="e",
        source_root=str(tmp_path), staged_docs_dir=str(tmp_path / "s"),
        provider="p", model="m", allow_example_exec=True,
    )
    assert "execute example" not in build_task_prompt(task2)

    task3 = contracts.PiTask(
        slug="s", title="T", description="d", evidence="e",
        source_root=str(tmp_path), staged_docs_dir=str(tmp_path / "s"),
        provider="p", model="m",
        coverage_checklist=["slugify", "TextStats"],
    )
    p3 = build_task_prompt(task3)
    assert "Required coverage" in p3
    assert "slugify" in p3 and "TextStats" in p3
    # An empty checklist must not add the section at all.
    assert "Required coverage" not in build_task_prompt(task2)


@pytest.mark.skipif(
    not os.path.exists(REAL_PI_BIN),
    reason="real pinned pi binary not provisioned",
)
def test_real_binary_probe_get_state(tmp_path):
    """Real pi v1.2.0: version + get_state handshake, no model needed."""
    backend = PiRpcBackend(REAL_PI_BIN, extension_path=None,
                           agent_dir=str(tmp_path / "agent"))
    probe = backend.probe(startup_deadline_s=30.0)
    assert probe.pi_version == "1.2.0"
    assert probe.state.get("isStreaming") is False
    assert probe.state.get("sessionId")
