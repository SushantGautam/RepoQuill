# MiniUtil

A tiny text + math toolkit. MiniUtil provides small, dependency-free
utilities for analyzing text and doing basic numeric computations.

## Modules

- **`miniutil.textkit`** — text analysis:
  - `TextStats` — word-level statistics for a piece of text
    (`word_count()`, `longest_word()`).
  - `slugify()` — turn arbitrary text into a URL-safe slug.

- **`miniutil.calc`** — basic math:
  - `Counter` — a running numeric counter (`add()`, `total()`).
  - `moving_average()` — sliding-window average over a sequence of
    numbers, with graceful handling of windows larger than the data.

## Quick start

```python
from miniutil import TextStats, Counter, slugify, moving_average

stats = TextStats("The quick brown fox")
stats.word_count()        # 4
stats.longest_word()      # "quick"

slugify("Hello, World!")  # "hello-world"

c = Counter([1, 2])
c.add(3)
c.total()                 # 6

moving_average([1, 2, 3, 4], 2)  # [1.5, 2.5, 3.5]
```

## Tests

```
pytest fixtures/miniutil/tests
```
