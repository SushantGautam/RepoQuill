## Architecture

RepoQuill is a two-layer documentation generator for Python packages. It combines deterministic static analysis with LLM-driven narrative generation to produce a complete, accurate documentation site. The system is designed to minimize hallucinations by grounding LLM outputs in verified source code symbols and maintaining an incremental update pipeline that only regenerates content when source files change.

### Core Components

The architecture is divided into four primary modules: `config`, `llm`, `reference`, `narrative`, `plan`, `verify`, `site`, and `cli`. Each module handles a specific stage of the documentation pipeline.

#### Configuration (`config`)

Configuration is managed via `RepoQuillConfig` and `LLMConfig` classes. These classes do not have custom `__init__` methods, implying they are likely populated via dataclass defaults or external loading mechanisms.

- **`RepoQuillConfig`**: Holds site-level metadata.
  - **Properties**: `site_name`, `site_url`, `repo_url`, `repo_name`.
  - **Function**: `load_config(config_path)` loads the configuration from a YAML file (typically `repoquill.yml`).

#### LLM Interaction (`llm`)

This module handles communication with Large Language Models and local retrieval-augmented generation (RAG).

- **`LLMClient`**:
  - **Constructor**: `LLMClient(llm_cfg)` where `llm_cfg` is an `LLMConfig` instance.
  - **Method**: `chat(messages, max_tokens, temperature, retries)`. This is the primary interface for generating text.
  - **Helper**: `strip_code_fences(text)` removes Markdown code fence markers from LLM output.
- **`LocalRAG`**:
  - **Constructor**: `LocalRAG(rag_cfg: Dict[str, Any], source_files: Dict[str, str])`.
  - **Methods**:
    - `build()`: Prepares the local retrieval index.
    - `retrieve(query, top_k)`: Retrieves relevant source code snippets for a given query.

#### Reference Generation (`reference`)

This module implements **Layer 1** of the architecture: deterministic API reference generation. It parses the target Python package to extract the API surface without using an LLM.

- **`extract_api_surface(pkg_path, max_chars)`**: Extracts the public API surface from the package source.
- **`extract_cli_surface(pkg_path, max_chars)`**: Extracts CLI command definitions.
- **`extract_constructor_signatures(pkg_path, names, max_chars)`**: Extracts exact constructor signatures for specified classes.
- **`extract_member_bodies(pkg_path, names, max_lines, max_chars)`**: Extracts method bodies for documentation.
- **`get_source_files(pkg_path)`**: Lists all source files in the package.
- **`get_file_tree(pkg_path)`**: Generates a file tree structure for the package.
- **`get_examples_context(root, max_chars)`**: Extracts context from example files for documentation generation.
- **`get_tests_context(root, max_chars)`**: Extracts context from test files for documentation generation.
- **`build_api_reference(cfg)`**: Renders the final API reference pages using the extracted data.
- **`render_module_reference(module_name, search_path, module_descriptions)`**: Renders a specific module's reference.

#### Narrative Generation (`narrative`)

This module implements **Layer 2**: LLM-driven guide generation. It uses the API surface and source code to write conceptual guides (e.g., Quickstart, Concepts).

- **`determine_structure(cfg, client)`**: Uses the LLM to determine the structure of the documentation site (e.g., which guide pages to create).
- **`generate_page(page, source_files, client, cfg)`**: Generates the content for a single documentation page.
- **`generate_all_pages(pages, source_files, client, cfg, old_hashes, new_hashes)`**: Orchestrates the generation of all pages, utilizing hash comparisons for incremental updates.

#### Planning and Incremental Updates (`plan`)

To ensure efficiency, RepoQuill tracks file hashes to determine which pages need regeneration.

- **`compute_file_hashes(source_files)`**: Computes hashes for all source files.
- **`load_plan(plan_file)`**: Loads the previous run's plan (hashes and page slugs).
- **`store_plan(plan_file, pages, file_hashes)`**: Saves the current plan for the next run.
- **`page_needs_regeneration(page, old_hashes, new_hashes, out_path)`**: Determines if a specific page's source dependencies have changed.
- **`cleanup_stale_pages(plan_slugs, guides_dir)`**: Removes documentation pages that no longer correspond to valid source structures.

#### Verification (`verify` and `surgical_verify`)

Accuracy is enforced through a verification pass that checks generated documentation against the actual source code.

- **`verify` module**:
  - **`build_index(pkg_path)`**: Builds a `SymbolIndex` of all valid symbols in the package.
  - **`check_page(page_md, idx, pkg_name)`**: Validates a single Markdown page against the symbol index.
  - **`check_all(guides_dir, idx, pkg_name)`**: Validates all pages in the guides directory.
  - **`extract_backtick_symbols(md)`**, **`extract_code_blocks(md)`**, **`extract_imports(md)`**, **`extract_method_calls(md)`**: Helper functions to parse Markdown content for verification.
  - **`fix_type_claims(content, pkg_path)`**: Corrects type claims in the documentation if they mismatch the source.
  - **`verify_pages(cfg, client)`**: Orchestrates the verification process, potentially using the LLM to fix errors.
- **`surgical_verify` module**:
  - **`build_class_index(pkg_path)`**: Builds a specific index for class verification.
  - **`run_surgical_verify(guide_dir, pkg_path)`**: Runs a targeted verification pass.
  - **`fix_missing_required(text, classes)`**: Fixes missing required parameters in code examples.
  - **`fix_property_calls(text, classes)`**: Ensures properties are accessed as attributes (`obj.name`) rather than methods (`obj.name()`).

#### Site Building (`site`)

This module assembles the final MkDocs site structure.

- **`build_nav(cfg, pages, reference_modules)`**: Constructs the navigation structure for MkDocs.
- **`build_mkdocs_yml(cfg, nav)`**: Generates the `mkdocs.yml` configuration file.
- **`build_index_md(cfg, pages, reference_modules)`**: Generates the main `index.md` page.
- **`build_llms_txt(cfg, pages, reference_modules)`**: Generates `llms.txt` for AI agent consumption.
- **`build_llms_full_txt(cfg, pages, reference_modules)`**: Generates `llms-full.txt`.
- **`build_skill_md(cfg)`**: Generates `SKILL.md` for coding agents.
- **`cross_link_guides(cfg, pages)`**: Adds internal cross-links between guide pages.

#### Grounding (`grounding`)

- **`run_grounding_pass(guides_dir, pkg_path, client, llm_cfg, max_findings_per_page)`**: Performs a final pass to ensure all LLM-generated content is grounded in the source code, limiting the number of findings per page to prevent overwhelming the user.

### CLI Entry Point

The `cli` module provides the command-line interface.

- **`main(argv)`**: The main entry point for the `repoquill` command.
- **Constants**:
  - `_CONFIG_TEMPLATE`: The template for `repoquill.yml`.
  - `_FEATURED_PROVIDERS`: List of supported LLM providers (e.g., `openai`, `anthropic`, `github_copilot`, `openrouter`).
  - `_LOCAL_PROVIDERS`: Set of local providers (`lm_studio`, `local`, `ollama`, `vllm`).
  - `_OAUTH_PROVIDERS`: Set of providers requiring OAuth (`github_copilot`).
  - `_WORKFLOW_TEMPLATE`: The template for the GitHub Actions workflow file.

### Data Flow

1. **Initialization**: `cli.main` parses arguments, loads `repoquill.yml` via `config.load_config`, and sets up the `LLMClient`.
2. **Reference Extraction**: `reference.extract_api_surface` and related functions parse the target package to build a deterministic API reference.
3. **Planning**: `plan.compute_file_hashes` compares current source hashes with the previous plan to identify changed files.
4. **Narrative Generation**: `narrative.determine_structure` and `narrative.generate_all_pages` use the LLM to write guides, only regenerating pages where source changes occurred.
5. **Verification**: `verify.check_all` and `surgical_verify.run_surgical_verify` validate the generated Markdown against the `SymbolIndex` to ensure no hallucinated symbols or incorrect property usage.
6. **Site Assembly**: `site.build_mkdocs_yml`, `site.build_nav`, and other site builders assemble the final MkDocs structure, including `llms.txt` and `SKILL.md`.
7. **Output**: The generated site is written to the output directory, ready for deployment via MkDocs.

This architecture ensures that the documentation is both comprehensive (via LLM narratives) and accurate (via deterministic reference generation and verification).

### See Also

*   [Key Ideas](key-ideas.md)
