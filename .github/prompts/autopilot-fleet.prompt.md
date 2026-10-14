---
description: Launch a multi-agent parallel coding fleet to implement RepoQuill Autopilot on dev
agent: RepoQuill Orchestrator
---
Implement **RepoQuill Autopilot** on the current `dev` branch. This is an **execution request**, not a request for another roadmap.

First read `AGENTS.md`, `.github/copilot-instructions.md` and `engineering/AUTOPILOT_PLAN.md`, plus existing `.claude/CLAUDE.md` and research best-known state. Inspect the actual code before making changes.

**Start a genuinely parallel first wave immediately**, using the available subagent/task tools and workspace custom agents:
- @RepoQuill Reliability — per-page success manifest, retries, atomic state (`plan.py`, new `core/manifest.py`, focused tests).
- @RepoQuill Impact — AST/symbol/export API diffs and conservative affected-page graph (new `core/impact.py` and tests).
- @RepoQuill Verification — independent structured import/example/quality gates (new `validation/` and tests).
- @RepoQuill Runtime — optional bounded documentation-only repair agents (new `agents/` and tests).
- @RepoQuill Skill — replace hardcoded auditing-specific SKILL.md generation with generic evidence-grounded project skill (`site.py` and tests).
- @RepoQuill CI — safe PR validation, permissions, concurrency, and last-good trusted publishing (GitHub workflows and tests).

Use exact **file ownership** from `engineering/AUTOPILOT_PLAN.md`. Each worker should start implementing now, produce code + focused passing tests, and report signatures/changes. Don't have workers edit each other's files. If parallel subagents are unavailable, use independent VS Code agent sessions/worktrees and integrate results; say when concurrency was not supported.

Reserve `repoquill/cli.py` and `repoquill/narrative.py` for the single integration owner. Begin integration as soon as the manifest and validation APIs are available, while the remaining specialists are still coding. Integrate early, not at the end.

Priority: **P0 reliability and secure publication**, then precise change detection, then optional repairs, then scheduled reconciliation. Implement thin vertical slices. Never stop at scaffold-only output. Keep `uvx repoquill init`, `repoquill generate/build/serve/plan` and `--no-llm` compatible. Preserve genericity and existing research baseline.

Explicit must-fix: currently a failed generated page can still have new hashes committed by `store_plan` and be incorrectly skipped on the next run. Also `build_skill_md` contains SimpleAudit-like auditing language for every package. Missing required validation must prevent publication.

Maintain a compact owner/status board and continually reconcile worker outputs. After each integration gate, run focused tests then `python -m pytest -q`, plus a real local build without publishing. Fix failures automatically. Don't run costly repeated full LLM experiments unnecessarily, but never skip essential correctness checks. Only claim test results you actually observed.

Keep `main` unchanged; commit coherent results on `dev`. Don't enable privileged auto-approval or run untrusted PR code with production credentials. Use bounded, docs-only agents with verifiable patch outcomes.

**Definition of done:** an API change causes correct affected docs to update; failed pages retry; no stale generated page is marked current; validators block bad publication and preserve last-good docs; example/import repair succeeds when evidence permits; unrelated Python projects receive a generic SKILL.md; CI is safe. Report concrete changed files, commit hashes, measured tests, known limitations, and next steps. Continue coding rather than presenting another proposal.
