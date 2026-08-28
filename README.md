<p align="center">
  <img src="https://raw.githubusercontent.com/SushantGautam/RepoQuill/main/assets/repoquill-logo-512.png" width="180" alt="RepoQuill logo">
</p>

<h1 align="center">RepoQuill</h1>

<p align="center">
  <a href="https://pypi.org/project/repoquill/"><img src="https://img.shields.io/pypi/v/repoquill?logo=pypi&logoColor=white" alt="PyPI version"></a>
  <a href="https://pypi.org/project/repoquill/"><img src="https://img.shields.io/pypi/dm/repoquill?logo=pypi&logoColor=white" alt="PyPI downloads"></a>
  <a href="https://pypi.org/project/repoquill/"><img src="https://img.shields.io/pypi/pyversions/repoquill" alt="Python versions"></a>
  <a href="https://pypi.org/project/repoquill/"><img src="https://img.shields.io/pypi/license/repoquill" alt="License"></a>
</p>

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

## Quick start

### 1. Scaffold your repo (one command)

```bash
pip install repoquill
cd your-repo
repoquill init
```

`repoquill init` auto-detects your package name, project name, and GitHub repo, then **asks which LLM provider you want** (OpenAI, Anthropic, GitHub Copilot, OpenRouter, Groq, Ollama, …) and fills in the matching model + auth. It creates:

- `repoquill.yml` — the config (provider, model, and auth already set)
- `.github/workflows/docs.yml` — the CI workflow that calls RepoQuill's reusable workflow

You can skip the prompts with flags: `repoquill init --provider anthropic --model claude-sonnet-4-5`.

### 2. Add your LLM API key as a GitHub secret

Settings → Secrets and variables → Actions → New repository secret:

| Name | Value |
|------|-------|
| `LLM_API_KEY` | `sk-...` (your provider's key) |

> **No API key needed** for `github_copilot` (device-code login) or local providers (`ollama`, `lm_studio`, `vllm`).

### 3. Push and go

```bash
git add repoquill.yml .github/workflows/docs.yml
git commit -m "docs: add RepoQuill"
git push
```

Docs build on every push to `main` and deploy to GitHub Pages (`https://<you>.github.io/<repo>/`).

### Local preview

```bash
export OPENAI_API_KEY=sk-...
repoquill serve          # live-reload at http://localhost:8000
```

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
| `repoquill init` | Scaffold `repoquill.yml` + GitHub Actions workflow (auto-detects package, name, repo). |
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

### `init` flags

| Flag | Description |
|------|-------------|
| `--name NAME` | Project name (default: from `pyproject.toml`). |
| `--package DIR` | Package directory (default: auto-detected). |
| `--description TEXT` | One-line description. |
| `--provider NAME` | LLM provider (default: interactive prompt). |
| `--model NAME` | LLM model (default: provider's default). |
| `--trigger MODE` | When the docs workflow runs: `manual` (default), `push_main`, `push_all`, `release`. |
| `--test` | Test the LLM connection after init. |
| `--force` | Overwrite existing files. |

`init` asks which LLM provider to use (a catalog derived from LiteLLM's own
model list) and when the GitHub Actions workflow should run:

| Trigger | `on:` block |
|---------|-------------|
| `manual` (default) | `workflow_dispatch` only — dormant, run from the Actions UI |
| `push_main` | `push` on `main` + `workflow_dispatch` |
| `push_all` | `push` (all branches) + `pull_request` + `workflow_dispatch` |
| `release` | `push` on `v*` tags + `workflow_dispatch` |

You can build docs **locally** (`repoquill build` / `repoquill serve`) or via
**GitHub Actions** (cloud runner). For the Actions path, set `LLM_API_KEY` as a
repository secret so the runner can call the LLM.

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

This puts the generated content (`index.md`, `guides/`, `reference/`), `mkdocs.yml`, and the built `site/` all inside `docs/`:

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
  api_key_env: OPENAI_API_KEY   # env var name the workflow exports your secret under
                                # (matches the provider: OPENAI_API_KEY, ANTHROPIC_API_KEY, ...)
  base_url: null                # null = provider default; set for custom endpoints

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

| `provider` | `model` example | key env var (set this) |
|------------|-----------------|------------------------|
| `openai` | `gpt-4o` | `OPENAI_API_KEY` |
| `anthropic` | `claude-sonnet-4-5` | `ANTHROPIC_API_KEY` |
| `github_copilot` | `gpt-4o` | _(none — device-code login)_ |
| `openrouter` | `openai/gpt-4o` | `OPENROUTER_API_KEY` |
| `groq` | `llama-3.3-70b-versatile` | `GROQ_API_KEY` |
| `ollama` | `llama3.1` | _(none — local)_ |

Auth is fully generic: **LiteLLM resolves each provider's key from its standard
env var automatically** — just set the env var in the "key env var" column (or
as a GitHub Actions secret) and you're done. You don't need to set
`api_key_env` in `repoquill.yml` for standard providers. Any provider in
LiteLLM's catalog works — no RepoQuill changes needed.

`api_key_env` is only consulted for a custom OpenAI-compatible endpoint
(`base_url` set, `provider: openai`).

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

RepoQuill ships a **reusable workflow**. The fastest path is `repoquill init` (see [Quick start](#quick-start)), which scaffolds both files for you. Here's what it generates, if you prefer to do it by hand:

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
    secrets:
      LLM_API_KEY: ${{ secrets.LLM_API_KEY }}
```

> **Note:** `secrets: inherit` only works for same-org/enterprise callers. For cross-org use (the common case), pass secrets explicitly as shown above. `repoquill init` generates this correctly.

That's it. Pushing to `main` regenerates the docs and deploys the site to `gh-pages`.

> **Tip:** Pin `@main` to a release tag (e.g. `@v0.1`) or commit SHA for reproducible builds. GitHub's security guidance recommends pinning third-party workflows to a SHA; use a tag for convenience, a SHA for maximum safety.

### Reusable workflow inputs

| Input | Default | Description |
|-------|---------|-------------|
| `config` | `repoquill.yml` | Path to your config. |
| `api_key_secret` | `LLM_API_KEY` | Name of the secret holding the LLM key. |
| `api_key_env` | `OPENAI_API_KEY` | Env var name the secret is exported under (e.g. `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`). Must match your provider — LiteLLM reads the key from this env var. |
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
