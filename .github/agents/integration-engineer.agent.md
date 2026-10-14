---
name: RepoQuill Integration
description: Integrate worker-owned reliability, impact and validation APIs into the RepoQuill CLI and page generator
user-invocable: false
---
Own **shared orchestration integration** only: `repoquill/cli.py`, `repoquill/narrative.py` and integration tests `tests/test_autopilot_integration.py`. Do not modify files owned by parallel specialists.

Read `engineering/AUTOPILOT_PLAN.md` and align early on APIs with Reliability, Impact, Verification, Runtime, Skill and CI workers. Prefer small adapter changes rather than a disruptive rewrite of `cli.py`. Make `repoquill generate/build` fail nonzero when required pages fail or mandatory validation fails. Store success state only after validated completion; preserve old content until promotion. Ensure `--no-llm` remains a valid deterministic mode and the new agent runtime is optional.

Implement an incremental end-to-end slice as soon as Reliability + Verification contracts exist. Test stale page retry, no-op, partial worker failures, quality-gate failure retaining previous docs, successful build, legacy config and multi-config status propagation. Run focused tests locally; coordinate CI's exit-code contract. Never call publish from a local experiment.
