## Quickstart

Welcome to **RepoQuill**. This guide provides a minimal, step-by-step example to help you get the library running in under five minutes. `repoquill` is a generic two-layer developer-docs generator. Point it at any Python package and it produces a complete, always-accurate documentation site.

It operates in two layers:
1.  **Layer 1 — API Reference (Deterministic):** Uses Griffe to parse your source code and renders classes, functions, signatures, and docstrings via mkdocstrings. This layer is fast, free, and never hallucinates.
2.  **Layer 2 — Narrative Guides (LLM):** Uses LiteLLM to write conceptual guide pages (quickstart, concepts, workflows) grounded in your actual source code. It is incremental, regenerating only pages whose source has changed.

The final output is a polished, searchable MkDocs Material site, including `llms.txt` / `llms-full.txt` for AI agents and a `SKILL.md` for coding agents.

### Prerequisites

Before you begin, ensure your environment meets the following requirements:

*   **Python Version:** 3.8 or higher.
*   **Operating System:** Linux, macOS, or Windows.
*   **Dependencies:** The `repoquill` package and its core dependencies.

### Installation

You can install `repoquill` using `pip`. Open your terminal and run the following command:

```bash
pip install repoquill
```

Alternatively, you can use `uv` to run RepoQuill in an isolated environment without a persistent installation:

```bash
uvx repoquill
```

If you prefer a persistent tool installation via `uv`:

```bash
uv tool install repoquill
```

### Basic Usage

The core functionality of `repoquill` is driven by the command-line interface (CLI). The primary entry point is the `init` command, which scaffolds the necessary configuration and CI workflow files for your repository.

#### Step 1: Initialize Your Repository

Navigate to the root of your Python package and run the `init` command. This command auto-detects your package name, project name, and GitHub repository. It will prompt you to select an LLM provider (e.g., OpenAI, Anthropic, GitHub Copilot, OpenRouter, Groq, Ollama) and configure the corresponding model and authentication.

```bash
cd your-repo
repoquill init
```

If you prefer to skip the interactive prompts, you can specify the provider and model directly using flags:

```bash
repoquill init --provider anthropic --model claude-sonnet-4-5
```

Running `repoquill init` creates the following files in your repository:

*   `repoquill.yml`: The configuration file containing provider, model, and authentication settings.
*   `.github/workflows/docs.yml`: The CI workflow that calls RepoQuill's reusable workflow to generate documentation on push.

#### Step 2: Configure LLM Authentication

For most providers, you need to provide an API key. If you are using GitHub Actions, add your API key as a repository secret:

1.  Go to your repository's **Settings** → **Secrets and variables** → **Actions**.
2.  Click **New repository secret**.
3.  Name: `LLM_API_KEY`
4.  Value: Your provider's API key (e.g., `sk-...`).

> **Note:** No API key is required for `github_copilot` (which uses device-code login) or local providers (such as `lm_studio`, `ollama`, `vllm`, or `local`).

### Configuration

The `repoquill.yml` file controls the behavior of the documentation generator. It is managed by the `RepoQuillConfig` class.

Key configuration properties include:

| Property | Description |
| :--- | :--- |
| `site_name` | The name of the documentation site. |
| `site_url` | The URL where the documentation site will be hosted. |
| `repo_url` | The URL of the source code repository. |
| `repo_name` | The name of the repository. |

You can load and inspect the configuration programmatically using the `load_config` function:

```python
from repoquill.config import load_config

# Load the configuration from the default 'repoquill.yml'
config = load_config("repoquill.yml")

print(config.site_name)
print(config.repo_url)
```

### Advanced Usage: Programmatic Generation

While the CLI is the recommended way to manage documentation in a CI/CD pipeline, you can also interact with the underlying modules for custom workflows.

#### LLM Client

The `LLMClient` class handles communication with the LLM provider. It is initialized with an `LLMConfig` object.

```python
from repoquill.config import LLMConfig
from repoquill.llm import LLMClient

# Initialize LLM configuration (parameters depend on provider)
llm_cfg = LLMConfig()

# Initialize the client
client = LLMClient(llm_cfg
    # NOTE: llm_cfg is required (no default)
,
    # NOTE: llm_cfg is required (no default)
)

# Example: Chat with the LLM
# Note: 'messages' format depends on the specific LLM provider
response = client.chat(
    messages=[{"role": "user", "content": "Hello"}],
    max_tokens=100,
    temperature=0.7,
    retries=3
)
```

#### API Reference Generation

The `reference` module contains functions to extract and build the deterministic API reference (Layer 1).

```python
from repoquill.reference import build_api_reference, get_source_files

# Get source files from the package path
source_files = get_source_files("./src/my_package")

# Build the API reference content
# 'cfg' is a RepoQuillConfig instance
api_ref = build_api_reference(cfg)
```

#### Site Building

The `site` module handles the generation of the MkDocs site structure and auxiliary files.

```python
from repoquill.site import build_index_md, build_llms_txt

# Build the main index.md file
# 'pages' is a list of page definitions
# 'reference_modules' is a list of module names
index_content = build_index_md(cfg, pages, reference_modules)

# Build the llms.txt file for AI agents
llms_txt_content = build_llms_txt(cfg, pages, reference_modules)
```

### Output Format

The generated documentation is a standard MkDocs Material site. The structure typically includes:

1.  **API Reference:** Automatically generated from source code using Griffe and mkdocstrings.
2.  **Narrative Guides:** LLM-generated pages such as Quickstart, Concepts, and Workflows.
3.  **AI Agent Files:**
    *   `llms.txt`: A lightweight index for LLMs.
    *   `llms-full.txt`: A full-text version for detailed context.
    *   `SKILL.md`: A skill definition for coding agents.

### Troubleshooting

*   **Configuration Errors:** Ensure that `repoquill.yml` is valid YAML and that the `provider` and `model` fields match a supported provider.
*   **Authentication Failures:** Verify that your `LLM_API_KEY` secret is correctly set in your CI environment or local environment variables.
*   **Parsing Errors:** If the API reference layer fails, ensure your Python source code is syntactically correct. Griffe relies on valid AST parsing.

### Next Steps

Now that you have successfully initialized `repoquill`, you can explore the following topics:

*   [API Reference](./api-reference.md): Detailed documentation for all classes and methods.
*   [Configuration Guide](./configuration.md): Advanced configuration options and templates.
*   [Integration with CI/CD](./ci-cd.md): How to automate documentation generation in your build pipeline.

By following this quickstart guide, you should now be able to integrate `repoquill` into your development workflow and maintain up-to-date documentation for your Python projects.

### See Also

*   [Installation](installation.md)
*   [Key Ideas](key-ideas.md)
