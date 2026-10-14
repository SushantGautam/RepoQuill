# RepoQuill — coding-agent contract (Pi-first milestone)

RepoQuill is a generic, continuously maintained documentation system. **Pi is the intended default, first-class narrative authoring runtime**; RepoQuill retains responsibility for planning, deterministic Griffe/AST API reference, source evidence, scoped tools, concurrency, verification, per-page manifests, and last-known-good publishing. The current on-branch agentic engine is a **homegrown Python tool-calling loop**, NOT Pi. Your coding task is to integrate the actual Pi runtime, not rename or wrap existing code while calling it Pi.

## Source of truth / current state

Read in order: `engineering/PI_FIRST_CLASS_PLAN.md` (active engineering mission), `.github/copilot-instructions.md` (VS Code workflow), `engineering/AUTOPILOT_PLAN.md` (completed/partly completed historical milestones), `research/BEST_KNOWN.md` and `.claude/CLAUDE.md` (research baseline).

At the start of this mission (`dev` was at `19cfcd0854ed1b1c0d4ff9673308877c7c5183aa`; recheck latest HEAD):
- `repoquill/agents/author.py` + `tools.py` + `scheduler.py` + `evidence.py` + `verify.py`: homegrown tool-calling authorship, tools, parallel pages, evidence and checks.
- `repoquill/agents/repair.py`: older bounded documentation repair, separate from authoring.
- `repoquill/config.py`: `llm.agentic.enabled` defaults to false; `cli.py` uses `--agentic`/`--no-agentic` and existing LLM client.
- `repoquill/validation/`, `core/manifest.py`, `core/impact.py`: independent gates, retry state, impact mapping.
- `tests/test_agentic_e2e.py`, `test_agent_*`, `fixtures/miniutil/`: valuable baseline; preserve them.

## Non-negotiable product contract
1. Running `uvx repoquill generate` should select **Pi** by default for agent-authored narratives, not the existing homegrown tool loop and not one-shot LLM prompts.
2. Pi actually runs: spawn Pi in `--mode rpc --no-session`, send RPC JSONL commands, observe tool events and `agent_settled`, and consume the staged artifact. Mock-only code does not satisfy this.
3. Keep `--no-llm` deterministic reference generation. Explicit `engine: python-agent` or `engine: legacy` can opt out; older `--agentic` flags are compatibility aliases or clearly migrated. Never silently fall back from Pi failure to another engine.
4. Keep the Python `uvx` entry point and no Node dependency for deterministic modes. For Pi mode, manage/discover/version-pin the required runtime, diagnose missing Node/Pi cleanly, and provision Pi in CI. No unreviewed installation script or silent global upgrade.
5. Reuse the existing Python evidence, ToolRegistry semantics, AST/Griffe extraction, verification, scheduling, and manifest. Do not reimplement a second documentation engine around Pi.
6. Pi is a coding harness, but documentation tasks are **docs-only**. Do NOT grant its default `bash`, `edit`, or `write` tools in ordinary unattended runs. Explicitly disable discovered/user/project extensions, skills, prompts, MCP and contexts where possible; load only RepoQuill's vetted extension bridging allowlisted tools, with source read-only and writes limited to staged documentation. Defense in depth: isolated filesystem/process credentials, not merely tool-name filtering. Example execution is opt-in, resource-limited, isolated and credential-free.
7. Pi's model inherits RepoQuill `llm.provider` / `model` / `base_url` / `api_key_env` where representable. Support self-hosted OpenAI-compatible Qwen using a generated temporary Pi provider configuration with environment references (not credentials embedded in tracked files). Match tested endpoint behavior; do not assume every OpenAI-compatible endpoint supports native tool calls or identical sampling.
8. Independent final verification must run **after all transformations** (cross-links, enrichments, repairs, index/site generation as applicable), and record fingerprints only for final verified output. Never publish incomplete, hallucinated or failed work. Retain last-good artifacts.
9. Preserve existing public CLI/config/reusable-workflow behavior or add documented, tested migration. Do not hardcode SimpleAudit; validate RepoQuill, `fixtures/miniutil` and one unrelated package.
10. During implementation, work on `dev` ONLY. Don't force-push, update `main`, or deploy without explicit user instruction. The old branch was accidentally merged early; never repeat that.

## Parallel coding policy
Delegate **genuinely independent** work concurrently to: Pi RPC, Pi Tool Bridge, Pi Models, Pi Bootstrap/CI, Pi Quality, Pi Integration. Profile instructions in `.github/agents/` and exact write ownership in `engineering/PI_FIRST_CLASS_PLAN.md` override earlier Autopilot ownership (which is historical). Integration owner alone touches `repoquill/cli.py`, `config.py`, `agents/scheduler.py` and existing `agents/author.py`. Never have independent agents edit overlapping files. Use separate worktrees/branches for concurrent commits and integrate continuously after agreeing on types and failure semantics.

Implement production-thin end-to-end first, not a framework comparison or documentation-only plan. Run focused tests, full `python -m pytest -q tests/`, then a **real Pi RPC tool-calling E2E** against a disposable fixture with controlled model endpoint when available. Fake models test protocol and failures; real Pi is required for claiming integration. Avoid expensive repeated model benchmarks in the inner loop.

Every worker reports owned files, contract, actual test commands/results, risks, and commit. Parent reports implemented vs planned honestly. Keep research baseline unchanged unless measured evidence supports updates. Never claim elapsed time, tests, or parallel execution that did not occur.

For the immediately executable brief use `.github/prompts/pi-first-class-fleet.prompt.md`.
