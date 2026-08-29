## Architecture

**repoquill** is a lightweight Python library designed to streamline the generation of developer documentation directly from source code repositories. Its primary objective is to bridge the gap between raw code and readable, maintainable documentation by analyzing repository structures, extracting metadata, and rendering formatted output.

The architecture of `repoquill` is modular, allowing for independent extension of parsing, analysis, and rendering components. This section provides a high-level overview of the system design, module interactions, and data flow.

### System Overview

The `repoquill` system operates on a two-layer pipeline model. Data flows from the source repository through a series of processing stages:

1.  **Discovery & Planning**: Identifying relevant files, computing hashes for incremental updates, and determining which documentation pages need regeneration.
2.  **Parsing (Layer 1)**: Extracting structural information (classes, functions, signatures) from source files using deterministic tools (Griffe). This layer generates the API reference without LLM involvement.
3.  **Narrative Generation (Layer 2)**: Using an LLM to write conceptual guide pages (quickstart, concepts, workflows) grounded in the actual source code.
4.  **Verification**: Checking generated documentation against the source code to ensure accuracy (e.g., verifying that symbols mentioned in docs actually exist).
5.  **Rendering**: Converting the analyzed data and generated narratives into a MkDocs Material site, including `llms.txt` and `SKILL.md` for AI agents.

This separation of concerns ensures that the core logic remains agnostic to the specific LLM provider being used and allows for deterministic API reference generation alongside creative narrative generation.

### Core Modules

The library is organized into several key modules, each responsible for a specific aspect of the documentation generation pipeline.

#### 1. `repoquill.config`

This module handles configuration management for the documentation generation process.

*   **`RepoQuillConfig`**:
    *   **Description**: Holds the global configuration for the documentation site.
    *   **Properties**:
        *   `site_name`: The name of the documentation site.
        *   `site_url`: The base URL for the site.
        *   `repo_url`: The URL of the source code repository.
        *   `repo_name`: The name of the repository.

*   **`LLMConfig`**:
    *   **Description**: Holds configuration details for the LLM provider, including model selection and authentication.

*   **`load_config(config_path)`**:
    *   **Description**: Loads and parses the `repoquill.yml` configuration file.
    *   **Parameters**:
        *   `config_path`: Path to the configuration file.

#### 2. `repoquill.llm`

This module manages interactions with Large Language Models and local retrieval-augmented generation (RAG) capabilities.

*   **`LLMClient`**:
    *   **Description**: A client for interacting with LLM providers via LiteLLM.
    *   **Constructor**: `LLMClient(llm_cfg)`
    *   **Key Methods**:
        *   `chat(messages, max_tokens, temperature, retries)`: Sends a chat request to the LLM and returns the response.

*   **`LocalRAG`**:
    *   **Description**: A local retrieval-augmented generation engine that indexes source files for context retrieval.
    *   **Constructor**: `LocalRAG(rag_cfg: Dict[str, Any], source_files: Dict[str, str])`
    *   **Key Methods**:
        *   `build()`: Builds the local index from the provided source files.
        *   `retrieve(query, top_k)`: Retrieves the most relevant chunks of source code for a given query.

*   **`strip_code_fences(text)`**:
    *   **Description**: Utility function to remove Markdown code fences from text.

#### 3. `repoquill.reference`

This module handles the deterministic extraction of API surfaces and the rendering of the API reference layer.

*   **`extract_api_surface(pkg_path, max_chars)`**:
    *   **Description**: Extracts the public API surface (classes, functions, signatures) from the package source code.
*   **`extract_cli_surface(pkg_path, max_chars)`**:
    *   **Description**: Extracts CLI command definitions and arguments.
*   **`extract_constructor_signatures(pkg_path, names, max_chars)`**:
    *   **Description**: Extracts specific constructor signatures for given class names.
*   **`get_source_files(pkg_path)`**:
    *   **Description**: Retrieves a list of source files in the package.
*   **`get_file_tree(pkg_path)`**:
    *   **Description**: Generates a tree structure of the package files.
*   **`build_api_reference(cfg)`**:
    *   **Description**: Builds the complete API reference documentation structure.
*   **`render_module_reference(module_name, search_path, module_descriptions)`**:
    *   **Description**: Renders the reference documentation for a specific module.

#### 4. `repoquill.narrative`

This module handles the LLM-driven generation of narrative guide pages.

*   **`determine_structure(cfg, client)`**:
    *   **Description**: Uses the LLM to determine the structure and topics for the narrative guides based on the configuration and source code.
*   **`generate_page(page, source_files, client, cfg)`**:
    *   **Description**: Generates the content for a single narrative page using the LLM.
*   **`generate_all_pages(pages, source_files, client, cfg, old_hashes, new_hashes)`**:
    *   **Description**: Orchestrates the generation of all narrative pages, handling incremental updates based on file hashes.

#### 5. `repoquill.plan`

This module manages the incremental documentation generation process.

*   **`compute_file_hashes(source_files)`**:
    *   **Description**: Computes hashes for source files to detect changes.
*   **`load_plan(plan_file)`**:
    *   **Description**: Loads the previous documentation plan from disk.
*   **`store_plan(plan_file, pages, file_hashes)`**:
    *   **Description**: Saves the current documentation plan and file hashes to disk.
*   **`page_needs_regeneration(page, old_hashes, new_hashes, out_path)`**:
    *   **Description**: Determines if a specific page needs to be regenerated based on source file changes.
*   **`cleanup_stale_pages(plan_slugs, guides_dir)`**:
    *   **Description**: Removes documentation pages that are no longer part of the plan.

#### 6. `repoquill.verify`

This module ensures the accuracy of the generated documentation by verifying it against the source code.

*   **`SymbolIndex`**:
    *   **Description**: An index of all symbols (classes, functions, methods) in the source code.
*   **`build_index(pkg_path)`**:
    *   **Description**: Builds the `SymbolIndex` from the package source code.
*   **`check_page(page_md, idx, pkg_name)`**:
    *   **Description**: Verifies a single Markdown page against the symbol index.
*   **`check_all(guides_dir, idx, pkg_name)`**:
    *   **Description**: Verifies all pages in the guides directory.
*   **`verify_pages(cfg, client)`**:
    *   **Description**: Orchestrates the verification process for all generated pages.
*   **`extract_backtick_symbols(md)`**, **`extract_code_blocks(md)`**, **`extract_imports(md)`**, **`extract_method_calls(md)`**:
    *   **Description**: Utility functions to extract specific code elements from Markdown for verification.

#### 7. `repoquill.surgical_verify`

This module performs more granular, "surgical" verification and correction of documentation.

*   **`build_class_index(pkg_path)`**:
    *   **Description**: Builds an index specifically for class structures.
*   **`fix_missing_required(text, classes)`**:
    *   **Description**: Identifies and fixes missing required parameters in code examples.
*   **`fix_property_calls(text, classes)`**:
    *   **Description**: Corrects instances where properties are incorrectly called as methods.
*   **`run_surgical_verify(guide_dir, pkg_path)`**:
    *   **Description**: Runs the full surgical verification pass on the guides directory.

#### 8. `repoquill.site`

This module handles the final assembly of the MkDocs site and auxiliary files.

*   **`build_nav(cfg, pages, reference_modules)`**:
    *   **Description**: Builds the navigation structure for the MkDocs site.
*   **`build_mkdocs_yml(cfg, nav)`**:
    *   **Description**: Generates the `mkdocs.yml` configuration file.
*   **`build_index_md(cfg, pages, reference_modules)`**:
    *   **Description**: Generates the main `index.md` page.
*   **`build_llms_txt(cfg, pages, reference_modules)`**:
    *   **Description**: Generates the `llms.txt` file for AI agent consumption.
*   **`build_llms_full_txt(cfg, pages, reference_modules)`**:
    *   **Description**: Generates the `llms-full.txt` file containing full content for AI agents.
*   **`build_skill_md(cfg)`**:
    *   **Description**: Generates the `SKILL.md` file for coding agents.
*   **`cross_link_guides(cfg, pages)`**:
    *   **Description**: Adds cross-links between narrative guide pages.

#### 9. `repoquill.grounding`

This module ensures that LLM-generated content is grounded in the actual source code.

*   **`run_grounding_pass(guides_dir, pkg_path, client, llm_cfg, max_findings_per_page)`**:
    *   **Description**: Runs a pass to verify and correct LLM-generated content against the source code, limiting the number of findings per page.

#### 10. `repoquill.cli`

This module provides the command-line interface.

*   **`main(argv)`**:
    *   **Description**: The main entry point for the CLI. Handles commands like `init` and `generate`.

### Data Flow

The following sequence describes the data flow during a typical documentation generation run:

1.  **Initialization**: The CLI (`cli.main`) loads the configuration using `config.load_config`.
2.  **Planning**: `plan.compute_file_hashes` calculates hashes for source files. `plan.load_plan` retrieves the previous state. `plan.page_needs_regeneration` determines which pages need updating.
3.  **API Reference (Layer 1)**: `reference.extract_api_surface` and related functions parse the source code deterministically. `reference.build_api_reference` constructs the API documentation.
4.  **Narrative Generation (Layer 2)**:
    *   `narrative.determine_structure` uses the LLM to plan the guide topics.
    *   `narrative.generate_all_pages` generates the content for each page, using `llm.LLMClient` and `llm.LocalRAG` for context.
5.  **Verification**:
    *   `verify.build_index` creates a symbol index.
    *   `verify.check_all` and `surgical_verify.run_surgical_verify` check the generated pages for accuracy and fix common errors (e.g., property calls).
    *   `grounding.run_grounding_pass` performs a final grounding check.
6.  **Site Assembly**: `site.build_nav`, `site.build_mkdocs_yml`, and other `site` functions assemble the final MkDocs site structure, including `llms.txt` and `SKILL.md`.
7.  **Output**: The generated files are written to the output directory.

### Configuration

`repoquill` supports configuration via a `repoquill.yml` file. Key configuration options are loaded into `RepoQuillConfig` and `LLMConfig`.

| Option | Type | Description |
| :--- | :--- | :--- |
| `site_name` | `str` | The name of the documentation site. |
| `site_url` | `str` | The base URL for the site. |
| `repo_url` | `str` | The URL of the source code repository. |
| `repo_name` | `str` | The name of the repository. |
| `provider` | `str` | The LLM provider (e.g., `openai`, `anthropic`, `github_copilot`). |
| `model` | `str` | The specific model to use. |
| `api_key` | `str` | The API key for the LLM provider (or environment variable reference). |

### Example Usage

The following example demonstrates how to initialize and run the documentation generation process programmatically.

```python
from repoquill.config import load_config
from repoquill.llm import LLMClient
from repoquill.narrative import determine_structure, generate_all_pages
from repoquill.reference import build_api_reference
from repoquill.site import build_nav, build_mkdocs_yml

def main():
    # Load configuration
    cfg = load_config("repoquill.yml")
    
    # Initialize LLM client
    llm_client = LLMClient(cfg.llm_config
    # NOTE: llm_cfg is required (no default)
)
    
    # Determine narrative structure
    pages = determine_structure(cfg, llm_client)
    
    # Generate API reference
    api_ref = build_api_reference(cfg)
    
    # Generate narrative pages
    # Note: source_files and hashes would be computed in a real pipeline
    # generate_all_pages(pages, source_files, llm_client, cfg, old_hashes, new_hashes)
    
    # Build site navigation and config
    nav = build_nav(cfg, pages, api_ref)
    mkdocs_yml = build_mkdocs_yml(cfg, nav)
    
    print("Documentation site structure generated successfully.")

if __name__ == "__main__":
    main()
```

### Design Principles

1.  **Two-Layer Architecture**: Separates deterministic API reference generation (Layer 1) from LLM-driven narrative generation (Layer 2), ensuring accuracy in the API docs while allowing flexibility in the guides.
2.  **Incremental Updates**: Uses file hashing to only regenerate documentation pages that have changed, improving performance for large repositories.
3.  **Verification**: Includes multiple verification passes (`verify`, `surgical_verify`, `grounding`) to ensure that generated documentation accurately reflects the source code.
4.  **AI-Ready Output**: Generates `llms.txt` and `SKILL.md` files to make the documentation easily consumable by AI agents and coding assistants.

By adhering to these principles, `repoquill` provides a robust and flexible foundation for automated documentation generation in software projects.

### See Also

*   [Key Ideas](key-ideas.md)
