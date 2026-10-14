---
name: RepoQuill Pi Quality
description: Measure Pi authoring success and prevent low-coverage or unverified generated documentation
user-invocable: false
---
Read `engineering/PI_FIRST_CLASS_PLAN.md`. Coordinate with existing RepoQuill Verification profile and use separate ownership.

**Exclusive ownership:** new `tests/test_pi_quality.py`, `tests/test_pi_agentic_e2e.py` and a concise `engineering/PI_EVAL_RESULTS.md` only when actual evidence exists. Changes to `repoquill/agents/verify.py` or `repoquill/validation/` must have one explicit owner (RepoQuill Verification profile).

Define deterministic fixtures that verify default engine selected Pi, ≥2 real tool calls, docs-only write, coverage threshold, correct symbol import/usage, final gate timing, incremental no-op/one-page re-gen, unavailable Pi, RPC timeout, last-good restoration and explicit legacy fallback. Benchmark Pi versus existing Python-agent and one-shot generator on `fixtures/miniutil` and at least one unrelated package; measure substantive coverage, unsupported claims, broken examples, model requests/tokens and elapsed time. Do not claim Pi is superior without observed measurements.

Make tests fast (fake RPC client) plus a separate opt-in real Pi/model smoke. Clearly report skipped real tests where credentials or binary unavailable. Never publish docs based on agent self-assessment.
