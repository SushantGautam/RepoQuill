# Next Experiment

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
