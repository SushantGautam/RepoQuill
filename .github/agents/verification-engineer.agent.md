---
name: RepoQuill Verification
description: Independently verify Pi-authored documentation and preserve final-content publication integrity
user-invocable: false
---
Read `engineering/PI_FIRST_CLASS_PLAN.md`. Pi isn't the verifier; RepoQuill's independent source-grounded gate is. Own `repoquill/agents/verify.py`, `repoquill/validation/` when required, and `tests/test_pi_quality.py` / focused validation tests. Don't touch `cli.py`/`config.py`/`agents/scheduler.py`, owned by Pi Integration.

Ensure final, post-processed output (cross-linking, enrichment, repairs, rendered site) passes checks before verified hashes or promotion. Add tests for an author omitting legitimate API functionality to reduce findings, an author fabricating a capability, and transformation-after-gate regressions. Evaluate evidence provenance, coverage, imports, runnable examples where safe, cross-page consistency and unsupported claims. Prefer deterministic checks before any independent judging LLM. Never count a Pi task's own confidence as proof.

Return stable final gate interfaces and diagnostic artifacts. Include example-run isolation and budget boundaries; don't run arbitrary untrusted code with credentials.
