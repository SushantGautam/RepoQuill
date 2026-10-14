"""MiniUtil: a tiny text + math toolkit.

Public API:
    - :class:`TextStats` — word-level statistics for text.
    - :func:`slugify` — URL-safe slug generation.
    - :class:`Counter` — running numeric counter.
    - :func:`moving_average` — sliding-window average.
"""

from .calc import Counter, moving_average
from .textkit import TextStats, slugify

__all__ = ["TextStats", "slugify", "Counter", "moving_average"]
