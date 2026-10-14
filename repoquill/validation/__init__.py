"""Deterministic, fail-closed quality gate for generated docs.

No LLM: static import/symbol checks against the AST-derived symbol
index, plus opt-in executable example checks run in isolated
subprocesses. Internal check errors fail the gate (``internal-error``
finding) rather than being skipped.
"""

from __future__ import annotations

from repoquill.validation.examples import run_page_examples
from repoquill.validation.gate import (
    EXAMPLES_CHECK,
    INTERNAL_ERROR_CHECK,
    REQUIRED_CHECKS,
    GateFinding,
    GateResult,
    run_gate,
)
from repoquill.validation.imports import check_page_imports
from repoquill.validation.symbols import check_page_symbols

__all__ = [
    "EXAMPLES_CHECK",
    "INTERNAL_ERROR_CHECK",
    "REQUIRED_CHECKS",
    "GateFinding",
    "GateResult",
    "check_page_imports",
    "check_page_symbols",
    "run_gate",
    "run_page_examples",
]
