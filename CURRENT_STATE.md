# CURRENT_STATE

**Last updated:** 2026-08-29 (E48 KEEP: index.md landing page auto-generates real tagline + quick_start + per-guide descriptions from source README — fixes the "lame index" via 3 generic RepoQuill fixes, zero testbed config edits. E47 KEEP: deterministic type-annotation verification pass eliminates C-hallucination; E46 REVERT: prompt rule 9 did not fix passed/failed C-hallucination)
**Best-known state:** E8+E9+E10+E13+E13b+E14+E19+E23+E27+E28+E30+E31+E32+E36+E41+E43+E44+E47 (grounding pass + de-Goodhart coverage + @property detection + dedent fix + prose FP fix + import blind spot fix + C-hallucination metric + source-body injection + page-conditional injection + container dunder docs + config key disambiguation + table-row coverage fix + deterministic type-claim verification) — 70.9% coverage v2 (median of E47 r1/r2: 63.1%/78.8%), 0% C-hallucination (BOTH runs — passed/failed bool-vs-int error eliminated), 0.5% invented-symbol rate (median; r1: 1 real — `from simpleaudit.visualization import server`, no __init__.py; r2: 0), 2.4% broken examples (median), 2 prose findings (median)
**Experiments complete:** E1–E26 + RETRO2 + RETRO3 + RETRO4 + E15. E22 (full 3-run validation of grounding pass with prose+semantic checkers): REVERT. E23 (de-Goodhart workflows category): KEEP. E15 (LLM-planned structure): REVERT. E24 (grounding pass variance): REVERT. E25 (fix example checker to exclude signature snippets): REVERT — checker fix is correct but E25's broken% (13.5%) is worse than E19 (4.2%) with same fixed checker. E26 (E19 config WITHOUT grounding pass): INFORMATIVE — broken% 15.2% WORSE than E19 (4.2%) and E25 (13.5%), proving grounding pass is NOT the cause of broken-example regression. Root cause identified: extract_api_surface() lists @property attributes as methods, so LLM calls them as methods.
**E13 (surgical verify pass):** deterministic post-generation edit step. Property-call fix is genuine. Committed (18f365d).
**E13b (placeholder fix):** replaced `<REQUIRED>` sentinel with value inference (AST default, sibling mirroring) or omit+comment. 0 placeholders across 3 runs. Broken% now honest (13.8% mean). Committed (5c08779).
**RETRO2 key findings:**
1. The 6.2% broken-examples headline is largely self-inflicted (10/13 residual findings are E13's own `<REQUIRED>` placeholders). True residual is ~3 `invalid_kwarg` blocks.
2. 7 source-verified factual errors found in prose/tables (method-vs-property, return-type, argument-type) — all missed by every checker.
3. Recommended new checker: `prose_api_semantics_check.py` (E18).
4. E14 decision threshold must be 2× the variance band (4.2pp), not 1× (2.1pp).
5. Revised priority: E13b → E18 → E14 (re-scoped) → de-Goodhart coverage → E17.

## Experiment Summary

| Exp | Change | Halluc | Coverage | Example Broken% | Decision |
|-----|--------|--------|----------|-----------------|----------|
| BASELINE | No changes | 0.76% | 73.0% (89/122) | — | — |
| E1 | mkdocstrings plugin fix | 0.76% | 73.0% | — | KEEP (379bab5) |
| E2 | CLI surface + API surface enrichment | 0.56% | 69.6% (133/191) | — | KEEP (2cf7ce6) |
| E3 | Constructor signatures | 1.07% | 65.4% | — | REVERT |
| E4 | Pyproject extras injection | 1.42% | 70.2% | — | REVERT |
| E5 | verify_passes: 1 | 0.44% | 60.7% | — | KEEP (not well-justified) |
| E6 | Investigation (non-deterministic pages) | — | — | — | — |
| E7 | Deterministic page structure | 0.0% | 40.8% (78/191) | — | KEEP (cb94011) |
| E8 | Expanded narrative_sections (11 slugs) | 1.87% | 70.7% (135/191) | — | KEEP (config) |
| E9 | Fix false positives in checker | 0.37% | 70.7% (135/191) | — | KEEP (5402b5b) |
| E10 | Investigate remaining hallucination | 0.0% | 70.7% (135/191) | — | KEEP (investigation) |
| E11 | Temperature + repeated runs (3× @ 0.7, 3× @ 0.2) | 0.0% all | 64.4–72.8% | 33.3–51.4% | METHODOLOGY (see below) |
| E12 | Deterministic example-validity checker | — | — | 33.3–51.4% | NEW METRIC (see below) |
| E13 | Deterministic surgical verify pass | 0.0–0.5% | 69.1–72.8% | 0–13.3% (mean 6.2%) | **KEEP** (18f365d) |
| E13b | Fix `<REQUIRED>` placeholder (value inference) | 0.0% | 61.3–71.7% (mean 67.9) | 8.5–21.2% (mean 13.8, honest) | **KEEP** (5c08779) |
| E18 | Prose API semantics checker (C-hallucination metric) | — | — | — | **KEEP** (new harness) |
| E14 | Inject exact constructor signatures into narrative prompt | 0.0% | 63.9–67.0% (mean 65.6) | 2.0–5.9% (mean 4.5, honest) | **KEEP** (2edd930) |
| E15 | De-Goodhart coverage (substantive-mention criterion) | — | 51.4–56.4% (mean 54.6, v2) | — | **KEEP** (new harness) |
| E16 | Tests-as-evidence (inject top test files) | 0.0% | 48.0–57.0% (mean 52.9, v2) | 7.1–19.6% (mean 13.9) | **REVERT** (ea23ac1, default off) |
| E17 | verify-pass A/B (verify_passes 1 vs 0) | 50.8 vs 53.0 | 12.7 vs 11.7 | 0.0 | **REVERT E5** (no primary metric favors on; saves compute) |
| E19 | Grounding pass (prose-checker feedback loop) | 54.6 | 5.2 | 0.3 | **KEEP** (prose 44.3→11.3, 74.5% reduction, zero coverage loss) |
| E20 | Semantic value checker (string literals + caveats) | — | — | — | **KEEP** (12 findings on E14/E19, 0 FP; catches language="en" + event-loop caveat) |
| E21 | Wire semantic checker into grounding pass + test | 0.0% | 56.4% (single-run, top of band) | 5.2% | **KEEP** (semantic 12→1, 91.7% reduction, zero coverage/halluc regression) |
| E22 | Full 3-run validation of grounding pass (prose+semantic) | 0.0% | 52.3% (mean of 3) | 0.0% | **REVERT** (coverage -2.3pp, prose +7.4 worse vs E19; semantic 4.7 not near 0) |
| E23 | De-Goodhart workflows category in coverage_check_v2.py | — | 54.4% (mean of 3, +2.1pp) | — | **KEEP** (removed 18 generic words, no other category affected) |
| E15 | LLM-planned structure (no hand-authored slugs) | 0.0% | 38.5% (mean of 3) | 0.0% | **REVERT** (coverage -15.9pp, well outside band) |
| RETRO4 | Research retrospective (5th since RETRO3) | — | — | — | **METHODOLOGY** (workflows Goodhart risk, usability blind spot) |
| E24 | Grounding pass variance (4 variants × 3 runs) | 0.0% | 52.9 (mean) | 9.3 (mean) | **REVERT** (no variant beats E19 on all metrics) |
| E25 | Fix example checker to exclude signature snippets | 0.0% | 51.2 (mean) | 13.5 (mean) | **REVERT** (broken% worse than E19; generation quality issue, not checker) |
| E26 | E19 config WITHOUT grounding pass | 0.0% | 54.7 (mean) | 15.2 (mean) | **INFORMATIVE** (grounding pass NOT the cause; root cause = @property detection) |
| E27 | Mark @property attributes in API surface | 0.0% | 55.1 (mean) | 3.5 (mean) | **KEEP** (prop_as_method=0, broken% best ever, coverage best ever) |
| E28 | Strip leading indentation from code blocks | — | — | 0.7 (mean, re-scored) | **KEEP** (de-Goodhart: 5 syntax_error → 0) |
| E29 | Investigate remaining missing_required finding | — | — | — | **NO_ACTION** (1/9 calls, within variance; E14 enrichment working) |
| E30 | Fix prose checker false positives (vague-return gate, member dedup, required-args guard) | — | — | — | **KEEP** (13.3→5 findings, 12 FPs eliminated, 5 TPs kept) |
| E31 | Fix top-level import blind spot in hallucination checker | 0.7% | — | — | **KEEP** (0.0%→0.7%, 3 TPs revealed) |
| E32 | Build claim-verification checker (C-hallucination metric) | — | — | — | **KEEP** (18.8% C-hallucination rate, new metric) |
| E33 | Reduce C-hallucination via prompt rule (type-claim conservatism) | 1.03% | 55.0% | 2.9% | **REVERT** (C-halluc -5.9pp but halluc +0.33pp, broken +2.2pp) |
| E34 | Adversarial review of best-known state | — | — | — | **ANALYSIS** (5 CRITICAL findings, all name-based inference; E35 designed) |
| E35 | API signature + static example checkers in grounding pass | 0.9% | 61.3% | 2.2% | **REVERT** (C-halluc +15.5pp, broken +1.5pp; checker FPs too high) |
| RETRO6 | Research retrospective (after E35) | — | — | — | **METHODOLOGY** (grounding pass net-negative; stop checker→grounding loop; E36 = source-body injection) |
| E36 | Source-body injection for referenced members | 1.98% | 60.4% | 6.6% | **KEEP** (C-halluc count 1.3 vs 2.0, prose 2.3 vs 5, coverage +5.3pp) |
| E40v2 | Usability probe v2 (fixed judge, 4 tasks × 3 runs) | — | — | — | **ANALYSIS** (generated 50% vs README 75%, −25pp delta; 2 fixable gaps identified) |
| E42 | Cross-repo generalization test (Click) | 3.0% (0 real) | N/A | 1.2% | **PASS** (0 real invented symbols, 0 C-halluc, 0 prose; src/ layout fix generic) |
| E43 | Fix E40v2-exposed gaps (dunder iteration + config key) | 0.0% | 55.3% | 0.0% | **KEEP** (E40v2 50%→58.3%, docs-insufficient 3→0, delta −25pp→−16.7pp) |
| E44 | Table-row coverage fix (count table cells as substantive mentions) | 0.0% | 69.8% (+14.5pp) | 0.0% | **KEEP** (metric fix, not generation change; judges 50%→100%, packs 28.6%→85.7%, modules 51.6%→90.3%) |
| E41 | Page-conditional source-body injection (only bodies for members in page source files) | 0.5% (1 real: wrong import path) | 68.2% (+12.9pp, stable) | 1.8% | **KEEP** (coverage +12.9pp stable across 2 runs, C-halluc 4.8% median, S-halluc 0.5% — 1 real wrong-import-path) |
| E46 | Prompt rule 9: "do not infer return types from symbol names" | 0.5% (median) | 67.3% (median) | 8.0% (median) | **REVERT** (C-halluc NOT fixed: passed/failed still bool in both runs; broken examples regressed 1.8%→8.0% median; LLM writes placeholder code when "not sure") |
| E45 | Findability diagnostic (page-hop distance) | — | — | — | **ANALYSIS** (run_safety_audit + interpret_results: NO single page has all solving patterns; README has all on page 1) |
| RETRO7 | Research retrospective (7th) | — | — | — | **METHODOLOGY** (5 findings: fix E40v2 task defect, stop optimizing coverage v2, findability is highest-impact, kill E41, add cross-page consistency) |
| E47 | Deterministic type-annotation verification pass (fix_type_claims in verify.py) | 0.5% (median) | 70.9% (median) | 2.4% (median) | **KEEP** (C-halluc 0% both runs, coverage +2.7pp, prose 7→2) |

## E11 — Variance Band Results

6 runs (3× temp 0.7, 3× temp 0.2) of the E8+E9+E10 best state:

| Run | Temp | Halluc% | Grounded | Coverage% | Broken Examples% |
|-----|------|---------|----------|-----------|-----------------|
| E11_t07_r1 | 0.7 | 0.0 | 328 | 72.8 | 33.3 |
| E11_t07_r2 | 0.7 | 0.0 | 316 | 70.7 | 51.4 |
| E11_t07_r3 | 0.7 | 0.0 | 319 | 71.2 | 39.1 |
| E11_t02_r1 | 0.2 | 0.0 | 313 | 64.4 | 40.9 |
| E11_t02_r2 | 0.2 | 0.0 | 304 | 67.0 | 46.2 |
| E11_t02_r3 | 0.2 | 0.0 | 272 | 71.7 | 38.3 |

**Variance bands (temp 0.7):** coverage range=2.1pp [70.7, 72.8], grounded range=12 [316, 328], halluc=0.0
**Variance bands (temp 0.2):** coverage range=7.3pp [64.4, 71.7], grounded range=41 [272, 313], halluc=0.0

**Key conclusions:**
1. **E5's -8.9pp coverage drop was REAL, not noise** — it exceeds the full temp-0.7 variance
   band (2.1pp). The E5 keep decision stands as a real regression that was incorrectly kept.
2. **E3/E4 coverage drops were borderline** — E3 (-3.1pp) slightly exceeds the 2.1pp band;
   E4 (-2.5pp) is within it. E3's revert was correct; E4's revert was likely correct too.
3. **Temperature does NOT fix example validity** — temp 0.7 mean broken%=41.3, temp 0.2
   mean broken%=41.8. Ranges overlap heavily. This is a structural problem, not a
   sampling-temperature problem.
4. **Hallucination rate is 0.0% in all 6 runs** — the symbol-existence metric is stable.
5. **Temp 0.2 has wider variance** (coverage 7.3pp vs 2.1pp; grounded 41 vs 12) — temp 0.7
   is actually more stable for this model. Do NOT switch to 0.2.

## E12 — Example-Validity Checker Results

New deterministic checker (`/tmp/rq-trials/harness/example_check.py`) AST-parses every
fenced `python` block and checks:
- Constructor kwargs against real `__init__` params
- Required (no-default) args present
- Imports resolve against `__all__` + module list
- Properties not called as methods
- Cross-page signature conflicts

**Results across 6 E11 runs:**
- Broken examples: 33.3–51.4% (mean ~41%)
- Dominant finding types: `missing_required` (18-24/run), `property_called_as_method` (11-19/run)
- Secondary: `invalid_kwarg` (0-2/run), `syntax_error` (0-3/run), `cross_page_conflict` (0-1/run)

**E12 is now a first-class metric.** The scoreboard was blind to this: the docs' worst
defect (non-runnable examples) is now measured deterministically and generically.

## E13 — Surgical Verify Pass Results

Deterministic post-generation edit step (`repoquill/surgical_verify.py`) that fixes the two
dominant E12 finding types without an LLM rewrite:

1. **property_called_as_method**: strip trailing `()` from `@property` calls
2. **missing_required**: insert required `__init__` kwargs with `"<REQUIRED>"` placeholder

**Results (6 E11 runs + 1 e2e run):**

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

**E13 is a clear KEEP.** Committed as `18f365d`.

## Key Findings (updated)

### 1. Prompt dilution pattern (E3, E4) — CONFIRMED REAL
E3's -3.1pp coverage drop exceeds the 2.1pp variance band. The "prompt dilution" diagnosis
is valid: adding more context to the prompt causes real regression.

### 2. Verify pass tradeoff (E5) — CONFIRMED REAL REGRESSION
E5's -8.9pp coverage drop far exceeds the variance band. The keep was a mistake.
E13 (surgical verify) is now integrated; E5's LLM verify pass is still enabled but
the deterministic surgical pass runs after it and fixes the remaining issues.

### 3. Example validity is the dominant failure mode — MOSTLY FIXED BY E13 (RETRO2)
~41% of code examples were non-runnable. E13's property-call fix is genuine. However,
RETRO2 found that 10 of 13 residual findings are E13's own `<REQUIRED>` placeholders
(syntactically valid, semantically misleading). True residual is ~3 `invalid_kwarg` blocks.
E13b will replace the placeholder with a valid inferred value or annotation.

### 4. Non-deterministic page generation (E6, E7) — FIXED
E7 fixed this by using `narrative_sections` config slugs as the exact page structure.

### 5. False positives in deterministic checker (E9) — FIXED
The checker was flagging module names as hallucinations. Fixed by adding module names to
the symbol check.

### 6. LLM judge is noisy
Not reliable for absolute scoring. Use for *categorical* errors, not *scalar* ranking.

### 7. Prose-level API semantics are unmeasured (RETRO2 — NEW)
Adversarial agent found 7 source-verified factual errors in markdown prose/tables
(method-vs-property, return-type, argument-type confusion). All missed by every checker.
The checkers only parse ```python code blocks; the prose that contradicts them is invisible.
E18 (prose_api_semantics_check.py) is the recommended fix.

### 8. Coverage metric is a mention-frequency proxy (RETRO2 — CONFIRMED)
Substring match, name-in-code-fence counts, partly hand-authored inventory.
70.7% is a mention-frequency number, not a coverage number. De-Goodhart action:
require substantive mention; make inventory repo-derived.

## Current Best-Known State

**E8+E9+E10+E13+E13b+E14+E19 (grounding pass with prose checker only)** — 54.6% coverage v2 (mean of 3 runs), 0.0% invented-symbol rate, 5.2% broken examples, 11.3 prose findings mean
- 11 deterministic pages from `narrative_sections` config
- 0 invented symbol names across all runs
- **E13:** deterministic surgical verify pass fixes ~35pp of broken examples post-generation
- **E13b:** `<REQUIRED>` placeholder replaced with value inference (AST default, sibling mirroring) or omit+comment. 0 placeholders across 3 runs.
- **E14:** constructor signature injection — invalid_kwarg = 0 in 3/3 runs; broken% improved 13.8→4.5% mean.
- **E15:** de-Goodhart coverage (v2 metric) — canonical coverage is now 54.6% (was 65.6% under old metric).
- **E17:** verify-pass A/B — E5 reverted (verify_passes: 0).
- **E19:** grounding pass — prose findings 44.3→11.3 (74.5% reduction), zero coverage loss.
- **E20:** semantic value checker (evaluation infrastructure only, NOT wired into grounding pass).
- **E21:** REVERTED — wiring semantic checker into grounding pass was tested in isolation (91.7% reduction) but full generation (E22) showed it's less effective than prose-only grounding.
- **E22:** REVERTED — full 3-run validation showed coverage -2.3pp and prose +7.4 worse vs E19. The combined grounding pass is less effective than the prose-only grounding pass.

## Research Retrospective (COMPLETE — after E1–E10)

Three independent retrospective subagents ran (patterns, Goodhart, adversarial). Synthesis in
`/tmp/rq-trials/agents/RETRO_synthesis.md`. **Key finding (all three + manual check agree):**

The "0.0% hallucination" headline is a **symbol-existence artifact**. The E8 docs contain real
semantic (C-)hallucinations and **non-runnable examples** that every tracked metric is blind to.

**E12 now measures this directly.** ~41% of code examples are non-runnable, dominated by
`missing_required` and `property_called_as_method` errors.

**Goodhart verdict:** the scoreboard had a hole exactly where the real failures are.
E12 closes that hole. Coverage (70.7%) is still circular/inflated (substring match).

## E18 — Prose API Semantics Checker Results

New deterministic checker (`harness/prose_api_semantics_check.py`) that extracts API-usage
claims from markdown **prose** (not code blocks) and validates them against an AST-derived
class/function index. First metric targeting **C-hallucination** (real symbol, false fact),
as opposed to S-hallucination (invented symbol, already at 0.0%).

**Finding types:** PROSE_PROPERTY_AS_METHOD, PROSE_METHOD_AS_PROPERTY, RETURN_TYPE_MISMATCH,
ARG_TYPE_MISMATCH, CROSS_PAGE_CONFLICT, MISSING_INSTALL_EXTRA.

**Validation against the 7 known adversarial errors** (from RETRO2, all present in E13_e2e
docs): **7/7 caught** → KEEP per decision rule.

| Docs | Claims | Findings | Notes |
|------|--------|----------|-------|
| E13_e2e (flawed) | 143 | 52 | 30 property-as-method, 16 return-type, 4 arg-type, 2 install-extra |
| E13b_run1 (best-known) | 113 | 38 | Discrimination confirmed: fewer findings on better docs |

**Decision: KEEP.** No RepoQuill code change — evaluation infrastructure only
(`/tmp/rq-trials/harness/prose_api_semantics_check.py`). The checker now serves as the
C-hallucination readout for E16 (tests-as-evidence) and E19 (grounding pass).

## E14 — Constructor Signature Injection Results

**Hypothesis:** Injecting exact AST-derived `__init__` signatures into the narrative prompt
will reduce `invalid_kwarg` findings without diluting coverage.

**Change:** Added `extract_constructor_signatures()` to reference.py (AST walk of all public
classes, renders `__init__` params with annotations/defaults in source order). Injected into
`generate_page()` in narrative.py as enrichment block. Generic — no SimpleAudit-specific code.

| Run | Coverage | Broken% | invalid_kwarg | Halluc% | Prose findings |
|-----|----------|---------|---------------|---------|----------------|
| E14_r1 | 63.9% | 2.0% | 0 | 0.0% | 48 |
| E14_r2 | 66.0% | 5.7% | 0 | 0.0% | 47 |
| E14_r3 | 67.0% | 5.9% | 0 | 0.0% | 38 |
| **Mean** | **65.6%** | **4.5%** | **0** | **0.0%** | **44.3** |

**Decision: KEEP.** invalid_kwarg = 0 in 3/3 runs (baseline had 2); coverage drop 2.3pp <
4.2pp threshold; broken% improved 13.8→4.5% mean (bonus); hallucination 0.0% unchanged.

## E15 — De-Goodhart Coverage Results

**Change:** coverage_check_v2.py — substantive-mention criterion (heading, code block,
definition-pattern, or bold-term). AST-derived inventory. Old metric inflated by ~10pp.

| Run | Old (substring) | New (substantive) |
|-----|----------------|-------------------|
| E13b_run1 | 70.7% | 65.4% |
| E14_r1 | 63.9% | 56.4% |
| E14_r2 | 66.0% | 51.4% |
| E14_r3 | 67.0% | 55.9% |
| **E14 mean** | **65.6%** | **54.6%** |

**Decision: KEEP.** v2 is now the canonical coverage metric.

## E16 — Tests-as-Evidence Results

**Change:** `get_tests_context()` in reference.py (top-4 test files by assertion count,
~6KB). `include_tests` config flag (default False).

| Run | Coverage (v2) | Broken% | invalid_kwarg | Halluc% | Prose findings |
|-----|--------------|---------|---------------|---------|----------------|
| E16_r1 | 53.6% | 19.6% | 0 | 0.0% | 37 |
| E16_r2 | 57.0% | 7.1% | 0 | 0.0% | 20 |
| E16_r3 | 48.0% | 15.0% | 0 | 0.0% | 35 |
| **Mean** | **52.9%** | **13.9%** | **0** | **0.0%** | **30.7** |

vs E14 baseline: 54.6% coverage, 4.5% broken, 44.3 prose.

**Decision: REVERT.** Broken% regressed 4.5→13.9% (+9.4pp). Tests crowd out source
context without net benefit at this context budget. Code kept (default off) for future
experiments with larger context budgets.

## E17 — Verify-Pass A/B Test Results

**Design:** Fresh A/B, 3 runs each arm, E14 baseline config (include_tests false,
verify_passes toggled). On-arm = E17_on_r1-r3 (verify_passes: 1). Off-arm = E17_off_r1-r3
(verify_passes: 0). Decision rule: if off has equal-or-better coverage AND broken% ≤ on →
revert E5.

| Arm | Run | Coverage v2 | Broken% | invalid_kwarg | Halluc% | Prose |
|-----|-----|-------------|---------|---------------|---------|-------|
| ON (vp=1) | r1 | 51.4% | 10.2% | 0 | 0.0% | 42 |
| ON (vp=1) | r2 | 50.8% | 11.9% | 1 | 0.0% | 39 |
| ON (vp=1) | r3 | 50.3% | 16.0% | 0 | 0.0% | 39 |
| **ON mean** | | **50.8%** | **12.7%** | **0.33** | **0.0%** | **40.0** |
| OFF (vp=0) | r1 | 50.8% | 16.3% | 0 | 0.0% | 49 |
| OFF (vp=0) | r2 | 57.5% | 14.3% | 1 | 0.0% | 70 |
| OFF (vp=0) | r3 | 50.8% | 4.5% | 0 | 0.0% | 42 |
| **OFF mean** | | **53.0%** | **11.7%** | **0.33** | **0.0%** | **53.7** |

**Decision: REVERT E5 (verify_passes: 0).** Coverage delta +2.2pp for off (within 4.2pp
variance band). Broken% within the 18.1pp E11 band. Prose findings worse off (53.7 vs
40.0) but prose is a secondary metric and E19 (grounding pass) addresses it deterministically.
No primary metric favors E5-on. Saves compute and simplifies pipeline. Config default is
already `verify_passes: 0` — no code change needed; just don't set it in configs.

**Note:** An earlier E17 analysis (in RETRO3) reused E14_r1-r3 as the on-arm and concluded
KEEP E5. That comparison was flawed: E14 runs used a different config (pre-E15 v2 coverage
metric, different run conditions). The fresh A/B above is the authoritative result.

## E19 — Grounding Pass Results

**Change:** `repoquill/grounding.py` — post-generation LLM correction pass. Runs the
prose API-semantics checker internally, groups findings by page, and sends each affected
page + its findings + the AST API surface to the LLM (temp 0.1) with instructions to fix
ONLY the flagged claims. Wired into `cli.py` behind `grounding_pass: true` config flag
(default false).

| Run | Coverage v2 | Broken% | invalid_kwarg | Halluc% | Prose before | Prose after |
|-----|-------------|---------|---------------|---------|-------------|-------------|
| E19_r1 | 56.4% | 4.0% | 0 | 0.8% | 48 | 30 |
| E19_r2 | 51.4% | 5.7% | 0 | 0.0% | 47 | 2 |
| E19_r3 | 55.9% | 5.9% | 0 | 0.0% | 38 | 2 |
| **Mean** | **54.6%** | **5.2%** | **0** | **0.3%** | **44.3** | **11.3** |

vs E14 baseline: 54.6% coverage, 4.5% broken, 44.3 prose.

**Decision: KEEP.** Prose findings dropped 74.5% (44.3→11.3) with zero coverage loss
(54.6% = 54.6%). Decision rule met: prose < 20 AND coverage ≥ 50.4%. Broken% slightly
higher (5.2% vs 4.5%) but within variance band. Generic — works on any repo with
prose-checker findings.

**RETRO3 secondary check:** The 2 HIGH-severity semantic errors (language="en", missing
event-loop caveat) are only partially addressed. The event-loop caveat appeared in r2
only; language="en" persists in r1 and r3. Expected: these errors are outside the prose
checker's finding types, so the grounding pass can't fix what the checker doesn't flag.
Confirms the need for a semantic-value checker (backlog item).

## RETRO3 — Adversarial Findings (E14/E16 era)

Completed 2026-08-29. Four questions addressed:

**Q1: Is E14's broken% improvement real?** YES. E14 examples are MORE complex than E13b
(4.41 vs 3.79 avg kwargs/call; 29 vs 14 constructor calls). The 13.8→4.5% improvement is
genuine, not an artifact of simpler examples.

**Q2: Is v2 coverage a better proxy?** PARTIALLY. v2 is stricter (requires substantive
mention) but sensitive to run quality. One E17_off run initially showed 24.6% due to
checker timing (guides still being written); the final coverage.json showed 57.5%. v2
needs 3+ runs to stabilize.

**Q3: Is E16 REVERT correct?** DEFENSIBLE. Prose improved (44.3→30.7) but broken%
regressed (4.5→13.9%). Broken examples are user-facing defects; the tradeoff favors
keeping broken% low.

**Q4: Biggest blind spots in E14 docs:**
1. **`language="en"` instead of `language="English"` (HIGH)** — custom-scenarios.md:131,163
   and model-auditor.md:71 use `"en"`. Source default is `"English"` (full word). The
   `language` param is injected verbatim into the system prompt as `"Write in {language}"`.
   Passing `"en"` makes the model write in a language code. **Status: STILL PRESENT in E14.**
2. **`run()` event loop restriction not documented (HIGH)** — `run()` raises `RuntimeError`
   if called from an active event loop. E14 docs never mention this. A developer copying
   examples into Jupyter will crash. **Status: STILL PRESENT in E14.**
3. **`provider` argument (CRITICAL from E8 era)** — E8 docs omitted `provider` in 4 pages.
   **Status: FIXED in E14** (all examples include `provider`).

**Key insight:** The current checkers (example_check, hallucination_check,
prose_api_semantics_check) do NOT catch semantic value errors (wrong string literal) or
omissions (missing caveat). These are C-hallucinations that require either:
- A new checker type (semantic value validation), or
- The grounding pass (E19) to correct them post-generation.

## E20 — Semantic Value Checker Results

**Change:** `eval/semantic_value_check.py` — new deterministic checker with 2 finding types:
- **STRING_VALUE_MISMATCH:** flags string kwargs in code blocks that are strict
  prefixes/abbreviations of the source param's default (e.g. `language="en"` when
  source has `language: str = "English"`). Uses a global param-name → defaults map
  (param-name-agnostic) so it works regardless of which class the doc's call targets.
- **MISSING_CAVEAT:** flags method calls that have a known runtime caveat (raises
  exception under specific conditions) but the page doesn't mention the caveat.
  Uses a global method-name → caveats map (method-name-agnostic) so instance calls
  like `auditor.run(...)` match caveats on `ModelAuditor.run`.

| Doc set | Total findings | STRING_VALUE_MISMATCH | MISSING_CAVEAT |
|---------|---------------|----------------------|----------------|
| E14 (3 runs) | 12 | 3 (language="en") | 9 (event-loop caveat) |
| E19 (3 runs) | 12 | 3 (language="en") | 9 (event-loop caveat) |

**Both known RETRO3 errors caught.** 0 false positives (verified `"en"` is not a valid
source value; all 9 MISSING_CAVEAT findings are on pages that genuinely call `.run()`
without mentioning the event-loop restriction).

**Decision: KEEP.** Evaluation infrastructure only; no RepoQuill code change. Closes the
last major C-hallucination blind spot identified by RETRO3. Confirms that E19's grounding
pass cannot fix these errors (same 12 findings on E19 docs) because they are outside the
prose checker's finding types.

## E21 — Wire Semantic Checker into Grounding Pass + Test

**Change:** `repoquill/grounding.py` extended to run BOTH the prose checker
(`prose_api_semantics_check.py`) AND the semantic value checker
(`semantic_value_check.py`), merge their findings, and send the combined list to the LLM
for correction. The `_fix_page_grounding` prompt includes type-specific instructions:
STRING_VALUE_MISMATCH (change value to match source default) and MISSING_CAVEAT (add
brief caveat note).

**Test (isolated, on E14 guides — OOM constraint blocks full generation):**

| Metric | E14 (pre-grounding) | E19 (prose-only grounding) | E21 (prose+semantic grounding) |
|--------|---------------------|---------------------------|-------------------------------|
| Semantic findings | 12 | 12 | **1** (91.7% reduction) |
| Prose findings | 44.3 | 11.3 | **2** |
| Coverage (v2) | 54.6% | 54.6% | **56.4%** |
| Hallucination rate | 0.0% | 0.3% | **0.0%** |
| Pages fixed | — | — | 10 |
| Total findings (before→after) | — | — | 60→3 |

**Fixes verified:** All 3 `language="en"` → `language="English"` (custom-scenarios.md,
model-auditor.md). 8/9 event-loop caveats added (architecture.md, judges-evaluation.md,
custom-scenarios.md, model-auditor.md, key-ideas.md, cli-reference.md, installation.md,
available-scenarios.md). 1 remaining MISSING_CAVEAT is a false negative: `exp.run()` on
results-analysis.md is `AuditExperiment.run()` (no event-loop caveat), not
`ModelAuditor.run()`.

**Decision: KEEP (evaluation infrastructure only).** Closes the E20 loop: checker detects →
grounding pass fixes → re-checker verifies. 91.7% semantic finding reduction with zero
coverage regression (56.4% vs 54.6% baseline, +1.8pp) and zero hallucination regression
(0.0%).

**Limitations:** Tested in isolation on E14 guides, not a full generation (OOM
constraint). 1 remaining MISSING_CAVEAT is a false negative in the checker.

**E22 UPDATE:** Full generation validation (E22) showed that wiring the semantic checker
into the grounding pass is LESS effective than the prose-only grounding pass from E19.
Coverage dropped 54.6%→52.3% (-2.3pp) and prose findings increased 11.3→18.7 (+7.4).
The semantic findings that remain (4.7 mean) are mostly MISSING_CAVEAT findings that the
LLM can't reliably fix, and STRING_VALUE_MISMATCH findings in LLM-generated signature
blocks that the grounding pass misses. **REVERT E21/E22 — keep E19 (prose-only grounding)
as best-known state. Keep E20 (semantic checker) as evaluation infrastructure only.**

## E22 — Full 3-Run Validation of Grounding Pass

**Design:** 3 fresh runs of E14 baseline (verify_passes: 0, temp 0.7, context_budget
60000) + grounding pass with BOTH prose and semantic checkers. This is the first full
generation validation of the E21 wiring (E21 was tested in isolation on E14 guides).

| Run | Coverage v2 | Broken% | invalid_kwarg | Halluc% | Prose before→after | Sem before→after |
|-----|-------------|---------|---------------|---------|-------------------|-----------------|
| E22_r1 | 52.0% | 0.0% | 0 | 0.0% | 32→2 | 4→1 |
| E22_r2 | 59.2% | 0.0% | 0 | 0.0% | 36→27 | 8→8 |
| E22_r3 | 45.8% | 0.0% | 0 | 0.0% | 33→27 | 6→5 |
| **Mean** | **52.3%** | **0.0%** | **0** | **0.0%** | **18.7** | **4.7** |

vs E19 baseline: 54.6% coverage, 5.2% broken, 11.3 prose.

**Decision criteria:**
- Coverage within 4.2pp band of 54.6%: **PASS** (52.3%, delta -2.3pp)
- Broken% within 18.1pp band of 5.2%: **PASS** (0.0%, delta -5.2pp)
- Semantic findings < 5: **PASS** (4.7)
- Prose findings < 20: **PASS** (18.7)

**Decision: REVERT.** E22 is NOT demonstrably better than E19 overall. Coverage 52.3%
is -2.3pp vs E19's 54.6% (within the 4.2pp variance band, but a regression). Prose
findings 18.7 are +7.4 worse than E19's 11.3. Semantic findings 4.7 (new metric) are
not "near 0" — the grounding pass only reduced them by 21% (6.0→4.7). Broken% improved
from 5.2% to 0.0% and hallucination from 0.3% to 0.0%, but these are secondary metrics.

**Root cause:** The combined grounding pass (prose + semantic) sends more findings to the
LLM per page, which dilutes the correction signal. The LLM fixes prose findings
inconsistently (r1: 32→2, r2: 36→27, r3: 33→27) and semantic findings even less
reliably (r1: 4→1, r2: 8→8, r3: 6→5). The STRING_VALUE_MISMATCH findings in
LLM-generated signature blocks (`language: str = "en"`) are not reliably fixed because
the LLM doesn't recognize them as errors when they appear in what looks like an API
reference section. The MISSING_CAVEAT findings are partially fixed (event-loop caveats
added to some pages) but the LLM often adds the caveat in a way that the checker still
doesn't detect.

**Note:** r1 had the best results (prose 32→2, semantic 4→1) while r2 and r3 had poor
prose reduction (36→27, 33→27) and no semantic improvement (8→8, 6→5). The variance in
grounding pass effectiveness is high; a future experiment could investigate why some
runs get thorough correction while others don't.

**Action:** Revert to E19 (prose-only grounding) as best-known state. Keep E20
(semantic checker) as evaluation infrastructure only. Do NOT wire the semantic checker
into the grounding pass.

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

## E24 — Grounding Pass Variance (REVERT)

**Status:** COMPLETE — 12 runs (4 variants × 3 runs). No variant beats E19.

| Variant | Temp | Max | Cov% | Broken% | Prose | Sem | Halluc% |
|---------|------|-----|------|---------|-------|-----|---------|
| A | 0.1 | 20 | 52.5 | 9.1 | 2.3 | 10.3 | 0.00 |
| B | 0.0 | 20 | 55.1 | 13.9 | 1.3 | 8.3 | 0.00 |
| C | 0.1 | 5 | 52.9 | 9.1 | 21.7 | 7.7 | 0.00 |
| D | 0.0 | 5 | 51.4 | 4.9 | 22.7 | 6.0 | 0.00 |
| **E19** | **0.1** | **20** | **54.6** | **5.2** | **11.3** | — | **0.3** |

**Decision: REVERT.** No variant beats E19 on all metrics simultaneously.
- B (temp 0.0) has the best prose (1.3) and coverage (55.1%) but broken 13.9% (E19: 5.2%)
- C/D (max 5) have terrible prose (21.7/22.7) — limiting findings makes the LLM fix fewer issues
- A (same config as E19) has broken 9.1% vs E19's 5.2% — this is base-generation variance

**Key insight:** The broken-example regression is NOT caused by grounding pass parameters.
The dominant failure mode is **syntax_error** from API signature snippets (e.g.
`ModelAuditor(model: str, provider: str, ...)` in code blocks). These are a legitimate
documentation pattern, not actually broken examples. This is a **Goodharting concern**:
the metric counts signature snippets as "broken" when they're not really broken.

**Code changes (KEEP):** Added `grounding_temperature`, `grounding_max_findings`, and
`grounding_semantic` to LLMConfig. `run_grounding_pass()` now accepts `temperature`
and `include_semantic` parameters. CLI passes these from config. These config options
are useful for future experiments even though E24's specific variants didn't beat E19.

## E25 — Fix Example Checker to Exclude Signature Snippets (REVERT)

**Status:** COMPLETE — REVERT.

**Implementation:** Added `_is_signature_block()` to `eval/example_check.py` that detects
API signature snippets (blocks that fail to parse, start with `Name(` or `Name.Name(`,
contain type annotations, and don't have assignment statements).

**Pre-validation (on existing E19 docs):**
- E19_r1: 0.0% broken (was 4.0%)
- E19_r2: 10.5% broken (was 18.4%)
- E19_r3: 2.1% broken (was 2.1%)
- **Mean: 4.2%** (was 5.2%)

**Validation:** 3 fresh generation runs (E25_r1, E25_r2, E25_r3) with E19 config +
grounding pass.

| Run | Coverage v2 | Broken% | Prose | Halluc% |
|-----|-------------|---------|-------|---------|
| E25_r1 | 48.6% | 21.3% | 5 | 0.0% |
| E25_r2 | 50.3% | 6.0% | 1 | 0.0% |
| E25_r3 | 54.7% | 13.3% | 25 | 0.0% |
| **Mean** | **51.2%** | **13.5%** | **10.3** | **0.0%** |

vs E19 baseline (with fixed checker): 54.6% coverage, 4.2% broken, 11.3 prose, 0.3% halluc.

**Decision: REVERT.** The checker fix is correct (properly excludes signature snippets —
no syntax_error findings in E25 runs), but E25's broken% (13.5% mean) is WORSE than E19
(4.2% mean) with the same fixed checker. The high broken% is a real quality issue: the LLM
is generating genuinely broken examples (property_called_as_method, missing_required,
invalid_kwarg). The checker fix doesn't improve generation quality — it only makes the
metric more honest. Coverage also regressed (51.2% vs 54.6%).

**Key finding:** The broken-example regression is NOT caused by the checker. It's a
generation quality issue. E25 runs have more broken examples than E19 runs, even though
they use the same config (E19 config + grounding pass). This suggests either (1) the
grounding pass is introducing errors, or (2) LLM variance.

## E26 — E19 Config WITHOUT Grounding Pass (INFORMATIVE)

**Design:** 3 fresh runs of E19 config WITHOUT grounding pass. Goal: isolate whether the
grounding pass introduces broken examples. If broken% drops without grounding → grounding
pass is the cause. If similar → LLM variance.

| Run | Coverage v2 | Broken% | Prose | Halluc% |
|-----|-------------|---------|-------|---------|
| E26_r1 | 54.7% | 15.9% | 49 | 0.0% |
| E26_r2 | 52.5% | 17.5% | 29 | 0.0% |
| E26_r3 | 57.0% | 12.3% | 34 | 0.0% |
| **Mean** | **54.7%** | **15.2%** | **37.3** | **0.0%** |

vs E19 (WITH grounding): 54.6% coverage, 4.2% broken, 11.3 prose, 0.3% halluc.
vs E25 (WITH grounding, fixed checker): 51.2% coverage, 13.5% broken, 10.3 prose, 0.0% halluc.

**Decision: INFORMATIVE.** E26 (WITHOUT grounding) has broken% = 15.2% — WORSE than E25
(13.5%) and E19 (4.2%). The grounding pass is NOT the cause of the broken-example
regression. The dominant error type is `property_called_as_method` (13/14 findings in r1)
— the LLM consistently calls @property attributes as methods.

**Root cause identified:** `extract_api_surface()` in reference.py lists ALL FunctionDef
items as "methods" without checking for @property decorators. The LLM sees `score()` in
the API surface and correctly calls it as a method. 16 @property attributes exist in
SimpleAudit (mostly on AuditResults). This is a generic issue affecting any Python package
with @property.

## E27 — Mark @property Attributes in API Surface (KEEP)

**Hypothesis:** Marking @property attributes as PROPERTIES (not methods) in the API
surface extraction, plus adding a prompt rule to use them as attributes, will eliminate
the dominant `property_called_as_method` broken-example type.

**Changes:**
1. `repoquill/reference.py`: `extract_api_surface()` now detects @property and
   @cached_property decorators, lists them separately as `[PROPERTIES: name1, name2]`
   instead of in the methods list.
2. `repoquill/narrative.py`: Added rule 7 to strict prompt: "PROPERTIES (marked
   [PROPERTIES: ...] in the API surface) are attributes, NOT methods. Use them as
   `obj.name`, never as `obj.name()`."

**Results:**

| Run | Coverage v2 | Broken% | prop_as_method | Prose | Halluc% |
|-----|-------------|---------|----------------|-------|---------|
| E27_r1 | 53.6% | 2.4% | 0 | 12 | 0.0% |
| E27_r2 | 62.0% | 8.2% | 0 | 15 | 0.0% |
| E27_r3 | 49.7% | 0.0% | 0 | 13 | 0.0% |
| **Mean** | **55.1%** | **3.5%** | **0.0** | **13.3** | **0.0%** |

vs E19 baseline: 54.6% coverage, 4.2% broken, 11.3 prose, 0.3% halluc.

**Decision: KEEP.** property_called_as_method = 0 in 3/3 runs (was the dominant error
type in E25/E26). Broken% 3.5% (E19: 4.2%, E25: 13.5%, E26: 15.2%). Coverage 55.1%
(E19: 54.6%, within 4.2pp band). Halluc 0.0% (E19: 0.3%). Remaining broken findings
are syntax_error (5 total across 3 runs) from legitimate code blocks, not property calls.
Generic fix — any Python package with @property benefits.

## E28 — Strip Leading Indentation from Code Blocks (KEEP)

**Hypothesis:** The 5 remaining syntax_error findings across E27 runs are from code
blocks with leading indentation (a formatting artifact), not genuine code errors.

**Change:** `eval/example_check.py`: `extract_python_blocks()` now applies
`textwrap.dedent()` to each code block before returning it.

**Results (re-scored E27 docs):**

| Run | Broken% (before) | Broken% (after) | syntax_error (before→after) |
|-----|-----------------|-----------------|------------------------------|
| E27_r1 | 2.4% | 0.0% | 1 → 0 |
| E27_r2 | 8.2% | 2.0% | 3 → 0 (1 missing_required remains) |
| E27_r3 | 0.0% | 0.0% | 0 → 0 |
| **Mean** | **3.5%** | **0.7%** | **5 → 0** |

**Decision: KEEP.** De-Goodhart fix — the metric now measures code correctness, not
markdown formatting. All 5 syntax_error findings were from indented code blocks. The
remaining 1 missing_required finding in E27_r2 is a genuine error. No generation change.

## E29 — Investigate Remaining missing_required Finding (NO_ACTION)

**Hypothesis:** The 1 remaining `missing_required` finding in E27_r2 (AuditExperiment()
missing 'models' param) is either a genuine generation error or a checker false positive.

**Analysis:** `models` is a required param (no default) in AuditExperiment.__init__.
The LLM generated AuditExperiment() without it in 1/9 cases (E27_r2 cli-reference.md).
In the other 8 AuditExperiment() calls across 3 runs, the LLM correctly includes models.
This is a one-off generation error, not a systematic issue.

**Decision: NO_ACTION.** The E14 constructor signature enrichment is working correctly
(8/9 calls include required params). The 1 missing_required finding is within variance.
No prompt change or checker refinement warranted.

## RETRO5 — Research Retrospective (after E29)

Completed 2026-08-29. Three independent subagents (patterns, Goodhart, adversarial).
Synthesis in `/tmp/rq-trials/agents/RETRO5_synthesis.md`.

**Key findings (cross-validated):**

1. **Prose findings metric is ~92% one false positive.** The `RETURN_TYPE_MISMATCH`
   "vague return claim" branch in `prose_api_semantics_check.py` fires on "returns" + noun
   when the source method has no return annotation. "Returns a summary of the results" →
   3 findings (one per class with a `summary` member) × 4 lines × 2 pages = 12 findings.
   The "13.3 prose findings" headline is dominated by this FP. **Action: fix before
   anything else (E30).**

2. **0.0% hallucination has a 100% blind spot for top-level imports.**
   `hallucination_check.py` skips every `from simpleaudit import X` because `"simpleaudit"`
   is in `_KNOWN_NON_PROJECT` and `_is_project_module("simpleaudit")` returns False.
   Verified: `from simpleaudit import duplicate_scenario_names` (real ImportError) → 0
   hallucinations. **Action: fix (E31).**

3. **C-hallucination is the largest unmeasured gap.** Invented-symbol check verifies nouns
   exist; nothing verifies predicates. 8 CONTRADICTED semantics found in best-known state
   (passed/failed typed as bool, summary() returns string/dict, AuditExperiment.run()
   returns AuditResults, run_async without await, run_scenario documented as sync).
   **Action: build claim-verification checker (E32).**

4. **0.7% broken examples is honest about syntax but blind to runtime.** No async-usage
   check, no attribute-existence check, no CLI/shell block validation. True broken rate
   on sampled pages: ~55% vs reported 0.7%.

5. **Coverage v2 inventory has structural gaps.** `get_workflows()` scrapes docstring
   vocabulary (noise); `is_substantive_mention` over-credits code-block mentions; 3-run
   spread is 12.3pp.

6. **Usability is the ultimate blind spot but not the next step.** Claim-level factuality
   (Finding 3) is the next step that is high-impact, deterministic, generic, and reuses
   existing ground-truth code.

**Patterns from E22–E29:**
- Root-cause fixes win (E27). Tuning parameters (E24) or adding more checkers (E22)
  without understanding the root cause is ineffective.
- Evaluation-infrastructure changes are low-risk (E23, E28 consistently KEEP).
- The grounding pass is most effective when focused (E19 prose-only > E22 combined).
- Hand-authored structure beats LLM-planned structure (E15-LLM: -16.1pp coverage).

## RETRO6 — Research Retrospective (after E35)

Completed 2026-08-29. Single independent subagent (7-question prompt: pattern recognition,
metric health of C-hallucination, checker strategy options, diminishing returns, next
experiment recommendation, Goodhart risk).

**Key findings:**

1. **E30–E35 are two conflated programs.** E30/E31/E32 are measurement-integrity work
   (de-Goodharting checkers, introducing C-hallucination metric) — all correctly KEPT.
   E33/E34/E35 are intervention work (reducing C-hallucination) — all three REVERTED.

2. **The grounding pass is net-negative for factuality.** Every time a new checker's
   findings are fed to the LLM for correction, collateral metrics regress:
   - E22: coverage −2.3pp
   - E33: broken +2.2pp
   - E35: C-halluc +15.5pp, broken +1.5pp
   The grounding pass has a 0-for-3 record as a correction mechanism.

3. **api_signature_check.py line 466 is a genuine bug.** `method_name = claim["claimed_async"]`
   assigns a boolean to `method_name`, then does `if method_name in cls_info["methods"]`.
   `True in {"run_scenario": {...}}` is `False`, so ASYNC_MISMATCH can never fire.
   The E35 "CRITICAL → 0" result is partly an artifact of a checker that could not
   detect its own target class.

4. **The C-hallucination metric is not reliable enough for keep/revert decisions.**
   Tiny denominator (n≈16–30), regex-dependent (phrasing-sensitive), no variance band
   established. Recommendation: use claim COUNT (not rate) as the decision metric until
   a variance band exists. Track claim count as a co-metric to detect claim-suppression
   Goodhart gaming.

5. **The checker→grounding→revert loop has hit diminishing returns.** Three consecutive
   reverts (E22, E33, E35) on the same loop. The correction mechanism (grounding pass)
   has no demonstrated benefit. Stop this loop.

6. **Root cause convergence.** E33 (prompt rule), E34 (adversarial diagnosis), E35
   (deterministic checker) all targeted the same failure mode (name-based inference:
   `passed`→bool, `summary`→str, `run_scenario`→sync) from three directions. None worked.
   This is a **context problem** — the generator LLM is not reading member bodies when it
   writes prose. No amount of post-hoc correction fixes a claim that was never grounded
   in source.

7. **Recommended next experiment: E36 — Source-body injection for referenced members.**
   First intervention that targets the identified root cause (context, not correction).
   Same strategy as E14 (constructor signatures) and E27 (property detection) — both
   context-side fixes, both KEEP.

**Goodhart risk:** The C-hallucination rate is structurally Goodhartable via claim
suppression (fewer extractable claims → lower rate without factual improvement). E33's
prompt rule partially triggered this. Fix: track claim count alongside rate; require
claim count to be stable (±20%) for a rate improvement to count.

**Actions:**
1. Stop the checker→grounding→revert loop.
2. Run E36 (source-body injection) with a 1-run pilot first.
3. Use C-hallucination claim COUNT (not rate) as the decision metric until a variance
   band is established.
4. Keep checkers advisory (log findings, report in eval summary) — do NOT feed to
   grounding LLM.
5. Fix the api_signature_check.py line 466 bug before any future use.

## E36 — Source-Body Injection Results (KEEP)

**Hypothesis:** The dominant C-hallucination failure mode is name-based inference: the
LLM writes prose about a member (e.g. "``passed`` returns a list of scenario names that
passed") without seeing the function body, so it infers the return type from the name.
Injecting full AST-derived source bodies into the generation context will ground the LLM's
claims in actual code, eliminating name-inference C-hallucinations.

**Change:** `repoquill/reference.py`: new `extract_member_bodies()` function — AST-walks
all `.py` files, finds FunctionDef/AsyncFunctionDef nodes whose `.name` is in the given
set, renders the source body (capped at 40 lines each, 40000 chars total). `repoquill/narrative.py`:
extracts all public method/property names via AST, calls `extract_member_bodies()`,
appends the result to the enrichment block with the instruction "when you describe a
member's behavior, return value, or side effects, base it on this body, NOT on what the
name suggests."

**Pilot (E36_r1):** The 5 E34 CRITICAL name-inference findings (passed=bool, failed=bool
×2, summary→str, run_scenario→sync) are GONE. The 2 remaining contradicted claims are
checker FPs (`expected_behavior` "list" vs `Optional[List[str]]` — the doc correctly says
"list of expected safe behaviors"). Pilot PASSES.

**Full 3-run validation:**

| Run | Coverage v2 | Invented-symbol | Broken% | Prose | C-halluc (count) | C-halluc (rate) |
|-----|-------------|-----------------|---------|-------|-------------------|-----------------|
| E36_r1 | 74.9% | 2.68% | 13.3% | 4 | 2 | 28.6% |
| E36_r2 | 50.3% | 3.26% | 6.4% | 2 | 2 | 16.7% |
| E36_r3 | 55.9% | 0.00% | 0.0% | 1 | 0 | 0.0% |
| **Mean** | **60.4%** | **1.98%** | **6.6%** | **2.3** | **1.3** | **15.1%** |

vs Best-Known (E27-E32): 55.1% coverage, 0.7% invented-symbol, 0.7% broken, 5 prose, 2.0 C-halluc count.

**Decision: KEEP.**
- C-hallucination count: 1.3 vs 2.0 (improved — per RETRO6's decision rule)
- Prose findings: 2.3 vs 5 (improved)
- Coverage: 60.4% vs 55.1% (+5.3pp, though E36_r1's 74.9% is an outlier; r2/r3 are 50.3%/55.9%)
- Invented-symbol: 1.98% vs 0.7% (regressed — but E36_r3 hit 0.0%, so high variance)
- Broken examples: 6.6% vs 0.7% (regressed — but E36_r3 hit 0.0%)

The regressions in invented-symbol and broken examples are within the E11 variance bands
(broken-examples band 18.1pp; invented-symbol not previously banded but E36_r3 shows
0.0% is achievable). The core improvements (C-halluc count down, prose findings down)
are consistent across all 3 runs. The name-inference C-hallucinations E36 was designed
to fix (passed=bool, failed=bool) are eliminated in all 3 runs.

**Known issue:** E36_r1's 74.9% coverage is a significant outlier (r2: 50.3%, r3: 55.9%).
The 3-run mean (60.4%) is inflated by r1. The median (55.9%) is closer to the previous
best-known (55.1%). The coverage improvement is real but smaller than the mean suggests.

## E37 — C-hallucination Variance Band (COMPLETE)

**Design:** Re-run `claim_verification_check.py` 3 times on each of the 3 E36 doc sets
(9 checker runs total, no LLM calls).

**Results:**

| Doc set | check1 | check2 | check3 | Range |
|---------|--------|--------|--------|-------|
| E36_r1 | 2 | 2 | 2 | **0** |
| E36_r2 | 2 | 2 | 2 | **0** |
| E36_r3 | 0 | 0 | 0 | **0** |

**Finding:** The C-hallucination claim count is **fully deterministic** for a fixed doc
set. Variance band = 0. The 1.3 vs 2.0 improvement (E36 vs best-known) is real, not
noise. **E36 KEEP is confirmed.**

## E38 — Coverage Variance Analysis (COMPLETE)

**Design:** Diff the coverage JSON across the 3 E36 runs to identify what r1 covers
that r2/r3 don't.

**Finding:** The coverage variance is driven by **code-block presence**. E36_r1
consistently includes code examples that reference judge names, class names, and
method names (e.g., `judge="abstention"` in a code block). E36_r2 and r3 don't include
these code examples. The coverage checker's substantive-mention criterion counts
code-block mentions, so r1 scores higher.

**Implication:** The 3-run mean (60.4%) is inflated by r1's code examples. The
**median (55.9%)** is the honest coverage estimate. E36's coverage improvement over
the previous best-known (55.1%) is marginal (+0.8pp), not the +5.3pp the mean
suggested.

**E36 KEEP is still justified** by:
- C-hallucination count: 1.3 vs 2.0 (deterministic metric, confirmed by E37)
- Prose findings: 2.3 vs 5 (improved)
- Coverage: 55.9% (median) vs 55.1% (marginal improvement, within noise)

## E39 — Coverage Variance Band (COMPLETE)

**Design:** Run E36 config 2 more times (5 total) to establish the coverage variance
band.

**5-run results:**

| Run | Coverage | Halluc% | Broken% | Prose | C-halluc |
|-----|----------|---------|---------|-------|----------|
| E36_r1 | 74.9% | 2.68% | 13.3% | 4 | 2 |
| E36_r2 | 50.3% | 3.26% | 6.4% | 2 | 2 |
| E36_r3 | 55.9% | 0.00% | 0.0% | 1 | 0 |
| E39_r1 | 55.3% | 0.00% | 0.0% | 1 | 0 |
| E39_r2 | 55.3% | 0.00% | 0.0% | 1 | 0 |
| **Mean** | **58.3%** | **1.19%** | **3.9%** | **1.8** | **0.8** |
| **Median** | **55.3%** | **0.00%** | **0.0%** | **1** | **0** |

**Finding:** The coverage median is stable at 55.3–55.9% (0.6pp range across 4 of 5
runs). E36_r1 (74.9%) is a clear outlier driven by code-block presence (E38 finding).
The 5-run median metrics are strong: 55.3% coverage, 0.0% hallucination, 0.0% broken,
1 prose finding, 0 C-halluc. **E36 KEEP is strongly confirmed.**

## E40 — Usability Metric (v1 complete, v2 complete)

**Hypothesis:** A usability metric — measuring whether generated docs enable a new
developer to complete a concrete task — will reveal whether the docs are actually
useful, not just factually correct.

**Design:** 4 tasks derived from SimpleAudit's API surface. Probe gives a fresh LLM
session ONLY the generated docs + one task; independent judge scores the solution
against source code. Control = README-only baseline.

**v1 results (n=1 per task, judge had 50k/10-file source cap):**
- Generated docs: 1/4 correct (25%), 2/4 partial, 1/4 incorrect
- README-only control: 0/4 correct (0%, lower bound due to judge truncation), 3/4 partial, 1/4 incorrect
- Generated docs outperform README-only
- Failures are real docs-vs-source mismatches: (1) phantom top-level `get_scenarios`
  import (docs suggest it; source has it as `ModelAuditor.get_scenarios` static method),
  (2) wrong judge-config key (`output_schema` in docs vs `response_schema` in source),
  (3) `summary()` void-method misuse, (4) `AuditExperiment` `judge` param unclear

**v2 results (n=3 per task, fixed judge with per-task curated source slices):**
- Generated docs: 6/12 correct (50.0%), 4/12 partial (33.3%), 0 incorrect, 2/12 insufficient (16.7%)
- README-only control: 9/12 correct (75.0%), 0 partial, 0 incorrect, 3/12 insufficient (25.0%)
- **Generated docs LOSE to README by 25pp** — the first experiment to show generated docs can be worse than the existing README
- Per-task delta (generated − control):
  - run_safety_audit: 0% vs 100% (−100pp) — docs fail to document how to access individual `AuditResult` objects from `AuditResults` (DOCS_INSUFFICIENT 2/3 runs)
  - interpret_results: 100% vs 100% (0pp) — tied
  - custom_judge: 33% vs 0% (+33pp) — docs have wrong key name (`output_schema` vs `response_schema`), README has no judge config docs at all
  - use_experiment: 67% vs 100% (−33pp) — docs don't clarify that `summary()` prints and returns None
- **Key finding:** The docs have a critical gap (AuditResults iteration) and a factual error (wrong config key). The README is already quite good for 3 of 4 tasks.

**RETRO7 findings (independent retrospective, 7-question analysis):**
1. Convergence phase on factuality; E40 is the formal phase transition to "usefulness"
2. 4 of 5 metrics at floor (guardrails, not targets); coverage v2 has live Goodhart seam
3. E40 v1 has 4 defects: same-model judge bias, judge source context lossy (10 files,
   50k cap), n=4 too tiny, no "docs insufficient" refusal capture
4. Diminishing returns on AST→narrate→check loop; next order = page-conditional body
   injection (E41)
5. Goodhart risk real — pre-register holdout task set + delta-over-control headline
6. Branch by E40 outcome
7. 5-point completion criteria including cross-repo test (E42)

**TOP 3 ACTIONS from RETRO7:**
1. ~~Fix E40 probe defects + pre-register anti-Goodhart protocol~~ (DONE: E40v2)
2. Run cross-repo test E42 (IN PROGRESS)
3. Freeze E36 medians + re-scope to E41

## E42 — Cross-Repo Generalization Test (IN PROGRESS)

**Hypothesis:** The unmodified RepoQuill pipeline will produce factually correct,
useful documentation on an unrelated Python repository, validating the mission's
core rule ("Would this reasonably improve documentation for an unrelated repository?").

**Design:** Pick a small Python repo (10-50 source files) deliberately unlike
SimpleAudit. Run unmodified pipeline. Measure all 6 checkers. Compare to SimpleAudit
best-known.

**Repo chosen:** Click (pallets/click) — a CLI framework, completely different domain
(ML audit tool vs CLI framework), different API pattern (async classes vs decorators).
32 source files in src/click/.

**Status:** Generation succeeded (11/11 guides). Agent found a `package_dir` issue on
first attempt (0 modules documented — looked for `click/click/` not `src/click/`),
fixed config and re-running. Checkers not yet started.

## E44 — Table-Row Coverage Fix (KEEP)

**Hypothesis:** The 55.3% coverage plateau is partly a metric artifact. The docs DO
document scenario packs, judges, and modules in markdown tables, but
`coverage_check_v2.py`'s `is_substantive_mention()` doesn't count table rows as
substantive mentions. Adding table-row recognition should lift coverage without any
generation change.

**Change:** `eval/coverage_check_v2.py` — added item 5 to `is_substantive_mention()`:
a concept appearing in a markdown table row (`| ... |`) counts as a substantive mention.
This is a generic checker improvement (any repo with tabular docs benefits), consistent
with prior de-Goodhart work (E15, E23).

**Results (re-scored E43 docs, no generation change):**

| Category | Before | After |
|----------|--------|-------|
| Judges | 50% | 100% |
| Packs | 28.6% | 85.7% |
| Modules | 51.6% | 90.3% |
| **Overall** | **55.3%** | **69.8% (+14.5pp)** |

**Decision: KEEP.** Metric fix only — no generation change. The docs were already
documenting these concepts in tables; the checker just wasn't counting them. This is
the same class of fix as E15 (substantive-mention criterion) and E23 (de-Goodhart
workflows category). The 55.3% "plateau" was largely a metric artifact.

## E45 — Findability Diagnostic (ANALYSIS)

**Hypothesis:** The README beats the generated docs on E40v2 not because the generated
docs lack information, but because the generated docs SPREAD task-relevant patterns
across multiple pages. A fresh reader (or LLM) has to synthesize across pages, whereas
the README presents dense, task-shaped examples on one page.

**Method:** For each E40v2 task, identify the "solving patterns" (the specific code
constructs needed to solve the task). Then check: on how many pages do ALL solving
patterns co-occur? Compare generated docs (28 pages) vs README (1 page).

**Results:**

| Task | Generated docs (pages with ALL patterns) | README (pages with ALL patterns) |
|------|------------------------------------------|----------------------------------|
| run_safety_audit | **0** (no single page has all 4) | 1 (page 1) |
| interpret_results | **0** (no single page has all 4) | 1 (page 1, 3/4 patterns) |
| custom_judge | 1 (page 4/12: architecture.md) | 1 (page 1) |
| use_experiment | 1 (page 5/12: key-ideas.md) | 1 (page 1) |

**Key finding:** For the two most important tasks (run_safety_audit, interpret_results),
**NO single page in the generated docs contains all the solving patterns.** The
information is fragmented across multiple pages. The README concentrates the key
patterns in one place.

**Root cause:** The generated docs are organized by CONCEPT (model-auditor.md,
results-analysis.md, available-scenarios.md, etc.), not by TASK. A task like
"run a safety audit" requires patterns from 3+ different concept pages. The README
is organized by WORKFLOW (install → run → interpret), which matches how a developer
approaches the task.

**Implication:** This is a page-structure / information-architecture problem, not a
findability (search) problem. The fix is to ensure each guide page is **task-complete**
— if a page introduces a concept, it should include the complete usage pattern, not just
a fragment. Alternatively, add task-oriented "quickstart" sections that consolidate
cross-page patterns.

**Next experiment (E46):** Add a task-oriented quickstart section to the generated docs
that consolidates the solving patterns for the most common tasks into single-page
examples. This is a generic fix (any repo benefits from task-oriented quickstart
sections) and directly addresses the fragmentation identified by E45.

## RETRO7 — Research Retrospective (7th)

Completed 2026-08-29. Five findings:

1. **E40v2 task defect:** The custom_judge task text says `output_schema` but the
   source reads `response_schema`. The task itself is factually wrong. E43's
   "fix" fitted docs to a defective fixture. **Action:** Rebuild E40v2 task set from
   a blind source walk; fix the defective task; add a third arm (generated+README).
   Treat E40v2 as a regression probe, not a primary metric.

2. **Stop optimizing coverage v2 as primary metric:** Coverage v2 is now at 69.8%
   (after E44) and is a mention-frequency proxy, not a true coverage measure.
   **Action:** Decompose into reference-page coverage vs narrative coverage, OR
   retire in favor of fixed usability + factuality metrics.

3. **Findability is the highest-impact unknown:** E45 shows the generated docs
   fragment task-relevant patterns across pages. The README's single-page density
   wins. **Action:** E46 (task-oriented quickstart sections) is the highest-leverage
   next experiment.

4. **Kill or re-scope E41:** The decision rule (≥2pp improvement) is underpowered
   relative to the coverage variance band (2.1pp). **Action:** Kill E41.

5. **Add cross-page claim-consistency checker and redundancy metric:** Both are
   unmeasured. A claim that is true on one page but contradicted on another is a
   severe defect. **Action:** Design a cross-page consistency checker.

## Next Steps (re-ranked after RETRO7)

1. **E46 (NEW, from E45/RETRO7):** Task-oriented quickstart sections. Consolidate
   solving patterns for the most common tasks into single-page examples. Generic fix.
   This directly addresses the fragmentation identified by E45 and the README's
   density advantage.
2. **Fix E40v2 task defect:** Change `output_schema` → `response_schema` in the
   custom_judge task text. Rebuild task set from blind source walk.
3. **Cross-page consistency checker:** Design and implement a checker that detects
   claims true on one page but contradicted on another.
4. **Backlog:** async-usage check; attribute-existence check; de-SimpleAudit harness.
