"""Opt-in, bounded, docs-only repair runtime (autopilot plan P1 item 8).

Repairs generated guide pages without touching the source package:

1. **Deterministic first (no LLM, always tried):** surgical fixes
   (``fix_property_calls``, ``fix_missing_required`` from
   :mod:`repoquill.surgical_verify` and ``fix_type_claims`` from
   :mod:`repoquill.verify`) are applied to the page text.  The page is
   rewritten only if the text actually changed, then re-diagnosed.
2. **LLM second (only if a ``client`` is provided and deterministic
   diagnostics remain):** the model receives ONLY the page text, the
   specific findings, and an API evidence excerpt built from the real
   AST symbol index of the package.  Every candidate is gated:

   * **evidence guard** — any NEW import/symbol the candidate
     introduces (not present in the current findings) must exist in the
     package symbol index, else the candidate is rejected and the
     previous page content restored;
   * **diagnostics must strictly decrease** — a candidate whose
     findings did not strictly decrease is rejected;
   * **optional validator** — if the caller supplies
     ``validator(candidate_path)``, returning an object whose
     ``.passed`` attribute is false, the candidate is rejected.

   The loop runs until the page is clean or the :class:`RepairBudget`
   is exhausted (status ``budget-exhausted``).  It can never loop
   unbounded.

Safety invariants
-----------------
* The only file ever written is ``page_path`` itself — never anything
  under ``pkg_path``.
* No shell, no process spawning, no network other than the provided
  ``client`` (the LLM path is strictly opt-in: ``client=None`` ⇒ fully
  deterministic).

Duck-typed LLM client interface
-------------------------------
The integrator wires in :class:`repoquill.llm.LLMClient`; any object
with this method works (tests use a fake):

.. code-block:: python

    class Client:
        def chat(self, messages, max_tokens=None,
                 temperature=None, retries=3) -> str: ...

``messages`` is an OpenAI-style ``list[dict]`` of ``{"role",
"content"}`` items; the return value is the model's text response.
This matches :meth:`repoquill.llm.LLMClient.chat`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from repoquill.surgical_verify import (
    build_class_index,
    fix_missing_required,
    fix_property_calls,
)
from repoquill.verify import (
    SymbolIndex,
    build_index,
    check_page,
    extract_backtick_symbols,
    extract_imports,
    extract_method_calls,
    fix_type_claims,
)

from .budget import RepairBudget

# ---------------------------------------------------------------------------
# Statuses
# ---------------------------------------------------------------------------

STATUS_FIXED = "fixed"
STATUS_BUDGET_EXHAUSTED = "budget-exhausted"
STATUS_NO_EVIDENCE = "no-evidence"
STATUS_ERROR = "error"
STATUS_CLEAN = "clean"

_MIN_CANDIDATE_CHARS = 50


@dataclass
class RepairResult:
    """Outcome of one page's repair attempt."""

    page_path: str
    fixed: bool
    attempts: int
    llm_calls: int
    diagnostics_before: list
    diagnostics_after: list
    status: str
    notes: str = ""

    def as_dict(self) -> dict:
        return {
            "page_path": self.page_path,
            "fixed": self.fixed,
            "attempts": self.attempts,
            "llm_calls": self.llm_calls,
            "diagnostics_before": list(self.diagnostics_before),
            "diagnostics_after": list(self.diagnostics_after),
            "status": self.status,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def _strip_code_fences(text: str) -> str:
    """Remove a wrapping markdown code fence from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def _infer_pkg_name(text: str, idx: SymbolIndex) -> str:
    """Best-effort package top-level name from the page's imports."""
    tops = set()
    for imp in extract_imports(text):
        top = imp.split(".")[0]
        if top in idx.modules:
            tops.add(top)
    if len(tops) == 1:
        return tops.pop()
    if idx.modules:
        return sorted(idx.modules)[0]
    return ""


def diagnose_page(page_path: str, idx) -> list:
    """Deterministic diagnostics for one page.

    Uses :func:`repoquill.verify.check_page` (imports, backtick
    symbols, method calls) so every repair is evidence-backed.  Returns
    the list of finding dicts (empty list ⇒ clean).
    """
    text = Path(page_path).read_text(encoding="utf-8")
    pkg_name = getattr(idx, "pkg_name", "") or _infer_pkg_name(text, idx)
    return check_page(text, idx, pkg_name)


def _diagnose_text(text: str, idx) -> list:
    pkg_name = getattr(idx, "pkg_name", "") or _infer_pkg_name(text, idx)
    return check_page(text, idx, pkg_name)


def _finding_key(f: dict):
    return (f.get("symbol"), f.get("kind"))


# ---------------------------------------------------------------------------
# Evidence excerpt
# ---------------------------------------------------------------------------

def _evidence_excerpt(page_text: str, idx: SymbolIndex, classes: dict) -> str:
    """Signatures of the symbols the page actually references."""
    referenced = set(extract_imports(page_text))
    referenced |= set(extract_backtick_symbols(page_text))
    for obj, meth in extract_method_calls(page_text):
        referenced.add(obj)
        referenced.add(meth)

    lines = []
    for cls in sorted(idx.classes):
        if cls not in referenced:
            continue
        info = classes.get(cls, {})
        params = ", ".join(sorted(info.get("init_params", {})))
        lines.append(f"class {cls}({params})" if params else f"class {cls}")
        for m in sorted(idx.class_methods.get(cls, ())):
            lines.append(f"    def {m}(self)")
        for p in sorted(info.get("properties", ())):
            lines.append(f"    @property {p}")
    for fn in sorted(idx.functions & referenced):
        lines.append(f"def {fn}()")
    for c in sorted(idx.constants & referenced):
        lines.append(f"{c}  # constant")

    if not lines:
        for cls in sorted(idx.classes):
            lines.append(f"class {cls}")
    return "\n".join(lines) if lines else "(no API symbols found)"


def _build_prompt(page_text: str, findings: list,
                  idx: SymbolIndex, classes: dict) -> str:
    findings_text = "\n".join(
        f"- {f['symbol']} ({f['kind']}, severity: {f['severity']})"
        for f in findings
    )
    evidence = _evidence_excerpt(page_text, idx, classes)
    return f"""You are fixing a documentation page that was flagged by an automated checker.

The following symbols in this page do NOT exist in the source code:
{findings_text}

REAL API SURFACE (the only symbols that exist):
{evidence}

PAGE TO FIX:
<page>
{page_text}
</page>

INSTRUCTIONS:
- Remove or correct every flagged symbol. If a code example uses a flagged symbol, rewrite the example using only symbols from the REAL API SURFACE, or remove the example if no real equivalent exists.
- Do not invent any symbol, module, method, or argument that is not in the REAL API SURFACE.
- Do not change anything else. Preserve structure, tone, and all accurate content.
- Return ONLY the complete fixed markdown page, no preamble."""


# ---------------------------------------------------------------------------
# Repair
# ---------------------------------------------------------------------------

def _apply_deterministic_fixes(text: str, pkg_path: str) -> str:
    """Run the known-safe deterministic fix passes over *text*."""
    classes = build_class_index(pkg_path)
    text, _ = fix_property_calls(text, classes)
    text, _ = fix_missing_required(text, classes)
    text = fix_type_claims(text, pkg_path)
    return text


def _write_page(page_path: str, text: str) -> None:
    """Write *text* to *page_path* — the ONLY file this module writes."""
    with open(page_path, "w", encoding="utf-8") as fh:
        fh.write(text)


def repair_page(page_path: str, pkg_path: str, client=None,
                budget=None, validator=None) -> RepairResult:
    """Repair one guide page.  Docs-only: never writes under *pkg_path*.

    Args:
        page_path: The generated ``.md`` page to repair (the only file
            ever written).
        pkg_path: Package source root, read-only (symbol index + AST).
        client: Optional LLM client (duck-typed, see module docstring).
            ``None`` ⇒ fully deterministic — no LLM, no network.
        budget: Optional :class:`RepairBudget`; defaults to one.
        validator: Optional ``callable(candidate_path) -> GateResult``
            whose ``.passed`` attribute must be true for a candidate to
            be kept.

    Returns:
        A :class:`RepairResult` (see ``status`` values: ``fixed``,
        ``budget-exhausted``, ``no-evidence``, ``error``, ``clean``).
    """
    if budget is None:
        budget = RepairBudget()

    try:
        if not os.path.isfile(page_path):
            return RepairResult(page_path, False, 0, 0, [], [], STATUS_ERROR,
                                "page file not found")

        original = Path(page_path).read_text(encoding="utf-8")
        try:
            return _repair_page_inner(page_path, pkg_path, original,
                                      client, budget, validator)
        except Exception as e:  # noqa: BLE001 — restore, report, never raise
            try:
                _write_page(page_path, original)
            except OSError:
                pass
            return RepairResult(page_path, False, 0, 0, [], [], STATUS_ERROR,
                                f"repair failed, original restored: {e}")
    except Exception as e:  # noqa: BLE001 — truly unexpected
        return RepairResult(page_path, False, 0, 0, [], [], STATUS_ERROR,
                            f"unexpected error: {e}")


def _repair_page_inner(page_path: str, pkg_path: str, original: str,
                       client, budget: RepairBudget, validator) -> RepairResult:
    idx = build_index(pkg_path)
    idx.pkg_name = os.path.basename(os.path.normpath(pkg_path))

    before = _diagnose_text(original, idx)

    if not budget.fits(original):
        return RepairResult(
            page_path, False, 0, 0, before, before, STATUS_ERROR,
            f"page exceeds max_chars_per_page ({budget.max_chars_per_page}); "
            "skipped",
        )

    # --- 1. Deterministic fixes (no LLM, always tried) ----------------
    fixed_text = _apply_deterministic_fixes(original, pkg_path)
    changed = fixed_text != original
    if changed:
        _write_page(page_path, fixed_text)

    current = _diagnose_text(
        Path(page_path).read_text(encoding="utf-8"), idx)

    if not changed and not before:
        return RepairResult(page_path, False, 0, 0, before, current,
                            STATUS_CLEAN, "no issues found")
    if not current:
        notes = ("deterministic fixes resolved all findings" if before
                 else "deterministic fixes applied; page clean")
        return RepairResult(page_path, True, 0, 0, before, current,
                            STATUS_FIXED, notes)

    # --- Diagnostics remain -------------------------------------------
    if client is None or not budget.can_start_iteration():
        if client is None:
            return RepairResult(
                page_path, False, 0, 0, before, current, STATUS_NO_EVIDENCE,
                "findings remain and no LLM client provided; deterministic "
                "fixes insufficient (page left as-is)",
            )
        return RepairResult(page_path, False, 0, 0, before, current,
                            STATUS_BUDGET_EXHAUSTED,
                            "budget exhausted before any LLM iteration")

    # --- 2. LLM repair loop (bounded) ----------------------------------
    classes = build_class_index(pkg_path)
    llm_calls = 0
    attempts = 0
    notes_parts = []
    llm_error = None

    while current:
        if not budget.can_start_iteration():
            break
        budget.consume_iteration()
        attempts += 1
        if not budget.consume_llm_call():
            break

        try:
            raw = client.chat(
                [{"role": "user",
                  "content": _build_prompt(
                      Path(page_path).read_text(encoding="utf-8"),
                      current, idx, classes)}],
                max_tokens=8192,
                temperature=0.1,
            )
        except Exception as e:  # noqa: BLE001
            llm_error = e
            notes_parts.append(f"llm error: {e}")
            break
        llm_calls += 1

        candidate = _strip_code_fences(raw or "")
        if len(candidate) < _MIN_CANDIDATE_CHARS:
            notes_parts.append("candidate too short; rejected")
            continue
        if not budget.fits(candidate):
            notes_parts.append(
                "candidate exceeds max_chars_per_page; rejected")
            continue

        previous = Path(page_path).read_text(encoding="utf-8")
        _write_page(page_path, candidate)
        cand_findings = _diagnose_text(candidate, idx)

        # (a) evidence guard: no NEW invented symbols allowed
        current_keys = {_finding_key(f) for f in current}
        invented = [f for f in cand_findings
                    if _finding_key(f) not in current_keys]
        # (c) diagnostics must strictly decrease
        decreased = len(cand_findings) < len(current)

        accepted = False
        if invented:
            notes_parts.append(
                "rejected: candidate invents symbols: "
                + ", ".join(sorted({f['symbol'] for f in invented})))
        elif not decreased:
            notes_parts.append("rejected: diagnostics did not decrease")
        elif validator is not None:
            gate = validator(page_path)
            if gate is not None and not getattr(gate, "passed", True):
                notes_parts.append("rejected: validator gate failed")
            else:
                accepted = True
        else:
            accepted = True

        if accepted:
            current = cand_findings
        else:
            _write_page(page_path, previous)  # never keep a worse page

    # --- Final state ----------------------------------------------------
    final = _diagnose_text(Path(page_path).read_text(encoding="utf-8"), idx)
    notes = "; ".join(notes_parts)

    if not final:
        return RepairResult(page_path, True, attempts, llm_calls, before,
                            final, STATUS_FIXED,
                            notes or "all findings resolved")
    if llm_error is not None:
        return RepairResult(page_path, False, attempts, llm_calls, before,
                            final, STATUS_ERROR,
                            notes or f"llm error: {llm_error}")
    return RepairResult(page_path, False, attempts, llm_calls, before,
                        final, STATUS_BUDGET_EXHAUSTED,
                        notes or "budget exhausted with findings remaining")


def repair_pages(guides_dir: str, pkg_path: str, slugs=None, client=None,
                 budget_per_page=None) -> list:
    """Repair many pages with per-page isolation.

    One page's error never stops the batch; it is reported as an
    ``error`` :class:`RepairResult`.  *budget_per_page* (a
    :class:`RepairBudget`) is copied fresh for every page.
    """
    files = sorted(Path(guides_dir).glob("*.md"))
    if slugs is not None:
        allowed = {s if s.endswith(".md") else f"{s}.md" for s in slugs}
        files = [f for f in files if f.name in allowed]

    results = []
    for f in files:
        try:
            page_budget = replace(budget_per_page) if budget_per_page is not None else None
            results.append(repair_page(str(f), pkg_path, client=client,
                                       budget=page_budget))
        except Exception as e:  # noqa: BLE001 — isolate per page
            results.append(RepairResult(str(f), False, 0, 0, [], [],
                                        STATUS_ERROR,
                                        f"batch isolation: {e}"))
    return results
