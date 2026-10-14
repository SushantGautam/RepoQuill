"""Opt-in, bounded, docs-only repair runtime for RepoQuill (P1-8).

Re-exports the public repair API.  The LLM path is strictly opt-in:
passing no client (``client=None``) keeps every operation fully
deterministic, offline, and shell-free.
"""

from __future__ import annotations

from .budget import RepairBudget
from .repair import (
    RepairResult,
    diagnose_page,
    repair_page,
    repair_pages,
)

__all__ = [
    "RepairBudget",
    "RepairResult",
    "diagnose_page",
    "repair_page",
    "repair_pages",
]
