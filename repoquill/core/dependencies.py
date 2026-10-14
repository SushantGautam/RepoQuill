"""Guide-page to source-symbol dependency mapping and affected-slug logic.

Bridges the structural diff from :mod:`repoquill.core.impact` and the
narrative guide pages:

- :func:`page_symbols` pulls API-looking references out of a markdown page
  (backticks, headings, import statements).
- :func:`build_page_dependencies` resolves those references against a known
  symbol inventory, producing ``{slug: {qualified names, module names}}``.
- :func:`affected_slugs` maps an :class:`~repoquill.core.impact.ApiDiff`
  onto the set of guide slugs that must be regenerated.

The mapping is deliberately conservative: anything unknown (a page with no
resolvable references, a source module that failed to parse, a slug with no
guide file on disk) is treated as affected, never as safe.
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Set

from repoquill.core.impact import ApiDiff, diff_surfaces, extract_api_surface, module_name_for_path

__all__ = [
    "page_symbols",
    "build_page_dependencies",
    "affected_slugs",
    "diff_source_files",
]


# ``Foo``, ``pkg.foo``, ``pkg.foo.Foo``, ``Foo.bar`` — dotted identifiers.
_DOTTED_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
# A bare identifier or dotted name optionally followed by ``(`` (a call).
_CALL_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*\($")
# CamelCase words in headings (class names).
_CAMEL_RE = re.compile(r"\b[A-Z][A-Za-z0-9_]*\b")
# import / from ... import at line start (markdown code blocks included).
_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+([A-Za-z_][\w.]*)\s+import\s+([^\n#]+)"
    r"|import\s+([A-Za-z_][\w.]*)(?:\s+as\s+[A-Za-z_]\w*)?)",
    re.M,
)
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")


def _token_from_backtick(raw: str) -> List[str]:
    """Turn a backtick token into candidate identifier tokens."""
    tok = raw.strip()
    if not tok:
        return []
    out: List[str] = []
    if _DOTTED_IDENT_RE.match(tok):
        out.append(tok)
        return out
    m = _CALL_RE.match(tok)
    if m:
        out.append(m.group(1))
        return out
    # Strip a single trailing signature, e.g. ``process(data: list)``.
    if tok.endswith(")") and "(" in tok:
        head = tok[: tok.rfind("(")].strip()
        if _DOTTED_IDENT_RE.match(head):
            out.append(head)
    return out


def page_symbols(page_md: str) -> Set[str]:
    """Extract API references from a guide page's markdown.

    Collects:
    - identifiers (and dotted names) inside inline backticks, including
      call syntax such as ``Foo()`` or ``process(data)``;
    - CamelCase names and dotted identifiers in markdown headings;
    - module names and imported names from ``import``/``from ... import``
      statements (which live in fenced code blocks).

    Returns:
        Set of identifier/dotted-name tokens. These are *candidates*;
        :func:`build_page_dependencies` matches them against the known
        symbol inventory.
    """
    tokens: Set[str] = set()

    for raw in _BACKTICK_RE.findall(page_md):
        tokens.update(_token_from_backtick(raw))

    for line in page_md.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            for m in _CAMEL_RE.finditer(stripped):
                tokens.add(m.group(0))
            for m in re.finditer(r"[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*", stripped):
                if "." in m.group(0):
                    tokens.add(m.group(0))

    for m in _IMPORT_RE.finditer(page_md):
        if m.group(1):  # from X import a, b as c
            tokens.add(m.group(1))
            for name in m.group(2).split(","):
                name = name.strip().split(" as ")[0].strip()
                if name and _DOTTED_IDENT_RE.match(name):
                    tokens.add(name)
        elif m.group(3):  # import X
            tokens.add(m.group(3))

    tokens.discard("")
    return tokens


def _source_file_modules(page: dict) -> Set[str]:
    """Module names implied by a page's ``source_files`` list."""
    out: Set[str] = set()
    for rel in page.get("source_files", []) or []:
        if rel.endswith(".py"):
            out.add(module_name_for_path(rel))
    return out


def build_page_dependencies(
    pages: List[dict],
    guides_dir: str,
    module_symbols: Dict[str, Set[str]],
) -> Dict[str, Set[str]]:
    """Map each guide slug to the qualified symbols/modules it references.

    Args:
        pages: Page dicts; each needs ``"slug"`` (and optionally
            ``"source_files"`` with package-relative ``.py`` paths).
        guides_dir: Directory holding the guide ``<slug>.md`` files.
        module_symbols: ``{module_name: {qualified symbol, ...}}`` where a
            qualified symbol is ``module.Name`` or ``module.Name.method``.

    Returns:
        ``{slug: {qualified symbols, module names}}``. A page's set contains
        every inventory symbol whose last component (or full dotted name)
        matches a token on the page, plus module names the page imports or
        is generated from. Pages whose guide file is missing get an empty
        set — :func:`affected_slugs` treats that as "unknown", not safe.
    """
    inventory: List[str] = []
    for mod in sorted(module_symbols):
        for sym in sorted(module_symbols[mod]):
            inventory.append(sym)
    module_names = set(module_symbols)

    deps: Dict[str, Set[str]] = {}
    for page in pages:
        slug = page.get("slug")
        if not slug:
            continue
        deps[slug] = set()

        md_path = os.path.join(guides_dir, slug + ".md")
        if os.path.exists(md_path):
            with open(md_path, "r", encoding="utf-8", errors="replace") as f:
                tokens = page_symbols(f.read())
        else:
            tokens = set()

        # Modules the page is generated from are always dependencies.
        deps[slug] |= _source_file_modules(page)

        for tok in tokens:
            if tok in module_names:
                deps[slug].add(tok)
            for sym in inventory:
                if sym == tok or sym.endswith("." + tok) or sym.split(".")[-1] == tok:
                    deps[slug].add(sym)
    return deps


def affected_slugs(
    diff: ApiDiff,
    deps: Dict[str, Set[str]],
    all_slugs: List[str],
) -> Dict[str, List[str]]:
    """Conservatively map an API diff to affected guide slugs.

    A slug is affected when:
    - any symbol/module it references is in :meth:`ApiDiff.changed_symbols`;
    - it references (imports/uses) a module whose reexports changed, or a
      module that had a removal;
    - the diff could not be fully computed for a module it depends on
      (parse errors);
    - it references no known symbols at all, or has no guide content, while
      the diff is non-empty (unknown must never mean "safe").

    Args:
        diff: The :class:`~repoquill.core.impact.ApiDiff`.
        deps: Output of :func:`build_page_dependencies`.
        all_slugs: Every slug in the current plan.

    Returns:
        ``{slug: [reasons]}`` — only affected slugs, with human-readable
        reasons. Deterministic ordering.
    """
    if diff.is_empty():
        return {}

    changed = diff.changed_symbols()
    reexport_modules = sorted(diff.reexport_changes)
    removed_modules = sorted(diff.removed_modules)
    errored_modules = sorted(diff.errors)

    result: Dict[str, List[str]] = {}
    for slug in sorted(all_slugs):
        reasons: List[str] = []
        page_deps = deps.get(slug)

        if page_deps is None:
            reasons.append("page has no dependency record; conservative fallback")
        elif not page_deps:
            reasons.append("page references no known symbols; conservative fallback")
        else:
            hits = sorted(d for d in page_deps if d in changed)
            if hits:
                reasons.append("references changed symbol(s): " + ", ".join(hits))
            for m in reexport_modules:
                if m in page_deps:
                    reasons.append("reexports changed in module " + m)
                    break
            for m in removed_modules:
                if m in page_deps:
                    reasons.append("symbol(s) removed from module " + m)
                    break
            for m in errored_modules:
                if m in page_deps:
                    reasons.append("unparseable source for module " + m
                                   + "; conservative fallback")
                    break
        if reasons:
            result[slug] = reasons
    return result


def diff_source_files(
    old_files: Dict[str, str],
    new_files: Dict[str, str],
) -> ApiDiff:
    """Extract both surfaces and diff them (convenience wrapper).

    Args:
        old_files: Previous ``{relative_path: content}`` source mapping.
        new_files: Current ``{relative_path: content}`` source mapping.

    Returns:
        The :class:`~repoquill.core.impact.ApiDiff` between them.
    """
    return diff_surfaces(extract_api_surface(old_files), extract_api_surface(new_files))
