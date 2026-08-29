"""Layer 1: deterministic API reference via Griffe.

Scans the package source tree and renders a complete, always-accurate API
reference (classes, functions, signatures, docstrings, constants) into
``site_src/reference/*.md`` using mkdocstrings ``::: module`` directives.

This layer uses NO LLM — it is purely deterministic. Griffe parses the
source; mkdocstrings renders the API at build time, which enables
``show_source``, source links, and all other mkdocstrings options.

Modules whose parent directory lacks an ``__init__.py`` are skipped (they
are not importable as part of the package).
"""

from __future__ import annotations

import ast
import os
import re
from typing import List, Optional


# ---------------------------------------------------------------------------
# File utilities
# ---------------------------------------------------------------------------

def _read_file(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def get_source_files(pkg_path: str) -> dict:
    """Read all ``.py`` files under the package into {relpath: content}.

    Args:
        pkg_path: Absolute path to the package directory.

    Returns:
        Mapping of package-relative path to file content.
    """
    files = {}
    for dirpath, _, filenames in os.walk(pkg_path):
        for f in filenames:
            if f.endswith(".py"):
                full = os.path.join(dirpath, f)
                rel = os.path.relpath(full, pkg_path)
                files[rel] = _read_file(full)
    return files


def get_file_tree(pkg_path: str) -> str:
    """Return a human-readable tree of the package directory.

    Args:
        pkg_path: Absolute path to the package directory.

    Returns:
        Multi-line string describing the directory structure.
    """
    lines = []
    for dirpath, dirnames, filenames in os.walk(pkg_path):
        dirnames.sort()
        rel = os.path.relpath(dirpath, pkg_path)
        depth = 0 if rel == "." else rel.count(os.sep)
        indent = "  " * depth
        lines.append(f"{indent}{os.path.basename(dirpath)}/")
        for f in sorted(filenames):
            if f.endswith(".py"):
                lines.append(f"{indent}  {f}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Griffe helpers
# ---------------------------------------------------------------------------

def _griffe_docstring(obj):
    """Best-effort docstring text for a Griffe object (never raises)."""
    try:
        doc = obj.docstring
    except Exception:  # noqa: BLE001
        return ""
    if doc is None:
        return ""
    text = getattr(doc, "value", doc)
    if text is None:
        return ""
    return str(text).strip()


def _griffe_signature(obj):
    """Best-effort signature string (never raises)."""
    try:
        sig = obj.signature
        if callable(sig):
            sig = sig()
        return str(sig)
    except Exception:  # noqa: BLE001
        return ""


def _is_public_member(obj):
    """True for real classes/functions/constants (not re-exported imports)."""
    import griffe
    return isinstance(obj, (griffe.Class, griffe.Function, griffe.Attribute))


def _resolve_alias(obj):
    """Resolve a Griffe Alias to its target object, or None on failure."""
    import griffe
    if not isinstance(obj, griffe.Alias):
        return obj
    try:
        return obj.target
    except Exception:  # noqa: BLE001
        return None


def _main_guard_line(mod):
    """Return the 1-indexed line of the ``if __name__ == "__main__":`` guard."""
    try:
        src = mod.source
    except Exception:  # noqa: BLE001
        return None
    if not src:
        return None
    for i, line in enumerate(src.splitlines(), 1):
        if "__name__" in line and "__main__" in line:
            return i
    return None


def _member_lineno(obj):
    """Best-effort 1-indexed source line for a member (None on failure)."""
    try:
        return obj.lineno
    except Exception:  # noqa: BLE001
        return None


def _render_member_md(name, obj, depth=3, module_members=None):
    """Render one class/function/attribute as markdown."""
    import griffe
    Class, Function = griffe.Class, griffe.Function

    lines = []
    header = "#" * depth
    doc = _griffe_docstring(obj)
    doc_lines = [l for l in doc.splitlines() if l.strip()] if doc else []

    if isinstance(obj, Class):
        lines.append(f"{header} `{name}`")
        if doc_lines:
            lines.append("")
            lines.extend(_format_docstring(doc))
            lines.append("")
        init = None
        try:
            for attr in obj.attributes.values():
                if attr.name == "__init__":
                    init = attr
                    break
        except Exception:  # noqa: BLE001
            pass
        if init is not None:
            sig = _griffe_signature(init)
            if sig:
                lines.append(f"**Signature:** `{sig}`")
                lines.append("")
        try:
            members = list(obj.members.values())
        except Exception:  # noqa: BLE001
            members = []
        methods = [a for a in members
                   if isinstance(a, Function) and not a.name.startswith("_")]
        if methods:
            lines.append("**Methods:**")
            lines.append("")
            for m in methods:
                mdoc = _griffe_docstring(m)
                first = mdoc.splitlines()[0].strip() if mdoc else ""
                msig = _griffe_signature(m)
                label = msig if msig else f"{m.name}()"
                try:
                    if m.source and m.source.lstrip().startswith("async def"):
                        label = f"async {label}"
                except Exception:  # noqa: BLE001
                    pass
                lines.append(f"- `{label}` — {first}" if first else f"- `{label}`")
            lines.append("")
        try:
            attrs = [a for a in obj.attributes.values() if not a.name.startswith("_")]
        except Exception:  # noqa: BLE001
            attrs = []
        if attrs:
            lines.append("**Attributes:**")
            lines.append("")
            for a in attrs:
                adoc = _griffe_docstring(a)
                first = adoc.splitlines()[0].strip() if adoc else ""
                lines.append(f"- `{a.name}` — {first}" if first else f"- `{a.name}`")
            lines.append("")
    elif isinstance(obj, Function):
        sig = _griffe_signature(obj)
        is_async = False
        try:
            if obj.source and obj.source.lstrip().startswith("async def"):
                is_async = True
        except Exception:  # noqa: BLE001
            pass
        label = sig if sig else f"{name}()"
        if is_async:
            label = f"async {label}"
        lines.append(f"{header} `{label}`")
        if doc_lines:
            lines.append("")
            lines.extend(_format_docstring(doc))
            lines.append("")
    else:
        lines.append(f"{header} `{name}`")
        if doc_lines:
            lines.append("")
            lines.extend(doc_lines)
            lines.append("")
        try:
            val = obj.value
        except Exception:  # noqa: BLE001
            val = None
        vtype = type(val).__name__ if val is not None else ""
        rendered_rich = False
        if "list" in vtype.lower() and val is not None:
            elements = getattr(val, "elements", None)
            if elements and len(elements) > 0:
                el0 = elements[0]
                k0 = getattr(el0, "keys", None)
                if k0 is not None:
                    k0_stripped = [_strip_token(k) for k in k0]
                    if "name" in k0_stripped and "description" in k0_stripped:
                        table = _render_name_desc_list_md(val)
                        if table:
                            lines.append("")
                            lines.extend(table)
                            lines.append("")
                            rendered_rich = True
        if not rendered_rich and "dict" in vtype.lower() and val is not None:
            config_md = _render_config_dict_md(val)
            if config_md:
                lines.append("")
                lines.extend(config_md)
                lines.append("")
                rendered_rich = True
        if not rendered_rich and not doc_lines:
            size_note = _describe_constant_value(obj, module_members)
            if size_note:
                lines.append("")
                lines.append(f"_{size_note}_")
                lines.append("")
    return lines


def _format_docstring(doc):
    """Format a docstring for markdown, handling numpydoc sections."""
    import textwrap
    if not doc:
        return []
    text = textwrap.dedent(doc)
    lines = text.splitlines()
    section_headers = {
        "args", "arguments", "parameters", "returns", "yields", "raises",
        "examples", "example", "attributes", "note", "notes", "see also",
        "references", "todo", "warning", "warnings",
    }
    out = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.endswith(":") and stripped[:-1].strip().lower() in section_headers:
            if out and out[-1].strip():
                out.append("")
            out.append(stripped)
            continue
        if stripped.lower() in section_headers and i + 1 < len(lines) \
                and set(lines[i + 1].strip()) <= {"-"} and lines[i + 1].strip():
            if out and out[-1].strip():
                out.append("")
            out.append(stripped + ":")
            continue
        if stripped.startswith("**") and stripped.endswith("**"):
            inner = stripped[2:-2].strip()
            if ":" in inner:
                colon = inner.find(":")
                param = inner[:colon].strip()
                rest = inner[colon + 1:].strip()
                line = line.replace(stripped, f"*{param}*: {rest}", 1)
            else:
                line = line.replace(stripped, f"*{inner}*", 1)
        elif stripped.startswith("**") and not stripped.endswith("**"):
            param = stripped[2:].strip()
            line = line.replace(stripped, f"*{param}*", 1)
        out.append(line)
    return out


def _strip_token(tok):
    """Strip quotes from a Griffe source token."""
    if isinstance(tok, str):
        s = tok.strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
            return s[1:-1]
        return s
    return str(tok)


def _describe_constant_value(obj, module_members=None):
    """Return a short human description of a constant's value, or ''."""
    try:
        val = obj.value
    except Exception:  # noqa: BLE001
        return ""
    if val is None:
        return ""
    vtype = type(val).__name__
    if hasattr(val, "as_posix"):
        return f"Path: `{val.as_posix()}`"
    if isinstance(val, str):
        if len(val) <= 80:
            return f"Value: `{val}`"
        return f"String ({len(val)} chars)"
    if isinstance(val, (int, float, bool)):
        return f"Value: `{val}`"
    if isinstance(val, list):
        if len(val) <= 8:
            items = ", ".join(repr(v) for v in val)
            return f"List: [{items}]"
        return f"List of {len(val)} items"
    if isinstance(val, dict):
        if "description" in val:
            return f"Config: {val['description']}"
        return f"Dict with {len(val)} keys"
    return ""


def _render_name_desc_list_md(val, depth=4):
    """Render a list-of-dicts with name/description as a markdown table."""
    elements = getattr(val, "elements", None)
    if elements is None:
        return []
    rows = []
    for el in elements:
        keys = getattr(el, "keys", None)
        values = getattr(el, "values", None)
        if keys is None or values is None:
            continue
        d = {}
        for i in range(len(keys)):
            k = _strip_token(keys[i])
            v = _strip_token(values[i])
            d[k] = v
        name = d.get("name", "")
        desc = d.get("description", "")
        if name:
            rows.append(f"| {name} | {desc} |")
    if not rows:
        return []
    return ["| Name | Description |", "| --- | --- |"] + rows


def _render_config_dict_md(val, depth=4):
    """Render a config dict with description/prompt fields as markdown."""
    keys = getattr(val, "keys", None)
    values = getattr(val, "values", None)
    if keys is None or values is None:
        return []
    d = {}
    for i in range(len(keys)):
        k = _strip_token(keys[i])
        v = values[i]
        if isinstance(v, str):
            d[k] = _strip_token(v)
        else:
            d[k] = v
    if "description" not in d:
        return []
    lines = []
    if d.get("name"):
        lines.append(f"**Name:** {d['name']}")
        lines.append("")
    if d.get("description"):
        lines.append(d["description"])
        lines.append("")
    for prompt_key in ("judge_prompt", "prompt", "system_prompt"):
        jp = d.get(prompt_key, "")
        if jp and isinstance(jp, str):
            jp_text = jp.replace("\\n", "\n")
            criteria = []
            in_criteria = False
            for line in jp_text.splitlines():
                stripped = line.strip()
                if "EVALUATION CRITERIA" in stripped.upper() or "CRITERIA" in stripped.upper():
                    in_criteria = True
                    continue
                if in_criteria:
                    if stripped and (stripped[0].isdigit() or stripped.startswith("-")):
                        criteria.append(stripped)
                    elif stripped and criteria:
                        break
                    elif not stripped and criteria:
                        break
            if criteria:
                lines.append("**Evaluation criteria:**")
                lines.append("")
                for c in criteria:
                    lines.append(f"- {c}")
                lines.append("")
            break
    src = d.get("source")
    if src is not None:
        if isinstance(src, str):
            lines.append(f"**Source:** {src}")
            lines.append("")
        else:
            src_keys = getattr(src, "keys", None)
            src_vals = getattr(src, "values", None)
            if src_keys is not None and src_vals is not None:
                lines.append("**Source:**")
                lines.append("")
                for i in range(len(src_keys)):
                    sk = _strip_token(src_keys[i])
                    sv = src_vals[i]
                    if isinstance(sv, str):
                        sv = _strip_token(sv)
                    lines.append(f"- {sk}: {sv}")
                lines.append("")
    return lines


def _list_size(obj):
    """Element count of a list-valued member, or None."""
    if obj is None:
        return None
    try:
        val = obj.value
    except Exception:  # noqa: BLE001
        return None
    elements = getattr(val, "elements", None)
    if elements is not None:
        try:
            return len(elements)
        except Exception:  # noqa: BLE001
            return None
    if isinstance(val, list):
        return len(val)
    return None


def _list_inline_values(val):
    """Render a small Griffe ExprList's string elements inline, or ''."""
    elements = getattr(val, "elements", None)
    if elements is None:
        return ""
    parts = []
    for el in elements:
        v = getattr(el, "value", el)
        if isinstance(v, str):
            s = v.strip()
            if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
                s = s[1:-1]
            parts.append(s)
    return ", ".join(parts) if parts else ""


def _dict_description(val):
    """Extract a human description from a Griffe ExprDict, or ''."""
    keys = getattr(val, "keys", None)
    values = getattr(val, "values", None)
    if keys is None or values is None:
        return ""
    try:
        n = len(keys)
    except Exception:  # noqa: BLE001
        return ""
    for i in range(n):
        k = keys[i]
        if not isinstance(k, str):
            k = getattr(k, "value", k)
        if not isinstance(k, str):
            continue
        if k.strip().strip("'\"") == "description":
            v = values[i]
            if not isinstance(v, str):
                v = getattr(v, "value", v)
            if isinstance(v, str):
                s = v.strip()
                if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
                    s = s[1:-1]
                return s
    return ""


def _extract_all_names(all_attr):
    """Extract the list of public names from a module's ``__all__`` attribute."""
    try:
        raw = all_attr.value
    except Exception:  # noqa: BLE001
        return []
    if raw is None:
        return []
    names = []
    for item in raw:
        val = getattr(item, "value", item)
        if not isinstance(val, str):
            continue
        s = val.strip()
        if s in ("[", "]", ","):
            continue
        if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
            s = s[1:-1]
        if s and s.isidentifier():
            names.append(s)
    return names


def _render_module_via_ast(module_name, py_path, module_descriptions=None):
    """Render a module page using Python's ast module (fallback)."""
    import ast

    with open(py_path) as f:
        source = f.read()

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return (f"## {module_name}\n\n"
                f"> Could not parse this module: `{e}`\n")

    lines = [f"## {module_name}", ""]
    module_descriptions = module_descriptions or {}
    desc = module_descriptions.get(module_name)
    mod_doc = ast.get_docstring(tree)
    if desc:
        lines += [desc, ""]
    if mod_doc:
        doc_body = mod_doc.strip()
        if not (desc and doc_body.splitlines()[0].strip() == desc):
            lines += [doc_body, ""]

    classes = []
    functions = []
    constants = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            if not node.name.startswith("_"):
                doc = ast.get_docstring(node) or ""
                classes.append((node.name, doc))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                doc = ast.get_docstring(node) or ""
                args = []
                for a in node.args.args:
                    args.append(a.arg)
                if node.args.vararg:
                    args.append("*" + node.args.vararg.arg)
                for a in node.args.kwonlyargs:
                    args.append(a.arg)
                if node.args.kwarg:
                    args.append("**" + node.args.kwarg.arg)
                sig = f"({', '.join(args)})"
                prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
                functions.append((node.name, f"{prefix}def {node.name}{sig}", doc))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    constants.append(target.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and not node.target.id.startswith("_"):
                constants.append(node.target.id)

    if classes:
        lines += ["### Classes", ""]
        for name, doc in classes:
            lines += [f"#### {name}", ""]
            if doc:
                lines += [doc.strip(), ""]
            else:
                lines += ["_No docstring._", ""]

    if functions:
        lines += ["### Functions", ""]
        for name, sig, doc in functions:
            lines += [f"#### {name}", ""]
            lines += [f"```python", sig, "```", ""]
            if doc:
                lines += [doc.strip(), ""]
            else:
                lines += ["_No docstring._", ""]

    if constants:
        lines += ["### Constants", ""]
        for name in constants:
            lines += [f"- `{name}`", ""]

    if not (classes or functions or constants):
        lines += ["_No public members found._", ""]

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_module_reference(module_name: str, search_path: str,
                            module_descriptions: Optional[dict] = None) -> str:
    """Render a single module's API reference markdown.

    Uses Griffe to load the module and emit an mkdocstrings
    ``::: module`` directive page. Falls back to an AST-based renderer
    if Griffe cannot load the module.

    Args:
        module_name: Dotted module name (e.g. ``mypackage.submodule``).
        search_path: Root path to add to Griffe's search paths.
        module_descriptions: Optional mapping of module name -> one-line
            description, prepended to the page when present.

    Returns:
        Markdown content for the reference page.
    """
    import griffe
    Class, Function = griffe.Class, griffe.Function

    try:
        mod = griffe.load(module_name, search_paths=[search_path])
    except Exception:  # noqa: BLE001
        py_path = os.path.join(search_path, *module_name.split(".")) + ".py"
        if os.path.isfile(py_path):
            return _render_module_via_ast(module_name, py_path, module_descriptions)
        else:
            return (f"## {module_name}\n\n"
                    f"> Could not locate source file for this module.\n")

    lines = [f"## {module_name}", ""]
    module_descriptions = module_descriptions or {}
    desc = module_descriptions.get(module_name)
    mod_doc = _griffe_docstring(mod)
    if desc:
        lines += [desc, ""]
    if mod_doc:
        doc_body = mod_doc.strip()
        if not (desc and doc_body.splitlines()[0].strip() == desc):
            lines += [doc_body, ""]

    try:
        all_members = dict(mod.members)
    except Exception:  # noqa: BLE001
        all_members = {}

    main_line = _main_guard_line(mod)

    members = {}
    for name, obj in all_members.items():
        if name.startswith("_"):
            continue
        if main_line is not None:
            ln = _member_lineno(obj)
            if ln is not None and ln >= main_line:
                continue
        if _is_public_member(obj):
            members[name] = obj
        else:
            resolved = _resolve_alias(obj)
            if resolved is not None and _is_public_member(resolved):
                members[name] = resolved

    all_attr = all_members.get("__all__")
    if all_attr is not None:
        ordered = _extract_all_names(all_attr)
        if ordered:
            members = {n: members[n] for n in ordered if n in members}

    if not members:
        lines += ["_No public members found._", ""]
        return "\n".join(lines) + "\n"

    classes = {n: o for n, o in members.items() if isinstance(o, Class)}
    functions = {n: o for n, o in members.items() if isinstance(o, Function)}
    constants = {n: o for n, o in members.items()
                 if not isinstance(o, (Class, Function))}

    if classes:
        lines += ["### Classes", ""]
        for n, o in classes.items():
            lines += _render_member_md(n, o, depth=4)
    if functions:
        lines += ["### Functions", ""]
        for n, o in functions.items():
            lines += _render_member_md(n, o, depth=4)
    if constants:
        lines += ["### Constants", ""]
        for n, o in constants.items():
            lines += _render_member_md(n, o, depth=4, module_members=all_members)

    return "\n".join(lines) + "\n"


def extract_api_surface(pkg_path: str, max_chars: int = 12000) -> str:
    """Extract a compact, ground-truth API surface from the package source.

    Uses pure AST parsing (no LLM, no imports) to list every public
    class, function, method, and constant with its signature. This is
    injected into narrative-generation prompts so the LLM can only use
    symbols that actually exist.

    Args:
        pkg_path: Absolute path to the package directory.
        max_chars: Truncate the result to this many characters.

    Returns:
        Multi-line string describing the real API surface.
    """
    pkg_name = os.path.basename(os.path.normpath(pkg_path))
    classes: dict = {}   # "Mod.Class" -> ["method(self, x, y)", ...]
    functions: dict = {} # "mod.func" -> "(a, b, c)"
    constants: dict = {} # "mod.CONST" -> value (short)

    for dirpath, _, filenames in os.walk(pkg_path):
        for f in sorted(filenames):
            if not f.endswith(".py"):
                continue
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, pkg_path)
            mod = rel[:-3].replace(os.sep, ".")
            if mod.endswith(".__init__"):
                mod = mod[:-9]
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as fh:
                    tree = ast.parse(fh.read())
            except SyntaxError:
                continue

            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    methods = []
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            if not item.name.startswith("_"):
                                args = [a.arg for a in item.args.args]
                                if args and args[0] in ("self", "cls"):
                                    args = args[1:]
                                methods.append(f"{item.name}({', '.join(args)})")
                    classes[f"{mod}.{node.name}"] = methods
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not node.name.startswith("_"):
                        args = [a.arg for a in node.args.args]
                        functions[f"{mod}.{node.name}"] = f"({', '.join(args)})"
                elif isinstance(node, ast.Assign):
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name) and tgt.id.isupper():
                            try:
                                val = ast.literal_eval(node.value)
                                sval = repr(val)
                                if len(sval) > 60:
                                    sval = sval[:57] + "..."
                            except Exception:  # noqa: BLE001
                                sval = "..."
                            constants[f"{mod}.{tgt.id}"] = sval

    lines = []
    if classes:
        lines.append("CLASSES (name -> public methods):")
        for cname, methods in sorted(classes.items()):
            m = ", ".join(methods) if methods else "(no public methods)"
            lines.append(f"  {cname}: {m}")
    if functions:
        lines.append("FUNCTIONS:")
        for fname, sig in sorted(functions.items()):
            lines.append(f"  {fname}{sig}")
    if constants:
        lines.append("CONSTANTS:")
        for cname, val in sorted(constants.items()):
            lines.append(f"  {cname} = {val}")

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... (truncated)"
    return text


def get_examples_context(root: str, max_chars: int = 4000) -> str:
    """Build a context block from the repo's examples/ directory.

    Lists example files and includes the first ~1500 chars of the most
    instructive ones (quickstart-style scripts). Generic: works for any
    repo that has an examples/ or examples dir at the root.

    Args:
        root: Absolute path to the repo root.
        max_chars: Truncate the result to this many characters.

    Returns:
        Multi-line string, or empty string if no examples found.
    """
    for cand in ("examples", "example", "examples/", "scripts"):
        ex_dir = os.path.join(root, cand.rstrip("/"))
        if os.path.isdir(ex_dir):
            break
    else:
        return ""

    files = []
    for f in sorted(os.listdir(ex_dir)):
        if f.endswith((".py", ".ipynb", ".sh")):
            files.append(f)
    if not files:
        return ""

    lines = [f"Files in {os.path.basename(ex_dir)}/: {', '.join(files)}"]
    # Include the first few .py examples (most likely to be quickstarts)
    included = 0
    for f in files:
        if not f.endswith(".py") or included >= 3:
            continue
        full = os.path.join(ex_dir, f)
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read(1500)
        except OSError:
            continue
        lines.append(f"\n### {f} (excerpt)\n```python\n{content}\n```")
        included += 1

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... (truncated)"
    return text


def extract_cli_surface(pkg_path: str, max_chars: int = 8000) -> str:
    """Extract the argparse CLI surface from the package source.

    Walks all .py files, finds ``argparse.ArgumentParser`` +
    ``add_subparsers`` + ``add_parser`` + ``add_argument`` calls, and
    returns a structured list of (prog, subcommand, flags, defaults, help).

    This is injected into narrative-generation prompts for CLI-related
    pages so the LLM can only document commands and flags that actually
    exist. Generic: works for any repo with an argparse-based CLI.

    Args:
        pkg_path: Absolute path to the package directory.
        max_chars: Truncate the result to this many characters.

    Returns:
        Multi-line string describing the real CLI surface, or empty
        string if no argparse usage found.
    """
    cli_files = []  # list of (prog, subcommands)
    # subcommands: dict of subcommand_name -> list of (flag, type, default, help)

    for dirpath, _, filenames in os.walk(pkg_path):
        for f in sorted(filenames):
            if not f.endswith(".py"):
                continue
            full = os.path.join(dirpath, f)
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as fh:
                    tree = ast.parse(fh.read())
            except SyntaxError:
                continue

            # Check if this file uses argparse
            uses_argparse = False
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "argparse":
                            uses_argparse = True
                elif isinstance(node, ast.ImportFrom):
                    if node.module and "argparse" in node.module:
                        uses_argparse = True
            if not uses_argparse:
                continue

            # Extract prog name from ArgumentParser(...) call
            prog = None
            subparsers_var = None  # variable name holding the subparsers
            subcommands = {}  # subcommand_name -> {"help": str, "args": [...]}

            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func

                # ArgumentParser(...)
                if isinstance(func, ast.Attribute) and func.attr == "ArgumentParser":
                    for kw in node.keywords:
                        if kw.arg == "prog" and isinstance(kw.value, ast.Constant):
                            prog = kw.value.value

                # add_subparsers(...)
                elif isinstance(func, ast.Attribute) and func.attr == "add_subparsers":
                    # Capture the variable this is assigned to
                    pass

                # add_parser("name", help="...")
                elif isinstance(func, ast.Attribute) and func.attr == "add_parser":
                    sub_name = None
                    sub_help = ""
                    if node.args and isinstance(node.args[0], ast.Constant):
                        sub_name = node.args[0].value
                    for kw in node.keywords:
                        if kw.arg == "help" and isinstance(kw.value, ast.Constant):
                            sub_help = kw.value.value
                    if sub_name:
                        subcommands[sub_name] = {"help": sub_help, "args": []}

                # add_argument(...)
                elif isinstance(func, ast.Attribute) and func.attr == "add_argument":
                    # Determine which subparser this belongs to
                    # (we can't easily track the receiver, so we attach
                    #  to the most recently seen subcommand, or to root)
                    flags = []
                    arg_type = None
                    default = None
                    help_text = ""
                    for arg in node.args:
                        if isinstance(arg, ast.Constant):
                            flags.append(arg.value)
                    for kw in node.keywords:
                        if kw.arg == "type" and isinstance(kw.value, ast.Name):
                            arg_type = kw.value.id
                        elif kw.arg == "default":
                            if isinstance(kw.value, ast.Constant):
                                default = repr(kw.value.value)
                            elif isinstance(kw.value, ast.NameConstant):
                                default = repr(kw.value.value)
                        elif kw.arg == "help" and isinstance(kw.value, ast.Constant):
                            help_text = kw.value.value

                    # Attach to the last subcommand seen, or to root
                    # (simplification: attach to all subcommands if any,
                    #  else to root — good enough for prompt context)
                    if subcommands:
                        # Attach to the last subcommand
                        last_sub = list(subcommands.keys())[-1]
                        subcommands[last_sub]["args"].append(
                            (flags, arg_type, default, help_text)
                        )
                    else:
                        if "root" not in subcommands:
                            subcommands["root"] = {"help": "", "args": []}
                        subcommands["root"]["args"].append(
                            (flags, arg_type, default, help_text)
                        )

            if prog or subcommands:
                cli_files.append((prog or "unknown", subcommands))

    if not cli_files:
        return ""

    lines = []
    for prog, subcommands in cli_files:
        lines.append(f"Program: {prog}")
        if "root" in subcommands and subcommands["root"]["args"]:
            lines.append("  Root-level arguments:")
            for flags, arg_type, default, help_text in subcommands["root"]["args"]:
                flag_str = " ".join(flags)
                type_str = f" (type: {arg_type})" if arg_type else ""
                default_str = f" (default: {default})" if default else ""
                help_str = f" — {help_text}" if help_text else ""
                lines.append(f"    {flag_str}{type_str}{default_str}{help_str}")
        for sub_name, sub_info in subcommands.items():
            if sub_name == "root":
                continue
            help_str = f" — {sub_info['help']}" if sub_info["help"] else ""
            lines.append(f"  Command: {sub_name}{help_str}")
            for flags, arg_type, default, help_text in sub_info["args"]:
                flag_str = " ".join(flags)
                type_str = f" (type: {arg_type})" if arg_type else ""
                default_str = f" (default: {default})" if default else ""
                h_str = f" — {help_text}" if help_text else ""
                lines.append(f"    {flag_str}{type_str}{default_str}{h_str}")

    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... (truncated)"
    return text


def build_api_reference(cfg) -> List[str]:
    """Generate ``reference/*.md`` for every importable module.

    Walks the package, writes one mkdocstrings directive page per module,
    and cleans up stale reference pages.

    Args:
        cfg: A :class:`repoquill.config.RepoQuillConfig`.

    Returns:
        List of documented module names.
    """
    ref_dir = cfg.ref_dir
    pkg_path = cfg.pkg_path
    root = cfg.root
    module_descriptions = cfg.raw.get("module_descriptions", {})

    os.makedirs(ref_dir, exist_ok=True)
    modules = []
    for dirpath, _, filenames in os.walk(pkg_path):
        for f in filenames:
            if not f.endswith(".py"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, f), root)
            mod = rel[:-3].replace(os.sep, ".")
            if mod.endswith(".__init__"):
                mod = mod[:-9]
            modules.append(mod)
    modules.sort()

    rendered = []
    for mod in modules:
        # Skip modules in directories without __init__.py (not importable)
        parts = mod.split(".")
        # Walk up: each parent package must have __init__.py
        importable = True
        for i in range(1, len(parts)):
            parent_dir = os.path.join(root, *parts[:i])
            if not os.path.isfile(os.path.join(parent_dir, "__init__.py")):
                importable = False
                break
        if not importable:
            print(f"    reference: {mod} (skipped — no __init__.py in parent)")
            continue
        print(f"    reference: {mod}")
        desc = module_descriptions.get(mod, "")
        lines = [f"## {mod}", ""]
        if desc:
            lines += [desc, ""]
        lines += ["::: " + mod, ""]
        content = "\n".join(lines)
        slug = mod.replace(".", "_")
        with open(os.path.join(ref_dir, f"{slug}.md"), "w") as f:
            f.write(content)
        rendered.append((mod, slug))

    current = {slug for _, slug in rendered}
    for fname in os.listdir(ref_dir):
        if fname.endswith(".md") and fname[:-3] not in current:
            os.remove(os.path.join(ref_dir, fname))
    return rendered
