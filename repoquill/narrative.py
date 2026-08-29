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
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

from repoquill.llm import strip_code_fences
from repoquill.plan import page_needs_regeneration
from repoquill.reference import (
    extract_api_surface,
    extract_cli_surface,
    extract_constructor_signatures,
    extract_member_bodies,
    get_examples_context,
    get_file_tree,
    get_source_files,
    get_tests_context,
)


_CONTAINER_DUNDERS = frozenset({
    "__iter__", "__getitem__", "__len__", "__contains__",
    "__next__", "__reversed__", "__setitem__", "__delitem__",
})


def _enrich_container_protocols(content: str, pkg_path: str) -> str:
    """Deterministically document container-protocol capabilities.

    The LLM frequently omits iteration, indexing, and length behavior
    for classes that define ``__iter__``, ``__getitem__``, ``__len__``,
    etc., because these are dunder methods and the LLM does not connect
    them to user-facing capabilities.  This pass scans the generated
    markdown for class names that appear in the API surface with
    container protocols, and appends a deterministic note about the
    iteration/indexing/length behavior if the content does not already
    mention it.

    This is generic: any Python package with collection types benefits.
    The extraction is AST-derived and deterministic.
    """
    try:
        surface = extract_api_surface(pkg_path)
    except Exception:  # noqa: BLE001
        return content

    # Parse the API surface to find classes with container protocols.
    # Format: "  module.ClassName: methods  [PROPERTIES: ...]  [CONTAINER PROTOCOLS: __iter__, __len__]"
    import re
    class_protocols = {}  # class_name -> list of protocol names
    for line in surface.split("\n"):
        m = re.match(r"\s+[\w.]+\.(\w+):.*\[CONTAINER PROTOCOLS: ([^\]]+)\]", line)
        if m:
            class_name = m.group(1)
            protocols = [p.strip() for p in m.group(2).split(",")]
            class_protocols[class_name] = protocols

    if not class_protocols:
        return content

    # For each class with container protocols that is mentioned in the
    # content, check if iteration/indexing/length is already documented.
    # If not, append a deterministic note.
    additions = []
    for class_name, protocols in sorted(class_protocols.items()):
        if class_name not in content:
            continue  # Class not mentioned on this page; skip.

        # Check if the content already documents the relevant behavior.
        # We look for explicit capability statements near the class name.
        # Generic phrases like "for each" are too common in technical
        # writing to be a reliable signal of iteration documentation.
        # We require the phrase to be within 200 chars of the class name.
        already_documented = False
        for proto in protocols:
            # Find the first occurrence of the class name in the content.
            idx = content.find(class_name)
            if idx < 0:
                continue
            # Look at a 200-char window around the class name.
            window = content[max(0, idx - 100):idx + 200].lower()
            if proto == "__iter__" and (
                "iterable" in window
                or "iteration" in window
                or "can be iterated" in window
                or "iterate over" in window
            ):
                already_documented = True
                break
            if proto == "__getitem__" and (
                "index access" in window
                or "getitem" in window
                or "indexed by" in window
                or "supports [" in window
            ):
                already_documented = True
                break
            if proto == "__len__" and (
                "len(" in window
                or "supports len" in window
            ):
                already_documented = True
                break

        if already_documented:
            continue

        # Build a deterministic note about the container capabilities.
        caps = []
        if "__iter__" in protocols:
            caps.append("can be iterated with `for`")
        if "__getitem__" in protocols:
            caps.append("supports index access with `[]`")
        if "__len__" in protocols:
            caps.append("supports `len()`")
        if "__contains__" in protocols:
            caps.append("supports `in` membership testing")

        if caps:
            note = (
                f"\n\n**Container capabilities:** `{class_name}` "
                f"{' and '.join(caps)}.\n"
            )
            additions.append(note)

    if not additions:
        return content

    return content + "".join(additions)


def determine_structure(cfg, client) -> List[dict]:
    """Plan the narrative documentation structure.

    When ``cfg.narrative_sections`` is defined, the page slugs are taken
    directly from the config (deterministic).  The LLM is then asked only
    to assign ``source_files`` to each page, so the page *names* are
    reproducible across runs while the *content mapping* is still
    LLM-informed.

    When ``cfg.narrative_sections`` is empty, the LLM plans the full
    structure (title, slug, description, source_files) as before.

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

    # --- Deterministic path: narrative_sections defines exact slugs ---
    if cfg.narrative_sections:
        # Build the fixed page list from config
        fixed_pages = []
        for sec in cfg.narrative_sections:
            title = sec.get("title", "")
            slugs = sec.get("slugs", [])
            for slug in slugs:
                fixed_pages.append({
                    "title": title,
                    "slug": slug,
                    "description": "",
                    "source_files": [],
                })

        # Ask the LLM to assign source_files to each fixed page
        slug_lines = "\n".join(
            f'  - slug: "{p["slug"]}" (title: {p["title"]})'
            for p in fixed_pages
        )
        prompt = f"""You are a technical documentation architect. Given this Python project's file tree and README, assign source files and a one-line description to each documentation page below.

FILE TREE:
{tree}

README (excerpt):
{readme}

FIXED PAGES (these are the exact pages that will be generated — do NOT add or remove any):
{slug_lines}

For each page, provide:
1. source_files: the source files (relative paths) that page should cover
2. description: a one-line description (max 80 chars) that tells a developer what they'll learn on this page

Return a JSON array with one entry per page, in the same order:
{{"slug": "kebab-case-slug", "source_files": ["relative/path.py", ...], "description": "One-line description"}}

Rules:
- Return exactly {len(fixed_pages)} entries, one per page listed above
- source_files lists which files each page should draw from
- description should be specific and useful (e.g. "Set up your first audit in 5 minutes"), not generic (e.g. "Getting started guide")
- Be specific and practical for developers who need to USE this library
- Return ONLY the JSON array, no markdown fences"""

        result = client.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=2048,
            temperature=getattr(cfg.llm, "plan_temperature", 0.1),
        )
        try:
            assignments = json.loads(strip_code_fences(result))
        except (json.JSONDecodeError, ValueError):
            assignments = []

        # Merge LLM-assigned source_files and descriptions into the fixed page list
        by_slug = {a.get("slug", ""): a for a in assignments}
        for p in fixed_pages:
            a = by_slug.get(p["slug"], {})
            p["source_files"] = a.get("source_files", [])
            p["description"] = a.get("description", "")
            # Give each page a better title (human-readable from slug)
            p["title"] = p["slug"].replace("-", " ").title()

        return fixed_pages

    # --- LLM-planned path: no narrative_sections defined ---
    prompt = f"""You are a technical documentation architect. Given this Python project's file tree and README, plan a developer documentation structure.

FILE TREE:
{tree}

README (excerpt):
{readme}

Return a JSON array of documentation pages. Each entry: {{"title": "Page Title", "slug": "kebab-case-slug", "description": "One-line description", "source_files": ["relative/path.py", ...]}}

Rules:
- source_files lists which files each page should cover
- Be specific and practical for developers who need to USE this library
- Return ONLY the JSON array, no markdown fences"""

    result = client.chat(
        [{"role": "user", "content": prompt}],
        max_tokens=2048,
        temperature=getattr(cfg.llm, "plan_temperature", 0.1),
    )
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
    llm = cfg.llm

    per_file = getattr(llm, "per_file_budget", 12000)
    total_budget = getattr(llm, "context_budget", 60000)

    code_context = ""
    for f in files:
        if f in source_files:
            content = source_files[f]
            if len(content) > per_file:
                content = content[:per_file] + "\n# ... (truncated)"
            code_context += f"\n### {f}\n```\n{content}\n```\n"

    if len(code_context) > total_budget:
        code_context = code_context[:total_budget] + "\n# ... (context truncated)"

    # --- Ground-truth enrichment blocks (all generic, AST/FS-derived) ---
    api_surface = ""
    if getattr(llm, "include_api_surface", True):
        try:
            api_surface = extract_api_surface(cfg.pkg_path)
        except Exception:  # noqa: BLE001
            api_surface = ""

    readme = ""
    if getattr(llm, "include_readme", True):
        readme_path = os.path.join(cfg.root, "README.md")
        if os.path.exists(readme_path):
            with open(readme_path, "r", encoding="utf-8", errors="replace") as f:
                readme = f.read()[:3000]

    examples = ""
    if getattr(llm, "include_examples", True):
        try:
            examples = get_examples_context(cfg.root)
        except Exception:  # noqa: BLE001
            examples = ""

    # --- E16: tests as behavioral ground truth ---
    tests_ctx = ""
    if getattr(llm, "include_tests", False):
        try:
            tests_ctx = get_tests_context(cfg.root)
        except Exception:  # noqa: BLE001
            tests_ctx = ""

    # --- CLI surface (E2): inject for CLI-related pages only ---
    cli_surface = ""
    if getattr(llm, "include_api_surface", True):
        slug_lower = page["slug"].lower()
        title_lower = title.lower()
        if any(kw in slug_lower or kw in title_lower
               for kw in ("cli", "command", "terminal", "shell", "command-line")):
            try:
                cli_surface = extract_cli_surface(cfg.pkg_path)
            except Exception:  # noqa: BLE001
                cli_surface = ""

    # --- E14: page-relevant constructor signatures ---
    # The LLM writes code examples that construct objects.  If it does
    # not see the exact __init__ signature in context, it invents
    # kwarg names (the dominant E12 `invalid_kwarg` finding type).
    # We extract signatures for ALL public classes in the package
    # (deterministic, AST-derived, ~2-4KB for a typical package).
    # This is generic: any repo benefits; the extraction is empty for
    # packages with no classes.
    ctor_sigs = ""
    if getattr(llm, "include_api_surface", True):
        try:
            import ast as _ast
            all_classes = set()
            for _dir, _, _fns in os.walk(cfg.pkg_path):
                for _fn in _fns:
                    if not _fn.endswith(".py"):
                        continue
                    try:
                        _tree = _ast.parse(
                            open(os.path.join(_dir, _fn), encoding="utf-8",
                                 errors="replace").read()
                        )
                        for _n in _ast.walk(_tree):
                            if isinstance(_n, _ast.ClassDef) \
                                    and not _n.name.startswith("_"):
                                all_classes.add(_n.name)
                    except (SyntaxError, OSError):
                        continue
            if all_classes:
                ctor_sigs = extract_constructor_signatures(
                    cfg.pkg_path, all_classes
                )
        except Exception:  # noqa: BLE001
            ctor_sigs = ""

    # --- E36/E41: page-relevant member source bodies ---
    # The API surface lists member names and signatures, and constructor
    # signatures give exact __init__ parameters, but neither includes the
    # function body.  When the LLM writes prose about a member (e.g.
    # "``passed`` returns a list of scenario names that passed"), it
    # infers the return value from the name — the dominant source of
    # C-hallucination.  We extract source bodies for the members the page
    # is likely to discuss (deterministic, AST-derived, capped at 40 lines
    # each).  This is generic: any repo benefits; the extraction is empty
    # for packages with no public methods.
    #
    # E41: page-conditional injection.  E36 injected ALL member bodies
    # into every page (~40K chars of the 60K context budget), crowding
    # out the page's own source files.  Now we inject only bodies for
    # members whose names appear in this page's assigned source files —
    # the members this page is actually about.  Container-protocol
    # dunders (__iter__, __getitem__, __len__, etc.) are included
    # because they define iteration, indexing, and length semantics that
    # are essential for documenting collection types.
    member_bodies = ""
    if getattr(llm, "include_api_surface", True):
        try:
            import ast as _ast
            in_scope = set()
            for _f in files:
                _content = source_files.get(_f)
                if not _content:
                    continue
                try:
                    _tree = _ast.parse(_content)
                except (SyntaxError, ValueError):
                    continue
                for _n in _ast.walk(_tree):
                    if isinstance(_n, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                        if not _n.name.startswith("_") or _n.name in _CONTAINER_DUNDERS:
                            in_scope.add(_n.name)
            if in_scope:
                member_bodies = extract_member_bodies(
                    cfg.pkg_path, in_scope, max_lines=40, max_chars=40000
                )
        except Exception:  # noqa: BLE001
            member_bodies = ""

    existing_path = os.path.join(cfg.out_guides, f"{page['slug']}.md")
    old_content = ""
    if os.path.exists(existing_path):
        with open(existing_path, "r") as f:
            old_content = f.read()

    # Extract project tagline from config for context anchoring
    tagline = cfg.index.get("tagline", "").strip()
    tagline_block = f"\nPROJECT CONTEXT: {cfg.project_name} is: {tagline}\n" if tagline else ""

    strict = getattr(llm, "strict_prompt", True)

    if strict:
        rules_block = """ABSOLUTE RULES (violating any of them makes the document useless):
1. NEVER invent a class, function, method, parameter, CLI flag, environment variable, or configuration option that is not present in the source code or API surface you were given.
2. Every code example MUST use only symbols (classes, functions, parameters) that appear verbatim in the REAL API SURFACE list or the source code.
3. If you are not sure whether something exists in the source, DO NOT write it. Omit it instead.
4. Do not describe behavior you cannot see in the source. No speculation about internals.
5. If the source does not contain the entry point you need for an example, say so explicitly instead of inventing one.
6. Prefer fewer, verified claims over more, plausible-sounding ones.
7. PROPERTIES (marked [PROPERTIES: ...] in the API surface) are attributes, NOT methods. Use them as `obj.name`, never as `obj.name()`.
8. When documenting configuration keys, only list keys that the source code actually reads from the config (e.g. `config.get("key_name")`). If multiple similar keys exist, note which one is authoritative (the one the source actually reads) and which, if any, is an alternative or legacy key. Do not list both without clarification.
"""
    else:
        rules_block = ""

    enrichment = ""
    if cli_surface:
        enrichment += (
            f"\nREAL CLI SURFACE (extracted from argparse — the ONLY commands and flags that exist):\n"
            f"{cli_surface}\n"
            f"CRITICAL: The CLI has EXACTLY the commands and flags listed above. "
            f"Do NOT invent additional commands, subcommands, or flags. "
            f"Do NOT describe the CLI as doing anything it does not do.\n"
        )
    if api_surface:
        enrichment += f"\nREAL API SURFACE (extracted from source — the only symbols that exist):\n{api_surface}\n"
    if ctor_sigs:
        enrichment += (
            f"\nEXACT CONSTRUCTOR SIGNATURES (use these parameter names and order verbatim "
            f"in any code example that constructs these objects):\n"
            f"{ctor_sigs}\n"
        )
    if member_bodies:
        enrichment += (
            f"\nSOURCE BODIES (ground truth for behavior — what these members "
            f"actually do, return, and accept; when you describe a member's "
            f"behavior, return value, or side effects, base it on this body, "
            f"NOT on what the name suggests):\n"
            f"{member_bodies}\n"
        )
        if any(d in member_bodies for d in ("__iter__", "__getitem__", "__len__")):
            enrichment += (
                "\nNOTE: The source bodies above include container-protocol "
                "methods (__iter__, __getitem__, __len__, etc.). When a class "
                "defines these, document its iteration and indexing behavior "
                "explicitly (e.g. 'can be iterated with for', 'supports "
                "index access with []', 'supports len()'). Do not omit these "
                "capabilities just because they are dunder methods.\n"
            )
    if readme:
        enrichment += f"\nREADME (excerpt):\n{readme}\n"
    if examples:
        enrichment += f"\nEXAMPLES FROM THE REPO (real example files — prefer their patterns):\n{examples}\n"
    if tests_ctx:
        enrichment += (
            f"\nTESTS (ground truth for behavior — verify your behavioral claims "
            f"against these; if a test asserts something, the doc may state it):\n"
            f"{tests_ctx}\n"
        )

    if old_content:
        prompt = f"""You are a senior technical writer maintaining developer documentation for the {cfg.project_name} Python library.
{tagline_block}
A documentation page already exists. The source code it documents has changed.
Your job is to UPDATE the existing page to reflect the current source code.
{rules_block}
EXISTING PAGE (keep as much of this as still accurate):
<existing_page>
{old_content}
</existing_page>
{enrichment}
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
{rules_block}
{enrichment}
SOURCE CODE CONTEXT:
{code_context}

REQUIREMENTS:
- Write in clear, professional technical English
- The documentation MUST accurately reflect what the source code actually does. Do NOT invent functionality that is not present in the code.
- Include a brief overview of what this module/subsystem does
- Document all public classes, functions, and their parameters that appear in the source above
- Include code examples showing how to use the API — ONLY using symbols from the REAL API SURFACE list. If an example needs a symbol not in the list, do not write that example.
- Use proper Markdown with headers (##, ###), code blocks, and tables where appropriate
- Reference specific class names, function names, and file paths
- If the source shows configuration options or environment variables, document them exactly as they appear
- Keep it practical: a developer should be able to use the library after reading this page
- Start with a ## {title} header
- Do NOT include a title (# header) - just start with ##
- Length: 800-2000 words depending on complexity

Return ONLY the markdown content, no preamble."""

    # Temperature: conservative for updates (preserve existing content),
    # configurable for new pages. max_tokens: enough for a full doc page.
    temp = getattr(llm, "update_temperature", 0.3) if old_content \
        else getattr(llm, "temperature", 0.7)
    content = client.chat(
        [{"role": "user", "content": prompt}],
        max_tokens=getattr(llm, "max_tokens", 8192),
        temperature=temp,
    )
    return content


def _generate_single_page(
    page: dict,
    source_files: Dict[str, str],
    client,
    cfg,
) -> tuple:
    """Generate a single page. Returns (slug, success, message)."""
    slug = page["slug"]
    title = page["title"]
    out_path = os.path.join(cfg.out_guides, f"{slug}.md")
    try:
        content = generate_page(page, source_files, client, cfg)
        with open(out_path, "w") as f:
            f.write(content)
        return (slug, True, f"OK ({len(content)} chars)")
    except Exception as e:  # noqa: BLE001
        return (slug, False, f"FAILED: {e}")


def generate_all_pages(
    pages: List[dict],
    source_files: Dict[str, str],
    client,
    cfg,
    old_hashes: Dict[str, str],
    new_hashes: Dict[str, str],
) -> List[str]:
    """Generate all narrative pages that need regeneration.

    Uses parallel execution when cfg.llm.max_concurrent > 1.

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
    
    # Filter pages that need regeneration
    to_generate = []
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
        to_generate.append((i, page, reason))

    if not to_generate:
        return []

    max_workers = max(1, cfg.llm.max_concurrent)
    generated: List[str] = []

    if max_workers == 1:
        # Sequential execution (default)
        for i, page, reason in to_generate:
            title = page["title"]
            print(f"  [{i + 1}/{len(pages)}] {title} ({reason})...", end=" ", flush=True)
            slug, success, msg = _generate_single_page(page, source_files, client, cfg)
            print(msg)
            if success:
                generated.append(slug)
    else:
        # Parallel execution
        print(f"  Generating {len(to_generate)} pages with {max_workers} workers...")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_generate_single_page, page, source_files, client, cfg): (i, page)
                for i, page, reason in to_generate
            }
            for future in as_completed(futures):
                i, page = futures[future]
                title = page["title"]
                slug, success, msg = future.result()
                print(f"  [{i + 1}/{len(pages)}] {title}: {msg}")
                if success:
                    generated.append(slug)

    return generated
