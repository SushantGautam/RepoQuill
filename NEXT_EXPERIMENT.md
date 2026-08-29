# NEXT_EXPERIMENT

## E48: Deterministic import-path verification pass

**Status:** DESIGNED, NOT STARTED

### Context

E47 (KEEP) eliminated C-hallucination (0% both runs) via a deterministic
type-annotation verification pass. The remaining quality gap is S-hallucination:
the LLM invents import paths for symbols that exist in submodules but are not
re-exported at the root level.

Two confirmed instances across E41/E47 runs:
1. `from simpleaudit import duplicate_scenario_names` — the function exists in
   `scenarios/__init__.py` but is NOT re-exported at the root. Correct import:
   `from simpleaudit.scenarios import duplicate_scenario_names`.
2. `from simpleaudit.visualization import server` — `visualization/` has no
   `__init__.py`, so `simpleaudit.visualization` is not an importable module.
   Correct import: `from simpleaudit.visualization.server import server`.

Both are real runtime-failing imports that a developer copying the docs would hit
immediately.

### Hypothesis

A deterministic post-generation pass that:
1. Extracts all `from X import Y` and `import X.Y` statements from generated
   code blocks (AST-parse each python block, collect Import/ImportFrom nodes)
2. Verifies each import resolves against the actual package structure:
   - For `from simpleaudit import Y`: check if Y is in `simpleaudit/__init__.py`
     (parse `__all__` or `from X import Y` re-exports)
   - For `from simpleaudit.sub import Y`: check if `sub/__init__.py` exists and
     re-exports Y, or if Y is defined in `sub.py`
   - For `import simpleaudit.sub`: check if `sub.py` or `sub/__init__.py` exists
3. If an import fails, fix it by finding the correct module path via AST search
   (search all `.py` files for the symbol definition, derive the import path)
4. If no fix is found, flag the import for the grounding pass (or remove it)

...will eliminate the S-hallucination import-path errors without LLM involvement,
mirroring E47's architecture (deterministic AST lookup, no variance, no side
effects).

### Design

1. **Baseline:** E47 output (already have it: 0.5% S-hallucination median,
   1 real error in r1).
2. **Change:** Add `fix_imports(content, pkg_path)` in `repoquill/verify.py`:
   - Parse each fenced python block with `ast.parse()`
   - Collect all `Import` and `ImportFrom` nodes
   - For each import, verify resolution against the package structure:
     - Build an index of all importable symbols: for each `.py` file, parse
       top-level names (functions, classes, `__all__` entries, re-exports)
     - For `from X import Y`: check if Y is importable from X
     - For `import X.Y`: check if X.Y is an importable module
   - If an import is wrong, search the index for the correct module that
     defines Y, and rewrite the import statement
   - Only fix imports that are clearly wrong (symbol exists in the package
     but at a different path). Do NOT touch imports of external packages.
3. **Wire into cli.py:** After type-claim verification (E47), before [6/6]
   site assembly.
4. **Run:** 2 runs from clean state (same config as E47).
5. **Measure:** S-hallucination rate (target: 0%), coverage v2 (target: ≥65%),
   C-hallucination (target: 0%), broken examples (target: ≤2.4%), prose
   findings (target: ≤2).
6. **Decision rule:** KEEP if S-hallucination 0% in both runs AND no other
   metric regresses >1pp. REVERT if any metric regresses.

### Why this is generic

Import-path verification is a universal technique — it works for any Python
package. The fix is deterministic (no LLM involvement), so it has no variance
and no side effects on other metrics. Any package with submodules and
re-exports benefits.

### Alternative approaches (if E48 fails)

1. **Checker-side fix (ground_truth.py):** Parse `__all__` and add re-exported
   names to module_symbols; handle submodules without `__init__.py`. This
   changes the METRIC (S-hallucination rate would drop because the checker
   would no longer flag legitimate imports), which requires careful Goodhart
   analysis — it makes the metric more honest but doesn't fix the docs.
2. **Prompt rule:** Add a rule to the strict prompt: "When writing import
   statements, verify the symbol is actually importable from the stated module.
   Check `__init__.py` for re-exports." Risk: prompt dilution (E3/E4 pattern),
   and the LLM may not reliably verify import paths.
3. **Accept as known limitation:** 0.5% S-hallucination (1 real error in 1 of
   2 runs) may be an acceptable residual. The error is in a code block, not
   prose, so it's less likely to mislead a developer reading the narrative.

### RETRO8 note

E45/E46/E47 have completed since RETRO7. A RETRO8 retrospective is due. Run it
before or alongside E48 to ensure the experiment direction is still valid.
