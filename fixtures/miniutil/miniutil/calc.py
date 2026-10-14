"""Basic numeric utilities: a running counter and sliding averages."""


class Counter:
    """A running numeric counter.

    Starts from an optional iterable of values (or zero) and accumulates
    further values with :meth:`add`.

    Example:
        >>> c = Counter([1, 2])
        >>> c.add(3)
        >>> c.total()
        6
    """

    def __init__(self, values=None):
        """Initialize the counter, optionally summing ``values`` first.

        ``values`` is any iterable of numbers, or ``None`` for a
        counter starting at zero.
        """
        self._total = 0
        if values is not None:
            for value in values:
                self._total += value

    def add(self, value) -> None:
        """Add ``value`` to the running total."""
        self._total += value

    def total(self) -> float:
        """Return the current running total."""
        return self._total


def moving_average(values, window) -> list:
    """Compute the sliding (moving) average of ``values`` over ``window``.

    Returns a list of length ``max(len(values) - window + 1, 0)`` where
    each entry is the mean of one consecutive ``window``-sized slice.

    Edge cases:
        - If ``window`` is larger than ``values``, the single overall
          mean of all values is returned (one element).
        - If ``values`` is empty, an empty list is returned.
        - ``window`` must be a positive integer.

    Example:
        >>> moving_average([1, 2, 3, 4], 2)
        [1.5, 2.5, 3.5]
        >>> moving_average([1, 2, 3], 5)
        [2.0]
    """
    if window < 1:
        raise ValueError("window must be a positive integer")
    if not values:
        return []
    if window > len(values):
        return [sum(values) / len(values)]
    return [
        sum(values[i:i + window]) / window
        for i in range(len(values) - window + 1)
    ]
