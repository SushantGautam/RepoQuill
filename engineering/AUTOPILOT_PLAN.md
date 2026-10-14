# RepoQuill Autopilot — implementation mission (dev)

**Date:** 2026-10-14
**Target branch:** `dev` (created from `main`)
**Objective:** Continuous verified documentation without routine human intervention: detect source/behavior changes, update affected docs, validate claims/examples, self-repair bounded failures, and publish only passing versions.

This is an **implementation program**, not authorization to claim work is already built. Research history remains in `research/`; `research/NEXT_EXPERIMENT.md` (E51 import resolution) is a relevant existing experiment. Keep genericity: improvements must help unrelated Python libraries, not merely SimpleAudit.

## What currently exists

- `repoquill/cli.py`: 6-stage generator, `build`/`serve`/`plan`/`init` and LLM config scaffold.
- `repoquill/plan.py`: page list and file SHA hashes; `docs/.plan.json` cache.
- `repoquill/narrative.py`: optional parallel LiteLLM page generation.
- `repoquill/reference.py`: Griffe/AST reference, API surface and source links.
- `repoquill/verify.py`, `surgical_verify.py`, `grounding.py`: correctness corrections; optional LLM-based passes.
- `repoquill/site.py`: MkDocs, `llms.txt`, generated `SKILL.md`.
- `.github/workflows/reusable.yml`: cross-repo build+commit+Pages publishing.
- `research/eval/`: factuality, coverage, claims, example and usability research checks; not yet a required production quality gate.

## Verified code-level blockers

### P0 — correctness and unattended trust

1. `narrative.generate_all_pages` returns successful slugs but its caller in `cli._cmd_generate` does not treat failed pages as a fatal generation result; `store_plan` still receives new hashes, potentially marking stale documents fresh. Ensure failures propagate, successes persist per page, failed pages retry without any new code change.
2. `config.LLMConfig.verify_passes` defaults to 0 and `grounding_pass` false; no release-wide mandatory verification gate. Separate writer/repair from independently scored validation; fail closed for required checks.
3. `site.build_skill_md` contains hardcoded audit/judge/scenario claims for **every** repository. Replace with evidence-derived, domain-generic skill.
4. Candidate generated documents are written directly to output before validation; design staging and last-good preservation, including safe handling of existing manual docs.
5. `.github/workflows/reusable.yml` both runs generation and directly pushes files; publishing from inappropriate trigger contexts risks secrets/permissions and races. Separate read-only PR validation from trusted publishing.

### P1 — change intelligence and self-healing

6. File-hash cache misses cross-file behavioral dependencies; implement conservative AST symbol/export/import graph with per-page evidence fingerprints.
7. Detect import and executable-example mistakes; build a structured required-check gate rather than an LLM confidence score. E51's import-path verification can be generalized here.
8. Add opt-in bounded docs-only repair workers, not an always-running unconstrained general coding agent.
9. Daily reconciliation / explicit schedule for source drift, broken links and missed updates; opt in per consuming repository to avoid unwanted API costs.
10. Avoid needless rewrites and LLM calls; known-safe deterministic corrections first.

### P2 — performance and quality

11. Structured run report (changed symbols, rebuilt pages, validated examples, repairs, cost, last-good commit).
12. Budget-aware batching, concurrency/backoff, optional local model, evaluation across repositories.
13. Document compatibility and portability beyond Python as a future milestone, not a v1 rewrite.

## Parallel ownership — wave 1 (launch simultaneously)

| Agent | Write-owned paths | Required deliverable |
|---|---|---|
| **RepoQuill Reliability** | `repoquill/plan.py`; new `repoquill/core/manifest.py`; `tests/test_manifest.py`, `test_plan_recovery.py` | per-page success fingerprint, retry-safe state, atomic manifest |
| **RepoQuill Impact** | new `repoquill/core/impact.py` / `dependencies.py`; `tests/test_impact.py` | AST diff, source-to-page affected set, conservative fallback |
| **RepoQuill Verification** | new `repoquill/validation/`; `tests/test_validation_*.py` | import/example checks, structured fail-closed quality gate |
| **RepoQuill Runtime** | new `repoquill/agents/`; `tests/test_agent_runtime.py` | bounded docs-only task/repair runtime, optional LLM |
| **RepoQuill Skill** | `repoquill/site.py`; `tests/test_skill_generic.py` | genuinely generic `SKILL.md` |
| **RepoQuill CI** | `.github/workflows/reusable.yml`, `docs.yml`; `tests/test_workflow_contract.py` | safe triggers, permissions, trusted publish |

**Reserved exclusively for integration owner:** `repoquill/cli.py`, `repoquill/narrative.py`, `tests/test_autopilot_integration.py`. Only the parent/integrator touches these files. Research files have a separate owner; update them only with measurement evidence.

**Shared package setup:** if a worker needs `repoquill/core/__init__.py` or `repoquill/validation/__init__.py` or `repoquill/agents/__init__.py`, establish a single owner first or rely on namespace packages temporarily. Never overwrite another worker's scaffolding.

## Wave 2 — integration immediately as contracts become available

Integration owner performs the following minimal sequence:

1. Agree on a small manifest API (read, `needs_update`, `mark_success`, atomic save), report/result type (passed, failed, skipped, diagnostics), impact API (affected slugs), and optional repair API (candidate patch+diagnostics).
2. Run focused new tests early. On failure, route one bounded fix request to the path owner; don't ask a second agent to race-edit.
3. Add generation success propagation and per-page retry semantics. Prevent the `store_plan` bug. No-LM mode and existing flags must keep working.
4. Generate to staging (or use temporary output + atomic promotion) so failed candidates never replace last validated docs.
5. Feed changed symbols through impact mapping; regenerate affected guide pages, update reference/index and stale pages where needed. Conservative fallback ensures no stale docs silently remain.
6. Run validator(s) on candidate; optionally invoke docs-only repair worker, then **independently** validate again. Required failure => nonzero exit, previous published site remains.
7. Wire CLI status into CI. Protect LLM credentials and publishing rights from untrusted PRs.

## Quality and safeguards

- **No test theater.** Don't assert all tests pass without running them. Initial quick loop: `python -m pytest -q tests/<focused>.py`; integration: `python -m pytest -q`; `python -m repoquill.cli generate --no-llm --build --config repoquill.yml` from a **temporary target location** to avoid modifying tracked docs. A test with LLM may run only when credentials and budget are available.
- **No claims from generated docs as evidence.** Resolve imports/annotations/source bodies and real behavior. Static checks may have uncertainty; unknown facts should be flagged rather than auto-invented.
- **No arbitrary code execution in privilege-bearing workflows.** Untrusted examples run in restricted, credential-free environments with time/resource limits, or are statically checked only.
- **No cross-agent file conflicts.** Parallelize paths, not overlapping edits. Commit scoped work; integrate compatible commits once per gate.
- **No uncontrolled deployment.** Normal local experimentation must never trigger GitHub Pages or push generated docs to `main`.
- **Keep compatibility.** Python >=3.9, current CLI flags, current `repoquill.yml` semantics, reusable workflow contracts unless an explicit migration is supplied.
- **Research rigor with short cycles.** Preserve best-known baseline, use one unrelated Python repository for factuality changes, record actual comparisons. Do not block P0 engineering on numerous broad repeated benchmarks.

## Milestone gates and stop conditions

**M1 / P0 working:** failed page retries; per-page state stays accurate; generic `SKILL.md`; required errors block publishing; old docs preserved. Focused failure-injection tests and basic docs build pass.

**M2 / semantic maintenance:** signature/import/export changes invalidate affected pages, unrelated modifications don't trigger LLM, page graph is conservative and measurable. Tests cover renames/removals/reexports/defaults.

**M3 / agentic repair:** repair agent fixes a deliberately broken generated import/example within a bounded budget and validator verifies the fix, while unsafe/no-evidence repairs fail closed. Agents cannot touch application source.

**M4 / autonomous CI:** PR checks run read-only, trusted merge publishes only validated artifacts, scheduled reconciliation recovers missed work, no loop/push race. Demonstrate via tests/verified GitHub workflow runs if available.

### Completion report

- Current `dev` SHA; accepted commits/changes by agent
- Working end-to-end commands, tests executed/results, measurement comparisons
- What is genuinely automatic versus still manual
- Remaining blockers ordered by severity
- Next 1-3 implementation tasks (then continue, don't stop at planning)

For ready-to-run instructions see `.github/prompts/autopilot-fleet.prompt.md`.
