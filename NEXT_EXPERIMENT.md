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

## E32 Results (KEEP)

**Change:** `eval/claim_verification_check.py` — NEW checker that extracts atomic
factual claims from generated docs and validates them against the source AST.

**Claim types checked:**
1. TYPE_CLAIM — "X is a bool/int/list/dict/str" vs source annotation
2. RETURN_CLAIM — "X() returns a list/dict/str/None" vs source return annotation
3. ASYNC_CLAIM — "X() is async" vs source @async def
4. FIELD_CLAIM — "result.X" where X doesn't exist on the class

**Results (E27_r3):**

| Metric | Value |
|--------|-------|
| Total claims | 16 |
| Contradicted | 3 |
| Supported | 9 |
| Unverifiable | 6 |
| **C-hallucination rate** | **18.8%** |

The 3 contradicted claims:
- `expected_behavior` claimed as `list` but actually `Optional[List[str]]` (×2 classes)
- `failed` claimed as `bool` but actually `int`

**Decision: KEEP.** New metric that measures the largest unmeasured gap (C-hallucination).
The 18.8% rate is a significant finding — nearly 1 in 5 factual claims in the best-known
state is contradicted by the source. No generation change.

## Next: E33 — Reduce C-hallucination Rate

**Hypothesis:** The 18.8% C-hallucination rate is driven by the LLM making confident
but wrong type claims (e.g., "bool" when the field is "int", "list" when it's
"Optional[List[str]]"). A prompt change that encourages the LLM to be more conservative
about type claims (or to verify them against the source) could reduce the rate.

**Design:**
1. Analyze the 3 contradicted claims to identify the pattern.
2. Test hypothesis: is the LLM confident but wrong, or is it hedging?
3. If confident but wrong: add a prompt rule that encourages the LLM to be more
   conservative about type claims (e.g., "If you're not sure about the type, say
   'a value' instead of 'a bool'").
4. If hedging: the prompt is already conservative; the issue is elsewhere.
5. Generate 3 new runs with the prompt change.
6. Measure C-hallucination rate.
7. Compare against E27+E28+E30+E31 baseline (18.8% C-hallucination).

**Decision criteria:**
- If C-hallucination rate drops by ≥5pp: KEEP (generation improvement).
- If C-hallucination rate is unchanged or worse: REVERT.

**Baseline for comparison:** E27+E28+E30+E31+E32 (55.1% coverage, 0.7% broken, 5 prose, 0.7% halluc, 18.8% C-halluc).

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
