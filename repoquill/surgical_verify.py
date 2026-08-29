"""Deterministic surgical verification pass for generated guide pages.

Fixes the two dominant example-validity finding types (E12) without an
LLM rewrite:

  1. property_called_as_method — strip trailing ``()`` from ``@property``
     calls (e.g. ``results.passed()`` → ``results.passed``).
  2. missing_required — insert required ``__init__`` kwargs that a
     constructor call in a code block is missing, using a
     ``"<REQUIRED>"`` placeholder so the example is syntactically valid
     and the reader sees exactly which argument is needed.

This is a post-generation edit step: it runs on the generated ``.md``
files after ``generate_all_pages`` produces them, before the mkdocs
build.  It is fully deterministic — no LLM calls, no network, no
non-determinism.

Genericity: the class index is built by AST-walking the package under
test.  No SimpleAudit-specific names appear here.
"""

from __future__ import annotations

import ast
import os
import re
from collections import defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Class index
# ---------------------------------------------------------------------------

def build_class_index(pkg_path: str) -> dict:
    """Return ``{ClassName: {init_params, properties, methods}}``.

    ``init_params`` maps parameter name → has_default (bool).  ``self``
    and ``cls`` are excluded.  ``properties`` is the set of names
    decorated with ``@property``.  ``methods`` is the set of regular
    method names.
    """
    classes: dict = {}
    for py in Path(pkg_path).rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            cls = node.name
            info = {"init_params": {}, "properties": set(), "methods": set()}
            for item in node.body:
                if not isinstance(item, ast.FunctionDef):
                    continue
                if item.name == "__init__":
                    args = item.args
                    # Skip self/cls (first positional arg)
                    all_args = list(args.args)
                    if all_args and all_args[0].arg in ("self", "cls"):
                        all_args = all_args[1:]
                    all_args = all_args + args.kwonlyargs
                    defaults = list(args.defaults) + list(args.kw_defaults)
                    n_args = len(all_args)
                    n_defaults = len(defaults)
                    default_map = {}
                    for i, _d in enumerate(defaults):
                        default_map[n_args - n_defaults + i] = True
                    for i, a in enumerate(all_args):
                        info["init_params"][a.arg] = i in default_map
                else:
                    info["methods"].add(item.name)
                    for deco in item.decorator_list:
                        if isinstance(deco, ast.Name) and deco.id == "property":
                            info["properties"].add(item.name)
            classes[cls] = info
    return classes


# ---------------------------------------------------------------------------
# Fix passes
# ---------------------------------------------------------------------------

def fix_property_calls(text: str, classes: dict) -> tuple[str, int]:
    """Strip ``()`` from property calls in code blocks and backtick prose."""
    all_props: set[str] = set()
    for info in classes.values():
        all_props |= info["properties"]
    if not all_props:
        return text, 0

    count = 0
    for prop in sorted(all_props):
        pattern = re.compile(r"(\.\s*" + re.escape(prop) + r")\(\s*\)")
        text, n = pattern.subn(r"\1", text)
        count += n
    return text, count


def _fix_missing_required_in_block(block: str, classes: dict) -> tuple[str, int]:
    """Fix missing required kwargs in a single python code block (no fences)."""
    try:
        tree = ast.parse(block)
    except SyntaxError:
        return block, 0

    fixes: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Name):
            continue
        cls_name = func.id
        if cls_name not in classes:
            continue
        info = classes[cls_name]
        init_params = info["init_params"]
        if not init_params:
            continue
        required = {p for p, has_default in init_params.items() if not has_default}
        if not required:
            continue
        present_kwargs = {kw.arg for kw in node.keywords if kw.arg is not None}
        missing = required - present_kwargs
        if not missing:
            continue
        for param in sorted(missing):
            fixes.append((node.lineno, param))

    if not fixes:
        return block, 0

    fixes_by_line: dict[int, list[str]] = defaultdict(list)
    for line_no, param in fixes:
        fixes_by_line[line_no].append(param)

    lines = block.split("\n")
    count = 0
    for line_no in sorted(fixes_by_line.keys(), reverse=True):
        params = fixes_by_line[line_no]
        idx = line_no - 1
        if idx >= len(lines):
            continue
        # Find the closing paren for this call
        paren_depth = 0
        close_idx = None
        found_open = False
        for j in range(idx, len(lines)):
            for ch in lines[j]:
                if ch == "(":
                    paren_depth += 1
                    found_open = True
                elif ch == ")":
                    paren_depth -= 1
                    if found_open and paren_depth == 0:
                        close_idx = j
                        break
            if close_idx is not None:
                break
        if close_idx is None:
            continue
        close_line = lines[close_idx]
        paren_idx = close_line.rindex(")")
        insert_text = ",\n" + ",\n".join(f'    {p}="<REQUIRED>"' for p in params)
        lines[close_idx] = close_line[:paren_idx] + insert_text + "\n" + close_line[paren_idx:]
        count += len(params)

    return "\n".join(lines), count


def fix_missing_required(text: str, classes: dict) -> tuple[str, int]:
    """Fix missing required kwargs in all python code blocks (preserving fences)."""
    count = 0
    for m in re.finditer(r"```python\n(.*?)```", text, re.DOTALL):
        block = m.group(1)
        new_block, n = _fix_missing_required_in_block(block, classes)
        if n > 0:
            text = text[: m.start(1)] + new_block + text[m.end(1):]
            count += n
    return text, count


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_surgical_verify(guide_dir: str, pkg_path: str) -> dict:
    """Apply surgical fixes to all ``.md`` files in *guide_dir*.

    Returns a summary dict with ``property_fixes``, ``required_fixes``,
    and ``pages_fixed``.
    """
    classes = build_class_index(pkg_path)
    total_prop = 0
    total_req = 0
    pages_fixed = 0

    for md in sorted(Path(guide_dir).glob("*.md")):
        text = md.read_text(encoding="utf-8")
        new_text, n_prop = fix_property_calls(text, classes)
        new_text, n_req = fix_missing_required(new_text, classes)
        if n_prop or n_req:
            md.write_text(new_text, encoding="utf-8")
            total_prop += n_prop
            total_req += n_req
            pages_fixed += 1

    return {
        "property_fixes": total_prop,
        "required_fixes": total_req,
        "pages_fixed": pages_fixed,
        "classes_indexed": len(classes),
    }
