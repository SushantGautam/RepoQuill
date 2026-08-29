## Key Ideas

RepoQuill is a two-layer developer documentation generator for Python packages. It combines deterministic static analysis with Large Language Model (LLM) generation to produce a complete, accurate, and searchable documentation site. The core philosophy is that documentation must be grounded in the actual source code to prevent hallucinations, while still providing the narrative context that raw API references lack.

### The Two-Layer Architecture

RepoQuill separates documentation generation into two distinct layers, each serving a specific purpose:

1.  **Layer 1: API Reference (Deterministic)**
    This layer uses static analysis (via Griffe) to parse the Python source code. It extracts class definitions, function signatures, parameters, and docstrings. This layer is fast, cost-free, and never hallucinates because it does not use an LLM. It produces the precise technical reference for every public symbol in the package.

2.  **Layer 2: Narrative Guides (LLM-Driven)**
    This layer uses an LLM to write conceptual guide pages, such as quickstarts, architectural overviews, and workflow explanations. Crucially, this generation is **grounded** in the actual source code. The LLM is provided with the real API surface and source files to ensure that the narrative accurately reflects the library's capabilities. This layer is incremental: only pages whose underlying source code has changed are regenerated, optimizing for speed and cost.

### Grounding and Verification

A central tenet of RepoQuill is that LLM-generated content must be verified against the source code. The library includes a robust verification subsystem (`verify` and `surgical_verify` modules) that ensures:

*   **Symbol Accuracy:** Every class, function, and method mentioned in the generated documentation must exist in the source code.
*   **Signature Fidelity:** Code examples and descriptions must match the exact parameter names and order found in the source.
*   **Property vs. Method Distinction:** The system explicitly distinguishes between attributes (properties) and methods, preventing common LLM errors where properties are incorrectly called as functions (e.g., `obj.name()` instead of `obj.name`).

The `grounding.run_grounding_pass` function orchestrates this process, scanning generated guides for inaccuracies and attempting to fix them or flagging them for review.

### Incremental Generation

RepoQuill is designed for continuous integration workflows. It tracks the state of the documentation using file hashes.

*   **Hashing:** The `plan.compute_file_hashes` function calculates hashes for all source files in the package.
*   **Change Detection:** The `plan.page_needs_regeneration` function compares old and new hashes to determine if a specific documentation page needs to be updated.
*   **Cleanup:** The `plan.cleanup_stale_pages` function removes documentation pages that correspond to deleted source files.

This ensures that running RepoQuill in CI only processes changes, making it efficient for large repositories.

### Configuration and Setup

RepoQuill is configured via a `repoquill.yml` file. The `config.RepoQuillConfig` class loads this configuration, providing properties such as `site_name`, `site_url`, `repo_url`, and `repo_name`. The LLM configuration is handled by `config.LLMConfig`, which specifies the provider, model, and authentication details.

The CLI entry point, `cli.main`, provides the `repoquill init` command to scaffold the configuration and GitHub Actions workflow. It supports various LLM providers, including OpenAI, Anthropic, GitHub Copilot, and local providers like Ollama and LM Studio.

### Core Modules and Functions

The library is structured into several key modules, each responsible for a specific part of the pipeline:

#### `reference` Module
Handles the extraction of the API surface from the source code.
*   `extract_api_surface(pkg_path, max_chars)`: Extracts the public API (classes, functions) from the package.
*   `get_source_files(pkg_path)`: Retrieves the source code files for grounding.
*   `build_api_reference(cfg)`: Generates the deterministic API reference pages.

#### `narrative` Module
Manages the LLM-driven generation of guide pages.
*   `determine_structure(cfg, client)`: Uses the LLM to decide the structure of the narrative guides.
*   `generate_all_pages(pages, source_files, client, cfg, old_hashes, new_hashes)`: Orchestrates the generation of all narrative pages, respecting incremental changes.
*   `generate_page(page, source_files, client, cfg)`: Generates a single narrative page using the LLM.

#### `verify` and `surgical_verify` Modules
Ensure the accuracy of the generated documentation.
*   `verify.verify_pages(cfg, client)`: Runs the full verification pass on all generated pages.
*   `surgical_verify.run_surgical_verify(guide_dir, pkg_path)`: Performs targeted fixes for common errors, such as incorrect method calls or missing required parameters.
*   `verify.check_page(page_md, idx, pkg_name)`: Checks a single page against the symbol index.

#### `site` Module
Assembles the final MkDocs site.
*   `build_mkdocs_yml(cfg, nav)`: Generates the `mkdocs.yml` configuration.
*   `build_nav(cfg, pages, reference_modules)`: Constructs the navigation structure.
*   `build_llms_txt(cfg, pages, reference_modules)`: Generates `llms.txt` and `llms-full.txt` files for AI agent consumption.

### Example Usage

While RepoQuill is primarily used via the CLI (`repoquill init` and the GitHub Actions workflow), the underlying API allows for programmatic control. Below is an example of how one might interact with the core components if integrating RepoQuill into a custom pipeline.

```python
from repoquill.config import load_config
from repoquill.llm import LLMClient
from repoquill.reference import extract_api_surface, get_source_files
from repoquill.narrative import determine_structure, generate_all_pages
from repoquill.plan import compute_file_hashes, load_plan, store_plan

# 1. Load Configuration
cfg = load_config("repoquill.yml")

# 2. Initialize LLM Client
llm_client = LLMClient(cfg.llm)

# 3. Extract Source Context
pkg_path = "my_package"
source_files = get_source_files(pkg_path)
api_surface = extract_api_surface(pkg_path, max_chars=50000)

# 4. Determine Documentation Structure
pages = determine_structure(cfg, llm_client)

# 5. Compute Hashes for Incremental Generation
old_hashes = load_plan("plan.json") if "plan.json" exists else {}
new_hashes = compute_file_hashes(source_files)

# 6. Generate Narrative Pages
generate_all_pages(
    pages=pages,
    source_files=source_files,
    client=llm_client,
    cfg=cfg,
    old_hashes=old_hashes,
    new_hashes=new_hashes
)

# 7. Store Plan for Next Run
store_plan("plan.json", pages, new_hashes)
```

### Output

The final output is a MkDocs Material site that includes:
*   **API Reference:** Deterministic, accurate documentation for all public symbols.
*   **Narrative Guides:** LLM-generated conceptual pages grounded in the source.
*   **AI-Ready Files:** `llms.txt` and `llms-full.txt` for easy consumption by AI agents.
*   **SKILL.md:** A file providing context for coding agents.

This architecture ensures that developers receive documentation that is both technically precise and conceptually helpful, while maintaining the integrity of the information through rigorous verification.

### See Also

*   [Architecture](architecture.md)
*   [Quickstart](quickstart.md)
*   [Installation](installation.md)
