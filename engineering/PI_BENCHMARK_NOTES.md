# Pi Benchmark Notes — pi vs python-agent vs legacy

- **Date:** 2026-10-14
- **Endpoint host:** `simulachat.sushant.pp.ua` (OpenAI-compatible proxy; no keys in this doc)
- **Model:** `default` (resolved by Pi as `simulachat-sushant-pp-ua/default`)
- **Pi version:** 1.2.0
- **Repo state:** `dev` @ `fb54a7b`, `fixtures/miniutil`

## Method

One controlled single-page task across the three narrative engines:

- **Task (identical for all engines):** generate the `textkit-guide` page
  (source `miniutil/textkit.py`) into a fresh temp `out_guides` dir,
  forced regeneration, coverage checklist = symbols in `textkit.py`
  (`TextStats`, `slugify`).
- **Verification (identical for all engines):** the same independent
  verifier (`agents/verify.verify_page_file`) run on the produced page with
  `run_examples=False` and coverage threshold `0.6`.
- **Model calls:** counted by the runner's LLMClient wrapper
  (`chat` + `chat_with_tools`) for python-agent/legacy, and by Pi RPC
  `turn_end` events (one per model completion) for pi.
- **Wall time:** monotonic wrap of the engine generation call.
- Runner: session-workspace `pi_bench_engine.py` (one engine per
  process; per-engine raw JSONs + aggregated JSON in the same folder).

## Results

| engine         | wall time | model calls | coverage | findings | accepted |
| -------------- | --------- | ----------- | -------- | -------- | -------- |
| pi             | 12.29 s   | 4           | 1.00 (2/2) | 0 import, 0 symbol | yes |
| python-agent   | 15.81 s   | 4           | 1.00 (2/2) | 0 import, 0 symbol | yes |
| legacy         | 21.80 s   | 1           | 1.00 (2/2) | 0 import, 0 symbol | yes |

All three passed the final independent verification
(`examples 0/0 passed`; examples disabled by design in this benchmark).

## Page heads (trimmed)

**pi** (2,343 chars):

    # TextKit Guide
    `miniutil.textkit` is MiniUtil's text analysis module. It provides two
    public symbols:
    - **`TextStats`** — word-level statistics for a piece of text
      (`word_count()`, `longest_word()`).
    - **`slugify()`** — converts arbitrary text into a URL-safe slug.
    Both are also re-exported from the top-level package, so you can import
    them either way:

**python-agent** (3,784 chars):

    ## TextKit Guide
    The `miniutil.textkit` module (source: `miniutil/textkit.py`) provides
    two small, dependency-free text utilities:
    - **`TextStats`** — word-level statistics for a piece of text
      (`word_count()`, `longest_word()`).
    - **`slugify(text)`** — turn arbitrary text into a URL-safe slug.
    Both symbols are also re-exported from the package root, so you can
    import them either way:

**legacy** (4,608 chars):

    ## TextKit Guide
    The `miniutil.textkit` module provides lightweight, dependency-free
    utilities for text analysis and URL slug generation. ... The module
    exposes one class, `TextStats`, and one standalone function, `slugify`.
    ### Overview
    *   **`TextStats`**: A class that encapsulates a piece of text and
        provides methods to analyze its word structure.
    *   **`slugify`**: A function that converts arbitrary strings into
        lowercase, hyphen-separated slugs suitable for URLs.

## Quality notes per engine

- **pi** — a real Pi 1.2.0 RPC process with the constrained tool bridge
  (trace: `read_file` ×2, `inspect_tests`, `write_doc`). Produced the most
  compact page; every claim is grounded in source files it actually read
  (`textkit.py`, `__init__.py`). Only engine that reports token usage
  (1,291 in / 638 out).
- **python-agent** — the homegrown tool-calling loop (3 steps in 4
  tool-calling requests). Clean, structured page with correct import
  options; content verified accurate against source.
- **legacy** — single one-shot prompt, no repository tool access. Longest
  and most verbose page; spot-checks accurate (its punctuation-attached-to-
  words claim matches the source docstring), but there is no evidence it
  read the repo at all.

## Caveats

- **One-shot, single page:** one run per engine on one page with a
  2-symbol checklist. Not statistically rigorous; no error bars, and the
  ranking (pi fastest) may not hold on larger/multi-symbol pages.
- **Pi multi-page parallelism not measured:** the task was a single page
  (the 4-worker scheduler ran with one task), so wall time here reflects a
  single Pi process, not pi's parallel multi-page throughput.
- **Model-call counts are not directly comparable:** python-agent/legacy
  count Python-side LLMClient requests; pi counts RPC `turn_end` events.
  The proxy does not return usage for the non-pi engines.
- **Failed first capture:** an earlier driver run (19:37–19:46) produced
  401/`stopReason=error` failures for all three engines — the runner's
  embedded key had been redacted to a placeholder. Those merged records
  (`pi_bench_raw.json`) are invalid; all numbers above are from clean
  re-runs after confirming the endpoint healthy via `/models`.
- **Budget:** this finishing session spent 9 live generations
  (pi 4 + python-agent 4 + legacy 1) against the ≤8 budget (+1, driven by
  pi's 4-turn tool loop).

## Artifacts (session workspace)

`pi_bench_raw_pi.json`, `pi_bench_raw_python_agent.json`,
`pi_bench_raw_legacy.json`, `pi_bench_aggregated.json`,
`pi_bench_engine.py`, `pi_bench_aggregate.py`.
