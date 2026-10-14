"""Shared JSONL RPC emulation for fake Pi processes (tests/pi_fakes/).

Each fake is a standalone executable Python script that speaks the Pi
1.2.0 RPC protocol on stdio (strict JSONL, LF-terminated records, exactly
as the pinned pi binary does): it answers ``get_state`` / ``prompt`` /
``abort`` commands and emits session events (``agent_start``,
``tool_execution_*``, ``message_update`` with cumulative ``usage``,
``agent_settled``).

Env knobs used by the fakes (set by the tests; the canonical
``contracts.build_runtime_env`` inherits ``os.environ`` into the Pi child,
so plain ``monkeypatch.setenv`` is enough):

* ``REPOQUILL_FAKE_PI_VERSION``  — value reported for ``--version``
  (default ``1.2.0``, matching the pinned runtime).
* ``REPOQUILL_FAKE_STAGED_DIR``  — where the fake ``write_doc`` writes the
  staged ``<slug>.md`` page.
* ``REPOQUILL_FAKE_SLUG``        — slug the fake uses for its ``write_doc``
  tool call (tests set it to the PiTask slug).
* ``REPOQUILL_FAKE_READ_PATH``   — path echoed in the fake ``read_file``
  tool args (should exist under the fake project root).
* ``REPOQUILL_FAKE_ARGV_FILE``   — if set, the fake dumps its full
  ``sys.argv`` (one JSON line) to this file at startup.
* ``REPOQUILL_TEST_SECRET``      — secret the secret-echo fake embeds into
  a tool arg under a secret-named key, to prove backend redaction.
* ``REPOQUILL_FAKE_COUNTER_FILE`` — if set, appended to once per accepted
  ``prompt`` command (no-op / spawn-counting tests).
* ``REPOQUILL_FAKE_STATE_FILE``  — if set, the fake writes the full
  ``get_state`` response data (one JSON line) here.
"""
from __future__ import annotations

import json
import os
import sys
import time

DEFAULT_VERSION = os.environ.get("REPOQUILL_FAKE_PI_VERSION", "1.2.0")

#: Doc-tool allowlist names (mirrors contracts.DOC_TOOL_ALLOWLIST; the
#: fakes only ever emit allowlisted tool names).
ALLOWED_TOOLS = [
    "list_files", "read_file", "search_code", "inspect_api",
    "inspect_tests", "run_example", "write_doc",
]


def emit(obj):
    """Write one LF-terminated JSON record to stdout (protocol framing)."""
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def respond(req_id, command, success=True, data=None, error=None):
    rec = {"id": req_id, "type": "response", "command": command,
           "success": success}
    if data is not None:
        rec["data"] = data
    if error is not None:
        rec["error"] = error
    emit(rec)


def arg_value(argv, flag):
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return ""


def dump_argv_if_requested():
    path = os.environ.get("REPOQUILL_FAKE_ARGV_FILE")
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(sys.argv) + "\n")
            fh.flush()


def bump_counter_if_requested():
    path = os.environ.get("REPOQUILL_FAKE_COUNTER_FILE")
    if not path:
        return
    n = 0
    if os.path.exists(path):
        try:
            n = int(open(path, "r", encoding="utf-8").read() or "0")
        except ValueError:
            n = 0
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(str(n + 1))


def do_write_doc(args):
    """Side effect of the fake write_doc: create the staged page file."""
    slug = args.get("slug") or os.environ.get("REPOQUILL_FAKE_SLUG", "page")
    content = args.get("content") or "# Fake page\n"
    staged = os.environ.get("REPOQUILL_FAKE_STAGED_DIR")
    if not staged:
        staged = os.path.join(os.getcwd(), "staged")
    os.makedirs(staged, exist_ok=True)
    path = os.path.join(staged, slug + ".md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return {"slug": slug, "path": path, "chars": len(content)}


def _tool_result(text):
    return {"content": [{"type": "text", "text": text}], "details": {}}


def _usage(i, o):
    return {"input": i, "output": o, "cacheRead": 0, "cacheWrite": 0,
            "totalTokens": i + o,
            "cost": {"input": 0, "output": 0, "cacheRead": 0,
                     "cacheWrite": 0, "total": 0}}


def happy_events(echo_secret=False):
    """Full success sequence: 3 tool executions, usage, agent_settled."""
    provider = arg_value(sys.argv, "--provider")
    model = arg_value(sys.argv, "--model")
    slug = os.environ.get("REPOQUILL_FAKE_SLUG", "page")
    read_path = os.environ.get("REPOQUILL_FAKE_READ_PATH",
                               "src/pkg/mod.py")
    now = int(time.time() * 1000)
    emit({"type": "agent_start"})
    emit({"type": "turn_start"})
    emit({"type": "message_start",
          "message": {"role": "user", "content": "write the page",
                      "timestamp": now}})
    emit({"type": "message_end",
          "message": {"role": "user", "content": "write the page",
                      "timestamp": now}})
    emit({"type": "message_start",
          "message": {"role": "assistant", "content": [],
                      "api": "openai-completions", "provider": provider,
                      "model": model,
                      "usage": _usage(0, 0), "stopReason": "pending",
                      "timestamp": now}})

    read_args = {"path": read_path}
    if echo_secret:
        # Echo the environment secret under a secret-named key: the
        # backend's sanitize_args must replace the value before it ever
        # reaches the trace.
        read_args["api_key"] = os.environ.get("REPOQUILL_TEST_SECRET", "")
    plan = [
        ("call_h1", "list_files", {},
         {"files": [read_path], "count": 1, "truncated": False}),
        ("call_h2", "read_file", read_args,
         {"path": read_path, "start_line": 1, "end_line": 3,
          "total_lines": 3,
          "content": "def greet(name):\n    return 'hi'\n",
          "truncated": False}),
        ("call_h3", "write_doc",
         {"slug": slug, "content": "# Fake page\n\nDocuments the module.\n"},
         None),
    ]
    for call_id, name, args, data in plan:
        emit({"type": "message_update", "usage": _usage(120, 15),
              "assistantMessageEvent": {"type": "toolcall_start",
                                        "contentIndex": 0, "id": call_id,
                                        "toolName": name}})
        emit({"type": "tool_execution_start", "toolCallId": call_id,
              "toolName": name, "args": args})
        result = do_write_doc(args) if name == "write_doc" else data
        emit({"type": "tool_execution_end", "toolCallId": call_id,
              "toolName": name, "result": _tool_result(json.dumps(result)),
              "isError": False, "durationMs": 3})
        emit({"type": "message_start",
              "message": {"role": "toolResult", "toolCallId": call_id,
                          "toolName": name,
                          "content": [{"type": "text",
                                       "text": json.dumps(result)}],
                          "isError": False, "timestamp": now}})
        emit({"type": "message_end",
              "message": {"role": "toolResult", "toolCallId": call_id,
                          "toolName": name,
                          "content": [{"type": "text",
                                       "text": json.dumps(result)}],
                          "isError": False, "timestamp": now}})

    # Cumulative usage on the closing text delta.
    emit({"type": "message_update", "usage": _usage(500, 60),
          "assistantMessageEvent": {"type": "text_delta",
                                    "contentIndex": 0,
                                    "delta": "Page written."}})
    emit({"type": "message_end",
          "message": {"role": "assistant",
                      "content": [{"type": "text", "text": "Page written."}],
                      "api": "openai-completions", "provider": provider,
                      "model": model, "usage": _usage(500, 60),
                      "stopReason": "stop", "timestamp": now}})
    emit({"type": "turn_end", "message": {"role": "assistant"},
          "toolResults": []})
    emit({"type": "agent_end", "messages": [], "willRetry": False})
    emit({"type": "agent_settled", "aborted": False})


def model_error_events():
    """Message stream carries a model failure (502) that never recovers."""
    emit({"type": "agent_start"})
    emit({"type": "turn_start"})
    emit({"type": "message_start",
          "message": {"role": "assistant", "content": [],
                      "stopReason": "pending"}})
    emit({"type": "message_update", "usage": _usage(0, 0),
          "assistantMessageEvent": {"type": "error", "reason": "error",
                                    "error": "502 Bad Gateway from "
                                             "upstream provider"}})
    emit({"type": "auto_retry_start", "attempt": 1, "maxAttempts": 2,
          "delayMs": 10, "errorMessage": "502 Bad Gateway"})
    emit({"type": "auto_retry_end", "success": False,
          "finalError": "502 Bad Gateway"})
    emit({"type": "agent_end", "messages": [], "willRetry": False})
    emit({"type": "agent_settled", "aborted": False})


def hang_events():
    """Accept the prompt, emit agent_start, never settle."""
    emit({"type": "agent_start"})
    while True:
        time.sleep(3600)


def crash_events():
    """Exit(3) right after the prompt response; leave a stderr marker."""
    sys.stderr.write("fake pi: simulated hard crash (exit 3)\n")
    sys.stderr.flush()
    os._exit(3)


def serve(prompt_hook, extra_state=None, count_prompts=True):
    """Main RPC loop.

    ``prompt_hook(prompt_record)`` runs after the prompt response and
    emits the scenario's events. ``extra_state`` is merged into the
    get_state data.
    """
    provider = arg_value(sys.argv, "--provider")
    model = arg_value(sys.argv, "--model")
    dump_argv_if_requested()
    for raw in sys.stdin.buffer:  # binary: lines arrive as soon as written
        line = raw.rstrip(b"\r\n")
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            emit({"type": "response", "command": "parse", "success": False,
                  "error": "Failed to parse command"})
            continue
        rid = req.get("id")
        rtype = req.get("type")
        if rtype == "get_state":
            data = {
                "sessionId": "fake-session-%d" % os.getpid(),
                "thinkingLevel": "off",
                "isStreaming": False,
                "isCompacting": False,
                "messageCount": 0,
                "pendingMessageCount": 0,
                "model": {"id": model, "provider": provider,
                          "api": "openai-completions"},
            }
            if extra_state:
                data.update(extra_state)
            state_file = os.environ.get("REPOQUILL_FAKE_STATE_FILE")
            if state_file:
                with open(state_file, "w", encoding="utf-8") as fh:
                    fh.write(json.dumps(data) + "\n")
            respond(rid, "get_state", success=True, data=data)
        elif rtype == "prompt":
            if count_prompts:
                bump_counter_if_requested()
            respond(rid, "prompt", success=True,
                    data={"disposition": "started"})
            prompt_hook(req)
        elif rtype == "abort":
            respond(rid, "abort", success=True, data={})
        else:
            respond(rid, rtype or "unknown", success=False,
                    error="unknown command")
    # stdin closed: orderly exit (all scenarios return here normally).


def version_cli():
    """Handle ``pi --version`` / ``--help``; returns True if handled."""
    for a in sys.argv[1:]:
        if a in ("--version", "-v"):
            print(DEFAULT_VERSION)
            return True
        if a in ("--help", "-h"):
            print("fake pi (repoquill test double)")
            return True
    return False
