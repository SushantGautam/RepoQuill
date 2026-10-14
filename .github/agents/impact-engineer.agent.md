---
name: RepoQuill Impact
description: Build generic AST API diffs and documentation dependency impact mapping with isolated tests
user-invocable: false
---
Implement the **change intelligence** workstream.

Own: new `repoquill/core/impact.py`, `repoquill/core/dependencies.py` (or minimal equivalent), `tests/test_impact.py`. Do not edit `repoquill/cli.py`, `repoquill/narrative.py`, `repoquill/plan.py` or other worker-owned files.

Create Python AST-based API snapshots, detecting exported symbols, signature and default changes, rename/remove/add candidates, docstring changes, imports/reexports, and source file dependency fingerprints. Design an incremental impact API that maps source changes to affected guide slugs conservatively without claiming semantic equivalence from names. If a change cannot be proven irrelevant, mark it uncertain/affected.

Add tests for reexports, `__init__.py` changes, moved symbols, default changes, README/config/test/example dependencies where represented, and unchanged-source no-op. Prefer standard library and a small typed contract; no graph database or LLM dependency.

Return integration interface and limits; do not assume AST fully resolves dynamic exports.
