---
name: RepoQuill CI
description: Configure trusted RepoQuill CI to provision pinned Pi and publish only independently verified docs
user-invocable: false
---
Active milestone: `engineering/PI_FIRST_CLASS_PLAN.md`. Own `.github/workflows/reusable.yml`, `.github/workflows/docs.yml`, `.github/workflows/publish.yml` as needed, and `tests/test_pi_ci.py` / workflow contract tests. Do not touch core runtime/CLI/model files.

CI should install a verified pinned Pi package/version with compatible Node.js, then call the same default `repoquill generate` pipeline as local runs. Keep current read-only validation/trusted publication split, concurrency safety, last-known-good behavior and no publication on failed model/runtime/gate. Don't introduce a secret-bearing untrusted PR execution path, user-global Pi extensions or arbitrary postinstall commands. Keep credentials out of artifact/log outputs. Keep no-LLM jobs viable without Pi and indicate missing credentials/Pi clearly.

Test workflow static contracts and, when permissions permit, verify real workflow behavior. Don't claim CI deployed until an actual successful run.
