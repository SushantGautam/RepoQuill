"""Structured symbol-existence findings for generated doc pages.

Reuses :func:`repoquill.verify.check_page` as the detection engine
(hallucinated imports, backtick symbols, method calls against the
AST-derived :class:`repoquill.verify.SymbolIndex`) and converts its
results into structured findings.

Only high- and medium-severity findings are emitted; low-severity
method-call findings are skipped by design because they are routinely
user-defined variables in examples (the same convention
``repoquill.verify.verify_pages`` applies for its fix pass).
"""

from __future__ import annotations

import os
from typing import List

from repoquill.verify import check_page

_SEVERITIES = ("high", "medium")


def _line_of(md: str, symbol: str):
    """1-based line of the first occurrence of *symbol* in the page, or None."""
    bare = symbol.rstrip("()")
    for n, line in enumerate(md.splitlines(), start=1):
        if bare in line:
            return n
    return None


def check_page_symbols(page_path: str, idx) -> List[dict]:
    """Check a page for references to nonexistent API symbols.

    Returns a list of findings shaped
    ``{"page": slug, "check": "symbol", "line": n_or_None, "detail": str}``.
    """
    slug = os.path.basename(page_path)
    if slug.endswith(".md"):
        slug = slug[:-3]
    with open(page_path, "r", encoding="utf-8") as fh:
        md = fh.read()

    # pkg_name is not recoverable from the index; verify.check_page only
    # uses it to recognise the project's top level, and the index already
    # contains the package name in ``modules``.
    raw = check_page(md, idx, pkg_name="")
    findings: List[dict] = []
    for f in raw:
        if f["severity"] not in _SEVERITIES:
            continue
        findings.append({
            "page": slug,
            "check": "symbol",
            "line": _line_of(md, f["symbol"]),
            "detail": (f"references nonexistent {f['kind']} "
                       f"'{f['symbol']}' (severity: {f['severity']})"),
        })
    return findings
