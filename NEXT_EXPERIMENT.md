# NEXT_EXPERIMENT

## E50: Deterministic import-path verification pass

**Status:** DESIGNED, NOT STARTED

### Context

E49 (KEEP) fixed the empty API Reference section by auto-detecting package_dir
and adding a deterministic fallback in `_reference_sections`. The remaining
quality gap is S-hallucination: the LLM invents import paths for symbols that
exist in submodules but are not re-exported at the root level.

Two confirmed instances across E41/E47 runs:
1. `from simpleaudit import duplicate_scenario_names` — the function exists in
   `scenarios/__init__.py` but is NOT re-exported at the root. Correct import:
   `from simpleaudit.scenarios import duplicate_scenario_names`.
2. `from simpleaudit.visualization import server` — `visualization/` has no
   `__init__.py`, so `simpleaudit.visualization` is not an importable module.
   Correct import: `from simpleaudit.visualization.server import server`.

### Hypothesis

A deterministic post-generation pass that extracts `from X import Y` statements
from generated code examples, resolves X against the actual package structure
(which modules exist, what's in each `__init__.py`'s `__all__`), and rewrites
incorrect imports to the correct path will eliminate S-hallucination without
LLM involvement.

### Change

New function `fix_import_paths(content, pkg_path)` in `repoquill/verify.py`:
1. Extract all `from X import Y` and `import X` statements via regex/AST.
2. For each, check if X is a real importable module (has `__init__.py` or is a `.py` file).
3. If X exists but Y is not in X's namespace, search submodules for Y.
4. Rewrite the import to the correct path.
5. If Y is not found anywhere, leave as-is (flag for manual review).

Wired into cli.py after the existing `fix_type_claims` pass.

### Decision Rule

KEEP if S-hallucination drops to 0% AND coverage >= 65% AND no other metric
regresses > 1pp. REVERT if any metric regresses.

### Genericity

Pure AST/path-based import resolution — works for any Python package. No
SimpleAudit-specific logic.
