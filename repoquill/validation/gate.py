"""Deterministic, fail-closed quality gate for generated doc pages.

The gate composes the independent static checks (imports, symbols) and,
only when explicitly requested, executable example checks. It never
calls an LLM. A gate result is ``passed`` only when no check produced a
finding; a check that itself raises is recorded as a failed
``internal-error`` finding (fail closed) — checks are never skipped
silently.

Public API (re-exported from ``repoquill.validation``):

* :func:`run_gate` — run all checks over a guides directory;
* :class:`GateResult` — ``.passed``, ``.findings``, ``.checks_run``,
  ``.checks_skipped``, ``.summary()``, ``.as_dict()``;
* :class:`GateFinding` — ``page``, ``check``, ``detail``, ``line``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

from repoquill.verify import build_index
from repoquill.validation.examples import run_page_examples
from repoquill.validation.imports import check_page_imports
from repoquill.validation.symbols import check_page_symbols

#: Checks that must run (and pass) for the gate to pass.
REQUIRED_CHECKS = ("import", "symbol")
#: Opt-in check, only run when ``run_gate(..., run_examples=True)``.
EXAMPLES_CHECK = "example"
INTERNAL_ERROR_CHECK = "internal-error"


@dataclass
class GateFinding:
    """One structured quality finding.

    Attributes:
        page: Page slug (guide filename without ``.md``; ``"*"`` for
            gate-level failures that do not belong to a single page).
        check: Check name — ``"import"``, ``"symbol"``, ``"example"`` or
            ``"internal-error"``.
        detail: Human-readable explanation of the problem.
        line: 1-based line in the page, when known.
    """

    page: str
    check: str
    detail: str
    line: Optional[int] = None

    def to_dict(self) -> dict:
        return {"page": self.page, "check": self.check,
                "detail": self.detail, "line": self.line}


class GateResult:
    """Aggregate outcome of a quality-gate run. JSON-serializable."""

    def __init__(self,
                 findings: Optional[List[GateFinding]] = None,
                 checks_run: Optional[List[str]] = None,
                 checks_skipped: Optional[List[str]] = None):
        self.findings: List[GateFinding] = list(findings or [])
        self.checks_run: List[str] = list(checks_run or [])
        self.checks_skipped: List[str] = list(checks_skipped or [])

    @property
    def passed(self) -> bool:
        """True only when no check (including internal errors) found a problem."""
        return not self.findings

    def add(self, finding: GateFinding) -> None:
        self.findings.append(finding)

    def summary(self) -> str:
        verdict = "PASSED" if self.passed else "FAILED"
        pages = sorted({f.page for f in self.findings})
        by_check: dict = {}
        for f in self.findings:
            by_check[f.check] = by_check.get(f.check, 0) + 1
        parts = ", ".join(f"{name}={count}"
                          for name, count in sorted(by_check.items()))
        detail = parts if parts else "no findings"
        return (f"gate {verdict}: {len(self.findings)} findings "
                f"({detail}); checks run: "
                f"{', '.join(self.checks_run) or 'none'}; skipped: "
                f"{', '.join(self.checks_skipped) or 'none'}")

    def as_dict(self) -> dict:
        """Cheap, JSON-safe dict form for run reports."""
        return {
            "passed": self.passed,
            "findings": [f.to_dict() for f in self.findings],
            "checks_run": list(self.checks_run),
            "checks_skipped": list(self.checks_skipped),
            "summary": self.summary(),
        }


def _pages(guides_dir: str) -> List[str]:
    return sorted(f for f in os.listdir(guides_dir) if f.endswith(".md"))


def _local_package_tops(pkg_path: str) -> set:
    """Top-level Python package/dir names in the source repository root.

    The documented package is verified against the symbol index; sibling
    top-level packages of the source repo (e.g. its ``tests`` package) are
    part of the repo but absent from the index. Returning their top-level
    names lets the import check treat them as in-scope (out-of-scope-for-
    verification) instead of flagging them as missing third-party libraries.

    The root is located by walking up from the package to the nearest
    directory containing ``pyproject.toml`` / ``setup.py`` / ``.git``
    (handles ``src/`` layouts). Bounded to 5 levels.
    """
    start = os.path.dirname(os.path.abspath(pkg_path))
    cur = start
    root = start
    for _ in range(5):
        if (os.path.exists(os.path.join(cur, "pyproject.toml"))
                or os.path.exists(os.path.join(cur, "setup.py"))
                or os.path.isdir(os.path.join(cur, ".git"))):
            root = cur
            break
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    tops: set = set()
    if os.path.isdir(root):
        for entry in os.listdir(root):
            if entry.startswith("."):
                continue
            d = os.path.join(root, entry)
            if not os.path.isdir(d):
                continue
            try:
                has_py = any(f.endswith(".py") for f in os.listdir(d))
            except OSError:
                has_py = False
            if has_py:
                tops.add(entry)
    return tops


def run_gate(guides_dir: str, pkg_path: str,
             pkg_name: Optional[str] = None,
             run_examples: bool = False,
             example_timeout: int = 15) -> GateResult:
    """Run the quality gate over every ``.md`` page in *guides_dir*.

    Args:
        guides_dir: Directory of generated guide pages.
        pkg_path: Path to the target package (directory containing
            ``__init__.py`` or the package tree).
        pkg_name: Package top-level name; derived from *pkg_path* when
            omitted. Currently advisory (checks derive it from the index).
        run_examples: Opt-in: also execute Python examples in
            subprocesses (default off).
        example_timeout: Wall-clock seconds per example block.

    Returns:
        A :class:`GateResult`. ``passed`` is False if any required
        check produced a finding or any check hit an internal error.
    """
    result = GateResult()
    if not run_examples:
        result.checks_skipped.append(EXAMPLES_CHECK)

    if not os.path.isdir(pkg_path):
        result.checks_run.append("import")
        result.checks_run.append("symbol")
        result.add(GateFinding(
            page="*", check=INTERNAL_ERROR_CHECK,
            detail=f"package path does not exist: {pkg_path}"))
        return result

    try:
        idx = build_index(pkg_path)
    except Exception as e:  # noqa: BLE001 - fail closed
        result.checks_run.append("import")
        result.checks_run.append("symbol")
        result.add(GateFinding(
            page="*", check=INTERNAL_ERROR_CHECK,
            detail=f"could not build symbol index: {e}"))
        return result

    try:
        pages = _pages(guides_dir)
    except Exception as e:  # noqa: BLE001 - fail closed
        result.add(GateFinding(
            page="*", check=INTERNAL_ERROR_CHECK,
            detail=f"could not list guides directory "
                   f"'{guides_dir}': {e}"))
        return result

    local_tops = _local_package_tops(pkg_path)
    check_names = ["import", "symbol"] + (
        [EXAMPLES_CHECK] if run_examples else [])
    for name in check_names:
        try:
            _run_check(name, pages, guides_dir, idx, pkg_path,
                       result, example_timeout, local_tops)
        except Exception as e:  # noqa: BLE001 - fail closed, never skip
            result.checks_run.append(name)
            result.add(GateFinding(
                page="*", check=INTERNAL_ERROR_CHECK,
                detail=f"check '{name}' raised: "
                       f"{type(e).__name__}: {e}"))
    return result


def _run_check(name: str, pages: List[str], guides_dir: str, idx,
               pkg_path: str, result: GateResult,
               example_timeout: int, local_tops: Optional[set] = None) -> None:
    for fname in pages:
        page_path = os.path.join(guides_dir, fname)
        if name == "import":
            findings = check_page_imports(page_path, idx, local_tops=local_tops)
        elif name == "symbol":
            findings = check_page_symbols(page_path, idx)
        else:
            raw = run_page_examples(page_path, pkg_path,
                                    timeout=example_timeout)
            findings = [{"page": r["page"], "check": r["check"],
                         "line": r.get("line"),
                         "detail": f"example block {r['block']}: "
                                   f"{r['status']}"
                                   + (f" — {r['detail']}" if r["detail"] else "")}
                        for r in raw if r["status"] != "passed"]
        for f in findings:
            result.add(GateFinding(page=f["page"], check=f["check"],
                                   detail=f["detail"],
                                   line=f.get("line")))
    result.checks_run.append(name)
