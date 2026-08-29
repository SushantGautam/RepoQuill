# Next Experiment

## E29 Results (NO_ACTION)

**Analysis:** `models` is a required param (no default) in AuditExperiment.__init__.
The LLM generated AuditExperiment() without it in 1/9 cases (E27_r2 cli-reference.md).
In the other 8 AuditExperiment() calls across 3 runs, the LLM correctly includes models.
This is a one-off generation error, not a systematic issue.

**Decision: NO_ACTION.** The E14 constructor signature enrichment is working correctly
(8/9 calls include required params). No prompt change or checker refinement warranted.

## Next: Research Retrospective (RETRO5)

3 subagents launched (patterns, Goodhart, adversarial). Awaiting results.

After RETRO5, the next experiment will be chosen based on the retrospective findings.
Likely candidates:
- Usability metric (next blind spot per RETRO4)
- Independent judge (different model family)
- Rename `hallucination_rate` → `invented_symbol_rate` (naming clarity)

## E28 Results (KEEP)

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
markdown formatting. All 5 syntax_error findings were from indented code blocks. No
generation change.

## E29 — Investigate Remaining missing_required Finding

**Hypothesis:** The 1 remaining `missing_required` finding in E27_r2 (AuditExperiment()
missing 'models' param) is either a genuine generation error or a checker false positive.
If genuine, a prompt fix can address it. If a false positive, the checker needs refinement.

**Context:** After E27 eliminated property_called_as_method and E28 eliminated
syntax_error (formatting artifacts), the only remaining broken-example type is
missing_required (1 finding in E27_r2).

**Design:**
1. Inspect the specific code block in E27_r2 that triggers the missing_required finding.
2. Check the AuditExperiment.__init__ signature in the source code.
3. Determine: is 'models' truly required (no default)? Is the LLM omitting it?
4. If genuine: add a prompt rule or enrichment to ensure required params are included.
5. If false positive: refine the checker's required-param detection.

**Decision criteria:**
- If genuine: KEEP prompt fix (generation improvement).
- If false positive: KEEP checker refinement (de-Goodhart).

**Baseline for comparison:** E27+E28 (55.1% coverage, 0.7% broken, 13.3 prose, 0.0% halluc).

## E27 Results (KEEP)

| Run | Coverage v2 | Broken% | prop_as_method | Prose | Halluc% |
|-----|-------------|---------|----------------|-------|---------|
| E27_r1 | 53.6% | 2.4% | 0 | 12 | 0.0% |
| E27_r2 | 62.0% | 8.2% | 0 | 15 | 0.0% |
| E27_r3 | 49.7% | 0.0% | 0 | 13 | 0.0% |
| **Mean** | **55.1%** | **3.5%** | **0.0** | **13.3** | **0.0%** |

vs E19 baseline: 54.6% coverage, 4.2% broken, 11.3 prose, 0.3% halluc.

**Decision: KEEP.** property_called_as_method = 0 in 3/3 runs (was the dominant error
type in E25/E26). Broken% 3.5% (best ever). Coverage 55.1% (best ever, within band).
Generic fix — any Python package with @property benefits.

## E28 — Investigate Remaining syntax_error Findings

**Hypothesis:** The 5 remaining syntax_error findings across 3 E27 runs are from
legitimate code blocks (not API signature snippets) that the example checker is
incorrectly flagging. If so, the checker should be refined to exclude them, or the
prompt should be adjusted to avoid the pattern.

**Context:** After E27 eliminated property_called_as_method (0 in 3/3 runs), the
remaining broken findings are all syntax_error (5 total). E24 already identified
signature snippets as a Goodharting concern — E25's checker fix (excluding signature
blocks) was REVERTED because E25's broken% was worse than E19's (13.5% vs 4.2%).
But E27's broken% is 3.5% (better than E19's 4.2%), so the syntax_error findings
are now the only remaining broken-example type.

**Design:**
1. Inspect the 5 syntax_error findings in E27_r1/r2/r3 eval outputs.
2. Classify each: is it a signature snippet, a legitimate code block, or a genuine error?
3. If signature snippets → refine `_is_signature_block()` in example_check.py to catch
   the remaining patterns (E25's version may have been too narrow).
4. If legitimate code blocks → the checker is too aggressive; adjust the detection logic.
5. If genuine errors → investigate what's causing the LLM to generate them.

**Decision criteria:**
- If findings are signature snippets: KEEP refined checker (de-Goodhart, no generation change).
- If findings are legitimate code blocks: KEEP checker refinement (more honest metric).
- If findings are genuine errors: investigate root cause before changing anything.

**Baseline for comparison:** E27 (55.1% coverage, 3.5% broken, 13.3 prose, 0.0% halluc).

## Backlog (after E28)

1. **Research retrospective due** (7 experiments since RETRO4: E22, E23, E15, E24, E25,
   E26, E27).
2. **Backlog:** rename `hallucination_rate` → `invented_symbol_rate`; independent judge
   (different model family); usability metric (next blind spot per RETRO4).
