---
name: RepoQuill Pi Bootstrap
description: Add predictable Pi installation/discovery/doctor semantics while keeping uvx deterministic mode Node-free
user-invocable: false
---
Read `engineering/PI_FIRST_CLASS_PLAN.md` and current official Pi install docs.

**Exclusive ownership:** new `repoquill/pi/bootstrap.py` and `tests/test_pi_bootstrap.py`; coordinate any `pyproject.toml` change with integration owner. CI workflows are owned by RepoQuill CI and must not be edited here.

Pi should be first class for consumers running `uvx repoquill generate`. Implement binary detection, version/Node compatibility checks (Pi requires a modern Node 22 runtime according to upstream), deterministic pinned version strategy and a documented explicit installation/bootstrap flow. No blind `curl | sh`, no silent global npm writes; prefer self-contained cache install and user-visible confirmation/diagnostic when installing requires network or permissions. In trusted CI a preprovisioned version is mandatory; `--no-llm` must not require Node or Pi. Ensure offline/missing binary cases return an actionable message without falsifying success.

Add tests for already-installed, mismatched-version, absent Node, offline missing Pi, explicit managed install, lock/pin and repeated no-op. Hand runtime invocation path/config to Pi RPC/integration.
