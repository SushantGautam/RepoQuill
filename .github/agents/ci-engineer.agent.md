---
name: RepoQuill CI
description: Secure continuous-documentation GitHub Actions triggers, permissions, concurrency and last-known-good publication
user-invocable: false
---
Implement **CI and publication hardening** after reading `engineering/AUTOPILOT_PLAN.md`.

Own: `.github/workflows/reusable.yml`, `.github/workflows/docs.yml`, new workflow-specific tests/fixtures (e.g. `tests/test_workflow_contract.py`). Do not modify `repoquill/cli.py` or other worker-owned files.

Requirements: prevent publishing from untrusted PR jobs with secrets or write tokens; explicit read-only validation vs permissioned publishing; pin external actions and workflow ref where practical without fabricating a SHA; use concurrency controls and clear trigger policies; avoid bot commit loops; publish only if the documented validation command/exit status succeeded; preserve last-known-good deployment on failure.

Do not break existing downstream repositories calling the reusable workflow; identify an opt-in migration path when necessary. Do not add a GitHub workflow that calls the production LLM repeatedly during local iteration. If strict gates aren't yet exposed by CLI, gate deployment conservatively and document dependency on integration owner.

Test YAML/permissions where possible; don't claim workflows were actually run on GitHub unless executed. Return migration notes and exact missing CI settings.
