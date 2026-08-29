# Research

All state for the RepoQuill documentation-generation research mission.
The mission itself is defined in `.claude/CLAUDE.md` (repo root).

## File map

| File | Purpose |
|---|---|
| `CURRENT_STATE.md` | Full experiment log + current status |
| `BEST_KNOWN.md` | Best-known configuration, prompts, scores, known weaknesses |
| `NEXT_EXPERIMENT.md` | The designed-but-not-started next experiment |
| `registry.jsonl` | One JSON line per experiment (id, date, hypothesis, decision, commit) |
| `eval/` | Deterministic evaluation checkers (hallucination, coverage, examples, C-hallucination, etc.) |
| `local/` | **Untracked / gitignored.** Local-only state, currently the SimpleAudit source clone |

## Resuming

1. Read `CURRENT_STATE.md` (top section) and `NEXT_EXPERIMENT.md`.
2. Read the "Best-known state" section of `BEST_KNOWN.md` for the current
   configuration and scores.
3. `research/local/simpleaudit-src/` is a git clone of
   `https://github.com/SushantGautam/simpleaudit` (the testbed source repo).
   Griffe derives GitHub source permalinks from its git metadata, so it must
   be a real clone with the remote intact. Recreate if missing:
   `git clone https://github.com/SushantGautam/simpleaudit research/local/simpleaudit-src`

## Local generation test

Never trigger GitHub Actions for the experiment loop — generate and build
locally:

```bash
SOURCE_ROOT=/Users/sushantgautam/RepoQuill/research/local/simpleaudit-src \
PYTHONPATH=/Users/sushantgautam/RepoQuill \
/Users/sushantgautam/RepoQuill/.venv/bin/python -m repoquill.cli generate \
  --config /Users/sushantgautam/simpleaudit-docs/repoquill.yml --build
```

Notes:

- Use the venv python (`.venv/`), never the system/anaconda python — the venv
  has Griffe >= 2.2.0, which is required for `source_link` permalinks.
- The testbed is `/Users/sushantgautam/simpleaudit-docs/` (generated docs,
  `mkdocs.yml`, `repoquill.yml`). **Never edit it** — it is the testbed, not
  a target for hard-coded behavior.
- The LLM step may fail with "Missing credentials" if `OPENAI_API_KEY` is not
  set; reference pages and the site build still complete.
- Preview the built site:
  `cd /Users/sushantgautam/simpleaudit-docs && /Users/sushantgautam/RepoQuill/.venv/bin/python -m http.server 8000 --directory site_repoquill`
