# RepoQuill / VS Code Copilot operating instructions

Read `AGENTS.md` and `engineering/AUTOPILOT_PLAN.md` first. Follow them as authoritative shared project instructions. Preserve the ongoing independent research protocol in `.claude/CLAUDE.md` and `research/`.

**Mission:** turn RepoQuill into self-healing, continuously verified documentation. Implement rather than only suggest changes. Work on `dev`; never write to `main` or publish a site during local experimentation.

## Use a coordinated parallel fleet
- In an Agent session, delegate independent, bounded implementation jobs immediately when parallel subagents are supported. Ask explicitly for *concurrent* execution; don't serially wait for independent agents.
- Workspace specialist profiles live in `.github/agents/`. Call the named agent when supported, otherwise delegate equivalent scoped tasks. These are **development agents**; the production mini-agent runtime inside RepoQuill is a separate optional feature.
- Assign disjoint file ownership from `engineering/AUTOPILOT_PLAN.md`. Let the integration agent own `repoquill/cli.py` and `repoquill/narrative.py` exclusively.
- Use branch/worktree isolation if multiple sessions may collide. Never silently overwrite another agent's edits or perform uncontrolled merges.
- Prefer small working vertical slices and early integration. Do not spend the whole session on framework comparisons, broad refactors or planning documents.
- Run small, relevant tests before every handoff. Capture real results. Keep fixes generic and measure against non-SimpleAudit repositories.

## Implementation guidelines
- Python >=3.9 per current pyproject, unless an intentional tested compatibility change is made. No unnecessary heavy runtime dependencies.
- Keep deterministic verification and LLM/agent repairs clearly separated. Validation gates must execute independently of a writing LLM.
- Commit only intentional source/config/test changes. Avoid generated site changes, accidental `docs/.plan.json` churn and research experiment output churn.
- Log failures clearly and preserve last-good published docs. A "success" exit code must mean required pages and checks succeeded.
- No silent fallback from failed generated content to stale content marked as fresh.
- For CI, isolate untrusted PR read/test jobs from secret-bearing publishing jobs.
- No generic or fabricated imports, example arguments, capabilities, credentials, benchmark scores or undocumented APIs.

## Concrete workflow
1. Confirm branch + repository state. Read latest plans.
2. Dispatch the six owner-scoped tasks concurrently; record ownership.
3. Have the integration owner prepare contracts/tests without editing worker-owned files.
4. Reconcile changes, run fast tests, end-to-end `--no-llm` and one LLM test when credentials exist.
5. Report implemented features, commands/tests, known gaps and exact next tasks. Continue fixing blockers rather than stopping at a high-level roadmap.

Launch prompt lives at `.github/prompts/autopilot-fleet.prompt.md`.
