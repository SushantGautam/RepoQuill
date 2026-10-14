---
name: RepoQuill Reliability
description: Implement retry-safe generation state, per-page manifests and atomic candidate promotion without editing orchestration files
user-invocable: false
---
Implement the **P0 reliability workstream** in `engineering/AUTOPILOT_PLAN.md`.

Own: `repoquill/plan.py`, new `repoquill/core/manifest.py` and `tests/test_manifest.py` / `tests/test_plan_recovery.py`. Do **not** edit `repoquill/cli.py` or `repoquill/narrative.py` (integration owner handles them).

Build minimal stable APIs for a per-page manifest tracking inputs, attempted version, successful version, validation and publish state. Preserve the current public plan functions for backward compatibility, and define migration behavior for existing `docs/.plan.json`. Ensure failed generation does not mark a page current, missing output forces retry, old plan formats load safely, and partial/atomic writes do not corrupt the manifest.

Return concrete exported function signatures and integration guidance. Write focused failure-injection tests: one changed page fails, next run retries unchanged inputs; partial generation never advances successful hashes; idempotent no-op preserves hashes. Report actual executed tests and commit.
