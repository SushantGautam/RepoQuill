# RepoQuill × Pi — SimpleAudit real-world evaluation

Autonomous **generate → inspect → verify → diagnose → improve → regenerate**
evaluation of the Pi-first RepoQuill documentation engine against a complex,
real Python repository (SimpleAudit). This is the mission that had to prove —
or reveal why — RepoQuill can *autonomously document a complex real-world
project*, not just pass a small fixture.

Isolated, reproducible workspace: `research/local/simpleaudit-pi-eval/`
(gitignored). All generated artifacts, Pi tool traces, model-traffic logs, and
this workspace's run notes are preserved there for inspection.

---

## 1. Environment (no secrets)

| Item | Value |
|---|---|
| **RepoQuill baseline commit** | `7350635` — *Pi engine: fix real-world failure modes found in SimpleAudit baseline* |
| **RepoQuill improvement commits** | `3d133a9` (Pi loop breaker + prompt hardening, P1/P3), `1d5dbaf` (site link integrity + partial build, P2/P5) |
| **SimpleAudit commit** | `19ef6ca64226659c7e12bc5211f10f7074b8c0f4` (2026-10-11), cloned to `research/local/simpleaudit-pi-eval/simpleaudit/` |
| **Pi runtime** | `@earendil-works/pi-coding-agent@1.2.0`, Node v24, `--mode rpc --no-session` (JSONL RPC subprocess) |
| **Model** | `default` on an OpenAI-compatible endpoint = **Qwen3.8-27B** behind the operator's proxy |
| **Endpoint** | `https://simulachat.sushant.pp.ua/api/v1` (the baseline logged traffic via a transparent `127.0.0.1:8931` forwarder; the regeneration calls the endpoint directly — same model) |
| **Auth** | API key supplied via the `REPOQUILL_LIVE_KEY` env var only; **never written to any tracked file** (a 0600 copy in the session workspace seeds the env) |
| **Engine** | `documentation.engine: pi` (real Pi tool calls + real LLM; no mocks, `--no-llm`, `python-agent`, or `legacy` for the primary run) |

### Pi per-page configuration (identical for baseline and regeneration — clean A/B)

| Key | Value | Why |
|---|---|---|
| `llm.agentic.timeout_s` | 900 | Run-1 showed the proxy takes 1.6–2.5 s per completion at 200 k+ char prompts; the old 300 s default timed out 7/8 pages before `write_doc` |
| `llm.agentic.context_window` | 100 000 | Proxy accepts >110 k-token contexts; 131 072 let `scenarios` churn to 179 k tokens (compaction regime); 100 000 avoids the 32 768-era amnesia while bounding per-page context |
| `llm.agentic.compaction_keep_recent_tokens` | 60 000 | Pi's default (20 000) wiped recently-read source: one 923-line file was re-read **307×** across 6 compaction cycles. Keeping 60 000 recent tokens verbatim dropped re-reads to 0 |
| `llm.agentic.max_file_chars` | 40 000 | `fact_check.py` is ~32 k chars; a 16 k cap forced 9-chunk paging |
| `llm.agentic.max_repeat_calls` | 6 | Orbit guard: abort a page at 6 identical tool calls |
| `llm.max_concurrent` | 4 | Parallel independent Pi workers (pages have no shared writes) |
| `include_tests` | true | Agents discover + inspect the package's own tests as evidence |

---

## 2. Generation commands & output locations

Config: `research/local/simpleaudit-pi-eval/simpleaudit/repoquill-regen.yml`
(engine `pi`, 8 narrative pages planned by the LLM planner, 76 deterministic
reference modules; SimpleAudit-specific behaviour is **not** hardcoded into
RepoQuill — the page plan is produced by RepoQuill's own planner from the repo).

```bash
# baseline (logged through the forwarder)
REPOQUILL_TRACE_FILE=$PWD/runs/baseline-1/run-4/trace.jsonl \
REPOQUILL_LIVE_KEY=*** \
uv run --project /home/susan/projects/repoquill repoquill generate \
  --config research/local/simpleaudit-pi-eval/simpleaudit/repoquill.yml

# final regeneration (direct endpoint, fresh output dir, full re-author)
REPOQUILL_LIVE_KEY=*** \
uv run repoquill generate \
  --config research/local/simpleaudit-pi-eval/simpleaudit/repoquill-regen2.yml \
  --force   # then one incremental `generate` (no --force) to retry the pages
```

| Artifact | Baseline location | Regeneration location |
|---|---|---|
| Narrative + reference Markdown | `runs/baseline-1/…` → `generated/simpleaudit-docs/` | `runs/regen-2/generated/simpleaudit-docs/` |
| Pi tool traces (per page) | `runs/baseline-1/run-{2,3,4,5}/trace.jsonl` | `runs/regen-2/` (generate.log per-page outcomes) |
| Model traffic log | `runs/baseline-1/forwarder.jsonl` (5 294 requests) | direct endpoint (per-page outcomes in generate.log) |
| Built MkDocs site | `generated/site_repoquill/` (85 HTML, 13 MB) | `runs/regen-2/generated/site_repoquill/` (86 HTML, 13 MB) |
| Run notes | `runs/baseline-1/RUN_NOTES.md` | `runs/regen-2/generate.log` |

---

## 3. Pages produced

- **8 narrative guides** planned (by RepoQuill's LLM planner, 2–5 source files each):
  `installation`, `quickstart`, `auditing-basics`, `targets-and-judges`,
  `scenarios`, `context-analysis`, `tracing-and-observability`, `custom-judges`.
- **76 deterministic reference modules** (Griffe/AST, `:::` mkdocstrings directives
  rendering real docstrings from source) across 7 sections: Core Engine, Targets,
  Judges, Context Analysis, Scenarios, Tracing & Observability, CLI & Utilities.

### Baseline outcome (commit `7350635`)

| Page | Outcome | Evidence |
|---|---|---|
| auditing-basics | ✅ published | 71 s, 16 tool calls, verified clean |
| context-analysis | ✅ published | 56 s, 9 calls |
| custom-judges | ✅ published | 53 s, 17 calls (transient-retry worked on attempt 2) |
| quickstart | ✅ published | 51 s, 18 calls (attempt 2, after transient abort) |
| scenarios | ✅ published | 49 s, 10 calls (attempt 2) |
| targets-and-judges | ✅ published | 76 s, 18 calls |
| tracing-and-observability | ✅ published | 78 s, 21 calls |
| **installation** | ❌ **FAILED** | **250-tool-call budget exhausted, `write_doc` never reached, 439 s** — degenerate near-duplicate search loop |

**7/8 narrative pages published & independently verified. 76 reference pages.
398 tests passing. Site: 85 HTML pages (built via the eval fallback because the
product gate was all-or-nothing).**

Baseline totals across all attempts (runs 4+5): **1 926 tool calls,
≈188 600 input + 39 200 output tokens.** Successful pages averaged 9–21 tool
calls each; the single failing page burned 250 (its budget) with no draft.

---

## 4. Independent, manual-style review (6 parallel reviewers, not the authoring agents)

The reviewers read every generated guide, the real SimpleAudit source, exported
symbols, signatures and tests, and the actual Pi tool traces. Their raw findings
are in `runs/baseline-1/reviews/{facts,examples,completeness,devex,traces,usability}.md`.

**A. Factual correctness** — **0 critical / 0 high.** 3 medium, all in
`tracing-and-observability`: an invented `auth` parameter, `scenario` used where
the API takes `scenario_name`, and a wrong `run_async` signature. Every other
public-API reference checked out against source.

**B. Executable examples** — 26 examples extracted: **12 offline PASS, 0 broken
eligible examples**, 10 external-service examples shape-verified (API shape
checked, runtime marked unavailable rather than faked), 4 illustrative. 5 minor
defects (missing constructed variables / `asyncio.run` wrappers in a few snippets).

**C. Completeness & architecture** — 15 capabilities well covered, 6 partial,
**5 missing**: `CrossJudgeExperiment`/`compare_judges`, local-model serving
(Ollama/vLLM), custom-scenario authoring, result viewing (Studio/plotting), and
the `ModelAuditor` configuration surface.

**D. Developer experience** — **2.5/5.** Causes: alphabetical sidebar (an
artifact of the eval's fallback site builder, not the product nav), a dead
`installation` link in the index (the failed page was still linked), some
judge duplication between pages, and near-absent cross-links.

**E. Pi behaviour & efficiency** — The `installation` failure fully reconstructed
from traces: a `search_code` orbit escalating only `max_results` 3→500, a
`read_file` `end_line` EOF ladder climbing to 1e300, and compaction amnesia
(one 923-line file re-read **307×**). Five ranked general-purpose fixes produced
(see §6).

**F. Real usability tasks** — **2/5 complete, 3 partial.** The offline/fake-client
story was missing, so "run a basic offline audit" could not be completed from the
docs alone; one instruction (`provider.store.by_trace`) was verified **false**
against source; the `[tracing]` extra was not documented.

> An automated quality-gate PASS was **not** accepted as proof of documentation
> quality — these reviews are the ground truth used to rank the backlog.

---

## 5. Ranked failure backlog (general-purpose only)

| # | Theme | Root cause (evidence) | Fix |
|---|---|---|---|
| **P1** | Pi over-exploration loop (the `installation`/`scenarios` failure) | Near-identical `search_code`/`read_file` re-issued 10–307× until the tool budget or deadline hit with no draft written | Loop breaker: normalized near-duplicate dedup + escalation + **write-only mode** at ~50 % budget / ~80 % deadline; `search_code` returns `total_matches` so `max_results` escalation is pointless; progress-gated deadline nudges; per-attempt budget 250→80 with an excerpt-preloaded retry |
| **P2** | Dead link + all-or-nothing site build | The failed `installation` page was still linked in the index; the CLI skipped the *entire* `mkdocs build` if any page failed | Link integrity: unavailable planned pages marked "(not yet available)" with no link (index/llms) or dropped (nav/llms-full); site builds from the successful subset, skipping only when **zero** pages succeeded or the gate failed globally |
| **P3** | Authoring-prompt gaps | Examples not runnable-as-shown, no offline/fake story, near-absent cross-links, 3 unfounded tracing specifics | System prompt now requires: verify every API reference against source (exact names/signatures/attributes); runnable-as-displayed examples (constructed vars, `asyncio.run`); an offline/no-API-key section when the package supports fakes; one canonical page per topic; a mandatory "Where to go next" with a concrete sibling-page list |
| **P4** | Planner coverage (5 missing capability areas) | The LLM planner under-plans cross-cutting capabilities (experiments, local models, result viewing) | **Documented, deferred** — higher effort (planner prompt + a coverage pass); tracked as a remaining weakness |
| **P5** | Navigation reading order | Sidebar appeared alphabetical | Product nav already preserves configured section + planner page order (confirmed, documented, pinned with a non-alphabetical test); the alphabetical sidebar was the eval fallback's artifact |

---

## 6. Before/after — regeneration with the fixed engine

_Regeneration `runs/regen-2/` (final commit `f54fed8` = baseline `7350635` +
`3d133a9` + `1d5dbaf` + `6d91f1a` + `f54fed8`), identical model config to the
baseline. The regeneration was a fresh full `--force` run followed by one
incremental retry of the pages the verifier held back._

| Metric | Baseline (`7350635`) | Regeneration (`f54fed8`) | Δ |
|---|---|---|---|
| **Narrative pages published** | 7/8 | **8/8** | **+1** |
| `installation` page | ❌ FAILED (250-call search orbit, `write_doc` never reached, 439 s) | ✅ **PUBLISHED, verified clean** — correctly documents the real `[tracing]` extra (`grpcio`/`aiohttp`/`opentelemetry-proto`) and `[plot]` extra | fixed |
| Reference modules | 76 | 76 | — |
| Cross-links across guides | near-absent (devex finding) | 63 `guides/*.md` links | improved |
| `installation` link in index | dead link | live (page published) | fixed |
| Site build | eval fallback — product gate was all-or-nothing and skipped the build | **product partial/full-build path** (P2); 86 HTML pages from the full successful set | fixed |
| HTML pages in built site | 85 (7 guides) | 86 (8 guides) | +1 |
| Verifier false-positives on real repo evidence | — (simpler pages) | **0** — keywords, test helpers, declared deps, tools, env-vars, single-char all recognized as ground truth | fixed |
| Genuine fabrications still blocked | n/a | yes — an invented `MissingApiKeyError` held fail-closed on the first pass before the retry authored a clean page | preserved |
| Test suite | 398 passing | **437 passing** (+39) | +39 |

**Regeneration narrative outcomes** (final `runs/regen-2/generate.log`): all 8
pages `OK` after the incremental retry; quality gate `passed` (import + symbol
checks); site assembled from the full successful set.

**What changed between the baseline and the final run** is the engine, not the
content bar: the loop breaker + write-only + excerpt retry (P1) stopped the
`installation` search orbit that made the baseline page fail; the prompt
hardening (P3) added the offline/fake-client and cross-link content the reviews
asked for; and the widened verifier ground truth stopped rejecting that better
content while still blocking fabricated APIs. Fail-closed held throughout — no
incomplete or unverified page was published.

---

## 7. Root causes & general-purpose fixes made to RepoQuill

**Baseline session (commit `7350635`)** — diagnosed and fixed six real failure
modes (D1–D6), all evidence-backed: D1 300 s deadline too tight → `timeout_s`
(900); D2 context-window mismatch → compaction amnesia → declared window +
`keepRecentTokens` 60 000; D3 `search_code` on a file path silently returned 0 →
file paths search that file; D4 model-level over-exploration → dedup + budget +
stopping rule; D5 verifier symbol false-positives (missing kwonly/posonly/`*args`,
module constants, type aliases, docstring names) → full signature + whole-tree
ground truth + import scoping; D6 zero-consumption `stopReason=error` → exactly
one retry on the transient shape. **398 tests.**

**Improvement session (commits `3d133a9` + `1d5dbaf`)** — the six independent
reviews ranked the residual failures; P1/P3 fixed the over-exploration loop and
prompt gaps, P2/P5 fixed the site. **429 tests. No SimpleAudit-specific logic
added** (all `simpleaudit` references in `repoquill/` are evidence-documenting
comments).

**Verifier-correctness session (commits `6d91f1a` + `f54fed8`)** — the first
regeneration exposed a subtle regression: the P3 prompt hardening *correctly*
steered agents to show offline/fake-client examples and to reference the real
dependency stack, but the **package-scoped** symbol verifier had no knowledge of
that evidence and rejected the improved pages as fabricated APIs (dropping the
run to 4/8). The verifier's ground truth was widened from "the package tree" to
"the repository, its tests, and its declared stack" — a backticked name is
flagged only if it exists *nowhere*:
- **keywords/builtins** (a bare `` `in` `` in an inline code span),
- **test-suite symbols** (`` include_tests: true `` makes tests first-class
  evidence; `FakeClient`, `make_auditor`, … in `tests/fakes.py`),
- **declared dependencies** + extra names (`pyproject.toml` via stdlib
  `tomllib`, `setup.cfg` via `configparser` — `grpcio` in the `[tracing]`
  extra, `ruff` as the linter),
- **standard ecosystem tooling** (backstop),
- **single-letter placeholders** (`` `S` ``/`` `x` `` in a worked example) and
  **credential env-vars** (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`).

`requires-python` raised to `>=3.11` (stdlib `tomllib`; CI tests 3.11/3.12) so
the parse is a clean stdlib call, not a fragile fallback. The hallucination
guarantee is intact: a name in *nowhere* (the installation page's invented
`MissingApiKeyError`) is **still flagged and blocks publication** — fail-closed
held. **437 tests.**

---

## 8. Remaining unresolved weaknesses (honest shortfalls)

- **P4 — planner coverage**: `CrossJudgeExperiment`/`compare_judges`, local-model
  serving (Ollama/vLLM), custom-scenario authoring, result viewing (Studio/plot),
  and the `ModelAuditor` configuration surface were not *autonomously* planned
  as first-class pages. Deferred to a planner-prompt + coverage pass.
- **Verifier residual**: third-party *class* names in backticks (e.g. OTel's
  `ExportTraceServiceRequest`) can still attract findings because they are neither
  in the package index nor importable top-level modules; this is by design (the
  verifier is package-scoped) and no longer blocks publication.
- **`installation` page (resolved)**: the loop breaker + write-only + excerpt
  retry converted the baseline's 250-call search orbit into a clean, verified
  page that documents the real dependency extras. On the first regeneration pass
  the model invented a plausible `MissingApiKeyError`; the verifier correctly
  held that page (fail-closed) and the incremental retry authored a clean page —
  i.e. the "fabricated API" bar is being enforced, not relaxed.
- **Model variance at the 27B tier (residual, bounded)**: per-page authoring is
  stochastic — the same page can take 10 or 51 tool calls, occasionally orbit a
  search, or invent a plausible exception name on one pass and not the next. The
  per-attempt budget, near-duplicate loop breaker, write-only mode, excerpt-
  preloaded retry, and the independent verifier bound this damage and keep
  fail-closed, but they cannot make a single page deterministically succeed on
  the first attempt. Occasional pages may need one retry to publish; none are
  published incomplete. (The P4 planner-coverage gaps listed above are
  backstopped by the deterministic reference layer, which documents those
  modules even where no narrative guide was planned.)

---

*Artifacts: `research/local/simpleaudit-pi-eval/` (gitignored). This report is
committed to `dev`.*
