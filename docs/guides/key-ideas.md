## Key Ideas

**repoquill** is a Python library designed to generate, manage, and version technical documentation directly from source code repositories. It operates as a generic two-layer developer-docs generator:

1.  **Layer 1 — API Reference (Deterministic):** Uses `Griffe` to parse source code and `mkdocstrings` to render classes, functions, signatures, and docstrings. This layer is fast, free, and does not rely on LLMs.
2.  **Layer 2 — Narrative Guides (LLM):** Uses `LiteLLM` to write conceptual guide pages (quickstart, concepts, workflows) grounded in the actual source code. This layer is incremental, regenerating only pages whose source files have changed.
3.  **Output:** A polished MkDocs Material site, including `llms.txt` / `llms-full.txt` for AI agents and a `SKILL.md` for coding agents.

The library is built upon three fundamental abstractions: **Configuration**, **LLM Interaction**, and **Site Generation**. These concepts work together to decouple the source of truth (the code) from the final output format, allowing developers to maintain a single configuration file (`repoquill.yml`) while targeting a complete documentation site.

### 1. Configuration

At the heart of `repoquill` is the `RepoQuillConfig` class. This abstraction allows the library to ingest project-specific settings from a `repoquill.yml` file without coupling the core engine to specific file systems or version control systems.

The primary implementation is `RepoQuillConfig`, which holds the site metadata and repository details. It exposes the following properties:
*   `site_name`: The name of the documentation site.
*   `site_url`: The base URL of the deployed site.
*   `repo_url`: The URL of the source code repository.
*   `repo_name`: The name of the repository.

```python
from repoquill.config import RepoQuillConfig, LLMConfig, load_config

# Load configuration from a YAML file
cfg = load_config("repoquill.yml")

# Access configuration properties
print(cfg.site_name)
print(cfg.repo_url)
```

**Design Pattern:** The *Configuration Object* pattern is employed here. By defining a common `RepoQuillConfig` interface, `repoquill` can swap out the data retrieval mechanism (YAML, JSON, etc.) at runtime without altering the downstream processing logic.

### 2. LLM Interaction

Documentation narrative generation requires interaction with Large Language Models. `repoquill` models this process through the `LLMClient` and `LocalRAG` classes.

#### The `LLMClient`

The `LLMClient` class serves as the interface for communicating with LLM providers. It encapsulates the logic for sending messages and handling responses.

```python
from repoquill.llm import LLMClient
from repoquill.config import LLMConfig

# Initialize the client with LLM configuration
llm_cfg = LLMConfig()
client = LLMClient(llm_cfg
    # NOTE: llm_cfg is required (no default)
,
    # NOTE: llm_cfg is required (no default)
)

# Send a chat request
response = client.chat(
    messages=[{"role": "user", "content": "Hello"}],
    max_tokens=100,
    temperature=0.7,
    retries=3
)
```

#### Local RAG

For grounding LLM responses in local source code, `repoquill` provides the `LocalRAG` class. This class builds a retrieval-augmented generation indfrom repoquill.llm import LocalRAG

# Initialize RAG with configuration and source files
rag_cfg = {"chunk_size": 500}
source_files = {"main.py": "print('hello')"}
rag = LocalRAG(rag_cfg, source_files
    # NOTE: rag_cfg is required (no default),
    # NOTE: source_files is required (no default)
)

# Build the index
rag.build()

# Retrieve relevant context
results = rag.retrieve(query="how to print", top_k=3)
= rag.retrieve(query="how to print", top_k=3)
```

### 3. Site Generation

Once the API reference and narrative guides are generated, they need to be assembled into a documentation site. `repoquill` abstracts this through the `site` module functions.

The `build_nav` function constructs the navigation structure for the MkDocs site. The `build_index_md` function generates the main index page.

```python
from repoquill.site import build_nav, build_index_md

# Build navigation structure
nav = build_nav(cfg, pages, reference_modules)

# Build the index page
index_md = build_index_md(cfg, pages, reference_modules)
```

**Design Pattern:** The *Builder Pattern* is used here. Each function in the `site` module handles a specific aspect of the site generation (navigation, index, llms.txt) and returns the resulting content. This promotes modularity and reusability of individual generation steps.

### Core Workflow

The typical usage of `repoquill` follows a clear, linear workflow:

1.  **Initialize Config**: Load the `RepoQuillConfig` from `repoquill.yml`.
2.  **Generate API Reference**: Use `reference.build_api_reference` to create the deterministic API docs.
3.  **Generate Narrative Guides**: Use `narrative.generate_all_pages` to create LLM-generated guides.
4.  **Build Site**: Use `site` functions to assemble the final MkDocs site.

```python
from repoquill.config import load_config
from repoquill.reference import build_api_reference
from repoquill.narrative import generate_all_pages
from repoquill.site import build_nav, build_index_md

# 1. Load Config
cfg = load_config("repoquill.yml")

# 2. Generate API Reference
api_ref = build_api_reference(cfg)

# 3. Generate Narrative Guides
# Note: This requires an LLM client and source files
# pages = generate_all_pages(pages, source_files, client, cfg, old_hashes, new_hashes)

# 4. Build Site
nav = build_nav(cfg, pages, reference_modules)
index_md = build_index_md(cfg, pages, reference_modules)
```

### Configuration and Context

The `repoquill.yml` file allows global variables to be injected into the documentation generation process. This is useful for injecting build information, such as the current version number or build timestamp, into all generated documents.

```yaml
# repoquill.yml
site_name: "My Project Docs"
site_url: "https://example.com/docs"
repo_url: "https://github.com/user/repo"
repo_name: "my-project"
```

Within the `RepoQuillConfig`, these values can be accessed via properties, enabling dynamic content generation based on the project configuration.

### Error Handling and Logging

`repoquill` employs standard Python exception handling. If an LLM request fails, the `LLMClient` will raise an exception containing the original error. This allows developers to identify problematic requests without halting the entire build process if configured to continue on error.

```python
try:
    response = client.chat(messages, max_tokens, temperature, retries)
except Exception as e:
    logger.error(f"Failed to process LLM request: {e}")
```

### Summary of Key Classes

| Class | Module | Description |
| :--- | :--- | :--- |
| `RepoQuillConfig` | `repoquill.config` | Configuration object for the documentation site. |
| `LLMConfig` | `repoquill.config` | Configuration object for LLM provider settings. |
| `LLMClient` | `repoquill.llm` | Client for interacting with LLM providers. |
| `LocalRAG` | `repoquill.llm` | Retrieval-augmented generation for local source code. |
| `SymbolIndex` | `repoquill.verify` | Index of symbols for verification purposes. |

By adhering to these abstractions, `repoquill` provides a flexible, extensible framework for documentation generation that can adapt to diverse project needs while maintaining a consistent and predictable API.

### See Also

*   [Architecture](architecture.md)
*   [Quickstart](quickstart.md)
