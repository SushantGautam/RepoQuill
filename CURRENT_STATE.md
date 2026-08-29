# CURRENT_STATE

**Last updated:** 2026-08-29 (E27 KEEP)
**Best-known state:** E8+E9+E10+E13+E13b+E14+E19+E23+E27 (grounding pass with prose checker only + de-Goodhart coverage + @property detection) — 55.1% coverage v2 (mean of 3 runs), 0.0% invented-symbol rate, 3.5% broken examples, 13.3 prose findings mean
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

## Next Steps (re-ranked after E29 NO_ACTION)

1. **Research retrospective in progress** (RETRO5: 3 subagents launched — patterns,
   Goodhart, adversarial).
2. **Backlog:** rename `hallucination_rate` → `invented_symbol_rate`; independent judge
   (different model family); usability metric (next blind spot).
