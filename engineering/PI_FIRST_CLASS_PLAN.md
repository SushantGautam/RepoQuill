# Pi-first RepoQuill — implementation brief

**Created:** 2026-10-14
**Target:** current `dev`, initially `19cfcd0854ed1b1c0d4ff9673308877c7c5183aa`. Recheck live HEAD; `main` was `9ac000b5aa009c44c60fe21b98fc34d0c2e91ec4`. Do not push or merge `main`.
**Mission:** Replace default narrative generation with a **real Pi coding-agent harness** embedded in RepoQuill. Keep the Python app, `uvx` UX, Griffe/AST docs, planning/impact, verification and publishing. **First-class means Pi runs and authors pages through tool calls.** Merely routing more messages through `LLMClient.chat_with_tools` is not Pi integration.

## Confirmed current foundation — reuse, do not rebuild

- `repoquill/agents/author.py`: custom Python tool loop with `chat_with_tools`; `tools.py`: path-scoped `RepoQuillTools`; `contracts.py`: tools/budgets; `evidence.py`: deterministic evidence; `scheduler.py`: parallel pages; `verify.py`: independent checks; `repair.py`: bounded fallback repairs.
- `repoquill/config.py`: current `llm.agentic.enabled = false` and `--agentic`/`--no-agentic` CLI; current engine is opt-in, custom Python, not Pi.
- `repoquill/core/manifest.py` + `impact.py`: retry-safe state and affected-page mapping. `repoquill/validation/`: deterministic gate; final gate ordering was recently fixed in CLI; verify against HEAD.
- `fixtures/miniutil/` and `tests/test_agentic_e2e.py`: cross-project regression fixture.
- Older `engineering/AUTOPILOT_PLAN.md` describes the earlier Autopilot implementation; don't repeat its already-completed P0 tasks.

## Reference integration interface: official Pi

Upstream: https://github.com/earendil-works/pi
RPC: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc.md
CLI: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/cli.md
Custom models: https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md
Official npm distribution as of this brief: `@earendil-works/pi-coding-agent` (pin a tested version; package names/version/flags may change).

- Launch Pi as a subprocess: `pi --mode rpc --no-session`, with verified version and audited startup flags.
- RPC is LF-delimited JSONL; send `{"id":"p1","type":"prompt","message":"..."}`; command response confirms accepted command **not** completed agent work. Read stream to `agent_settled`, observing tool events; correlate IDs and handle stderr/EOF/deadlines/cancellation; record a sanitized tool trace.
- Pi normal default tools include unrestricted `read`, `write`, `edit`, `bash`. **Never run those defaults in production documentation jobs.** Start with explicit allowlist restricted to a RepoQuill vetted extension/bridge (or approved read tools only on an isolated snapshot); use `--no-extensions` with explicit `--extension`, `--no-mcp`, `--no-skills`, `--no-prompt-templates` and `--no-context-files`. Verify with `pi --help` for the pinned version.
- SDK is a Node-first alternative. Prefer RPC because RepoQuill is Python. Only introduce a tiny Node/TypeScript extension for custom tools; avoid moving the whole app to JavaScript.
- To support custom OpenAI-compatible Qwen/vLLM/SimulaChat, generate ephemeral Pi model/provider configuration with `api: openai-completions` and existing `llm.model`, `base_url`, `api_key_env`; preserve secrets as env references, not committed strings. Confirm actual tool-call + streaming compatibility and sampling behavior against endpoint.

## Architecture / contracts

`repoquill/cli.py`: CLI/engine selection, detect changes, build references, plan tasks
→ `repoquill/agents/scheduler.py`: parallel page tasks, existing evidence packs
→ `repoquill/pi/rpc.py`: Pi process per task, start/send/stream/wait/stop
↔ `repoquill/pi/extension.ts` + `repoquill/pi/bridge.py`: narrowly authenticated IPC bridge translating Pi custom tool requests into existing `RepoQuillTools` for file list/read/search, API/test inspection, eligible example runs, staged `write_doc`.
→ existing `repoquill/agents/verify.py` and `repoquill/validation` run independently after **all** content post-processing
→ `core/manifest.py` records per-page success fingerprint only after checks; MkDocs build/publish last-good only on success.

Use small data contracts: `PiTask` (slug/title/description/evidence + readonly source root + staged docs root + model + budget), `PiRunResult` (completed, tool calls, source paths, staged output, token/request/cost metrics if Pi reports them, elapsed, errors, process version), and `PiBackend` interface. Reuse existing `PageTask` and `PageOutcome` where possible rather than inventing redundant types. Send structured results through the existing run report.

**Security:** Pi extension code executes inside the host Pi process. Tool policies alone are not an OS sandbox. Ensure source is mounted read-only or copied to a readonly snapshot in untrusted CI, staging separate from source, no inherited secrets beyond necessary model credential, blocked user Pi resources, no dangerous built-in tools. The Python bridge independently validates realpaths and symlink traversal. Example subprocess `-I` alone does NOT block filesystem/network access; use real container/sandbox or disable execution in untrusted contexts. No user-provided repo instructions override product security instructions.

## Default behavior and compatibility

User-facing intended behavior:

`uvx repoquill init` → config scaffolding picks/defaults Pi as `documentation.engine: pi` (config key placement finalized by integration owner).
`uvx repoquill generate` → default Pi for narratives, deterministic references.
`uvx repoquill generate --no-llm` → deterministic docs, no Pi/Node requirement.
`uvx repoquill generate --engine python-agent` → explicit fallback to current custom agentic loop (name may be `--engine` or config; implement consistently).
`uvx repoquill generate --engine legacy` → current one-shot narrative generator.
`uvx repoquill doctor` / `uvx repoquill init --setup-pi` → suggested setup UX, implement only as supported by CLI, verified Node/Pi and permission model.

For old configs using `llm.agentic.enabled: true` preserve intent by mapping to Python-agent or transparently documenting migration; **do not silently change existing consumers to another runtime without communication**. A fresh config defaults to Pi; consider explicit legacy selection for existing configs to preserve backward compatibility. Clearly distinguish fresh-install defaults vs migration defaults in tests. Never silently fall back from Pi failure to lower-quality docs; fail closed and report how to override.

Use a pinned, auditable Pi version, not `npm install -g ...@latest` at runtime. For a Python-only user, `uvx` may provision the optional Pi payload to an app cache if permission/network available; do not silently execute external install scripts. Provide useful self-service `doctor` instructions and preprovision CI. Preserve `--no-llm` without Node.

## Parallel wave — start immediately with mutually exclusive ownership

| Specialist | Exclusive paths | Deliverable |
|---|---|---|
| Pi RPC | `repoquill/pi/__init__.py`, `rpc.py`, `protocol.py`, `tests/test_pi_rpc.py` | production JSONL process supervisor and event trace |
| Pi Bridge | `repoquill/pi/bridge.py`, `extension.ts`, `tests/test_pi_bridge.py` | actual Pi tools delegated to Python RepoQuillTools with security |
| Pi Models | `repoquill/pi/models.py`, `tests/test_pi_models.py` | ephemeral Pi config + Qwen/OpenAI-compatible auth |
| Pi Bootstrap | `repoquill/pi/bootstrap.py`, `tests/test_pi_bootstrap.py`; coordinate `pyproject.toml` | versioned discovery, setup/doctor, no-LLM path |
| Pi Quality | `tests/test_pi_quality.py`, `tests/test_pi_agentic_e2e.py`, results once measured | compare coverage and prove actual authoring |
| Pi Integration | ONLY `repoquill/cli.py`, `config.py`, `agents/scheduler.py`, `agents/author.py` if needed, `narrative.py`, `repoquill.yml`, `README.md`, `tests/test_pi_integration.py` | default Pi and compatibility, staged integration |

Reserve `repoquill/agents/verify.py`, `repoquill/validation/*` for one named validation owner, and `.github/workflows/*` + workflow contract tests for a single CI owner, after core APIs stabilize. Do NOT let the test owner and validation owner edit `test_pi_quality.py` concurrently. Package __init__ files belong to the RPC owner; share exported signatures promptly.

## Milestones — thin real E2E before broad refactor

**M0 — contracts (brief):** Agree on PiBackend/PiTask/PiRunResult signatures, model config path, IPC envelope, staging layout, runtime exception/retry taxonomy, version pin and ownership. No large up-front redesign.

**M1 — real Pi tool-use proof:** Start actual Pi from Python, send a documentation task, watch two or more tool calls (real list/search/read/API/test tools), write Markdown into staging by allowlisted tool, wait for `agent_settled`, return a trace and result. Include deterministic fake process tests. If no live LLM key, report unverified live portion, not pretend.

**M2 — default CLI integration:** New project `repoquill generate` selects Pi automatically. Existing Python-agent and legacy modes are explicitly selectable; `--no-llm` works. Multi-page concurrency works with separate Pi sessions; no work done for unchanged pages, retries after failure.

**M3 — reliability/security:** Strict resource/tool confinement, isolated examples or no execution, timeouts/restarts, 502/backoff handling, never marking incomplete pages verified. **Final gate after all transforms**; publish only successful build. Secrets absent from debug logs and artifacts.

**M4 — model/installation/CI:** Qwen via custom OpenAI-compatible Pi model config, supported thinking modes and tool_calls tested; pinned managed Pi install and clean error without Node, trustworthy CI preprovision and no unauthorized publishing.

**M5 — benchmarks:** RepoQuill + `fixtures/miniutil` + one unrelated package. Compare Pi to homegrown Python agent and one-shot legacy: claims supported, feature coverage, runnable examples, token usage, model/tool calls, wall-clock, unchanged-file no-op. Tune default concurrency and context size using real measurements.

## Acceptance tests

1. Fresh config chooses Pi; actual `pi --mode rpc` launches, ≥2 repository tool calls, staged docs write, final gate passes and site builds. Show Pi version and tool trace.
2. `--no-llm` runs without Node/Pi, and explicit `python-agent`/`legacy` flags work without invoking Pi.
3. Missing Pi/Node or broken custom model endpoint gives nonzero actionable error and **last-good output remains**; no silent fallback.
4. Tools cannot edit app source, escape repo via paths/symlinks, read secrets, execute arbitrary shell or write outside staging. No secrets in logs.
5. Changed API regenerates affected pages, unchanged repo makes zero Pi model calls; failed page retries.
6. Post-processing can introduce a broken symbol; final gate detects it before fingerprint/publish.
7. CI read-only validation and trusted publish stay separate; correct pinned runtime installed only where needed.
8. No claims of correctness, tests, metrics or live E2E unsupported by observed results.

**Stop condition:** Implement M1–M4 and run passing acceptance tests, not just stubs. If blocked by external credentials or unavailable Pi binary, report what truly passed, leave a reproducible smoke command, and continue implementing all offline-testable parts. Update `research/` only after measurements.
