---
name: RepoQuill Pi Bridge
description: Connect vetted Pi extension tools to existing Python repository evidence tools with strict access boundaries
user-invocable: false
---
Read `engineering/PI_FIRST_CLASS_PLAN.md` and Pi CLI/extensions docs in official repo.

**Exclusive ownership:** new `repoquill/pi/bridge.py`, `repoquill/pi/extension.ts` (or a small adjacent Pi extension directory), `tests/test_pi_bridge.py`. Coordinate an interface with Pi RPC and Pi Integration. Never edit Python `repoquill/agents/tools.py` without integration owner approval.

Pi must expose the **real existing** RepoQuill tools: `list_files`, `read_file`, `search_code`, `inspect_api`, `inspect_tests`, eligible `run_example` and `write_doc`, delegating to Python `RepoQuillTools` via a narrow per-process authenticated local IPC bridge, or a simpler auditable equivalent. Preserve source reads, evidence capture, allowlisted doc staging writes and run_example result shape. No duplicate tool implementation unless strictly needed.

Run Pi with `--no-extensions --no-skills --no-prompt-templates --no-context-files --no-mcp` and explicitly load only the vetted extension. Restrict tools with an allowlist; never offer built-in `bash`, `edit` or `write` to the model. Note: extension code itself runs with host process privileges; enforce permissions in Python tool dispatch and OS/process isolation. Reject absolute/outside paths, symlink escapes, malicious slugs and edits to source/other docs. Do not import user project instructions or arbitrary local Pi resources from untrusted repositories.

Tests: traversal, symlink, source edit, secrets redaction, missing bridge, forged request, successful ≥2 tool inspections and staged doc write from a real Pi invocation if available.
