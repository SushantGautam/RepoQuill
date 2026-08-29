## Quickstart

RepoQuill is a two-layer developer documentation generator for Python packages. It combines deterministic API reference generation with LLM-driven narrative guides to produce a complete, accurate MkDocs Material site.

- **Layer 1 (API Reference):** Uses `Griffe` to parse source code and `mkdocstrings` to render classes, functions, and docstrings. This layer is deterministic, fast, and does not use an LLM.
- **Layer 2 (Narrative Guides):** Uses `LiteLLM` to write conceptual pages (e.g., quickstarts, workflows) grounded in the actual source code. It supports incremental regeneration, updating only pages where the source code has changed.

The final output is a polished, searchable documentation site, including `llms.txt` and `SKILL.md` files for AI agent consumption.

### Prerequisites

- Python 3.x
- A Python package you wish to document
- An LLM API key (unless using local providers or GitHub Copilot)

### Installation

You can run RepoQuill in an isolated environment using `uvx`, or install it persistently using `uv` or `pip`.

**Option 1: Isolated environment (Recommended for one-off runs)**
```bash
uvx repoquill init
```

**Option 2: Persistent installation**
```bash
# Using uv
uv tool install repoquill
repoquill init

# Or using pip
pip install repoquill
repoquill init
```

### Step 1: Initialize Your Repository

Run the `init` command from the root of your Python package repository. This command auto-detects your package name, project name, and GitHub repository URL.

```bash
cd your-repo
repoquill init
```

During initialization, RepoQuill will prompt you to select an LLM provider (e.g., OpenAI, Anthropic, GitHub Copilot, Ollama). It will then configure the appropriate model and authentication details in your config file.

You can skip interactive prompts by specifying flags:
```bash
repoquill init --provider anthropic --model claude-sonnet-4-5
```

This step generates two key files:
1.  **`repoquill.yml`**: The main configuration file containing provider, model, and auth settings.
2.  **`.github/workflows/docs.yml`**: A GitHub Actions workflow file that calls RepoQuill’s reusable workflow for CI/CD documentation generation.

### Step 2: Configure LLM Authentication

For most cloud-based providers, you need to provide an API key.

**GitHub Actions (CI/CD):**
Add your API key as a repository secret in GitHub Settings:
1.  Go to **Settings** → **Secrets and variables** → **Actions**.
2.  Create a new repository secret named `LLM_API_KEY`.
3.  Set the value to your provider's API key (e.g., `sk-...` for OpenAI).

**Local Development:**
If running locally, ensure your API key is available in your environment variables or configured within `repoquill.yml` as per the provider's requirements.

> **Note:** Providers like `github_copilot` (using device-code login) or local providers (Ollama, LM Studio) may not require a standard API key.

### Step 3: Generate Documentation

Once initialized, you can generate the documentation site. In a CI/CD context, this is handled automatically by the generated workflow. For local testing, you can invoke the CLI directly.

The core entry point for the CLI is `cli.main(argv)`. While typically invoked via the `repoquill` command, understanding the underlying functions helps with customization.

#### Key Configuration Objects

RepoQuill uses two primary configuration classes defined in the `config` module:

1.  **`config.RepoQuillConfig`**: Holds global site and repository settings.
    *   Properties: `site_name`, `site_url`, `repo_url`, `repo_name`
2.  **`config.LLMConfig`**: Holds LLM-specific settings (provider, model, etc.).

You can load a configuration from a file using:
```python
from config import load_config

# Load settings from repoquill.yml
cfg = load_config("repoquill.yml")
```

#### Programmatic Usage

If you are integrating RepoQuill into a custom pipeline, you can use the public API directly.

**1. Initialize the LLM Client**

The `llm.LLMClient` class handles communication with the LLM provider. It requires an `LLMConfig` instance.

```python
from config import LLMConfig, load_config
from llm import LLMClient

# Load config
cfg = load_config("repoquill.yml")

# Note: The API surface lists LLMConfig but does not explicitly show how it is extracted from RepoQuillConfig.
# You must obtain an LLMConfig instance to initialize the client.
llm_cfg = LLMConfig() # Or extract from cfg if available in your specific version/context

# Initialize client
client = LLMClient(llm_cfg
    # NOTE: llm_cfg is required (no default)
)
```

**2. Generate Narrative Pages**

The `narrative` module handles the generation of conceptual guides.

*   `narrative.determine_structure(cfg, client)`: Determines the structure of the documentation based on the config and LLM.
*   `narrative.generate_page(page, source_files, client, cfg)`: Generates content for a single page.
*   `narrative.generate_all_pages(pages, source_files, client, cfg, old_hashes, new_hashes)`: Generates all pages, supporting incrementalimport narrative
import reference
import config
import plan
from llm import LLMClient

# 1. Load configuration
cfg = config.load_config("repoquill.yml")

# 2. Initialize LLM Client
# Note: You must obtain an LLMConfig instance. 
# Based on the API surface, LLMConfig is a class, but the exact attribute name on RepoQuillConfig is not listed in PROPERTIES.
# Assuming standard practice, you would access it via the config object or construct it.
llm_cfg = LLMConfig() 
client = LLMClient(llm_cfg
    # NOTE: llm_cfg is required (no default)
)

# 3. Get source files for grounding
source_files = reference.get_source_files("path/to/your/package")

# 4. Determine documentation structure
pages = narrative.determine_structure(cfg, client)

# 5. Generate all pages
# old_hashes and new_hashes are used for incremental generation
# You can compute hashes using plan.compute_file_hashes(source_files)
old_hashes = {} 
new_hashes = plan.compute_file_hashes(source_files)

narrative.generate_all_pages(
    pages=pages,
    source_files=source_files,
    client=client,
    cfg=cfg,
    old_hashes=old_hashes,
    new_hashes=new_hashes
)
ashes=old_hashes,
    new_hashes=new_hashes
)
```

**3. Build API Reference**

The `reference` module provides functions to extract and render the deterministic API reference.

*   `reference.build_api_reference(cfg)`: Builds the main API reference.
*   `reference.extract_api_surface(pkg_path, max_chars)`: Extracts the API surface from the package path.
*   `reference.render_module_reference(module_name, search_path, module_descriptions)`: Renders a specific module's reference.

### Verification and Grounding

To ensure the generated documentation is accurate, RepoQuill includes verification tools.

*   `verify.verify_pages(cfg, client)`: Verifies that the generated pages contain valid symbols and claims.
*   `grounding.run_grounding_pass(guides_dir, pkg_path, client, llm_cfg, max_findings_per_page)`: Runs a grounding pass to ensure narrative guides are grounded in the source code.

### Output Structure

After running the generation process, RepoQuill produces:
1.  **MkDocs Site**: A complete `mkdocs.yml` and markdown files ready for `mkdocs serve` or `mkdocs build`.
2.  **AI Agent Files**:
    *   `llms.txt`: A lightweight index for LLMs.
    *   `llms-full.txt`: The full content of the documentation for LLM ingestion.
    *   `SKILL.md`: A skill file for coding agents.

### Troubleshooting

*   **Configuration Errors**: Ensure `repoquill.yml` is valid YAML and that the `provider` and `model` fields match your LLM provider's requirements.
*   **API Key Issues**: Verify that `LLM_API_KEY` is correctly set in your environment or GitHub secrets.
*   **Incremental Generation**: If pages are not updating, ensure that `plan.compute_file_hashes` is correctly identifying changes in your source files.

For more advanced usage, refer to the specific module documentation for `config`, `llm`, `narrative`, `reference`, `site`, and `verify`.

### See Also

*   [Installation](installation.md)
*   [Key Ideas](key-ideas.md)
