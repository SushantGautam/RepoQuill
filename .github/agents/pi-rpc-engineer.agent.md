---
name: RepoQuill Pi RPC
description: Implement the actual Pi subprocess JSONL protocol client with reliable lifecycle and task results
user-invocable: false
---
Read `engineering/PI_FIRST_CLASS_PLAN.md` and official Pi RPC docs at https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc.md.

**Exclusive ownership:** new `repoquill/pi/__init__.py`, `repoquill/pi/rpc.py`, `repoquill/pi/protocol.py`, `tests/test_pi_rpc.py`. Do not edit `cli.py`, `config.py`, `agents/author.py`, `agents/scheduler.py` or bridge/model/bootstrap files.

Build a Python supervisor for **real `pi --mode rpc --no-session`** subprocesses. Use binary stdin/stdout JSONL, command IDs, multiplexed responses/events, bounded startup/run/shutdown time, stderr drains, cancellation, malformed JSON diagnostics, process-exit detection, tool-use event summaries and `agent_settled` semantics (prompt acceptance is NOT completion). Return structured result / explicit failure; support isolated process per task initially and concurrency managed upstream.

Provide fake-protocol-process tests for missing binary, timeout, nonzero exit, interleaved response/event, Unicode, error event, timeout/cancel and success. Also run and report a real Pi RPC smoke test with installed pinned version; if environment doesn't allow it, clearly mark it unverified. Hand signatures to integration owner early.
