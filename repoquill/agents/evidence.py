"""Deterministic, no-LLM evidence discovery for one documentation page.

Builds an :class:`~repoquill.agents.contracts.EvidencePack` seed for the
authoring agent. Everything here is read-only and offline; the agent is
expected to confirm and extend the pack with live tool calls.

The heuristics are fully generic — they operate on package layout, module
names and the public AST symbol index, with no domain-specific assumptions.
"""
from __future__ import annotations

import os
import re
from typing import List

from repoquill.agents.contracts import EvidencePack, PageTask
from repoquill.reference import extract_api_surface, get_file_tree
from repoquill.verify import build_index

__all__ = [
    "build_evidence_pack",
    "candidate_source_files",
    "candidate_tests",
    "coverage_checklist",
]

# Words that carry no topical signal when tokenizing a slug or title.
_STOP_WORDS = frozenset({
    "the", "get", "and", "use", "using", "with", "for", "how", "to",
    "of", "in", "on", "via", "by", "is", "are", "be", "do", "does",
    "your", "our", "its", "this", "that", "from", "into", "about",
    "which", "when", "what", "all", "any", "can", "you", "have",
})

# Directories never worth descending into when discovering test files.
_SKIP_DIRS = frozenset({
    "__pycache__", ".venv", "venv", "node_modules", ".git", ".tox",
    ".mypy_cache", ".pytest_cache", "site-packages",
})

_MAX_SOURCE_FILES = 12
_MAX_TEST_FILES = 8


def _tokenize(*texts: str) -> List[str]:
    """Lowercased, de-duplicated topical tokens from slug/title text."""
    tokens: List[str] = []
    seen = set()
    for text in texts:
        for word in re.split(r"[^0-9A-Za-z]+", text.lower()):
            if len(word) < 3 or word in _STOP_WORDS:
                continue
            if word not in seen:
                seen.add(word)
                tokens.append(word)
    return tokens


def _package_py_files(pkg_path: str) -> List[str]:
    """Sorted package-relative paths of all ``.py`` files (read-only)."""
    out: List[str] = []
    for dirpath, dirnames, filenames in os.walk(pkg_path):
        dirnames[:] = [d for d in sorted(dirnames) if d not in _SKIP_DIRS]
        for f in sorted(filenames):
            if f.endswith(".py"):
                full = os.path.join(dirpath, f)
                out.append(os.path.relpath(full, pkg_path).replace(os.sep, "/"))
    return out


def candidate_source_files(task: "PageTask", pkg_path: str) -> List[str]:
    """Likely source files for this page, relative to ``pkg_path``.

    Prefers the task's explicit ``source_hints`` (filtered to files that
    actually exist). Otherwise falls back to a generic heuristic: modules
    whose filename or path shares a token with the page slug/title, and,
    if nothing matches, the top-level package modules.
    """
    all_files = _package_py_files(pkg_path)

    hints = [h for h in (task.source_hints or []) if h]
    if hints:
        existing = []
        for hint in hints:
            hint_norm = hint.replace(os.sep, "/")
            if os.path.isfile(os.path.join(pkg_path, hint_norm)):
                if hint_norm not in existing:
                    existing.append(hint_norm)
        if existing:
            return existing[:_MAX_SOURCE_FILES]

    tokens = _tokenize(task.slug, task.title)
    if tokens:
        matched = []
        for rel in all_files:
            stem = os.path.splitext(os.path.basename(rel))[0]
            parts = rel[:-3].split("/")
            file_tokens = {p for p in parts if p and p != "__init__"}
            file_tokens.add(stem)
            file_tokens.add(" ".join(stem.split("_")))
            if file_tokens & set(tokens):
                matched.append(rel)
        if matched:
            return matched[:_MAX_SOURCE_FILES]

    top_level = [f for f in all_files if "/" not in f]
    top_level.sort(key=lambda f: (f != "__init__.py", f))
    return top_level[:_MAX_SOURCE_FILES]


def candidate_tests(task: "PageTask", root: str) -> List[str]:
    """Test files related to this page, relative to ``root``.

    Discovers ``test_*.py`` / ``*_test.py`` files and anything under a
    ``tests``/``test`` directory, skipping caches and virtualenvs. Files
    whose name shares a token with the page slug/title come first.
    """
    found: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in sorted(dirnames) if d not in _SKIP_DIRS]
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        in_tests_dir = (
            rel_dir in ("tests", "test")
            or any(p in ("tests", "test") for p in rel_dir.split("/"))
        )
        for f in sorted(filenames):
            if not f.endswith(".py"):
                continue
            is_test_name = f.startswith("test_") or f.endswith("_test.py")
            if not (is_test_name or in_tests_dir):
                continue
            rel = os.path.join(rel_dir, f).replace(os.sep, "/") if rel_dir != "." else f
            if rel not in found:
                found.append(rel)

    tokens = set(_tokenize(task.slug, task.title))
    def _rank(rel: str):
        name = os.path.splitext(os.path.basename(rel))[0]
        parts = {p for p in name.split("_") if p}
        parts.add(" ".join(p for p in name.split("_") if p))
        return 0 if (tokens and parts & tokens) else 1

    found.sort(key=lambda rel: (_rank(rel), rel))
    return found[:_MAX_TEST_FILES]


def coverage_checklist(task: "PageTask", pkg_path: str) -> List[str]:
    """Public package symbols (classes + top-level functions) as strings.

    Uses the deterministic AST symbol index; private (underscore) names
    are excluded. A parse failure degrades to an empty list.
    """
    try:
        idx = build_index(pkg_path)
    except Exception:
        return []
    public = set()
    public.update(n for n in idx.classes if not n.startswith("_"))
    public.update(n for n in idx.functions if not n.startswith("_"))
    return sorted(public)


def _readme_excerpt(root: str) -> str:
    readme = os.path.join(root, "README.md")
    if not os.path.isfile(readme):
        return ""
    try:
        with open(readme, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(2000)
    except OSError:
        return ""


def build_evidence_pack(task: "PageTask", pkg_path: str, root: str) -> "EvidencePack":
    """Assemble the deterministic seed evidence pack for one page."""
    file_tree = ""
    try:
        file_tree = get_file_tree(pkg_path)
    except OSError:
        file_tree = ""

    api_surface = ""
    try:
        api_surface = extract_api_surface(pkg_path)
    except Exception:
        api_surface = ""

    checklist = list(task.coverage_checklist or [])
    if not checklist:
        checklist = coverage_checklist(task, pkg_path)

    return EvidencePack(
        file_tree=file_tree,
        candidate_files=candidate_source_files(task, pkg_path),
        candidate_tests=candidate_tests(task, root),
        api_surface=api_surface,
        coverage_checklist=checklist,
        readme_excerpt=_readme_excerpt(root),
    )
