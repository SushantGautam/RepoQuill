## Installation

RepoQuill is a Python library and command-line tool designed to generate comprehensive, two-layer developer documentation for any Python package. It combines deterministic API reference generation with LLM-powered narrative guides to create a complete MkDocs Material site.

This page details how to install and initialize RepoQuill in your project.

### Prerequisites

Before installing RepoQuill, ensure your environment meets the following requirements:

1.  **Python**: A recent version of Python compatible with the PyPI distribution.
2.  **Package Manager**: While `pip` is supported, RepoQuill is optimized for use with `uv` or `uvx` for isolated, fast execution.
3.  **LLM Provider**: You must have an API key for a supported LLM provider (e.g., OpenAI, Anthropic, GitHub Copilot, OpenRouter, Groq, Ollama) or access to a local LLM server.

### Installation Methods

RepoQuill can be installed in two primary ways: as an ephemeral tool via `uvx` (recommended for one-off scaffolding) or as a persistent installation via `uv` or `pip`.

#### Option 1: Ephemeral Installation with `uvx` (Recommended)

Using `uvx` allows you to run RepoQuill without installing it into your project's environment. This is ideal for initializing documentation in a new repository.

```bash
# Navigate to your project root
cd your-repo

# Run RepoQuill init in an isolated environment
uvx repoquill init
```

This command downloads and executes RepoQuill in a temporary environment. It does not modify your `requirements.txt` or `pyproject.toml` directly but generates the necessary configuration files.

#### Option 2: Persistent Installation with `uv`

If you plan to run RepoQuill frequently or need it in your CI/CD pipeline, you may prefer a persistent installation.

```bash
# Install RepoQuill as a standalone tool
uv tool install repoquill

# Initialize documentation
repoquill init
```

#### Option 3: Installation with `pip`

You can also install RepoQuill using standard `pip`.

```bash
# Install from PyPI
pip install repoquill

# Initialize documentation
repoquill init
```

### Initializing Your Project

The `repoquill init` command is the primary entry point for setting up documentation generation. It performs the following actions:

1.  **Auto-detection**: It automatically detects your package name, project name, and GitHub repository URL.
2.  **Provider Selection**: It prompts you to select an LLM provider. Supported providers include:
    *   `openai`
    *   `anthropic`
    *   `github_copilot`
    *   `openrouter`
    *   `groq`
    *   `ollama`
    *   `lm_studio`
    *   `local`
    *   `vllm`
3.  **Configuration Generation**: It creates a `repoquill.yml` file in your project root. This file contains the selected provider, model, and authentication settings.
4.  **CI Workflow Creation**: It generates a `.github/workflows/docs.yml` file that calls RepoQuill's reusable GitHub Actions workflow. This ensures your documentation is automatically regenerated on every push.

#### Command-Line Flags

You can skip the interactive prompts by specifying the provider and model directly via command-line flags:

```bash
# Example: Initialize with Anthropic Claude Sonnet 4.5
repoquill init --provider anthropic --model claude-sonnet-4-5
```

Available providers for the `--provider` flag include: `openai`, `anthropic`, `github_copilot`, `openrouter`, `groq`, `ollama`, `lm_studio`, `local`, and `vllm`.

### Configuration

After running `repoquill init`, a `repoquill.yml` file is created in your project root. This file is the single source of truth for your documentation generation settings.

The configuration is managed by the `config.RepoQuillConfig` class, which exposes the following properties:

*   `site_name`: The name of your documentation site.
*   `site_url`: The base URL where your documentation will be hosted.
*   `repo_url`: The URL of your GitHub repository.
*   `repo_name`: The name of your repository.

The `config.LLMConfig` class manages LLM-specific settings, including the provider, model, and authentication details.

You can load the configuration programmatically using:

```python
from config import load_config

# Load configuration from the default location
cfg = load_config("repoquill.yml")

# Access configuration properties
print(cfg.site_name)
print(cfg.repo_url)
```

### Setting Up LLM Authentication

RepoQuill requires an LLM API key to generate narrative guides. The method for providing this key depends on your chosen provider and execution context.

#### GitHub Actions (CI/CD)

If you are using the generated GitHub Actions workflow, you must add your API key as a repository secret.

1.  Navigate to your GitHub repository.
2.  Go to **Settings** → **Secrets and variables** → **Actions**.
3.  Click **New repository secret**.
4.  Add a secret named `LLM_API_KEY` with your provider's API key as the value.

| Secret Name | Value |
| :--- | :--- |
| `LLM_API_KEY` | `sk-...` (your provider's key) |

> **Note**: Providers like `github_copilot` may use device-code login, and local providers (e.g., `ollama`, `lm_studio`) do not require an API key.

#### Local Execution

When running `repoquill` locally, the `LLM_API_KEY` environment variable is typically used for authentication. Ensure this variable is set in your shell environment before running the tool:

```bash
export LLM_API_KEY="your-api-key-here"
repoquill generate
```

### Verification

To verify that RepoQuill is installed and configured correctly, you can run the verification module. This checks the generated documentation against the actual source code to ensure accuracy.

```python
from verify import verify_pages
from config import load_config

# Load configuration
cfg = load_config("repoquill.yml")

# Initialize LLM client (requires llm.LLMClient)
from llm import LLMClient
from config import LLMConfig

# Note: LLMConfig initialization depends on the specific provider setup
# This is a conceptual example of the verification flow
# client = LLMClient(llm_cfg) 
# verify_pages(cfg, client)
```

The `verify_pages` function takes the configuration and an LLM client instance to check all documentation pages for consistency with the source code.

### Next Steps

Once installed and initialized, you can proceed to:

1.  **Generate Documentation**: Run `repoquill generate` to create the initial documentation site.
2.  **Review Configuration**: Adjust `repoquill.yml` to customize site metadata or LLM parameters.
3.  **Deploy**: Push your changes to trigger the GitHub Actions workflow, which will build and deploy the documentation site.

### See Also

*   [Quickstart](quickstart.md)
*   [Key Ideas](key-ideas.md)
