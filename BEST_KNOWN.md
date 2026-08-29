# BEST_KNOWN

**Last updated:** 2026-08-29 (after E16)

## Best-Known State

**E8+E9+E10+E13+E13b+E14 (commit 2edd930)** — 54.6% coverage v2 (mean of 3 runs), 0.0% invented-symbol rate, 4.5% honest broken examples
- 11 deterministic pages from `narrative_sections` config
- 0 invented symbol names
- **Coverage metric:** v2 (substantive-mention, E15) — old substring metric inflated by ~10pp
- **E14 metric:** 4.5% of code examples are non-runnable (mean of 3 E14 runs: 2.0/5.7/5.9)
- **E14:** 0 `invalid_kwarg` findings across all 3 runs (baseline had 2). Constructor signatures
  injected into prompt via AST walk.

**E13 (surgical verify pass):** deterministic post-generation edit step. Property-call fix
is genuine. Committed as `18f365d`.

**E13b (placeholder fix):** replaced `<REQUIRED>` sentinel with value inference (AST default,
sibling mirroring for `judge_*`/`provider` params) or omit+comment. 0 placeholders across 3
runs. Committed as `5c08779`.

**E14 (constructor signature injection):** `extract_constructor_signatures()` in reference.py
walks all public classes via AST and renders exact `__init__` parameter names, order,
annotations, and defaults. Injected into `generate_page()` in narrative.py as enrichment.
Generic — no SimpleAudit-specific code. Committed as `2edd930`.

**E18 (prose semantics checker):** new deterministic harness
(`/tmp/rq-trials/harness/prose_api_semantics_check.py`) — first metric for C-hallucination
(real symbol, false fact). Extracts API-usage claims from markdown prose and validates
against an AST-derived class/function index. Caught 7/7 known adversarial errors in E13_e2e
docs (52 findings) vs 38 findings in E13b_run1 (best-known). Evaluation infrastructure only —
no RepoQuill code change. **KEEP** per decision rule.

## Configuration (E8)

```yaml
project_name: simpleaudit
package_dir: simpleaudit
root: /tmp/rq-trials/simpleaudit-src
output_dir: site

llm:
  provider: openai
  model: Qwen/Qwen3.8-27B-FP8
  base_url: https://simulachat.sushant.info.np/api/v1
  api_key_env: OPENAI_API_KEY
  max_concurrent: 4

narrative_sections:
  - title: Getting Started
    slugs: [quickstart, installation]
  - title: Core Concepts
    slugs: [architecture, key-ideas]
  - title: Scenarios
    slugs: [available-scenarios, custom-scenarios]
  - title: Evaluation
    slugs: [judges-evaluation, results-analysis]
  - title: CLI
    slugs: [cli-reference]
  - title: Advanced
    slugs: [model-auditor, visualization-server]

reference_sections:
  - title: Core
    modules: [simpleaudit]
```

## Code Changes

1. **E1 (379bab5):** Auto-insert mkdocstrings plugin + search + default md extensions in generated mkdocs.yml
2. **E2 (2cf7ce6):**
   - `reference.py`: `extract_api_surface()`, `get_examples_context()`, `extract_cli_surface()`
   - `narrative.py`: API surface + CLI surface + examples enrichment in `generate_page()`
   - `narrative.py`: 6 strict rules in prompt (no invented symbols, etc.)
3. **E5:** `verify_passes: 1` in config — KEEP is NOT well-justified (−8.9pp coverage,
   −35% grounded for +0.12pp hallucination). E11 confirmed the -8.9pp drop is REAL.
   E13 now handles the deterministic fixes; E5's LLM verify pass is still enabled but
   its value is questionable.
4. **E7 (cb94011):** Deterministic page structure from `narrative_sections` config
5. **E9 (5402b5b):** Fix false positives in hallucination checker (module names)
6. **E13 (18f365d):** Deterministic surgical verify pass (`repoquill/surgical_verify.py`)
   - `build_class_index()`: AST-walks package for ClassDef, __init__ params, @property
   - `fix_property_calls()`: strips `()` from property calls in code blocks + backtick prose
   - Runs automatically after LLM verify passes in `_cmd_generate()`
7. **E13b (5c08779):** Replaced `<REQUIRED>` placeholder with value inference
   - `build_class_index()` now records `init_defaults` (param → `ast.unparse(default)`)
   - `_infer_value()`: AST default → sibling mirroring (`judge_X` mirrors `X`, `provider` mirrors `judge_provider`) → None
   - `_fix_missing_required_in_block()`: inserts inferred value or `# NOTE: {param} is required (no default)` comment
   - `_normalize_quotes()`: normalizes single→double quotes to match doc style
   - `example_check.py`: new `placeholder_value` finding type (sentinel values can never satisfy the checker again)

## E11 Variance Band (methodology anchor)

| Metric | Temp 0.7 range | Temp 0.2 range |
|--------|---------------|---------------|
| Coverage% | 2.1pp [70.7, 72.8] | 7.3pp [64.4, 71.7] |
| Grounded | 12 [316, 328] | 41 [272, 313] |
| Halluc% | 0.0 [0, 0] | 0.0 [0, 0] |
| Broken examples% | 18.1pp [33.3, 51.4] | 8.6pp [38.3, 46.2] |

Any future experiment's delta must exceed the relevant variance band to be considered real.

## E13 Results

| Run | Before (E12) | After (E13) |
|-----|-------------|-------------|
| t07_r1 | 41.0% | 8.3% |
| t07_r2 | 43.3% | 13.3% |
| t07_r3 | 37.5% | 2.5% |
| t02_r1 | 41.0% | 5.1% |
| t02_r2 | 44.1% | 2.9% |
| t02_r3 | 38.1% | 4.8% |
| **e2e** | — | **0.0%** |
| **Mean** | **41.0%** | **6.2%** |

- Coverage: unchanged (69.1–72.8%, within variance band)
- Hallucination: unchanged (0.0–0.5%)
- Generic: AST-walks the package under test, no SimpleAudit-specific code

## Known Weaknesses

1. ~~**Prose-level API semantics are unmeasured (RETRO2)**~~ — **FIXED by E18.**
   prose_api_semantics_check.py now measures C-hallucination: 7/7 known adversarial errors
   caught. 52 findings on E13_e2e docs vs 38 on E13b_run1 (discrimination confirmed).
   The metric now exists; the remaining gap is *fixing* the errors in generated docs (E19).
2. ~~**Coverage metric is circular/inflated**~~ — **FIXED by E15.**
   coverage_check_v2.py requires substantive mention (heading/code-block/definition-sentence/bold-term).
   Old substring metric inflated coverage by ~10pp (65.6% → 54.6% honest).
3. **Grounded-claims (277) is a hollow proxy** — counts symbol mentions WITH repetition;
   weak `literal` grounding. Not a measure of correct information.
4. **Self-judging** — judge.py uses the same model as the generator (violates independence).
5. **Evaluation harness is SimpleAudit-hardcoded** — coverage_check.py hard-codes concepts;
   hallucination_check.py has hand-tuned stopword lists. Core-rule violation.
6. **Verify pass (E5) may be unnecessary** — E13 handles the deterministic fixes. E5's
   whole-page LLM rewrite caused -8.9pp coverage regression. E17 will A/B test this.

**Fixed by E13b:** `<REQUIRED>` placeholders (was weakness #1) — 0 placeholders across 3 runs.
Broken% is now honest (13.8% mean).

## E15 — De-Goodhart Coverage (KEEP)

coverage_check_v2.py: substantive-mention criterion (heading, code block, definition-pattern,
or bold-term). AST-derived inventory. Old substring metric inflated coverage by ~10pp
(65.6% → 54.6% honest for E14). v2 is now the canonical coverage metric. Evaluation
infrastructure only — no RepoQuill code change.

## E16 — Tests-as-Evidence (REVERT)

`get_tests_context()` in reference.py (top-4 test files by assertion count, ~6KB).
`include_tests` config flag (default False). Broken% regressed 4.5→13.9% mean (+9.4pp).
Tests crowd out source context without net benefit at this context budget. Code kept
(default off) for future experiments with larger context budgets.

## Next Experiment

**E17 — Investigate E5 regression.** A/B test `verify_passes: 1` on/off (3 runs each) on
the E14 baseline. If E5-off has equal or better metrics → revert E5 (saves compute,
simplifies pipeline). See NEXT_EXPERIMENT.md.
