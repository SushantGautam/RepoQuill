"""Layer 2: LLM-generated narrative guide pages (incremental).

Generates/updates the narrative documentation pages (getting started,
architecture, guides, examples) by sending source-code context to the LLM.

Incremental behavior (driven by :mod:`repoquill.plan`):
    - A page is only (re)generated when one of its source files changed.
    - When updating, the existing page is passed to the LLM so only
      outdated sections are edited.
    - Stale pages are deleted.

The LLM is called through :class:`repoquill.llm.LLMClient`, so this module
is provider-agnostic.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List

from repoquill.llm import strip_code_fences
from repoquill.plan import page_needs_regeneration
from repoquill.reference import get_file_tree, get_source_files


def determine_structure(cfg, client) -> List[dict]:
    """Ask the LLM to plan the narrative documentation structure.

    Sends the package file tree and README excerpt to the LLM and asks
    for a JSON array of page dicts (title, slug, description,
    source_files).

    Args:
        cfg: A :class:`repoquill.config.RepoQuillConfig`.
        client: An :class:`repoquill.llm.LLMClient`.

    Returns:
        List of page dicts.
    """
    tree = get_file_tree(cfg.pkg_path)
    readme_path = os.path.join(cfg.root, "README.md")
    readme = ""
    if os.path.exists(readme_path):
        with open(readme_path, "r", encoding="utf-8", errors="replace") as f:
            readme = f.read()[:3000]

    prompt = f"""You are a technical documentation architect. Given this Python project's file tree and README, plan a developer documentation structure.

FILE TREE:
{tree}

README (excerpt):
{readme}

Return a JSON array of documentation pages. Each entry: {{"title": "Page Title", "slug": "kebab-case-slug", "description": "One-line description", "source_files": ["relative/path.py", ...]}}

Rules:
- 8-12 narrative pages total (the API reference is generated separately — do NOT include an api-reference page)
- Must include: Getting Started, Core Architecture, CLI Usage (if applicable), and pages covering the major subsystems
- source_files lists which files each page should cover
- Be specific and practical for developers who need to USE this library
- Return ONLY the JSON array, no markdown fences"""

    result = client.chat([{"role": "user", "content": prompt}],
                         max_tokens=2048, temperature=0.1)
    pages = json.loads(strip_code_fences(result))
    return pages


def generate_page(
    page: dict,
    source_files: Dict[str, str],
    client,
    cfg,
) -> str:
    """Generate or update a single narrative documentation page.

    Builds a prompt from the page's source files (and optionally RAG
    context), calls the LLM, and returns the markdown.

    Args:
        page: Page dict (slug, title, description, source_files).
        source_files: Mapping of file path to content.
        client: An :class:`repoquill.llm.LLMClient`.
        cfg: A :class:`repoquill.config.RepoQuillConfig`.

    Returns:
        The generated/updated markdown page content.
    """
    title = page["title"]
    desc = page.get("description", "")
    files = page.get("source_files", [])

    code_context = ""
    for f in files:
        if f in source_files:
            content = source_files[f]
            if len(content) > 12000:
                content = content[:12000] + "\n# ... (truncated)"
            code_context += f"\n### {f}\n```\n{content}\n```\n"

    if len(code_context) > 60000:
        code_context = code_context[:60000] + "\n# ... (context truncated)"

    existing_path = os.path.join(cfg.out_guides, f"{page['slug']}.md")
    old_content = ""
    if os.path.exists(existing_path):
        with open(existing_path, "r") as f:
            old_content = f.read()

    # Extract project tagline from config for context anchoring
    tagline = cfg.index.get("tagline", "").strip()
    tagline_block = f"\nPROJECT CONTEXT: {cfg.project_name} is: {tagline}\n" if tagline else ""

    if old_content:
        prompt = f"""You are a senior technical writer maintaining developer documentation for the {cfg.project_name} Python library.
{tagline_block}
A documentation page already exists. The source code it documents has changed.
Your job is to UPDATE the existing page to reflect the current source code.

EXISTING PAGE (keep as much of this as still accurate):
<existing_page>
{old_content}
</existing_page>

CURRENT SOURCE CODE:
{code_context}

INSTRUCTIONS:
- Compare the existing page against the current source code.
- ONLY change sections that are now inaccurate, outdated, or incomplete.
- Preserve the existing structure, tone, headings, and examples that are still correct.
- Add documentation for any new public classes, functions, or parameters.
- Remove or update documentation for anything that no longer exists.
- Do NOT reword or restructure sections that are still accurate.
- Do NOT add new sections unless the source code introduces genuinely new functionality.
- Keep the same Markdown formatting style (## headers, code blocks, tables).
- Start with a ## {title} header. Do NOT include a # title header.

Return ONLY the complete updated markdown page, no preamble."""
    else:
        prompt = f"""You are a senior technical writer generating developer documentation for the {cfg.project_name} Python library.
{tagline_block}
Write a complete documentation page titled "{title}".
Description: {desc}

SOURCE CODE CONTEXT:
{code_context}

REQUIREMENTS:
- Write in clear, professional technical English
- The documentation MUST accurately reflect what the source code actually does. Do NOT invent functionality that is not present in the code.
- Include a brief overview of what this module/subsystem does
- Document all public classes, functions, and their parameters
- Include code examples showing how to use the API
- Use proper Markdown with headers (##, ###), code blocks, and tables where appropriate
- Reference specific class names, function names, and file paths
- If the source shows configuration options, document them
- Keep it practical: a developer should be able to use the library after reading this page
- Start with a ## {title} header
- Do NOT include a title (# header) - just start with ##
- Length: 800-2000 words depending on complexity

Return ONLY the markdown content, no preamble."""

    content = client.chat(
        [{"role": "user", "content": prompt}],
        max_tokens=8192,
        temperature=0.3 if old_content else 0.7,
    )
    return content


def generate_all_pages(
    pages: List[dict],
    source_files: Dict[str, str],
    client,
    cfg,
    old_hashes: Dict[str, str],
    new_hashes: Dict[str, str],
) -> List[str]:
    """Generate all narrative pages that need regeneration.

    Args:
        pages: List of page dicts.
        source_files: Mapping of file path to content.
        client: An :class:`repoquill.llm.LLMClient`.
        cfg: A :class:`repoquill.config.RepoQuillConfig`.
        old_hashes: Hashes from the previous plan.
        new_hashes: Hashes of the current source files.

    Returns:
        List of slugs that were (re)generated.
    """
    os.makedirs(cfg.out_guides, exist_ok=True)
    generated: List[str] = []
    for i, page in enumerate(pages):
        slug = page["slug"]
        title = page["title"]
        out_path = os.path.join(cfg.out_guides, f"{slug}.md")

        if not page_needs_regeneration(page, old_hashes, new_hashes, out_path):
            print(f"  [{i + 1}/{len(pages)}] {title} — SKIP (source unchanged)")
            continue

        changed = [f for f in page.get("source_files", [])
                   if old_hashes.get(f) != new_hashes.get(f)]
        reason = f"changed: {', '.join(changed)}" if changed else "new page"
        print(f"  [{i + 1}/{len(pages)}] {title} ({reason})...", end=" ", flush=True)
        try:
            content = generate_page(page, source_files, client, cfg)
            with open(out_path, "w") as f:
                f.write(content)
            print(f"OK ({len(content)} chars)")
            generated.append(slug)
        except Exception as e:  # noqa: BLE001
            print(f"FAILED: {e}")
    return generated
