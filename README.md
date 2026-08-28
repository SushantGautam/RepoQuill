<p align="center">
  <img src="https://raw.githubusercontent.com/SushantGautam/RepoQuill/main/assets/repoquill-logo-512.png" width="180" alt="RepoQuill logo">
</p>

<h1 align="center">RepoQuill</h1>

Generic two-layer developer-docs generator. Point it at any Python package and it produces a complete, always-accurate documentation site:

- **Layer 1 — API reference (deterministic, no LLM).** Griffe parses your source; mkdocstrings renders classes, functions, signatures, and docstrings. This layer is fast, free, and never hallucinates.
- **Layer 2 — narrative guides (LLM).** LiteLLM writes conceptual guide pages (quickstart, concepts, workflows) grounded in your actual source. Incremental: only pages whose source changed are regenerated.
- **MkDocs Material site.** A polished, searchable, themeable site with `llms.txt` / `llms-full.txt` for AI agents and a `SKILL.md` for coding agents.

RepoQuill is a standalone pip package. Your repo keeps a single `repoquill.yml` config and a GitHub Actions workflow that calls RepoQuill's reusable workflow.

## How it works

```
your Python package
        │
        ▼
┌─────────────────────────────────────────────┐
│  repoquill generate                          │
│                                              │
│  [1] Load source files                       │
│  [2] Layer 1: Griffe → reference/*.md        │  (deterministic)
│  [3] Layer 2: LLM → guides/*.md              │  (incremental, LiteLLM)
│  [4] Cross-link guides                       │
│  [5] Assemble: index.md, nav, mkdocs.yml,    │
│      llms.txt, llms-full.txt, SKILL.md       │
│  [6] mkdocs build → site/                    │
└─────────────────────────────────────────────┘
```

## Install

```bash
pip install repoquill
# optional: local RAG (offline embeddings, no API key)
pip install "repoquill[rag]"
```

## Quick start (local)

1. Create a `repoquill.yml` at your repo root (see [Config](#config)).
2. Set your LLM API key in the environment:
   ```bash
   export OPENAI_API_KEY=sk-...
   ```
3. Generate + build + preview in one command:
   ```bash
   repoquill serve
   ```
   This generates the docs and starts a live-reload server at `http://localhost:8000`.

   Or, for a one-shot build:
   ```bash
   repoquill build
   ```

To generate only the deterministic reference (no LLM, no API key):
```bash
repoquill build --no-llm
```

## CLI

| Command | Description |
|---------|-------------|
| `repoquill plan` | Show the planned page structure (which guides, which sources). |
| `repoquill generate` | Run Layer 1 + Layer 2, assemble the site. |
| `repoquill build` | Same as `generate`, always runs `mkdocs build`. |
| `repoquill serve` | Generate + start `mkdocs serve` for local live-reload preview. |

Flags:

| Flag | Description |
|------|-------------|
| `--config PATH` | Path to `repoquill.yml`, a **directory** of configs, or a **comma-separated list**. Default: `./repoquill.yml` or `./configs/`. |
| `--no-llm` | Skip Layer 2 (deterministic reference only). |
| `--force` | Re-plan and regenerate everything (ignore the change cache). |
| `--build` | Run `mkdocs build` after generating. |
| `--source-root PATH` | Override the source repo root. |
| `--port PORT` | Port for `serve` (default `8000`). |

### Multiple configs

Point `--config` at a directory to process all `*.yml`/`*.yaml` files inside:

```bash
# Process all configs in configs/
repoquill build --config configs/

# Or a specific list
repoquill build --config "configs/api.yml,configs/guides.yml"
```

If no `--config` is given, RepoQuill looks for `./repoquill.yml` first, then `./configs/`.

### Same-repo integration

When your docs live in the **same repo** as your code, use `output_dir` to keep all generated artifacts in one folder:

```yaml
# repoquill.yml (at repo root, same repo as your package)
project_name: MyProject
package_dir: mypackage
output_dir: docs          # everything goes into docs/
```

This puts `site_src/`, `mkdocs.yml`, and the built `site/` all inside `docs/`:

```
myrepo/
├── mypackage/
├── repoquill.yml
└── docs/                 # ← all RepoQuill output lives here
    ├── mkdocs.yml
    ├── index.md
    ├── guides/
    ├── reference/
    ├── llms.txt
    ├── llms-full.txt
    ├── SKILL.md
    └── site/             # built site (gitignore this)
```

Add `docs/site/` to your `.gitignore`. Then:

```bash
repoquill serve --port 8000   # live preview
repoquill build                # one-shot build
```

## Config

`repoquill.yml` drives everything. A minimal example:

```yaml
project_name: MyProject
package_dir: mypackage          # the Python package to document
output_dir: docs                # optional: keep all artifacts in one folder (same-repo)

llm:
  provider: openai              # openai | anthropic | openrouter | groq | ollama | ...
  model: gpt-4o
  api_key_env: OPENAI_API_KEY   # env var NAME holding the key (never the key itself)
  base_url: null                # null = provider default; set for custom endpoints
  temperature: 0.3
  max_tokens: 8192

site:
  name: MyProject
  description: "What MyProject does"
  url: https://example.com/myproject-docs/
  repo_url: https://github.com/you/myproject
  repo_name: you/myproject

# Narrative guide sections (Layer 2). Each section lists page slugs.
narrative_sections:
  - title: Getting Started
    slugs: [quickstart, installation]
  - title: Core Concepts
    slugs: [architecture, key-ideas]

# API reference nav sections (Layer 1). Module prefixes per section.
reference_sections:
  - title: Core
    modules: [mypackage, mypackage.core]
  - title: Plugins
    modules: [mypackage.plugins]

# Optional per-module descriptions (shown on the index page).
module_descriptions:
  mypackage: "Top-level package."
  mypackage.core: "The core engine."
```

### LLM providers

RepoQuill uses [LiteLLM](https://github.com/BerriAI/litellm), so any provider works:

| `provider` | `model` example | `api_key_env` |
|------------|-----------------|---------------|
| `openai` | `gpt-4o` | `OPENAI_API_KEY` |
| `anthropic` | `claude-sonnet-4-5` | `ANTHROPIC_API_KEY` |
| `openrouter` | `openai/gpt-4o` | `OPENROUTER_API_KEY` |
| `groq` | `llama-3.3-70b-versatile` | `GROQ_API_KEY` |
| `ollama` | `llama3.1` | _(none — local)_ |

For a custom OpenAI-compatible endpoint, set `base_url` and use `provider: openai`.

### Local RAG (optional)

Enable offline retrieval-augmented generation so the LLM grounds its guides in your source without sending it to an API:

```yaml
llm:
  # ...
  rag:
    enabled: true
    model: all-MiniLM-L6-v2   # any sentence-transformers model
    top_k: 6
    chunk_size: 1500
```

Requires `pip install "repoquill[rag]"`. Runs fully offline on the GitHub runner — no API key for the embeddings.

## Use in your repo (GitHub Actions)

RepoQuill ships a **reusable workflow**. Your repo adds a thin wrapper that calls it.

### 1. Add `repoquill.yml` to your repo

(See [Config](#config) above.)

### 2. Add the LLM API key as a secret

In your repo's **Settings → Secrets and variables → Actions**, add a secret (e.g. `LLM_API_KEY`) with your provider's API key.

### 3. Add a workflow that calls RepoQuill

`.github/workflows/docs.yml`:

```yaml
name: Docs
on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  docs:
    uses: SushantGautam/RepoQuill/.github/workflows/reusable.yml@main
    with:
      config: repoquill.yml
      api_key_secret: LLM_API_KEY      # name of YOUR secret
      api_key_env: OPENAI_API_KEY       # must match repoquill.yml
      deploy_branch: gh-pages           # empty to skip deploy
      deploy_path: site
    secrets: inherit
```

That's it. Pushing to `main` regenerates the docs and deploys the site to `gh-pages`.

### Reusable workflow inputs

| Input | Default | Description |
|-------|---------|-------------|
| `config` | `repoquill.yml` | Path to your config. |
| `api_key_secret` | `LLM_API_KEY` | Name of the secret holding the LLM key. |
| `api_key_env` | `OPENAI_API_KEY` | Env var name the LLM client reads (must match `api_key_env` in your config). |
| `no_llm` | `false` | Set `true` for reference-only (no API key needed). |
| `python_version` | `3.11` | Runner Python version. |
| `install_rag` | `false` | Install the `[rag]` extra. |
| `deploy_branch` | `""` | Branch to deploy `site/` to (empty = no deploy). |
| `deploy_path` | `site` | Path to the built site folder. |

## Project layout

```
RepoQuill/
├── pyproject.toml
├── README.md
├── .github/
│   └── workflows/
│       └── reusable.yml        # the reusable workflow your repos call
└── repoquill/
    ├── __init__.py
    ├── cli.py                  # entry point + orchestration
    ├── config.py               # repoquill.yml loader → RepoQuillConfig
    ├── reference.py            # Layer 1: Griffe API reference
    ├── narrative.py            # Layer 2: LLM guide generation
    ├── llm.py                  # LiteLLM client + optional local RAG
    ├── site.py                 # MkDocs assembly (index, nav, llms.txt, SKILL.md)
    └── plan.py                 # change-detection cache (incremental regen)
```

## License

MIT
