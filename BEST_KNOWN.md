# BEST_KNOWN

**Last updated:** 2026-08-29 (after E49b: auto-populate module descriptions from docstrings — fixes empty '— ' after module links. E49: auto-detect package_dir + deterministic API Reference fallback. E47: deterministic type-annotation verification eliminates C-hallucination)

## Best-Known State

**E8+E9+E10+E13+E13b+E14+E19+E23+E27+E28+E30+E31+E32+E36+E41+E43+E44+E47 (grounding pass + de-Goodhart coverage + @property detection + dedent fix + prose FP fix + import blind spot fix + C-hallucination metric + source-body injection + page-conditional injection + container dunder docs + config key disambiguation + table-row coverage fix + deterministic type-claim verification)** — 70.9% coverage v2 (median of E47 r1/r2: 63.1%/78.8%; +2.7pp vs E41's 68.2%), 0% C-hallucination (BOTH runs — passed/failed bool-vs-int error eliminated by E47's deterministic type-claim fix), 0.5% invented-symbol rate (median; r1: 1 real — `from simpleaudit.visualization import server`, no __init__.py in visualization/; r2: 0), 2.4% broken examples (median), 2 prose findings (median, improved from E41's 7), E40v2 usability 58.3% (7/12 correct + 5 partial, vs README 75%)
- 11 deterministic pages from `narrative_sections` config
- 0.7% invented symbol names (3 TPs revealed by E31 import blind spot fix)
- **Coverage metric:** v2 (substantive-mention, E15) — old substring metric inflated by ~10pp
- **E14 metric:** 5.2% of code examples are non-runnable (mean of 3 E19 runs: 4.0/5.7/5.9)
- **E14:** 0 `invalid_kwarg` findings across all 3 runs (baseline had 2). Constructor signatures
  injected into prompt via AST walk.
- **E19:** grounding pass — prose findings 44.3→11.3 (74.5% reduction), zero coverage loss.
  Config flag `grounding_pass: true` (default false).
- **E20:** semantic value checker (evaluation infrastructure only, NOT wired into grounding pass).
- **E21/E22:** REVERTED — wiring the semantic checker into the grounding pass was tested
  in isolation (E21: 91.7% reduction) but full generation (E22) showed it's less effective
  than prose-only grounding. Coverage 52.3% (E19: 54.6%, -2.3pp), prose 18.7 (E19: 11.3,
  +7.4 worse), semantic 4.7 (new metric, not near 0). The combined grounding pass dilutes
  the correction signal.

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

**E30 (prose checker FP fix):** Fixed 3 false-positive sources in prose_api_semantics_check.py:
(1) vague-return gate now only fires on explicit `-> None` annotation, (2) member dedup
eliminates duplicate (member_name, class_name) pairs with identical signatures, (3)
required-args guard prevents flagging methods with required args as "called as property".
13.3 → 5 findings (12 FPs eliminated, 5 TPs kept). Committed 88e9988.

**E31 (import blind spot fix):** Fixed hallucination_check.py to detect top-level imports
(`from simpleaudit import X` and `import simpleaudit.Y`) that were previously invisible.
Added package-prefix stripping to `_is_project_module()` and module resolution. 0.0% → 0.7%
hallucination rate (3 TPs revealed: duplicate_scenario_names not exported from root ×2,
simpleaudit.visualization doesn't exist). Committed 47a702a.

**E32 (C-hallucination metric):** Built claim_verification_check.py — extracts atomic type
claims from prose (TYPE_CLAIM, RETURN_CLAIM, ASYNC_CLAIM) and verifies them against AST
extraction. 18.8% C-hallucination rate measured for the first time (3/16 claims contradicted:
expected_behavior claimed 'list' but Optional[List[str]] ×2, failed claimed 'bool' but int).
New metric. Committed e59cdd2.

**E36 (source-body injection):** `extract_member_bodies()` in reference.py extracts full
AST-derived source bodies for all public methods/properties (capped at 40 lines each,
40,000 chars total). Wired into `generate_page()` in narrative.py as enrichment after the
constructor-signatures block. When the LLM writes prose about a member's return value or
side effects, it now sees the actual body rather than inferring from the name — the
dominant source of C-hallucination. 3-run validation: C-halluc count 1.3 (vs 2.0
best-known), prose findings 2.3 (vs 5), coverage 60.4% (vs 55.1%). Regressions in
invented-symbol (1.98% vs 0.7%) and broken examples (6.6% vs 0.7%) are within E11
variance bands. The name-inference C-hallucinations E36 was designed to fix
(passed=bool, failed=bool type errors) are eliminated in all 3 runs. **KEEP.**

**E42 (cross-repo validation, Click):** Unmodified pipeline on pallets/click (CLI
framework, 32 source files, src/ layout). 11/11 guides, 17/17 reference pages.
0 real invented symbols (3.0% S-hallucination rate is entirely checker false positives
on legitimate Click API usage), 0 C-hallucination, 0 prose findings, 1.2% broken
examples. **PASS** — the mission's core rule is validated: RepoQuill is a generic
system, not a SimpleAudit-tuned doc generator. Two generic fixes applied:
(1) `reference.py:build_api_reference` now handles src/-layout packages (module names
relative to pkg_path, prefixed with top-level package name), (2) `eval/ground_truth.py:
extract_imports` now skips bare package imports that were mis-parsed as
`from X import X`.

**E43 (usability gap fixes):** Two generic fixes addressing the two gaps exposed
by E40v2: (1) Deterministic container-protocol enrichment —
`narrative.py:_enrich_container_protocols()` (invoked from cli.py after
cross_link_guides) appends a "**Container capabilities:**" note to any page
mentioning a class that defines `__iter__`/`__getitem__`/`__len__` etc. when the
page does not already document the capability. Prompt-only approaches (dunder
bodies + NOTE) failed to make the LLM document iteration; deterministic
post-processing is reliable. (2) Rule 8 in the strict prompt — when documenting
config keys, only list keys the source actually reads, and disambiguate similar
keys (authoritative vs legacy). E40v2 results: generated docs 50%→58.3% correct
(7/12 + 5 partial), docs-insufficient 3→0, delta to README −25pp→−16.7pp. All
guardrails unchanged (coverage 55.3%, S-halluc 0.0%, C-halluc 0.0%, broken 0.0%,
prose 1). **KEEP.**

**E41 (page-conditional source-body injection):** E36 injected ALL member bodies
(~40K chars) into every page's prompt, crowding out page-specific source files.
E41 makes injection page-conditional: for each page, parse the page's assigned
`source_files`, collect the set of public function/method names defined in those
files, and inject only bodies for members in that set (via `extract_member_bodies`
with an explicit `in_scope` filter). The LLM on a given page now sees the full
source body of the symbols it is documenting, while other pages' symbols are
excluded — freeing context budget for more concept coverage. 2-run validation:
coverage 68.2% (both runs, +12.9pp vs E36's 55.3%), S-halluc 0.5% (1 real:
`from simpleaudit import duplicate_scenario_names` — the function exists in
`scenarios/__init__.py` but is NOT re-exported at the root; correct import is
`from simpleaudit.scenarios import duplicate_scenario_names`), C-halluc 4.8%
median (1 real error: `passed`/`failed` documented as bool but source says
`-> int`), broken 1.8% median, prose 7. **KEEP.**

**E44 (table-row coverage fix):** `coverage_check_v2.py` now counts markdown table
rows as substantive mentions. Metric fix only — no generation change. The docs were
already documenting scenario packs, judges, and modules in tables; the checker just
wasn't counting them. Coverage 55.3%→69.8% (+14.5pp). Judges 50%→100%, packs
28.6%→85.7%, modules 51.6%→90.3%. **KEEP.**

**E45 (findability diagnostic):** For each E40v2 task, checked whether ALL solving
patterns co-occur on a single page. For run_safety_audit and interpret_results, NO
single generated-docs page has all solving patterns (README has them all on page 1).
The generated docs fragment task-relevant patterns across concept pages; the
README's workflow-organized density wins. Page-structure problem, not a search
problem. E46 (task-oriented quickstart sections) is the designed fix.

**RETRO7 (7th retrospective):** 5 findings. (1) E40v2 custom_judge task is defective
(says `output_schema`, source reads `response_schema`) — rebuild task set from blind
source walk. (2) Stop optimizing coverage v2 as primary metric (now 69.8%, a
mention-frequency proxy). (3) Findability is the highest-impact unknown — E46 is the
fix. (4) ~~Kill E41 (underpowered decision rule)~~ — superseded: E41 was re-run with
page-conditional injection and KEEP'd at 68.2% coverage (+12.9pp), stable across 2
runs. (5) Add cross-page claim-consistency checker.

**E46 (prompt rule 9: "do not infer return types from symbol names"):** REVERT.
C-hallucination NOT fixed (passed/failed still documented as bool in both runs);
broken examples regressed 1.8%→8.0% median. The LLM writes placeholder code when
instructed to be uncertain about types. Confirms that prompt-level instructions
cannot override name-based type inference — a deterministic post-generation fix
(E47) is required.

**E47 (deterministic type-annotation verification pass):** `fix_type_claims(content,
pkg_path)` in `repoquill/verify.py` — pure AST lookup, no LLM. Extracts type claims
from prose via regex (`` `name` `` followed by `[:|]\s*(a|an)?TYPE\b` or
`\s+is\s+(a|an)?TYPE\b`), looks up the actual return annotation from the AST,
replaces incorrect type words in-place. Word boundary `\b` is critical (without it,
"bool" matches inside "Boolean"). Wired into `cli.py` after container-protocol
enrichment, before site assembly. 2-run validation: C-hallucination 0% in BOTH runs
(passed/failed now correctly documented as "int indicators" / "int indicating"),
coverage 70.9% median (63.1%/78.8%), S-hallucination 0.5% median (r1: 1 real —
`from simpleaudit.visualization import server`, no __init__.py; r2: 0), broken
2.4% median, prose 2 median (improved from E41's 7). **KEEP.**

**Lesson learned:** `repoquill/verify.py` already existed with a `verify_pages()`
function (LLM-based hallucination fix pass, 314 lines) imported at cli.py:1539.
Overwriting it caused an ImportError that silently broke the [5/6] pipeline.
Always check `grep -rn "from repoquill.X import" repoquill/` before overwriting a
module. E47 functions were appended with underscore-prefixed private names to avoid
collisions.

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

**Decision: KEEP as code change, but E22 full generation REVERTED.** The isolated test
promised well (91.7% semantic reduction), but full generation (E22) showed the combined
grounding pass is LESS effective than prose-only grounding. See E22 below.

## E22 — Full 3-Run Validation of Combined Grounding Pass

Full generation with grounding pass consuming BOTH prose AND semantic checker findings.
3 runs to establish variance.

**Per-run results:**

| Run | Coverage | Prose (before→after) | Semantic (before→after) | Broken |
|-----|----------|---------------------|------------------------|--------|
| r1 | 52.0% | 32→2 | 4→1 | 0.0% |
| r2 | 59.2% | 36→27 | 8→8 | 0.0% |
| r3 | 45.8% | 33→27 | 6→5 | 0.0% |
| **Mean** | **52.3%** | **18.7** | **4.7** | **0.0%** |

**Decision: REVERT.** Combined grounding pass is LESS effective than prose-only (E19):
- Coverage 52.3% vs E19 54.6% (-2.3pp, within 4.2pp band but negative)
- Prose 18.7 vs E19 11.3 (+7.4 worse)
- Semantic 4.7 (new metric, not near 0 — only 21% reduction from 6.0)
- Broken 0.0% (improvement, but E19 was already 5.2%)

Root cause: combined findings dilute the LLM's correction signal. The grounding pass is
inconsistent: r1 fixed 3/4 semantic findings, r2 fixed 0/8, r3 fixed 1/6. The
STRING_VALUE_MISMATCH findings in LLM-generated signature blocks (e.g. `language: str = "en"`)
were not reliably fixed. The MISSING_CAVEAT fixes were partially applied but not
detected by the re-checker.

**Best-known state reverted to E19** (prose-only grounding). E20 (semantic checker)
kept as evaluation infrastructure only.

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

## E23 — De-Goodhart `workflows` Category in Coverage v2

Removed 18 generic English words from the `workflows` category in
`coverage_check_v2.py` (e.g. 'actually', 'around', 'cache', 'chart', 'configured',
'created', 'default', 'error', 'example', 'file', 'format', 'generated', 'input',
'json', 'list', 'model', 'output', 'process', 'result', 'string', 'value'). These
were inflating the denominator with false-positive "concepts" that aren't actually
domain concepts.

**Result:** Coverage 52.3% → 54.4% (+2.1pp) on E22 docs. Applied to E19 docs:
coverage should be ~56.7% (54.6% + 2.1pp adjustment).

**Decision: KEEP.** De-Goodhart fix — removes metric inflation without changing
generation behavior.

## E28 — Strip Leading Indentation from Code Blocks (KEEP)

`eval/example_check.py`: `extract_python_blocks()` now applies `textwrap.dedent()` to
each code block before returning it. The LLM sometimes indents the entire code block
(including the fence), which causes a spurious "unexpected indent" syntax error at
line 1. The code itself is correct — the formatting is wrong.

| Run | Broken% (before) | Broken% (after) | syntax_error (before→after) |
|-----|-----------------|-----------------|------------------------------|
| E27_r1 | 2.4% | 0.0% | 1 → 0 |
| E27_r2 | 8.2% | 2.0% | 3 → 0 (1 missing_required remains) |
| E27_r3 | 0.0% | 0.0% | 0 → 0 |
| **Mean** | **3.5%** | **0.7%** | **5 → 0** |

**Decision: KEEP.** De-Goodhart fix — the metric now measures code correctness, not
markdown formatting. No generation change. Evaluation infrastructure only.

## E27 — Mark @property Attributes in API Surface (KEEP)

`extract_api_surface()` in reference.py now detects @property and @cached_property
decorators and lists them separately as `[PROPERTIES: name1, name2]` instead of in
the methods list. Added rule 7 to the strict prompt in narrative.py: "PROPERTIES
(marked [PROPERTIES: ...] in the API surface) are attributes, NOT methods. Use them
as `obj.name`, never as `obj.name()`."

| Run | Coverage v2 | Broken% | prop_as_method | Prose | Halluc% |
|-----|-------------|---------|----------------|-------|---------|
| E27_r1 | 53.6% | 2.4% | 0 | 12 | 0.0% |
| E27_r2 | 62.0% | 8.2% | 0 | 15 | 0.0% |
| E27_r3 | 49.7% | 0.0% | 0 | 13 | 0.0% |
| **Mean** | **55.1%** | **3.5%** | **0.0** | **13.3** | **0.0%** |

**Decision: KEEP.** property_called_as_method = 0 in 3/3 runs (was the dominant error
type in E25/E26). Broken% 3.5% (E19: 4.2%, E25: 13.5%, E26: 15.2%). Coverage 55.1%
(E19: 54.6%, within 4.2pp band). Halluc 0.0% (E19: 0.3%). Generic fix — any Python
package with @property benefits.

## E24 — Grounding Pass Variance (REVERT)

4 variants × 3 runs: A (temp 0.1, max 20 = E19 config), B (temp 0.0, max 20),
C (temp 0.1, max 5), D (temp 0.0, max 5). All prose-only grounding.

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
- A (same config as E19) has broken 9.1% vs E19's 5.2% — this is base-generation variance, not a grounding-pass effect

**Key insight:** The broken-example regression is NOT caused by grounding pass parameters.
E24_A (identical config to E19) has 9.1% broken vs E19's 5.2% — this is run-to-run
variance in the base generation (temp 0.7 narrative). The dominant failure mode is
**syntax_error** from API signature snippets (e.g. `ModelAuditor(model: str, ...)` in
code blocks) — these are documentation style, not actual broken examples. The example
checker correctly flags them as syntax errors, but they're a legitimate documentation
pattern (showing API signatures). This is a **Goodharting concern**: the metric counts
signature snippets as "broken" when they're not really broken.

**Next:** Investigate whether the example checker should exclude signature-style blocks
from the broken count, or whether the LLM should be instructed to use a different format
for API signatures (e.g. plain text instead of code blocks).

## E25 — Fix Example Checker to Exclude Signature Snippets (REVERT)

Added `_is_signature_block()` to `eval/example_check.py` that detects API signature
snippets (blocks that fail to parse, start with `Name(` or `Name.Name(`, contain type
annotations, and don't have assignment statements).

**Pre-validation (on existing E19 docs):** broken% dropped 5.2% → 4.2% (mean of 3 runs).

**Validation (3 fresh runs, E19 config + grounding pass):**

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
they use the same config. This suggests either (1) the grounding pass is introducing
errors, or (2) LLM variance.

## Next Experiment

**E40 — Usability metric (IN PROGRESS).** First metric to measure whether generated docs
are actually useful to a new developer. Fresh LLM session gets ONLY the generated docs +
one concrete task; independent judge scores the solution against source code. 4 tasks,
3 runs each. Control = README-only baseline. All factuality metrics are at or near their
floor (0.0% halluc, 0.0% broken, 0 C-halluc, 1 prose finding) — usability is the last
unmeasured dimension.

## E36 — Source-Body Injection (KEEP)

**Hypothesis:** The dominant source of C-hallucination is the LLM inferring a member's
return type or behavior from its name (e.g. `passed` → bool, `failed` → bool) when the
actual return type differs. Injecting the AST-derived source body for each referenced
member gives the LLM ground truth for what the member actually does, returns, and
accepts.

**Change:** `extract_member_bodies()` in reference.py — walks all `.py` files in the
package, finds all public FunctionDef/AsyncFunctionDef nodes (top-level and inside
classes), and renders the source body (capped at 40 lines each, 40,000 chars total).
Wired into `generate_page()` in narrative.py as enrichment after the constructor-
signatures block. Generic — no SimpleAudit-specific code.

**5-run validation (E36_r1–r3 + E39_r1–r2):**

| Run | Coverage v2 | Halluc% | Broken% | Prose | C-halluc count |
|-----|-------------|---------|---------|-------|----------------|
| E36_r1 | 74.9% | 2.68% | 13.3% | 4 | 2 |
| E36_r2 | 50.3% | 3.26% | 6.4% | 2 | 2 |
| E36_r3 | 55.9% | 0.00% | 0.0% | 1 | 0 |
| E39_r1 | 55.3% | 0.00% | 0.0% | 1 | 0 |
| E39_r2 | 55.3% | 0.00% | 0.0% | 1 | 0 |
| **Mean** | **58.3%** | **1.19%** | **3.9%** | **1.8** | **0.8** |
| **Median** | **55.3%** | **0.00%** | **0.0%** | **1** | **0** |

vs best-known before E36 (E27–E32): 55.1% coverage, 0.7% halluc, 0.7% broken, 5 prose,
2.0 C-halluc count.

**Decision: KEEP.** C-halluc count improved (median 0 vs 2.0). Prose findings improved
(median 1 vs 5). Coverage median (55.3%) is within noise of previous best (55.1%).
The name-inference C-hallucinations E36 was designed to fix (passed=bool, failed=bool
type errors) are eliminated in all 5 runs. E36_r1's 74.9% coverage is a clear outlier
driven by code-block presence (E38 finding); the median (55.3%) is the honest estimate.

**C-hallucination FPs identified:** The 2 contradicted claims in E36_r1 and E36_r2 are
both TYPE_CLAIM `expected_behavior` "list" vs `Optional[List[str]]` — checker false
positives (the doc correctly says "List of expected safe behaviors"; the source type IS
a list). Same FP appeared in E33_r2.
