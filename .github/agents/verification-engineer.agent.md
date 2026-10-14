---
name: RepoQuill Verification
description: Implement independent documentation release-quality gates, import checks and runnable-example diagnostics
user-invocable: false
---
Implement the **independent validation** workstream. Read current `repoquill/verify.py` and research E51 import-path experiment first; preserve existing experimental verifiers and avoid SimpleAudit-specific rules.

Own: new `repoquill/validation/` files (`imports.py`, `examples.py`, `gate.py` as appropriate) and `tests/test_validation_*.py`. Do not edit `repoquill/verify.py`, `repoquill/cli.py` or `repoquill/narrative.py` (integration owner handles call sites).

Develop an evidence-producing gate with explicit PASS/WARN/FAIL results. At minimum check project imports/reexports statically, parse Python fenced blocks, and safely run explicitly eligible examples in bounded subprocesses only in trusted local environments. Avoid executing arbitrary untrusted example code with credentials or write tokens. Do not treat all prose/partial snippets as runnable; classify snippet eligibility.

Implement fail-closed release decisions for required checks; report structured findings and paths. Include tests for invented root import, namespace package caveat, syntax error, valid snippet, skipped incomplete snippet, timeout, absent optional tools. Provide stable integration signatures and all test results.
