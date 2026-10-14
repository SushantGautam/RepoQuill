"""Bounded budget for docs-only repair workers.

A :class:`RepairBudget` caps how much work a single repair loop may do
(autonomous-plan P1 item 8: opt-in, bounded, docs-only — never
unbounded).  Exceeding any cap stops the loop with status
``budget-exhausted``; the loop can never run past these limits.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RepairBudget:
    """Hard caps for one page's repair loop.

    Attributes:
        max_iterations: Maximum repair iterations (one iteration = one
            diagnose → fix → re-diagnose cycle).
        max_llm_calls: Maximum LLM calls for this page (0 disables the
            LLM path even if a client is provided).
        max_chars_per_page: A page or LLM candidate larger than this
            many characters is never sent to or kept from an LLM.

    Usage accounting is held in ``iterations_used`` / ``llm_calls_used``
    and exposed through the ``*_remaining`` helpers.
    """

    max_iterations: int = 2
    max_llm_calls: int = 2
    max_chars_per_page: int = 200_000

    iterations_used: int = field(default=0, repr=False)
    llm_calls_used: int = field(default=0, repr=False)

    # ------------------------------------------------------------------
    # Accounting helpers
    # ------------------------------------------------------------------

    @property
    def iterations_remaining(self) -> int:
        """Iterations still allowed (never negative)."""
        return max(0, self.max_iterations - self.iterations_used)

    @property
    def llm_calls_remaining(self) -> int:
        """LLM calls still allowed (never negative)."""
        return max(0, self.max_llm_calls - self.llm_calls_used)

    @property
    def exhausted(self) -> bool:
        """True once any cap has been reached."""
        return (
            self.iterations_used >= self.max_iterations
            or self.llm_calls_used >= self.max_llm_calls
        )

    def can_start_iteration(self) -> bool:
        """True if one more iteration (and one LLM call) is possible."""
        return (
            self.iterations_remaining > 0 and self.llm_calls_remaining > 0
        )

    def consume_iteration(self) -> None:
        """Reserve the next iteration (no-op if none remain)."""
        if self.can_start_iteration():
            self.iterations_used += 1

    def consume_llm_call(self) -> bool:
        """Consume one LLM call slot.  Returns False if none remain."""
        if self.llm_calls_used >= self.max_llm_calls:
            return False
        self.llm_calls_used += 1
        return True

    def fits(self, text: str) -> bool:
        """True if *text* is within the per-page character cap."""
        return len(text) <= self.max_chars_per_page
