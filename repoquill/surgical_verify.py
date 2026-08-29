"""Deterministic surgical verification pass for generated guide pages.

Fixes the two dominant example-validity finding types (E12) without an
LLM rewrite:

  1. property_called_as_method — strip trailing ``()`` from ``@property``
     calls (e.g. ``results.passed()`` → ``results.passed``).
  2. missing_required — insert required ``__init__`` kwargs that a
     constructor call in a code block is missing.  The value is inferred
     from sibling kwargs (e.g. ``judge_provider`` mirrors ``provider``
     when both are model-auditor-style params) or from the param's
     default in the AST.  If no valid value can be inferred, the kwarg
     is omitted and a comment is added instead of inserting a sentinel.

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
    """Return ``{ClassName: {init_params, init_defaults, properties, methods}}``.

    ``init_params`` maps parameter name → has_default (bool).
    ``init_defaults`` maps parameter name → default value (as source
    string, via ``ast.unparse``), or ``None`` if no default.  ``self``
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
            info = {
                "init_params": {},
                "init_defaults": {},
                "properties": set(),
                "methods": set(),
            }
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
                        has_def = i in default_map
                        info["init_params"][a.arg] = has_def
                        if has_def:
                            di = i - (n_args - n_defaults)
                            if di < len(defaults):
                                try:
                                    info["init_defaults"][a.arg] = ast.unparse(defaults[di])
                                except Exception:
                                    info["init_defaults"][a.arg] = None
                            else:
                                info["init_defaults"][a.arg] = None
                        else:
                            info["init_defaults"][a.arg] = None
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


def _normalize_quotes(src: str) -> str:
    """Convert single-quoted strings to double-quoted for consistency."""
    if src.startswith("'") and src.endswith("'") and src.count("'") == 2:
        return '"' + src[1:-1] + '"'
    return src


def _infer_value(
    param: str,
    present_kwargs: dict[str, str],
    info: dict,
) -> str | None:
    """Infer a value for *param* from sibling kwargs or the AST default.

    Returns a source-ready string (e.g. ``'"ollama"'``) or ``None`` if
    no valid value can be inferred.
    """
    init_defaults = info.get("init_defaults", {})

    # Rule 1: if the param has a default in the AST, use it.
    default_src = init_defaults.get(param)
    if default_src is not None:
        return _normalize_quotes(default_src)

    # Rule 2: judge/sibling mirroring.
    # If param is "judge_X" and "X" is present, mirror X's value.
    if param.startswith("judge_"):
        base = param[len("judge_"):]
        if base in present_kwargs:
            return _normalize_quotes(present_kwargs[base])

    # Rule 3: if param is "provider" and "judge_provider" is present,
    # mirror judge_provider (the reverse direction).
    if param == "provider" and "judge_provider" in present_kwargs:
        return _normalize_quotes(present_kwargs["judge_provider"])

    return None


def _fix_missing_required_in_block(block: str, classes: dict) -> tuple[str, int]:
    """Fix missing required kwargs in a single python code block (no fences).

    For each missing required kwarg, tries to infer a valid value:
      1. AST default (if the param has one).
      2. Sibling mirroring (e.g. ``judge_provider`` ← ``provider``).
    If no value can be inferred, the kwarg is omitted and a comment
    ``# NOTE: <arg> is required`` is inserted instead.
    """
    try:
        tree = ast.parse(block)
    except SyntaxError:
        return block, 0

    # Collect all Call nodes that are constructor calls for known classes.
    call_fixes: list[tuple[int, list[tuple[str, str]]]] = []
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
        # Map present kwargs to their source values.
        present_kwargs: dict[str, str] = {}
        for kw in node.keywords:
            if kw.arg is not None:
                try:
                    present_kwargs[kw.arg] = ast.unparse(kw.value)
                except Exception:
                    present_kwargs[kw.arg] = ""
        missing = required - set(present_kwargs.keys())
        if not missing:
            continue
        # For each missing param, try to infer a value.
        inferred: list[tuple[str, str]] = []
        for param in sorted(missing):
            val = _infer_value(param, present_kwargs, info)
            if val is not None:
                inferred.append((param, val))
            else:
                inferred.append((param, ""))  # empty = omit + comment
        call_fixes.append((node.lineno, inferred))

    if not call_fixes:
        return block, 0

    lines = block.split("\n")
    count = 0
    for line_no, inferred in sorted(call_fixes, key=lambda x: x[0], reverse=True):
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
        # Build the insertion: kwargs with inferred values, or comments.
        parts: list[str] = []
        for param, val in inferred:
            if val:
                parts.append(f"    {param}={val}")
            else:
                parts.append(f"    # NOTE: {param} is required (no default)")
        # Check if the line before the closing paren already ends with a comma
        # (i.e., the last kwarg before the close has a trailing comma).
        # If so, don't add another comma.
        # Find the last non-empty, non-comment line before close_idx.
        last_content_idx = close_idx - 1
        while last_content_idx >= idx:
            stripped = lines[last_content_idx].strip()
            if stripped and not stripped.startswith("#"):
                break
            last_content_idx -= 1
        if last_content_idx >= idx:
            last_content = lines[last_content_idx].rstrip()
            if last_content.endswith(","):
                insert_text = "\n" + ",\n".join(parts)
            else:
                insert_text = ",\n" + ",\n".join(parts)
        else:
            insert_text = "\n" + ",\n".join(parts)
        lines[close_idx] = close_line[:paren_idx] + insert_text + "\n" + close_line[paren_idx:]
        count += len(inferred)

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
