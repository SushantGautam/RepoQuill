# NEXT_EXPERIMENT

**Last updated:** 2026-08-29 (after E16)

## E13b — Fix the `<REQUIRED>` Placeholder — DONE (KEEP, 5c08779)

### Hypothesis

E13's `fix_missing_required` inserts `"<REQUIRED>"` as a placeholder for missing required
kwargs. This is syntactically valid but not runnable — a real user copying the example gets
a `TypeError`/`ValueError`. The placeholder satisfies the checker's `missing_required` test
(the param is now present as a kwarg) but is semantically a trap. Replacing the placeholder
with a valid inferred value (from the param's default, a test value, or a documented example)
or omitting the kwarg with an annotation will make the broken-examples metric honest.

### Why first

RETRO2 found that 10 of 13 residual findings across the E13 runs are E13's own `<REQUIRED>`
placeholders (19 across 9 of 11 e2e pages). The "6.2% broken" headline is largely
self-inflicted. The true residual is ~3 `invalid_kwarg` blocks. Fixing the placeholder is:
- Deterministic (no LLM, no sampling variance)
- Zero-hallucination-risk
- Makes the baseline honest for every subsequent experiment
- De-risks E14's decision rule (which is currently gated on a placeholder-inflated number)

### Goal

Reduce placeholder-patched examples from 19 to 0. Re-baseline broken-examples% with the
placeholder-aware checker. The new "true" broken% should be ~3–5% (the 3 `invalid_kwarg`
blocks plus any remaining genuine errors).

### Implementation sketch

1. **Add `placeholder_value` finding type to `example_check.py`:**
   - Any constructor call containing `<...>`, `TODO`, `...`, or a known sentinel string
     in a kwarg value is flagged as `placeholder_value`.
   - A block with `placeholder_value` is **broken**, not fixed.

2. **Change `surgical_verify.py` `fix_missing_required`:**
   - Instead of inserting `"<REQUIRED>"`, try to infer a real value:
     a. Check if the param has a default in the AST (use it).
     b. Check if the package's tests use a value for this param (use it).
     c. Check if the param's docstring mentions an example value (use it).
     d. If none can be inferred, **omit the kwarg** and add a comment:
        `# NOTE: <arg> is required — see <module>.<class>.__init__`
   - Never insert a sentinel string.

3. **Re-run all 6 E11 runs + 1 e2e run** through the updated pipeline.
4. **Re-run all checkers:** E12 (example validity with new `placeholder_value` type),
   coverage, hallucination.

### Controlled variables

- Same config (E8: 11 slugs), same source, same checker (with new `placeholder_value` type).
- Only change: `fix_missing_required` no longer inserts `<REQUIRED>`.
- 3 runs to measure variance.

### Decision rule

- If placeholder-patched examples drop to 0 AND broken-examples% is in the range 3–8%
  (the true residual) → KEEP.
- If broken-examples% jumps above 15% → the inferred values are wrong; revert to
  omitting the kwarg with an annotation (conservative fallback).
- If coverage drops >4.2pp (2× variance band) → REVERT.

### Risk

Inferring values from tests may pick up test-specific values that are not representative
of real usage. Mitigation: prefer param defaults over test values; if no default exists,
omit the kwarg with an annotation rather than guessing.

## E18 — Prose API Semantics Checker — DONE (KEEP)

**Result:** 7/7 known adversarial errors caught. 52 findings on E13_e2e docs
(30 property-as-method, 16 return-type, 4 arg-type, 2 install-extra) vs 38 findings
on E13b_run1 (best-known) — discrimination confirmed. Checker lives at
`/tmp/rq-trials/harness/prose_api_semantics_check.py`. Evaluation infrastructure only;
no RepoQuill code change. E16 (tests-as-evidence) is now unblocked.

## E18 — Prose API Semantics Checker (original spec)

### Hypothesis

The adversarial RETRO2 agent found 7 source-verified factual errors in markdown prose/tables
(method-vs-property, return-type, argument-type confusion). All are missed by the current
checkers because they only parse ```python code blocks. A new deterministic checker that
extracts API-usage claims from prose and validates them against the AST class index will
catch this class of error.

### Why second

Without this checker, the C-hallucination axis (behavioral correctness) is unmeasurable.
E16 (tests-as-evidence) needs it as a readout. The 7 errors found by the adversarial agent
are the most severe defects in the current docs — more severe than the 3 `invalid_kwarg`
blocks.

### Goal

Build `prose_api_semantics_check.py` that flags at minimum:
- Property written as method in prose (`passed()` when source has `@property passed`)
- Return-type mismatch ("returns a list" when source has `-> int`)
- Argument-type mismatch for free functions (`compare_judges` documented as taking
  `AuditResults` when source annotates `RepeatedExperimentResults`)
- Cross-page method/property inconsistency

### Implementation sketch

1. Extend `build_class_index` to record return annotations per method/property.
2. Extract API-usage claims from markdown prose (outside ```python blocks):
   - Bullet claims: `* `name(args)`: <description>``
   - Table cells: `| `name(args)` | ... |`
   - Return-shape phrases: "Returns a dictionary", "Return lists of", etc.
3. Validate each claim against the AST index.
4. Cross-page consistency sub-check.

### Decision rule

- If the checker flags all 7 known errors on the current E13 docs → KEEP (instrument works).
- If the checker misses 3+ of the 7 → refine patterns and re-test.

## E14 — Constructor Signature Injection — DONE (KEEP, 2edd930)

**Results:** invalid_kwarg = 0 in 3/3 runs (baseline had 2); coverage 65.6% mean
(drop 2.3pp < 4.2pp threshold); broken% 4.5% mean (was 13.8%); halluc 0.0%.
Committed as `2edd930`.

## De-Goodhart Coverage (E15) — DONE (KEEP)

**Result:** coverage_check_v2.py written. Old substring metric inflated coverage by ~10pp.
E14 honest coverage = 54.6% mean (not 65.6%). E13b honest coverage = 65.4%.
v2 is now the canonical coverage metric. Evaluation infrastructure only — no RepoQuill code change.

## E16 — Tests-as-Evidence — DONE (REVERT, ea23ac1 default off)

**Result:** Broken% regressed 4.5→13.9% mean (+9.4pp). Coverage dropped 1.7pp.
Prose findings improved (44.3→30.7) but broken% regression dominates.
Tests crowd out source context without net benefit at 60KB budget.
Code kept (default off) for future experiments with larger context budgets.

## E17 — Investigate E5 Regression — NEXT

### Hypothesis

Now that E13b handles the deterministic fixes, the LLM verify pass (E5) is unnecessary
and its −8.9pp coverage cost is pure harm.

### Goal

A/B test: E5 on vs off, 3 runs each, on the E14 baseline. If E5-off has equal or better
metrics → revert E5.

### Changes

1. **Config A (E5 on):** `verify_passes: 1` in llm config (current E14 state)
2. **Config B (E5 off):** `verify_passes: 0` in llm config
3. 3 runs each, same E14 baseline, same checkers (v2 coverage, example_check, hallucination, prose)

### Decision rule

- If E5-off coverage ≥ E5-on coverage (within variance) AND broken% ≤ E5-on → revert E5.
- If E5-off coverage < E5-on by >4.2pp → E5 is genuinely helping; keep E5.
- Either way, record the A/B result in registry.

## E15 — Generic Structure Derivation

### Hypothesis

The 11 narrative slugs are hand-authored for SimpleAudit. A generic system should derive
page structure from the repository itself.

## Backlog (after E16)

- **E19 — Grounding pass.** Feed E18 findings back into generation to correct
  method/property confusion.
- **E15 — Generic structure derivation.** Repo-derived slugs, not hand-authored.
- **Independent judge:** use a different model family for judging.
- **Rename `hallucination_rate` to `invented_symbol_rate`** in the registry.
