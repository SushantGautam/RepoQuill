"""MkDocs site assembly.

Generates the static-site scaffolding from the config and the generated
pages:

- ``mkdocs.yml`` — the full MkDocs config (theme, plugins, nav, site
  identity), written entirely from ``repoquill.yml``.
- ``index.md`` — the landing page (deterministic, from config).
- ``nav`` — the navigation tree (guides + reference).
- ``llms.txt`` / ``llms-full.txt`` — AI-agent-friendly summaries.
- ``SKILL.md`` — an agent skill describing how to use the docs.
- Cross-linking of guide pages (related-page links).

This module uses NO LLM — it is purely deterministic assembly.
"""

from __future__ import annotations

import os
import re
from typing import List


def _read_file(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _section_modules(cfg, section_name, reference_modules):
    """Return the modules belonging to a reference section (no duplicates)."""
    for title, prefixes in _reference_sections(cfg, reference_modules):
        if title == section_name:
            return [m for m in reference_modules
                    if any(m == p or m.startswith(p + ".") for p in prefixes)]
    return []


def _narrative_sections(cfg):
    """Narrative sections as (title, slugs) tuples."""
    return [(s["title"], s["slugs"]) for s in cfg.narrative_sections]


def _reference_sections(cfg, reference_modules=None):
    """Reference sections as (title, module prefixes) tuples.

    When the config has no explicit ``reference_sections`` but reference
    modules exist, falls back to a single "API Reference" section that
    covers every documented module — so the index, nav, and llms.txt
    never show an empty API Reference block.
    """
    sections = cfg.raw.get("reference_sections") or []
    result = [(s["title"], s["modules"]) for s in sections]
    if not result and reference_modules:
        result = [("API Reference", reference_modules)]
    return result


def _module_descriptions(cfg, reference_modules=None):
    """Module descriptions: config overrides, then docstring fallback.

    Returns a dict of module name -> one-line description.  Config
    ``module_descriptions`` take precedence; any module without a config
    description falls back to its docstring (first line, truncated to 120
    chars).  When ``reference_modules`` is given, only those modules are
    described; otherwise every module name already present in the config is
    kept as-is.
    """
    descs = dict(cfg.raw.get("module_descriptions") or {})
    if not reference_modules:
        return descs
    pkg_path = cfg.pkg_path
    if not pkg_path or not os.path.isdir(pkg_path):
        return descs
    pkg_name = os.path.basename(os.path.normpath(pkg_path))
    for mod in reference_modules:
        if descs.get(mod):
            continue
        # Resolve module name to file path.
        # pkg_path IS the package root, so strip the top-level package name.
        parts = mod.split(".")
        if parts and parts[0] == pkg_name:
            parts = parts[1:]
        if not parts:
            # The package itself → its __init__.py
            path = os.path.join(pkg_path, "__init__.py")
        else:
            # Submodule: simpleaudit.cli → parts=['cli'] → pkg_path/cli.py
            # Subpackage: simpleaudit.judges → parts=['judges'] → pkg_path/judges/__init__.py
            # simpleaudit.judges.safety → parts=['judges','safety'] → pkg_path/judges/safety.py
            path = os.path.join(pkg_path, *parts[:-1], parts[-1] + ".py")
            if not os.path.isfile(path):
                # Could be a subpackage (directory with __init__.py).
                path = os.path.join(pkg_path, *parts, "__init__.py")
        if not os.path.isfile(path):
            continue
        doc = _extract_module_docstring(path)
        if doc:
            descs[mod] = doc
    return descs


def _name_to_phrase(name: str) -> str:
    """Convert a Python identifier to a readable phrase.

    ``UNG_SCENARIOS`` → ``ung scenarios``, ``AuditExperiment`` → ``audit experiment``.
    """
    import re
    # Split camelCase: AuditExperiment → Audit Experiment
    s = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
    # Split on underscores
    s = s.replace('_', ' ')
    return s.lower()[:120]


def _extract_module_docstring(path):
    """Return a one-line description for a module file.

    Fallback chain:
    1. Module docstring (first line)
    2. Leading ``#`` comment block (first non-empty line, ``#`` stripped)
    3. First top-level variable name (e.g. ``UNG_SCENARIOS`` → ``ung_scenarios``)
    Returns '' if none of the above yield a description.
    """
    import ast
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
        tree = ast.parse(source)
        # 1. Docstring
        doc = ast.get_docstring(tree)
        if doc:
            first = doc.strip().split("\n")[0].strip()
            return first[:120] if len(first) > 120 else first
        # 2. Leading # comments (skip shebang, file-path comments, blank lines)
        for line in source.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#!"):
                continue
            if stripped.startswith("#"):
                text = stripped.lstrip("#").strip()
                # Skip file-path-style comments (contain / or end in .py)
                if text and "/" not in text and not text.endswith(".py"):
                    return text[:120] if len(text) > 120 else text
                continue
            break  # first non-comment, non-blank line — stop
        # 3. First top-level name (variable, function, or class)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        return _name_to_phrase(target.id)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                return _name_to_phrase(node.name)
        return ""
    except (OSError, SyntaxError):
        return ""


def build_index_md(cfg, pages: List[dict], reference_modules: List[str]) -> None:
    """Write the ``index.md`` landing page (deterministic, from config).

    Args:
        cfg: A :class:`repoquill.config.RepoQuillConfig`.
        pages: List of narrative page dicts.
        reference_modules: List of documented module names.
    """
    page_map = {p["slug"]: p for p in pages}
    assigned = set()
    tagline = cfg.index.get("tagline", cfg.site.get("description", ""))
    quick = cfg.index.get("quick_start", {})

    lines = [
        f"# {cfg.project_name}",
        "",
        tagline.strip(),
        "",
        "## Quick Start",
        "",
    ]
    if quick.get("install"):
        lines += ["```bash", quick["install"], "```", ""]
    if quick.get("example"):
        lines += ["```python", quick["example"].rstrip(), "```", ""]
    if quick.get("cli"):
        lines += ["```bash", quick["cli"].rstrip(), "```", ""]

    lines += ["## Guides", ""]
    for section_name, slugs in _narrative_sections(cfg):
        section_pages = [page_map[s] for s in slugs if s in page_map]
        if not section_pages:
            continue
        lines.append(f"### {section_name}")
        lines.append("")
        for p in section_pages:
            lines.append(f"- [{p['title']}](guides/{p['slug']}.md) — {p.get('description', '')}")
            assigned.add(p["slug"])
        lines.append("")

    unassigned = [p for p in pages if p["slug"] not in assigned]
    if unassigned:
        lines.append("### More")
        lines.append("")
        for p in unassigned:
            lines.append(f"- [{p['title']}](guides/{p['slug']}.md) — {p.get('description', '')}")
        lines.append("")

    lines += ["## API Reference", ""]
    for section_name, _ in _reference_sections(cfg, reference_modules):
        mods = _section_modules(cfg, section_name, reference_modules)
        if not mods:
            continue
        lines.append(f"### {section_name}")
        lines.append("")
        descs = _module_descriptions(cfg, mods)
        for m in mods:
            slug = m.replace(".", "_")
            desc = descs.get(m, "")
            lines.append(f"- [`{m}`](reference/{slug}.md) — {desc}")
        lines.append("")

    content = "\n".join(lines)
    with open(os.path.join(cfg.site_src, "index.md"), "w") as f:
        f.write(content)
    print("  index.md")


def build_llms_txt(cfg, pages: List[dict], reference_modules: List[str]) -> None:
    """Write ``llms.txt`` — a concise AI-agent-friendly index.

    Args:
        cfg: A :class:`repoquill.config.RepoQuillConfig`.
        pages: List of narrative page dicts.
        reference_modules: List of documented module names.
    """
    page_map = {p["slug"]: p for p in pages}
    base = cfg.site_url.rstrip("/") if cfg.site_url else ""

    lines = [
        f"# {cfg.site_name}",
        "",
        cfg.site.get("description", ""),
        "",
        f"> {cfg.repo_url}",
        "",
        "## Guides",
        "",
    ]
    for section_name, slugs in _narrative_sections(cfg):
        section_pages = [page_map[s] for s in slugs if s in page_map]
        if not section_pages:
            continue
        for p in section_pages:
            desc = p.get("description", "")
            url = f"{base}/guides/{p['slug']}/" if base else f"guides/{p['slug']}/"
            lines.append(f"- [{p['title']}]({url}): {desc}" if desc else f"- [{p['title']}]({url})")
    lines.append("")

    lines.append("## API Reference")
    lines.append("")
    seen_modules = set()
    descs = _module_descriptions(cfg, reference_modules)
    for section_name, _ in _reference_sections(cfg, reference_modules):
        mods = _section_modules(cfg, section_name, reference_modules)
        if not mods:
            continue
        for m in mods:
            if m in seen_modules:
                continue
            seen_modules.add(m)
            slug = m.replace(".", "_")
            desc = descs.get(m, "")
            url = f"{base}/reference/{slug}/" if base else f"reference/{slug}/"
            lines.append(f"- [{m}]({url}): {desc}" if desc else f"- [{m}]({url})")
    lines.append("")

    lines.append("## Agent Skill")
    lines.append("")
    skill_url = f"{base}/SKILL.md" if base else "SKILL.md"
    lines.append(f"- [SKILL.md]({skill_url}): Agent skill for generating, maintaining, and validating this project's documentation.")
    lines.append("")

    content = "\n".join(lines)
    with open(os.path.join(cfg.site_src, "llms.txt"), "w") as f:
        f.write(content)
    print(f"  llms.txt ({len(lines)} lines)")


def build_llms_full_txt(cfg, pages: List[dict], reference_modules: List[str]) -> None:
    """Write ``llms-full.txt`` — the full docs concatenated for AI agents.

    Args:
        cfg: A :class:`repoquill.config.RepoQuillConfig`.
        pages: List of narrative page dicts.
        reference_modules: List of documented module names.
    """
    page_map = {p["slug"]: p for p in pages}
    parts = [
        f"# {cfg.site_name} — Full Documentation",
        "",
        cfg.site.get("description", ""),
        "",
        f"Source: {cfg.repo_url}",
        "",
        "=" * 60,
        "",
    ]

    # Guides
    for section_name, slugs in _narrative_sections(cfg):
        section_pages = [page_map[s] for s in slugs if s in page_map]
        if not section_pages:
            continue
        for p in section_pages:
            path = os.path.join(cfg.out_guides, f"{p['slug']}.md")
            if os.path.exists(path):
                parts.append(f"{'=' * 60}")
                parts.append(f"## {p['title']}")
                parts.append("")
                parts.append(_read_file(path))
                parts.append("")

    # Unassigned guides
    assigned = {s for _, slugs in _narrative_sections(cfg) for s in slugs}
    for p in pages:
        if p["slug"] not in assigned:
            path = os.path.join(cfg.out_guides, f"{p['slug']}.md")
            if os.path.exists(path):
                parts.append(f"{'=' * 60}")
                parts.append(f"## {p['title']}")
                parts.append("")
                parts.append(_read_file(path))
                parts.append("")

    # API reference — include module docstrings and a link to the full page.
    # Raw mkdocstrings directives (::: module) are not rendered in plain text,
    # so we extract the module docstring and provide a URL instead.
    seen_modules = set()
    for section_name, _ in _reference_sections(cfg, reference_modules):
        mods = _section_modules(cfg, section_name, reference_modules)
        if not mods:
            continue
        for m in mods:
            if m in seen_modules:
                continue
            seen_modules.add(m)
            slug = m.replace(".", "_")
            path = os.path.join(cfg.ref_dir, f"{slug}.md")
            if os.path.exists(path):
                content = _read_file(path)
                # Strip raw mkdocstrings directives — they don't render in plain text.
                # Keep the module docstring (text before the first ::: directive).
                lines = content.split("\n")
                doc_lines = []
                for line in lines:
                    if line.startswith(":::"):
                        break
                    doc_lines.append(line)
                doc_text = "\n".join(doc_lines).strip()
                base = cfg.site_url.rstrip("/") if cfg.site_url else ""
                url = f"{base}/reference/{slug}/" if base else f"reference/{slug}/"
                parts.append(f"{'=' * 60}")
                parts.append(f"## {m}")
                parts.append("")
                if doc_text:
                    parts.append(doc_text)
                    parts.append("")
                parts.append(f"Full API docs: {url}")
                parts.append("")

    content = "\n".join(parts)
    with open(os.path.join(cfg.site_src, "llms-full.txt"), "w") as f:
        f.write(content)
    size_kb = len(content) // 1024
    print(f"  llms-full.txt ({size_kb} KB)")


def cross_link_guides(cfg, pages: List[dict]) -> int:
    """Add 'related pages' cross-links to each guide page.

    Args:
        cfg: A :class:`repoquill.config.RepoQuillConfig`.
        pages: List of narrative page dicts.

    Returns:
        Number of pages cross-linked.
    """
    guides_dir = cfg.out_guides
    if not os.path.isdir(guides_dir):
        return 0

    pages_info = {}
    for fname in sorted(os.listdir(guides_dir)):
        if not fname.endswith(".md"):
            continue
        slug = fname[:-3]
        path = os.path.join(guides_dir, fname)
        with open(path) as f:
            content = f.read()
        title = slug.replace("-", " ").title()
        for line in content.splitlines():
            if line.startswith("## "):
                title = line[3:].strip()
                break
        headings = []
        for line in content.splitlines():
            if line.startswith("## ") or line.startswith("### "):
                h = line.lstrip("#").strip()
                if h.lower() != "see also":
                    headings.append(h)
        pages_info[slug] = {"title": title, "headings": headings, "path": path}

    if len(pages_info) < 2:
        return 0

    stop = {"the", "and", "for", "with", "from", "that", "this", "using",
            "use", "via", "all", "any", "not", "can", "may", "will", "are",
            "was", "were", "has", "have", "had", "its", "their", "your",
            "our", "how", "what", "when", "where", "which", "who", "why",
            "python", "function", "functions", "class", "classes", "method",
            "methods", "example", "examples", "usage", "guide", "guides",
            "page", "pages", "section", "sections", "module", "modules",
            "reference", "api", "overview", "details", "note", "notes",
            "tip", "tips", "best", "practices", "troubleshooting",
            "configuration", "config", "implementation", "architecture",
            "core", "basic", "advanced", "getting", "started",
            "installation", "setup", "environment", "variables",
            "command", "commands", "line", "interface", "output",
            "input", "data", "file", "files", "directory", "path", "paths",
            "error", "errors", "handling", "resilience", "privacy"}

    slug_section = {}
    for section_name, slugs in _narrative_sections(cfg):
        for s in slugs:
            slug_section[s] = section_name

    def related_to(slug, max_results=4):
        info = pages_info[slug]
        my_words = set(re.findall(r"[a-z]{3,}",
                     " ".join([info["title"]] + info["headings"]).lower()))
        my_words -= stop
        my_section = slug_section.get(slug)
        scores = {}
        for other_slug, other_info in pages_info.items():
            if other_slug == slug:
                continue
            score = 0
            if my_section and slug_section.get(other_slug) == my_section:
                score += 2
            other_words = set(re.findall(r"[a-z]{3,}",
                          " ".join([other_info["title"]] + other_info["headings"]).lower()))
            other_words -= stop
            score += len(my_words & other_words)
            if score > 0:
                scores[other_slug] = score
        ranked = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
        return [s for s, _ in ranked[:max_results]]

    for slug, info in pages_info.items():
        with open(info["path"]) as f:
            content = f.read()

        content = re.sub(
            r"\n### See Also\n[\s\S]*?(?=\n## |\Z)",
            "",
            content,
        ).rstrip() + "\n"

        related = related_to(slug)
        if not related:
            related = [s for s in pages_info if s != slug][:4]

        lines = ["", "### See Also", ""]
        for r_slug in related:
            r_info = pages_info[r_slug]
            lines.append(f"*   [{r_info['title']}]({r_slug}.md)")
        content += "\n".join(lines) + "\n"

        with open(info["path"], "w") as f:
            f.write(content)

    print(f"  Cross-linked {len(pages_info)} guide pages")
    return len(pages_info)


def build_nav(cfg, pages: List[dict], reference_modules: List[str]) -> List:
    """Build the navigation tree from narrative pages + reference modules.

    Args:
        cfg: A :class:`repoquill.config.RepoQuillConfig`.
        pages: List of narrative page dicts.
        reference_modules: List of documented module names.

    Returns:
        The nav tree (list of section dicts / page entries).
    """
    page_map = {p["slug"]: p for p in pages}
    nav = ["index.md"]

    # --- Guides section (only if there are guide pages) ---
    guides_nav = []
    for section_name, slugs in _narrative_sections(cfg):
        section_pages = [page_map[s] for s in slugs if s in page_map]
        if not section_pages:
            continue
        if len(section_pages) == 1:
            # Single page — flatten to a direct link instead of a nested group
            guides_nav.append(f"guides/{section_pages[0]['slug']}.md")
        else:
            guides_nav.append([section_name, [f"guides/{p['slug']}.md" for p in section_pages]])
    unassigned = [p for p in pages
                  if p["slug"] not in {s for _, slugs in _narrative_sections(cfg) for s in slugs}]
    if unassigned:
        guides_nav.append(["More", [f"guides/{p['slug']}.md" for p in unassigned]])
    if guides_nav:
        nav.append(["Guides", guides_nav])

    # --- API Reference section (only if there are reference modules) ---
    ref_nav = []
    for section_name, _ in _reference_sections(cfg, reference_modules):
        mods = _section_modules(cfg, section_name, reference_modules)
        if not mods:
            continue
        if len(mods) == 1:
            ref_nav.append(f"reference/{mods[0].replace('.', '_')}.md")
        else:
            ref_nav.append([section_name, [f"reference/{m.replace('.', '_')}.md" for m in mods]])
    if ref_nav:
        # A single section would otherwise nest as API Reference → section
        # → pages; lift it one level so the nav reads API Reference → pages.
        # When the section is itself named "API Reference" (the fallback
        # case), use the pages directly to avoid a redundant label.
        if len(ref_nav) == 1 and isinstance(ref_nav[0], list):
            name, pages = ref_nav[0]
            ref_nav = pages if name == "API Reference" else [name, pages]
        nav.append(["API Reference", ref_nav])

    return nav


def _yaml_dump_block(obj, indent=0):
    """Serialize a Python object to a YAML block (indented).

    Uses PyYAML if available, otherwise a simple recursive serializer.
    """
    try:
        import yaml
        dumped = yaml.dump(obj, default_flow_style=False, sort_keys=False).rstrip()
        # Indent each line
        pad = "  " * indent
        lines = [pad + line if line.strip() else line for line in dumped.split("\n")]
        return "\n".join(lines)
    except ImportError:
        return _minimal_yaml_dump(obj, indent)


def _minimal_yaml_dump(obj, indent=0):
    """Fallback YAML serializer (no external deps)."""
    pad = "  " * indent
    lines = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                lines.append(f"{pad}{k}:")
                lines.append(_minimal_yaml_dump(v, indent + 1))
            else:
                lines.append(f"{pad}{k}: {v}")
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}-")
                lines.append(_minimal_yaml_dump(item, indent + 1))
            else:
                lines.append(f"{pad}- {item}")
    else:
        lines.append(f"{pad}{obj}")
    return "\n".join(lines)


def _nav_to_yaml(nav, indent=0):
    """Serialize the nav list to YAML (no external deps)."""
    pad = "  " * (indent + 1)
    lines = []
    for item in nav:
        if isinstance(item, str):
            lines.append(f"{pad}- {item}")
        elif isinstance(item, dict):
            path, title = next(iter(item.items()))
            lines.append(f"{pad}- {path}: {title}")
        elif len(item) == 2 and isinstance(item[1], str):
            lines.append(f"{pad}- {item[0]}: {item[1]}")
        else:
            title, children = item
            lines.append(f"{pad}- {title}:")
            lines.append(_nav_to_yaml(children, indent + 1))
    return "\n".join(lines)


def build_mkdocs_yml(cfg, nav: List) -> None:
    """Write ``mkdocs.yml`` entirely from the config.

    Injects the package ``paths`` into the mkdocstrings handler so source
    links and ``show_source`` resolve correctly.

    Args:
        cfg: A :class:`repoquill.config.RepoQuillConfig`.
        nav: The navigation tree.
    """
    nav_yaml = _nav_to_yaml(nav)

    theme_cfg = cfg.theme
    theme_primary = theme_cfg.get("primary", "indigo")
    theme_accent = theme_cfg.get("accent", "indigo")
    theme_features = theme_cfg.get("features", [
        "navigation.sections", "navigation.top", "navigation.footer",
        "content.code.copy", "search.highlight", "search.suggest", "toc.follow",
    ])

    # Build theme block
    theme_block = {
        "name": theme_cfg.get("name", "material"),
        "palette": [
            {
                "scheme": "default",
                "primary": theme_primary,
                "accent": theme_accent,
                "toggle": {"icon": "material/brightness-7", "name": "Switch to dark mode"},
            },
            {
                "scheme": "slate",
                "primary": theme_primary,
                "accent": theme_accent,
                "toggle": {"icon": "material/brightness-4", "name": "Switch to light mode"},
            },
        ],
        "features": theme_features,
    }
    # Pass through optional theme fields from the config
    for key in ("favicon", "logo", "font", "icon", "sticky_navigation", "sticky_header"):
        if key in theme_cfg:
            theme_block[key] = theme_cfg[key]

    # Build plugins block (inject paths into mkdocstrings if present).
    # Reference pages are emitted as mkdocstrings directives, so the
    # plugin MUST be present for the site to render them — if the config
    # doesn't declare one, we insert a working default rather than
    # silently producing literal ":::" text on every reference page.
    plugins = []
    has_mkdocstrings = any(
        isinstance(p, dict) and "mkdocstrings" in p for p in cfg.plugins
    )
    if not has_mkdocstrings:
        plugins.append({"search": None})
        plugins.append({
            "mkdocstrings": {
                "handlers": {
                    "python": {
                        "paths": [cfg.root],
                        "options": {
                            "docstring_style": "google",
                            "show_root_heading": False,
                            "show_submodules": False,
                        },
                    }
                }
            }
        })
    for p in cfg.plugins:
        if isinstance(p, dict) and "mkdocstrings" in p:
            mk = dict(p["mkdocstrings"])
            handlers = mk.get("handlers", {})
            py = handlers.get("python", {})
            # paths is a top-level handler config field (not under options)
            py["paths"] = [cfg.root]
            handlers["python"] = py
            mk["handlers"] = handlers
            plugins.append({"mkdocstrings": mk})
        else:
            plugins.append(p)

    # Markdown extensions: reference pages and generated guides rely on
    # standard extensions; provide a working default set when absent.
    md_exts = list(cfg.markdown_extensions) or [
        "admonition",
        "attr_list",
        "tables",
        "toc",
    ]

    # Optional site fields
    extra_site_lines = []
    edit_uri = cfg.site.get("edit_uri", "")
    site_author = cfg.site.get("author", "")
    copyright = cfg.site.get("copyright", "")
    if edit_uri:
        extra_site_lines.append(f"edit_uri: {edit_uri}")
    if site_author:
        extra_site_lines.append(f"site_author: {site_author}")
    if copyright:
        # Make relative links in copyright root-absolute so they work
        # on all pages (not just the index).
        if cfg.site_url:
            base = cfg.site_url.rstrip("/")
            # Convert href="SKILL.md" → href="https://.../SKILL.md"
            copyright = re.sub(
                r'href="([^/h][^"]*)"',
                lambda m: f'href="{base}/{m.group(1)}"',
                copyright,
            )
        extra_site_lines.append(f"copyright: {copyright}")
    extra_site_block = "\n".join(extra_site_lines) + "\n" if extra_site_lines else ""

    build_cfg = cfg.build
    # When output_dir is used (same-repo integration), mkdocs.yml is written
    # to the PARENT of site_src/ and docs_dir points at the output dir.
    # (mkdocs rejects docs_dir == the config file's own directory, so the
    # config must live one level above the content.)
    # Otherwise, mkdocs.yml is in config_dir/ and docs_dir points to site_src/.
    if cfg.raw.get("output_dir"):
        docs_dir = os.path.basename(cfg.site_src)
        mkdocs_path = os.path.join(os.path.dirname(cfg.site_src), "mkdocs.yml")
    else:
        docs_dir = build_cfg.get("docs_dir", "docs")
        mkdocs_path = os.path.join(cfg.config_dir, "mkdocs.yml")
    site_dir = build_cfg.get("site_dir", "site_repoquill")
    # With output_dir, a relative site_dir would land INSIDE docs_dir,
    # which mkdocs rejects. Place the build output as a sibling of the
    # output dir instead.
    if cfg.raw.get("output_dir") and not os.path.isabs(site_dir):
        site_dir = os.path.join(os.path.dirname(cfg.site_src), site_dir)
    use_directory_urls = build_cfg.get("use_directory_urls", True)

    content = f'''# MkDocs configuration for {cfg.site_name}
# Generated by repoquill — DO NOT EDIT by hand.
# All values come from repoquill.yml. Edit that file to change anything.

site_name: {cfg.site_name}
site_description: {cfg.site.get("description", "")}
site_url: {cfg.site_url}
repo_url: {cfg.repo_url}
repo_name: {cfg.repo_name}
{extra_site_block}
docs_dir: {docs_dir}
site_dir: {site_dir}
use_directory_urls: {str(use_directory_urls).lower()}

theme:
{_yaml_dump_block(theme_block, indent=1)}

plugins:
{_yaml_dump_block(plugins, indent=1)}

markdown_extensions:
{_yaml_dump_block(md_exts, indent=1)}

nav:
{nav_yaml}
'''
    # Convert plain mermaid format string to the !!python/name: YAML tag
    content = content.replace(
        "format: pymdownx.superfences.fence_code_format",
        "format: !!python/name:pymdownx.superfences.fence_code_format",
    )
    os.makedirs(os.path.dirname(mkdocs_path), exist_ok=True)
    with open(mkdocs_path, "w") as f:
        f.write(content)


def build_skill_md(cfg, reference_modules=None) -> str:
    """Build ``SKILL.md`` content — an agent skill for USING the software.

    This is NOT about the docs pipeline. It's a practical guide for an
    agent (or human) on how to use {cfg.project_name} in testing workflows.

    Returns the content as a string. The caller is responsible for
    writing it to the site output (NOT to site_src, because MkDocs
    would render it to HTML).

    Args:
        cfg: A :class:`repoquill.config.RepoQuillConfig`.

    Returns:
        The SKILL.md content as a string.
    """

    tagline = cfg.index.get("tagline", "").strip()
    tagline_line = f"\n{tagline}\n" if tagline else ""

    # Build module list from reference sections
    module_lines = []
    for section_name, prefixes in _reference_sections(cfg, reference_modules):
        module_lines.append(f"  - **{section_name}**: {', '.join(f'`{p}`' for p in prefixes)}")
    module_table = "\n".join(module_lines)

    # Build guide list from narrative sections
    guide_lines = []
    for section_name, slugs in _narrative_sections(cfg):
        guide_lines.append(f"  - **{section_name}**: {', '.join(f'`{s}`' for s in slugs)}")
    guide_table = "\n".join(guide_lines)

    # Module descriptions (top-level modules only, for brevity)
    desc_lines = []
    for mod, desc in _module_descriptions(cfg, reference_modules).items():
        if mod.count(".") <= 1:  # top-level or one-level-deep
            desc_lines.append(f"| `{mod}` | {desc} |")
    desc_table = "\n".join(desc_lines) if desc_lines else "| _none_ | _none_ |"

    content = f'''# {cfg.project_name} Usage Skill
{tagline_line}
Agent skill for using {cfg.project_name} in testing and evaluation workflows.
Generated by `repoquill` — DO NOT EDIT by hand. Re-run the generator to update.

## When to Use

- User wants to audit, evaluate, or test an LLM's outputs
- User wants to score model responses for safety, harm, factuality, or helpfulness
- User wants to compare models or judges side-by-side
- User wants to run scenario-based evaluations
- User asks about {cfg.project_name} capabilities, setup, or results

## Core Principle

**NEVER invent API behavior.** Always verify against the actual source code before writing examples.

Source priority (highest to lowest):

1. Python implementation (`{cfg.package_dir}/*.py`)
2. Tests (`tests/`)
3. `pyproject.toml` / configuration
4. Existing documentation
5. `README.md`

If documentation conflicts with implementation, **flag the conflict** rather than guessing.

## What {cfg.project_name} Does

{cfg.project_name} is a testing/evaluation tool. You use it to:

1. **Define scenarios** — curated prompts/inputs that probe specific behaviors
2. **Run a model** — send scenarios to an LLM (local or API)
3. **Judge the outputs** — score responses using LLM judges on specific dimensions
4. **Aggregate results** — compare scores across models, judges, and scenarios
5. **Visualize** — view results in the browser

## Key Modules

| Module | Description |
|--------|-------------|
{desc_table}

## API Reference Sections

{module_table}

## Guide Pages

{guide_table}

## Typical Workflow

### 1. Set up

```python
# Install
pip install {cfg.project_name}

# Configure your LLM endpoint (API key, base URL, model)
```

### 2. Load scenarios

```python
# Load a scenario pack (curated test inputs)
# See the guides for available scenario packs
```

### 3. Run the model

```python
# Send scenarios to the model under test
# Collect raw outputs
```

### 4. Judge the outputs

```python
# Score outputs using LLM judges
# Dimensions: safety, harm, factuality, helpfulness (and more)
```

### 5. Aggregate & compare

```python
# Aggregate scores across scenarios
# Compare across models and judges
# Export results (JSON, etc.)
```

## Configuration

- **LLM endpoint**: API key, base URL, model name (for both the model under test AND the judges)
- **Scenario packs**: curated sets of test inputs organized by domain
- **Judge configs**: which dimensions to score, which judge model to use
- **Output format**: JSON results with per-scenario and aggregate scores

## Rules

1. **Never invent API names.** Verify class/function names against `{cfg.package_dir}/__init__.py` and the reference pages.
2. **Keep examples runnable.** All code examples must use the current API (verify against source).
3. **Flag conflicts, don't guess.** If code and docs disagree, report the conflict.
4. **Respect the config.** All structure comes from the config file. Don't hardcode values.
5. **This skill file is generated.** Do not edit it directly. Update the config and re-run the generator.

## Environment

- Repo: {cfg.repo_url}
- Site: {cfg.site_url}
- Package: `{cfg.package_dir}`
'''

    return content
