---
name: RepoQuill Integration
description: Wire the real Pi RPC runtime into the default CLI/config/scheduler and preserve legacy/no-LLM behavior
user-invocable: false
---
Read `engineering/PI_FIRST_CLASS_PLAN.md`. You alone own `repoquill/cli.py`, `repoquill/config.py`, `repoquill/agents/scheduler.py`, `repoquill/agents/author.py` if needed, `repoquill/narrative.py`, plus `tests/test_pi_integration.py` and CLI docs. Other workers implement Pi RPC, tool bridge, model mapping and bootstrap; contract first, integration immediately.

Required: `repoquill generate` defaults to `pi` for narrative authoring. `--no-llm` remains deterministic; config `engine: python-agent` or `engine: legacy` explicitly selects old runtimes; existing `--agentic` compatibility behavior is documented and tested. Pi missing or failing must not silently fall back or mark stale docs verified. Preserve 1:1 page task / result / evidence/manifest mapping and bounded parallel workers.

Keep end-to-end staging and last-known-good semantics: all changes and postprocessors complete before independent final gate and success fingerprint. Reuse existing AST/Griffe reference generation. Show real Pi tool event trace and validated produced docs in the happy-path E2E (mock tests are necessary but insufficient). Preserve existing config compatibility and CLI flags as appropriate.

Never touch `main` or any worker-owned Pi runtime files; coordinate patches/tests continuously.
