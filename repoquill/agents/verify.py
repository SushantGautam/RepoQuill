"""Independent verification of agent-authored documentation pages.

This module is the authoritative pass/fail gate for publication. It is
deliberately decoupled from the authoring agent: it takes an already
written page and checks it against ground truth using the deterministic
checkers in :mod:`repoquill.verify` and :mod:`repoquill.validation`.

Checks performed (all independent of any LLM):

* **Semantic coverage** — does the page mention every symbol in the
  page task's coverage checklist? (word-boundary match, not counting
  symbols the checker rejects)
* **Executable examples** — every python code block is executed in an
  isolated subprocess (handled by :func:`run_page_examples`).
* **Imports** — every import statement resolves against the package
  symbol index.
* **Symbols** — the page does not reference symbols that do not exist.

A page only passes when all of the above are clean (see
:meth:`VerificationResult.compute_passed`).
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from typing import Dict, List

from repoquill.agents.contracts import (
    CoverageReport,
    PageTask,
    ToolContext,
    VerificationResult,
)
from repoquill.validation.examples import run_page_examples
from repoquill.validation.imports import check_page_imports
from repoquill.validation.symbols import check_page_symbols
from repoquill.verify import build_index


def _coverage_match(sym: str, content: str) -> bool:
    """True if *sym* appears in *content* as a standalone word."""
    pattern = r"(?<![A-Za-z0-9_])" + re.escape(sym) + r"(?![A-Za-z0-9_])"
    return re.search(pattern, content) is not None


def _compute_coverage(
    expected: List[str], content: str,
) -> CoverageReport:
    """Build a :class:`CoverageReport` from word-boundary matches."""
    covered = [s for s in expected if _coverage_match(s, content)]
    missing = [s for s in expected if s not in covered]
    ratio = (len(covered) / len(expected)) if expected else 1.0
    return CoverageReport(expected=list(expected), covered=covered,
                          missing=missing, ratio=ratio)


def _build_summary(
    coverage: CoverageReport,
    coverage_ok: bool,
    examples_ok: bool,
    example_findings: List[Dict],
    import_findings: List[Dict],
    symbol_findings: List[Dict],
) -> str:
    n_examples = len(example_findings)
    n_passed = sum(1 for f in example_findings if f.get("status") == "passed")
    parts = [
        "coverage {0}/{1} ({2:.2f})".format(len(coverage.covered),
                                            len(coverage.expected),
                                            coverage.ratio),
        "examples {0}/{1} passed".format(n_passed, n_examples),
        "{0} import finding{1}".format(
            len(import_findings), "" if len(import_findings) == 1 else "s"),
        "{0} symbol finding{1}".format(
            len(symbol_findings), "" if len(symbol_findings) == 1 else "s"),
    ]
    if coverage_ok and examples_ok and not import_findings and not symbol_findings:
        return "; ".join(parts)
    missing = coverage.missing
    if missing:
        parts.append("missing: " + ", ".join(missing))
    if import_findings:
        parts.append("imports: " + ", ".join(
            f.get("detail", "") for f in import_findings[:5]))
    if symbol_findings:
        parts.append("symbols: " + ", ".join(
            f.get("detail", "") for f in symbol_findings[:5]))
    return "; ".join(parts)


def verify_page(
    slug: str,
    content: str,
    task: "PageTask",
    ctx: "ToolContext",
    run_examples: bool = True,
    coverage_threshold: float = 0.6,
    example_timeout: float = 30.0,
) -> "VerificationResult":
    """Independently verify one written page against ground truth.

    Never raises for a bad page: any unexpected checker error is turned
    into a failed :class:`VerificationResult` with the error recorded in
    ``summary``.

    Args:
        slug: The page slug (used in the result).
        content: The full markdown content of the page.
        task: The :class:`PageTask` for this page (provides the
            ``coverage_checklist``).
        ctx: The :class:`ToolContext` (provides ``pkg_path``).
        run_examples: Execute python code blocks (default True).
        coverage_threshold: Minimum coverage ratio to pass.
        example_timeout: Wall-clock seconds per example block.

    Returns:
        A :class:`VerificationResult`.
    """
    workdir = tempfile.mkdtemp(prefix="repoquill-verify-")
    tmp_page = os.path.join(workdir, f"{slug}.md")
    try:
        with open(tmp_page, "w", encoding="utf-8") as fh:
            fh.write(content)

        try:
            idx = build_index(ctx.pkg_path)
        except Exception as e:  # noqa: BLE001 - report, don't raise
            return VerificationResult(
                slug=slug, passed=False,
                coverage_ok=False, examples_ok=False,
                summary="failed to build symbol index: {0}".format(e),
            )

        symbol_findings = check_page_symbols(tmp_page, idx)
        import_findings = check_page_imports(tmp_page, idx)

        example_findings: List[Dict] = []
        if run_examples:
            example_findings = run_page_examples(
                tmp_page, ctx.pkg_path, timeout=int(example_timeout),
                workdir=workdir,
            )
        examples_ok = all(f.get("status") == "passed" for f in example_findings)

        expected = list(task.coverage_checklist or [])
        coverage = _compute_coverage(expected, content)
        coverage_ok = coverage.ratio >= coverage_threshold

        passed = VerificationResult.compute_passed(
            coverage_ok, examples_ok, import_findings, symbol_findings)
        summary = _build_summary(coverage, coverage_ok, examples_ok,
                                 example_findings, import_findings,
                                 symbol_findings)
        return VerificationResult(
            slug=slug, passed=passed, coverage=coverage,
            example_findings=example_findings,
            import_findings=import_findings,
            symbol_findings=symbol_findings,
            coverage_ok=coverage_ok, examples_ok=examples_ok,
            summary=summary,
        )
    except Exception as e:  # noqa: BLE001 - report, don't raise
        return VerificationResult(
            slug=slug, passed=False,
            coverage_ok=False, examples_ok=False,
            summary="verification error: {0}".format(e),
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def verify_page_file(
    slug: str,
    page_path: str,
    task: "PageTask",
    ctx: "ToolContext",
    run_examples: bool = True,
    coverage_threshold: float = 0.6,
    example_timeout: float = 30.0,
) -> "VerificationResult":
    """Convenience wrapper: verify the page stored at *page_path*."""
    with open(page_path, "r", encoding="utf-8") as fh:
        content = fh.read()
    return verify_page(
        slug, content, task, ctx,
        run_examples=run_examples,
        coverage_threshold=coverage_threshold,
        example_timeout=example_timeout,
    )
