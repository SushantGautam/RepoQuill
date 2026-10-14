"""Opt-in, bounded, docs-only repair runtime (P1-8) and the agentic
documentation engine (P2) for RepoQuill.

The legacy repair API is exported eagerly (no further dependencies). The
agentic engine modules (tools / author / evidence / verify / scheduler)
are exported **lazily** (PEP 562) so importing ``repoquill.agents`` never
forces the whole engine to load and each module can be developed/tested
independently.
"""

from __future__ import annotations

import importlib

from .budget import RepairBudget
from .repair import (
    RepairResult,
    diagnose_page,
    repair_page,
    repair_pages,
)

__all__ = [
    # Legacy bounded repair.
    "RepairBudget",
    "RepairResult",
    "diagnose_page",
    "repair_page",
    "repair_pages",
    # Agentic engine (lazy).
    "ToolContext",
    "RepoQuillTools",
    "build_tool_context",
    "run_page_agent",
    "run_page_agent_specialized",
    "build_evidence_pack",
    "verify_page",
    "verify_page_file",
    "run_pages",
    "run_agentic_generation",
    "PageOutcome",
]

_LAZY = {
    "ToolContext": ".contracts",
    "RepoQuillTools": ".tools",
    "build_tool_context": ".tools",
    "run_page_agent": ".author",
    "run_page_agent_specialized": ".author",
    "build_evidence_pack": ".evidence",
    "verify_page": ".verify",
    "verify_page_file": ".verify",
    "run_pages": ".scheduler",
    "run_agentic_generation": ".scheduler",
    "PageOutcome": ".scheduler",
}


def __getattr__(name):
    if name in _LAZY:
        module = importlib.import_module(_LAZY[name], __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
