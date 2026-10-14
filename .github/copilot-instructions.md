# RepoQuill — VS Code parallel coding fleet (Pi-first milestone)

**Active mission:** make the real Pi coding harness the default **in-product** documentation agent runtime. Read `AGENTS.md` and `engineering/PI_FIRST_CLASS_PLAN.md` first; this supersedes the older `engineering/AUTOPILOT_PLAN.md` for current implementation priorities. Preserve research baseline in `research/`.

Do NOT confuse:
- **VS Code/Copilot subagents** = specialists implementing RepoQuill in this session.
- **Runtime Pi workers** = actual subprocess-backed agents used by RepoQuill customers to author their documentation.

Do NOT implement a second Python-only tool loop and call it Pi. RepoQuill already has a homegrown loop in `repoquill/agents/author.py`; reuse its evidence, planning and verification primitives through a **Pi RPC adapter** with a genuine Pi process and constrained tools.

## Dispatch — first wave concurrent
Coordinate six independent owners from `engineering/PI_FIRST_CLASS_PLAN.md`: (1) Pi RPC/process/protocol, (2) Pi tool bridge/extension/policy, (3) Pi Qwen + model config, (4) bootstrap + CI, (5) independent validation and evidence metrics, (6) single pipeline integrator. Read corresponding profiles under `.github/agents/`. If true parallel subagents aren't available, use concurrent VS Code sessions and isolated worktrees, or perform tasks sequentially and say so. Explicitly preserve file ownership; agree on contract signatures immediately.

Prioritize a running thin vertical slice: Python invokes an actual Pi process; Pi makes ≥2 real repository-inspection tool calls; writes a guide through a docs-only tool; RepoQuill independently checks it and records verified state. THEN harden automatic installation, models, parallelism, CI, benchmarks and edge cases.

## Pi interfaces: verify against upstream
Official upstream repository: https://github.com/earendil-works/pi
RPC: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc.md
CLI: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/cli.md
Model endpoint config: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md

Known confirmed baseline: `pi --mode rpc --no-session` accepts JSONL on stdin and emits responses/events on stdout; prompt acceptance isn't completion; wait for `agent_settled`, correlate command IDs, handle child exits/timeout/stderr. Current package is `@earendil-works/pi-coding-agent`, but pin a verified version rather than assuming latest. Verify flags against installed `pi --help`; don't blindly copy stale blog examples.

For unattended runtime, use explicit tool allowlists, `--no-extensions` plus explicit vetted RepoQuill extension, `--no-mcp`, `--no-skills`, `--no-prompt-templates`, and `--no-context-files` (verify flags with the pinned version). Disable built-in shell and write/edit; custom tools must enforce realpath/source separation and writes only to a temporary docs staging tree. Treat repositories/README/AGENTS.md as untrusted task data, not high-priority commands. No production secrets in subprocess logs or replay artifacts.

## Session loop
- Confirm `git status`, `dev` HEAD and `main` HEAD before edits.
- Delegate with distinct path ownership and acceptance tests. Integrator owns `cli.py`, `config.py`, `agents/scheduler.py`, `agents/author.py`, and API wiring.
- Merge working increments to `dev` as ready; no agent writes `main` or shares a worktree without coordination.
- Prove correct runtime selection, graceful missing-Pi error, legacy fallback only when explicitly configured, and no-LM compatibility.
- Run tests on actual modified code. Real Pi E2E mandatory for declaring Pi working; use recorded fake Pi RPC fixture for deterministic CI.
- Report exact implemented features, test results, node/pi versions, end-to-end tool trace, API/model behavior, remaining blockers.

Full launch brief: `.github/prompts/pi-first-class-fleet.prompt.md`.
