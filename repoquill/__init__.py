"""RepoQuill — generic two-layer developer-docs generator.

Layer 1 (deterministic, no LLM):
    Griffe scans the package source tree and renders a complete,
    always-accurate API reference (classes, functions, signatures,
    docstrings) into ``site_src/reference/*.md``.

Layer 2 (LLM, via LiteLLM):
    Narrative pages (getting started, architecture, guides, examples)
    are generated/updated by an LLM with source-code context.
    Incremental: pages are only regenerated when their source files change.

Site assembly:
    ``mkdocs.yml``, nav, index, ``llms.txt`` / ``llms-full.txt``, and an
    agent ``SKILL.md`` are generated from a single ``repoquill.yml`` config.

The package is project-agnostic: all project-specific values live in the
``repoquill.yml`` config file in the consuming repository.
"""

__version__ = "0.1.0"
