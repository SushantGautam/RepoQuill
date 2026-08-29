# Next Experiment

## E31 Results (KEEP)

**Change:** `eval/hallucination_check.py` — 3 fixes to eliminate the top-level import blind spot:

1. **Remove "simpleaudit" from `_KNOWN_NON_PROJECT`**: Previously all `from simpleaudit import X`
   statements were silently skipped.

2. **Update `_is_project_module()` to accept `pkg_name`**: Now checks if the module name
   (or a prefix) matches when the package prefix is stripped. Also treats the package root
   itself as a valid module.

3. **Handle submodule imports**: `from simpleaudit import judges` (where `judges` is a
   submodule) is now correctly grounded, not flagged as a hallucination.

**Results (re-scored E27_r3):**

| Metric | Before (E27) | After (E31) | Change |
|--------|-------------|-------------|--------|
| Hallucination rate | 0.0% | 0.7% | +0.7pp |
| High-severity findings | 0 | 3 | +3 |
| Grounded imports | 406 | 449 | +43 |

The 3 new findings are TRUE POSITIVES:
- `from simpleaudit import duplicate_scenario_names` (×2 pages) — exists in
  `simpleaudit.scenarios` but NOT exported from root
- `from simpleaudit.visualization import server` — module doesn't exist

**Decision: KEEP.** De-Goodhart fix — the metric now measures real hallucinations,
not blind spots. The 0.0% headline was 100% blind to top-level imports. No generation
change.

## Next: E32 — Build Claim-Verification Checker (C-hallucination)

**Hypothesis:** The largest unmeasured gap is C-hallucination — doc references a REAL
symbol but asserts a FALSE fact about it. RETRO5 identified 8 CONTRADICTED semantics
in the best-known state (e.g., `passed`/`failed` typed as bool when they're int counts,
`summary()` returns "string" when it prints and returns None).

**Design:**
1. Build a claim-verification checker on `ground_truth.py` that extracts atomic claims
   from generated docs (e.g., "X is a bool", "Y returns a list", "Z is async").
2. Validate each claim against the source AST.
3. Classify claims as SUPPORTED / CONTRADICTED / UNVERIFIABLE.
4. Report the C-hallucination rate (CONTRADICTED / total_claims).

**Baseline for comparison:** E27+E28+E30+E31 (55.1% coverage, 0.7% broken, 5 prose, 0.7% halluc).

## E30 Results (KEEP)

**Change:** `eval/prose_api_semantics_check.py` — 3 fixes to eliminate false positives:

1. **Vague-return gate**: Only flag "Returns a <noun>" when source EXPLICITLY annotates
   `-> None`. Previously flagged on missing annotation (ambiguous — method might return
   something unannotated).

2. **Member dedup**: Dedupe `member_lookup` so one sentence → one finding, not one per
   same-named class. Previously "Returns a summary of the results" generated 3 findings
   (one per class with a `summary` member: AuditResults, ModelStabilityReport,
   RepeatedExperimentResults).

3. **Required-args guard**: `PROSE_METHOD_AS_PROPERTY` now only flags when the method
   takes required args (no defaults). Previously flagged unconditionally, contradicting
   the documented intent.

**Results (re-scored E27_r3):**

| Metric | Before (E27) | After (E30) | Change |
|--------|-------------|-------------|--------|
| Prose findings | 13.3 (mean of 3) | 5 (single run) | -62.4% |
| False positives | ~12 | 0 | -100% |
| True positives | 1 | 5 | +4 (4 summary() TPs + 1 install-extra) |

The 4 remaining `summary()` findings are TRUE POSITIVES — the doc claims "Returns a
summary" but `summary()` only prints and returns None. The 1 `MISSING_INSTALL_EXTRA`
is also a true positive.

**Decision: KEEP.** De-Goodhart fix — the metric now measures real semantic errors,
not false positives. The 13.3 headline was ~92% false positive. No generation change.

## Next: E31 — Fix Top-Level Import Blind Spot

**Hypothesis:** `hallucination_check.py` skips all `from simpleaudit import X` statements
because "simpleaudit" is in `_KNOWN_NON_PROJECT` and `_is_project_module()` returns
False for the project root module. This creates a 100% blind spot for top-level imports.

**Evidence:** `from simpleaudit import duplicate_scenario_names` (r3/available-scenarios.md:44)
is a real ImportError but generates 0 hallucination findings.

**Design:**
1. Remove "simpleaudit" from `_KNOWN_NON_PROJECT` in `hallucination_check.py`.
2. Special-case the project root module in `_is_project_module()` so top-level imports
   are checked against the actual module namespace.
3. Re-score E27 docs with the fixed checker.
4. Expect: 0.0% hallucination rate may increase (new blind spot revealed).

**Decision criteria:**
- If new findings are true positives: KEEP (de-Goodhart, more honest metric).
- If new findings are false positives: refine the checker further.

**Baseline for comparison:** E27+E28+E30 (55.1% coverage, 0.7% broken, 5 prose, 0.0% halluc).

## Backlog (after E31)

1. **E32**: Build claim-verification checker (C-hallucination metric) on `ground_truth.py`.
2. **Async-usage check**: Add to `example_check.py` to catch `run_async()` without `await`.
3. **Attribute-existence check**: Add to `example_check.py` to catch `result.recommendation`
   (field is `recommendations`).
4. **Reframe hallucination headline**: "0.0% hallucination" → "0.0% invented symbols
   (S-hallucination); C-hallucination unmeasured".
5. **De-SimpleAudit the harness**: Make `ground_truth.py` and checkers generic.
6. **Usability metric**: Non-self-judging usability probe.
