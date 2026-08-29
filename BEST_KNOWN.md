# BEST_KNOWN

**Last updated:** 2026-08-29 (after RETRO4)

## Best-Known State

**E8+E9+E10+E13+E13b+E14+E19+E21+E22 (grounding pass with prose+semantic checkers, full generation)** — 52.3% coverage v2 (mean of 3 runs), 0.0% invented-symbol rate, 0.0% broken examples, 18.7 prose findings mean, 4.7 semantic findings mean
- 11 deterministic pages from `narrative_sections` config
- 0 invented symbol names
- **Coverage metric:** v2 (substantive-mention, E15) — old substring metric inflated by ~10pp
- **E14 metric:** 5.2% of code examples are non-runnable (mean of 3 E19 runs: 4.0/5.7/5.9)
- **E14:** 0 `invalid_kwarg` findings across all 3 runs (baseline had 2). Constructor signatures
  injected into prompt via AST walk.
- **E19:** grounding pass — prose findings 44.3→11.3 (74.5% reduction), zero coverage loss.
  Config flag `grounding_pass: true` (default false).
- **E21:** grounding pass now consumes BOTH prose AND semantic checker findings.
  Tested in isolation on E14 guides: semantic findings 12→1 (91.7% reduction).
- **E22:** full 3-run validation of grounding pass with prose+semantic checkers.
  Per-run: r1 cov=52.0%/prose=32→2/sem=4→1, r2 cov=59.2%/prose=36→27/sem=8→8,
  r3 cov=45.8%/prose=33→27/sem=6→5. Mean: cov=52.3%, broken=0.0%, prose=18.7, sem=4.7.
  All 4 decision criteria PASS (cov within 4.2pp band, broken within 18.1pp band,
  sem<5, prose<20). New best-known state.

**E13 (surgical verify pass):** deterministic post-generation edit step. Property-call fix
is genuine. Committed as `18f365d`.

**E13b (placeholder fix):** replaced `<REQUIRED>` sentinel with value inference (AST default,
sibling mirroring for `judge_*`/`provider` params) or omit+comment. 0 placeholders across 3
runs. Committed as `5c08779`.

**E14 (constructor signature injection):** `extract_constructor_signatures()` in reference.py
walks all public classes via AST and renders exact `__init__` parameter names, order,
annotations, and defaults. Injected into `generate_page()` in narrative.py as enrichment.
Generic — no SimpleAudit-specific code. Committed as `2edd930`.

**E15 (de-Goodhart coverage, canonical metric):** coverage_check_v2.py — a concept counts
as covered only if mentioned in a heading, fenced code block, definition-style sentence, or
bold term; inventory is AST-derived. Old substring metric inflated by ~10pp (E14 mean:
65.6% old → 54.6% v2). **KEEP** — evaluation infrastructure only, no RepoQuill code change.

**E16 (tests-as-evidence):** get_tests_context() in reference.py + include_tests config
flag (default False). **REVERTED as a config change** — broken% regressed 4.5→13.9% mean
(+9.4pp) with coverage −1.7pp, despite prose findings improving 44.3→30.7. ~6KB of test
context crowds out source context at the current 60K budget. Code kept dormant (commit
ea23ac1, default off) for future experiments with larger budgets.

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
6. ~~**Verify pass (E5) may be unnecessary**~~ — **RESOLVED by E17: REVERT E5.**
   Fresh A/B test (3 runs each): E5-on cov 50.8% / broken 12.7% / prose 40.0;
   E5-off cov 53.0% / broken 11.7% / prose 53.7. No primary metric favors E5-on
   (coverage delta -2.0pp within 4.2pp band, broken delta within 18.1pp band).
   REVERT: verify_passes defaults to 0. Saves compute with no quality loss.

**Fixed by E13b:** `<REQUIRED>` placeholders (was weakness #1) — 0 placeholders across 3 runs.
Broken% is now honest (13.8% mean).

7. **Semantic value errors and omissions are unmeasured (RETRO3, confirmed by E19)** —
   The current checkers (example_check, hallucination_check, prose_api_semantics_check)
   catch API misuse in code blocks and prose, but NOT wrong string literals (e.g.
   `language="en"` instead of `language="English"`) or missing caveats (e.g. `run()`
   event-loop restriction). RETRO3 found 2 HIGH-severity issues in E14 docs that no
   checker catches. E19's grounding pass confirmed the limitation: it can only fix what
   the checker flags, and these semantic errors persist in 2 of 3 runs. Requires E20
   (semantic-value checker).

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

## E17 — Verify-Pass A/B (REVERT E5)

Fresh A/B, 3 runs each arm, E14 baseline config. On (vp=1): coverage 50.8% mean,
broken 12.7% mean, prose 40.0. Off (vp=0): coverage 53.0% mean, broken 11.7% mean,
prose 53.7. No primary metric favors E5-on. Coverage delta +2.2pp for off (within 4.2pp
band). Prose worse off but E19 (grounding pass) addresses that deterministically.
Revert E5: saves compute, simplifies pipeline. Config default already `verify_passes: 0`.

**Note:** An earlier analysis (RETRO3) concluded KEEP E5 by reusing E14_r1-r3 as the
on-arm. That comparison was flawed (different config/run conditions). The fresh A/B is
authoritative.

## E19 — Grounding Pass (KEEP)

`repoquill/grounding.py` — post-generation LLM correction pass. Runs the prose
API-semantics checker internally, groups findings by page, and sends each affected
page + its findings + the AST API surface to the LLM (temp 0.1) with instructions to
fix ONLY the flagged claims. Wired into `cli.py` behind `grounding_pass: true` config
flag (default false).

| Run | Coverage v2 | Broken% | invalid_kwarg | Halluc% | Prose before | Prose after |
|-----|-------------|---------|---------------|---------|-------------|-------------|
| E19_r1 | 56.4% | 4.0% | 0 | 0.8% | 48 | 30 |
| E19_r2 | 51.4% | 5.7% | 0 | 0.0% | 47 | 2 |
| E19_r3 | 55.9% | 5.9% | 0 | 0.0% | 38 | 2 |
| **Mean** | **54.6%** | **5.2%** | **0** | **0.3%** | **44.3** | **11.3** |

**Decision: KEEP.** Prose findings dropped 74.5% (44.3→11.3) with zero coverage loss.
Decision rule met: prose < 20 AND coverage ≥ 50.4%. Generic — works on any repo with
prose-checker findings.

**Limitation:** The grounding pass only fixes checker-detected findings. It does NOT fix
unmeasured semantic errors (RETRO3: `language="en"`, missing `run()` event-loop caveat).
E20 now provides the checker; E21 will feed it into the grounding pass.

## E20 — Semantic Value Checker

`eval/semantic_value_check.py` — new deterministic checker with 2 finding types:
- **STRING_VALUE_MISMATCH:** string kwargs in code blocks that are strict
  prefixes/abbreviations of the source param's default. Global param-name → defaults
  map (param-name-agnostic).
- **MISSING_CAVEAT:** method calls with a known runtime caveat not mentioned in the page.
  Global method-name → caveats map (method-name-agnostic).

| Doc set | Total | STRING_VALUE_MISMATCH | MISSING_CAVEAT | FP |
|---------|-------|----------------------|----------------|----|
| E14 (3 runs) | 12 | 3 (language="en") | 9 (event-loop caveat) | 0 |
| E19_r3 (re-validated) | 11 | 2 (language="en") | 9 (event-loop caveat) | 0 |

**Decision: KEEP.** Both known RETRO3 errors caught, 0 false positives on re-validation.
An earlier registry entry reported 87% FP (20/23) from a less refined version of the
checker that flagged legitimate user-chosen values (provider='ollama', label_a='opus-4-7').
The current version correctly distinguishes user-chosen values from wrong defaults:
only flags string values that are strict prefixes of the source default. Evaluation
infrastructure only; no RepoQuill code change. Confirms E19 grounding pass cannot fix
these (same findings on E19 docs) — they are outside the prose checker's finding types.

## E21 — Wire Semantic Checker into Grounding Pass + Test

`grounding.py` extended to run BOTH the prose checker and the semantic value checker,
merge findings, and send the combined list to the LLM for correction. The
`_fix_page_grounding` prompt includes type-specific instructions for
STRING_VALUE_MISMATCH (change value to match source default) and MISSING_CAVEAT (add
brief caveat note).

**Test results (isolated, on E14 guides):**

| Metric | E14 (pre) | E19 (prose-only) | E21 (prose+semantic) |
|--------|-----------|-----------------|---------------------|
| Semantic findings | 12 | 12 | **1** (91.7% reduction) |
| Prose findings | 44.3 | 11.3 | **2** |
| Coverage (v2) | 54.6% | 54.6% | **56.4%** |
| Hallucination rate | 0.0% | 0.3% | **0.0%** |
| Pages fixed | — | — | 10 |
| Total findings (before→after) | — | — | 60→3 |

All 3 `language="en"` → `"English"` fixed. 8/9 event-loop caveats added (1 remaining is
a false negative: `exp.run()` is `AuditExperiment.run()`, not `ModelAuditor.run()`).

**Decision: KEEP.** Closes the E20 loop: checker detects → grounding pass fixes →
re-checker verifies. 91.7% semantic finding reduction with zero coverage regression
(+1.8pp) and zero hallucination regression (0.0%).

## RETRO4 — Research Retrospective (after E21)

Completed 2026-08-29. Four questions addressed:

**Q1: Is the E21 semantic-finding reduction real or an artifact?** REAL, but tested in
isolation (not full generation). The mechanism is sound; the next full generation should
validate on fresh docs.

**Q2: Is v2 coverage stable at 56.4%?** NOISY. 56.4% is a single-run number at the TOP
of the E14/E19 variance band (51.4–56.4%). The +1.8pp "improvement" is likely noise.
Do NOT claim E21 improved coverage.

**Q3: Next highest-impact failure mode?** The `workflows` category in
coverage_check_v2.py admits generic English words ('actually', 'around', 'cache',
'chart', 'configured', etc.) as "concepts", inflating the denominator by ~14
false-positive concepts (~5pp coverage deflation).

**Q4: Are we Goodharting any metric?** YES — the `workflows` category is a Goodhart
risk (word-frequency, not concept-coverage). No other metrics are at risk. **Usability
is the next blind spot** — no metric measures whether docs are USEFUL to a new
developer.

**Actions:** (1) Fix `workflows` category (de-Goodhart). (2) Validate E21 on full
generation when OOM resolved. (3) Do NOT claim E21 improved coverage. (4) Establish
3-run mean for E21 best-known state. (5) Consider usability metric.

## Next Experiment

**E22 — Fix `workflows` category in coverage_check_v2.py.** De-Goodhart: require
substantive mention (heading, code block, definition-style sentence, or bold term)
rather than any mention. Should raise coverage by ~5pp (removes ~14 false-positive
concepts from denominator). See NEXT_EXPERIMENT.md.
