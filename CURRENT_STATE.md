# CURRENT_STATE

**Last updated:** 2026-08-29 (after E16)
**Best-known state:** E8+E9+E10+E13+E13b+E14 (commit 2edd930) — 54.6% coverage v2 (mean of 3 runs), 0.0% invented-symbol rate, 4.5% broken examples (HONEST), 0 placeholders
**Experiments complete:** E1–E13 + E13b + E18 + E14 + E15 + E16 + RETRO2 (3 independent subagents: patterns, Goodhart, adversarial). E17 (verify-pass A/B) IN PROGRESS — off-arm running.
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
| E17 | verify-pass A/B (verify_passes 1 vs 0) | — | — | — | **IN PROGRESS** (off-arm running) |

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

**E8+E9+E10+E13+E13b (commit 5c08779)** — 67.9% coverage (mean of 3 runs; within 2× band of 70.7%), 0.0% hallucination rate, 13.8% honest broken examples
- 11 deterministic pages from `narrative_sections` config
- 277 grounded claims (mean of 3 runs: 287/294/250), 0 invented symbol names
- **E13:** deterministic surgical verify pass fixes ~35pp of broken examples post-generation
- **E13b:** `<REQUIRED>` placeholder replaced with value inference (AST default, sibling mirroring) or omit+comment. 0 placeholders across 3 runs. Broken% now honest (13.8% mean vs E13's 6.2% placeholder-inflated).

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

## Next Steps (re-ranked after E16)

1. **E17 — verify-pass A/B (IN PROGRESS).** E5's LLM verify pass (verify_passes: 1) was
   "KEEP (not well-justified)" since E11: −8.9pp coverage for +0.12pp hallucination.
   Now that E13/E13b/E14 handle the deterministic fixes, the LLM rewrite pass is likely
   pure cost. A/B: verify_passes 0 vs 1, 3 runs each, E14 baseline config otherwise.
   Decision rule: if off-arm has broken% ≤ on-arm + 4.2pp AND coverage ≥ on-arm − 4.2pp
   → REVERT E5 (set verify_passes: 0 in config; saves ~30s/page of LLM calls).
   Off-arm (E17_off_r1–r3) launched 2026-08-29; on-arm = existing E14_r1–r3.
2. **E19 — Grounding pass.** Feed E18 findings back into generation to correct
   method/property confusion (E14 mean prose findings = 44.3; E16 showed tests help prose
   but hurt broken% — a deterministic correction pass may get the prose benefit without
   context bloat).
3. **E15 (structure) — Generic structure derivation.** Repo-derived slugs, not hand-authored.
4. **Research retrospective (RETRO3)** — due (5 experiments since RETRO2). A Goodhart-audit
   fork was launched at end of E16 segment; fold its result in when it lands.
5. **Backlog:** rename `hallucination_rate` → `invented_symbol_rate`; independent judge
   (different model family); fix noisy `workflows` category in coverage_check_v2.py
   (includes generic words like 'actually', 'around').
