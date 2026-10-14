# RepoQuill — shared coding-agent contract

RepoQuill is a **generic Python documentation maintenance engine**, not a SimpleAudit-specific tool. Its north star is **continuous, verified documentation with no routine human maintenance**: detect source changes, update only affected docs, validate independently, repair failures within a bounded budget, and never publish an unverified candidate.

## Start here
- Read `engineering/AUTOPILOT_PLAN.md` for milestones, ownership, interfaces and acceptance criteria.
- Read `.github/copilot-instructions.md` when running GitHub Copilot in VS Code.
- Read `research/BEST_KNOWN.md` and `research/NEXT_EXPERIMENT.md` before modifying the documented generation/verification behavior. `.claude/CLAUDE.md` defines the preserved research methodology.
- Core code: `repoquill/cli.py` (orchestration), `plan.py` (hash cache), `narrative.py` (LLM pages), `reference.py` (AST/Griffe), `verify.py` / `surgical_verify.py` / `grounding.py`, `site.py` (MkDocs/agent skill), `llm.py`.
- Existing tests: `tests/`. Research evaluations: `research/eval/`.

## Execution policy
1. **Deliver code, not just a plan.** The default is autonomous implementation on `dev` with fast incremental milestones; do not wait for repeated human acknowledgements.
2. **Parallelize only independent file ownership.** Parent coordinates; specialists own disjoint paths. Never let two agents modify the same file concurrently. Put a task and its tests under one owner. When collisions arise, use worktrees/feature branches or serialize that change.
3. **Integrate continuously.** Agree on function contracts before implementation, implement thin vertical slices, and run relevant tests at each handoff. Don't defer integration to the end.
4. **Keep all existing public CLI behavior working.** Preserve `uvx repoquill init`, `repoquill generate`, `build`, `serve`, `plan`, `--no-llm` and existing YAML compatibility unless a tested migration is included.
5. **Fix urgent correctness before optimization:** failed generation advancing successful hashes; missing quality gate; genericity bug in `build_skill_md`; secure CI publishing.
6. **Source of truth is implementation + tests.** A generated page is *not* evidence that its own assertions are correct. Do not hardcode for SimpleAudit. Validate on at least one unrelated package when altering factuality behavior.
7. **Never publish on generation failure.** Use per-page success state, temporary output, independent validation, then atomic publish; retain last-known-good docs when a run fails. Unverified claims must not silently become facts.
8. **Agent code is opt-in, bounded, and scoped to documentation.** Default fast deterministic path; no arbitrary source-code edits, no secret exposure in logs, no unsafe execution of untrusted PRs with write tokens, no irreversible operations.
9. **Fast tests are mandatory, exhaustive reruns are not.** Use focused tests during development and full suite + one offline `--no-llm` integration before merging. Report failing tests explicitly, never declare success from unrun tests.
10. **Do not edit `main`, force-push, or deploy from experiment branches.** Commit coherent, reviewable changes on `dev` (or separate worktrees integrated into `dev`). Keep research outputs and best-known state intact unless measurements justify an update.

## Speed + synchronization
- Launch a **first parallel wave of up to six independent specialists** (reliability, impact, validation, agent-runtime, skill-generator, CI), then a single integration owner for shared orchestration files.
- Each worker reports: file changes, tests actually run, results, API contract, risks, commit/hash.
- Use `python -m pytest -q tests/<focused_test>.py` (or `uv run pytest ...` if supported), then `python -m pytest -q`.
- Parent reports measurable progress by functional milestone, not by number of files.
- If subagent tooling cannot execute in parallel, use separate VS Code agent sessions/worktrees and merge nonoverlapping work; do not claim parallel execution happened unless verified.

## Definition of done for autopilot v1
- Modified Python API / docs source triggers impact detection and appropriate pages regenerate.
- A failed page is retried on the next invocation even when source hashes did not change again.
- A failed validator or build prevents publishing; last-known-good site remains intact.
- Examples/imports are checked, with bounded, evidence-backed automated repair; unknown behavior is flagged rather than invented.
- A generated `SKILL.md` makes no domain-specific claims about an unrelated package.
- Tests cover failures/recovery, incremental no-op, CI permissions, and one cross-repository case.
- `uvx` CLI remains backward compatible; regular runs need not use the agent subsystem.

See `engineering/AUTOPILOT_PLAN.md` for precise worker assignments and integration gates.
