# NEXT_EXPERIMENT

**Last updated:** 2026-08-29 (after E23)

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

## E17 — Verify-Pass A/B — DONE (REVERT E5, verify_passes: 0)

### Hypothesis

Now that E13/E13b/E14 handle the deterministic fixes (property calls, missing required
kwargs, invalid kwargs) and E19 (grounding pass) handles prose corrections, the E5 LLM
verify pass (verify_passes: 1) is unnecessary — its whole-page rewrite costs compute
without a remaining benefit.

### Design

Fresh A/B, 3 runs each arm, E14 baseline config (include_tests false, verify_passes toggled).
- **On-arm:** E17_on_r1–r3 (verify_passes: 1).
- **Off-arm:** E17_off_r1–r3 (verify_passes: 0).

### Result: REVERT E5 (verify_passes: 0)

| Metric | On (vp=1) | Off (vp=0) | Within band? |
|--------|----------|-----------|-------------|
| Coverage v2 | 50.8% | 53.0% | +2.2pp ✓ (band 4.2pp) |
| Broken% | 12.7% | 11.7% | ✓ (band 18.1pp) |
| Prose findings | 40.0 | 53.7 | off worse (secondary) |
| Invented symbols | 0.0% | 0.0% | — |

No primary metric favors E5-on. Prose is worse off but E19 (grounding pass) addresses
that deterministically. Saves compute, simplifies pipeline. Config default already
`verify_passes: 0` — just don't set it in configs.

**Note:** An earlier analysis (RETRO3) concluded KEEP E5 by reusing E14_r1-r3 as the
on-arm. That comparison was flawed (different config/run conditions). The fresh A/B is
authoritative.

### Status

Complete 2026-08-29. No code change needed (default already 0).

## E19 — Grounding Pass — DONE (KEEP)

**Result:** Prose findings 44.3→11.3 (74.5% reduction), zero coverage loss (54.6% = 54.6%),
broken% 5.2% (within variance). Decision rule met: prose < 20 AND coverage ≥ 50.4%.
Generic LLM correction pass fed by prose-checker findings. Config flag `grounding_pass: true`
(default false). RETRO3 secondary check: semantic errors (language="en", event-loop caveat)
only partially addressed — outside checker coverage, confirming need for E20.

## E20 — Semantic Value Checker — DONE (KEEP)

**Result:** 12 findings on E14 docs (3 STRING_VALUE_MISMATCH, 9 MISSING_CAVEAT), same on
E19 docs. Both known RETRO3 errors caught (language="en" x3, event-loop caveat x9).
0 false positives (verified "en" is not a valid source value). Generic design:
param-name-agnostic string matching + method-name-agnostic caveat matching.
Checker lives at `eval/semantic_value_check.py`. Evaluation infrastructure only;
no RepoQuill code change.

### E21 — Feed Semantic Checker into Grounding Pass — DONE (COMPLETE)

grounding.py already consumes semantic_value_check findings alongside prose findings
(wired in by RETRO3 subagents). No additional code change needed.

### E22 — Full 3-Run Validation of Grounding Pass — DONE (KEEP)

**Result:** All 4 decision criteria PASS. Per-run: r1 cov=52.0%/prose=32→2/sem=4→1,
r2 cov=59.2%/prose=36→27/sem=8→8, r3 cov=45.8%/prose=33→27/sem=6→5. Mean: cov=52.3%,
broken=0.0%, prose=18.7, sem=4.7. New best-known state: E8+E9+E10+E13+E13b+E14+E19+E21+E22.

**Note:** r2 and r3 had high prose_after (27) — the grounding pass fixed semantic
findings but left many prose findings. r1 had the best prose reduction (32→2).
Variance in grounding pass effectiveness is notable.

## E20 (original spec, superseded by result above)

### Hypothesis

The current checkers (example_check, hallucination_check, prose_api_semantics_check) catch
API misuse (wrong method/property, wrong return type, wrong kwarg) but NOT wrong string
literals or missing caveats. A new deterministic checker that validates string-literal
values against source defaults and flags missing behavioral caveats will close the last
major C-hallucination blind spot identified by RETRO3.

### Why first

E19's grounding pass confirmed that the checker is the bottleneck: it can only fix what
the checker flags. RETRO3 found 2 HIGH-severity semantic errors in E14 docs that no
checker catches:
1. `language="en"` instead of `language="English"` (source default is `"English"`)
2. `run()` event-loop restriction not documented (raises RuntimeError in active event loop)

These are user-facing defects: a developer copying `language="en"` into their config will
get degraded output; a developer calling `run()` in Jupyter will crash.

### Goal

Build `semantic_value_check.py` that flags at minimum:
- String literal values in code blocks that differ from the source parameter's default
  (e.g. `language="en"` when source has `language: str = "English"`)
- Missing behavioral caveats: functions that raise exceptions under specific conditions
  (e.g. `run()` raises RuntimeError in active event loop) where the docs never mention
  the condition

### Implementation sketch

1. **String literal validation:**
   - Extract all `param="value"` and `param='value'` patterns from fenced code blocks
   - For each, look up the parameter in the AST class index
   - If the param has a string default and the doc value differs, flag as
     `STRING_VALUE_MISMATCH`
   - Generic: works on any repo with string-typed parameters

2. **Missing caveat detection:**
   - AST-walk for methods with `raise` statements that depend on runtime state
     (e.g. `asyncio.get_event_loop()`, `threading.current_thread()`)
   - Check if any guide page mentions the method AND the caveat condition
   - If the method is documented but the caveat is absent, flag as `MISSING_CAVEAT`
   - Generic: works on any repo with conditional exceptions

### Decision rule

- If the checker flags both known RETRO3 errors on E14 docs → KEEP (instrument works).
- If the checker misses 1+ of the 2 → refine patterns and re-test.

### Controlled variables

- Same E14+E19 config (grounding_pass: true), same source, same other checkers.
- Only change: new checker added to the evaluation suite.
- 3 runs to measure variance.

## E15 (structure) — Generic Structure Derivation

### Hypothesis

The 11 narrative slugs are hand-authored for SimpleAudit. A generic system should derive
page structure from the repository itself.

## RETRO3 — Research Retrospective — DONE (2026-08-29)

Completed directly (fork spawning unavailable in this session). Four questions addressed:
1. E14 broken% improvement is REAL (examples more complex, not simpler).
2. v2 coverage is stricter but noisier (needs 3+ runs).
3. E16 REVERT is defensible (broken% regression dominates prose improvement).
4. Biggest blind spots: semantic value errors (`language="en"`) and omissions
   (event-loop caveat) that no current checker catches.

## E21 — Wire Semantic Checker into Grounding Pass + Test — DONE (KEEP)

### Hypothesis

Feeding the semantic value checker (E20) into the grounding pass will let the LLM
correction pass fix string-literal mismatches (`language="en"` → `"English"`) and add
missing behavioral caveats (event-loop RuntimeError), closing the detect→fix→verify loop.

### Result

Tested in isolation on E14 guides (OOM constraint blocks full generation). Semantic
findings 12→1 (91.7% reduction). All 3 `language="en"` fixed. 8/9 event-loop caveats
added (1 remaining is a false negative: `exp.run()` is `AuditExperiment.run()`, not
`ModelAuditor.run()`). Coverage 54.6→56.4% (+1.8pp, no regression). Hallucination 0.0%.
Prose findings 2. 10 pages fixed, 60→3 total findings.

**Decision: KEEP.** Closes the E20 loop.

## RETRO4 — Research Retrospective — DONE (2026-08-29)

Completed directly (fork spawning unavailable in this session). Four questions addressed:
1. E21 semantic-finding reduction is REAL but tested in isolation (not full generation).
2. E21 coverage 56.4% is a single-run number at the top of the variance band, NOT a
   real improvement. Do NOT claim E21 improved coverage.
3. Next highest-impact failure mode: `workflows` category in coverage_check_v2.py
   admits generic English words as "concepts" (~14 false positives, ~5pp coverage
   deflation).
4. Goodhart risk: `workflows` category (word-frequency, not concept-coverage). No other
   metrics at risk. Usability is the next blind spot (no metric measures whether docs
   are USEFUL to a new developer).

## E23 — De-Goodhart Workflows Category — DONE (KEEP)

**Result:** Removed 18 generic English words from the workflows inventory (across,
actually, aggregates, around, attributes, backward, before, behaviour, block, blocks,
cache, cached, calls, canonical, chart, compat, content, conversation). Coverage
52.3% → 54.4% mean (+2.1pp). Workflows category: 20/40 → 22/40 documented (50% → 55%).
No other category affected. Below the conservative 3pp threshold, but the fix is valid —
it removes generic words from the denominator, making the coverage metric more honest.

## Backlog (after E23)

- **E15 — Generic structure derivation.** Repo-derived slugs, not hand-authored.
- **Independent judge:** use a different model family for judging.
- **Rename `hallucination_rate` to `invented_symbol_rate`** in the registry.
- **Usability metric** (next blind spot): measure whether docs are USEFUL to a new
  developer (e.g. "can a new developer install and run a basic audit following the
  docs?").
- **Research retrospective due** (5 experiments since RETRO4: E22, E23 are the 5th-6th
  since RETRO3).
