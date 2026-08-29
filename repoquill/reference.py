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
    classes: dict = {}   # "Mod.Class" -> (["method(self, x, y)", ...], ["prop", ...])
    functions: dict = {} # "mod.func" -> "(a, b, c)"
    constants: dict = {} # "mod.CONST" -> value (short)

    # E43: container-protocol dunders that define iteration, indexing,
    # and length semantics.  These are essential for documenting
    # collection types and must be explicitly listed so the LLM
    # knows to document iteration/indexing behavior.
    _CONTAINER_DUNDERS = frozenset({
        "__iter__", "__getitem__", "__len__", "__contains__",
        "__next__", "__reversed__", "__setitem__", "__delitem__",
    })

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
                    properties = []
                    container_protocols = []
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            if not item.name.startswith("_"):
                                # E27: detect @property (and @cached_property)
                                # decorators so the LLM uses them as
                                # attributes, not methods.
                                is_prop = any(
                                    (isinstance(d, ast.Name) and d.id in
                                     ("property", "cached_property")) or
                                    (isinstance(d, ast.Attribute) and d.attr in
                                     ("property", "cached_property"))
                                    for d in item.decorator_list
                                )
                                if is_prop:
                                    properties.append(item.name)
                                else:
                                    args = [a.arg for a in item.args.args]
                                    if args and args[0] in ("self", "cls"):
                                        args = args[1:]
                                    methods.append(f"{item.name}({', '.join(args)})")
                            elif item.name in _CONTAINER_DUNDERS:
                                # E43: track container-protocol dunders
                                # explicitly so the LLM knows to document
                                # iteration/indexing behavior.
                                container_protocols.append(item.name)
                    classes[f"{mod}.{node.name}"] = (methods, properties, container_protocols)
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
        lines.append("CLASSES (name -> public methods; PROPERTIES are attributes, not methods):")
        for cname, (methods, props, container_protocols) in sorted(classes.items()):
            m = ", ".join(methods) if methods else "(no public methods)"
            if props:
                m += f"  [PROPERTIES: {', '.join(props)}]"
            if container_protocols:
                m += f"  [CONTAINER PROTOCOLS: {', '.join(sorted(container_protocols))}]"
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


def extract_constructor_signatures(
    pkg_path: str, names: set, max_chars: int = 4000
) -> str:
    """Extract exact ``__init__`` signatures for the given class names.

    E14: page-relevant constructor context.  When the LLM writes code
    examples it must know the exact parameter names, order, and defaults
    of the constructors it calls.  ``extract_api_surface`` lists method
    *names* but not full signatures, so the model sometimes invents
    kwarg names.  This function fills that gap with deterministic,
    AST-derived constructor signatures.

    Args:
        pkg_path: Absolute path to the package directory.
        names: Set of class or function names to include.  A class is
            included when its name (or any dotted suffix, e.g.
            ``"results.AuditResults"`` matches ``"AuditResults"``) is in
            the set.  A free function is included when its name is in
            the set.
        max_chars: Truncate the result to this many characters.

    Returns:
        Multi-line string with exact signatures, or empty string if
        nothing matches.
    """
    lines: list = []
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
            except (SyntaxError, OSError):
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    short = node.name
                    dotted = f"{mod}.{node.name}"
                    if short not in names and dotted not in names:
                        continue
                    init = None
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                            init = item
                            break
                    if init is None:
                        lines.append(f"  {dotted}(): (no custom __init__)")
                        continue
                    args = _sig_args(init)
                    lines.append(f"  {dotted}.__init__({', '.join(args)})")
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name.startswith("_"):
                        continue
                    short = node.name
                    dotted = f"{mod}.{node.name}"
                    if short not in names and dotted not in names:
                        continue
                    # Only top-level functions (skip methods, which are
                    # covered by the class branch above).
                    if any(
                        isinstance(p, ast.ClassDef) for p in ast.walk(tree)
                        if node in ast.walk(p)
                    ):
                        continue
                    args = _sig_args(node)
                    lines.append(f"  {dotted}({', '.join(args)})")

    if not lines:
        return ""
    text = "CONSTRUCTOR / FUNCTION SIGNATURES (exact — use these parameter names verbatim):\n"
    text += "\n".join(sorted(set(lines)))
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... (truncated)"
    return text


def _sig_args(node) -> list:
    """Render a function's parameter list with annotations and defaults.

    Order: posonly, regular, *vararg, kwonly, **kwarg — matching the
    source's visual order.  ``self``/``cls`` are included (the caller
    decides whether to strip them).
    """
    args = node.args
    parts = []
    # Positional (posonly + regular) share the trailing defaults list.
    pos_args = list(args.posonlyargs) + list(args.args)
    n_pos = len(pos_args)
    n_def = len(args.defaults)
    for i, a in enumerate(pos_args):
        ann = f": {ast.unparse(a.annotation)}" if a.annotation else ""
        d = i - (n_pos - n_def)
        default = (f"={ast.unparse(args.defaults[d])}"
                   if d >= 0 and d < n_def else "")
        parts.append(f"{a.arg}{ann}{default}")
    if args.vararg:
        parts.append(f"*{args.vararg.arg}")
    for i, a in enumerate(args.kwonlyargs):
        ann = f": {ast.unparse(a.annotation)}" if a.annotation else ""
        default = (f"={ast.unparse(args.kw_defaults[i])}"
                   if args.kw_defaults[i] is not None else "")
        parts.append(f"{a.arg}{ann}{default}")
    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}")
    return parts


def extract_member_bodies(
    pkg_path: str, names: set, max_lines: int = 40, max_chars: int = 8000
) -> str:
    """Extract full source bodies for the given function/method/property names.

    E36: source-body injection.  The API surface lists member *names* and
    *signatures*, and constructor signatures give exact ``__init__``
    parameters, but neither includes the function body.  When the LLM
    writes prose about a member (e.g. "``passed`` returns a list of
    scenario names that passed"), it infers the return value from the
    name — the dominant source of C-hallucination.  This function fills
    that gap with deterministic, AST-derived source bodies.

    A name matches a top-level function, a method, or a property when the
    node's ``.name`` is in the set.  The body is rendered from the source
    text using the node's line span, capped at ``max_lines`` lines.

    Args:
        pkg_path: Absolute path to the package directory.
        names: Set of function/method/property names to include.
        max_lines: Cap on rendered lines per member body.
        max_chars: Truncate the result to this many characters.

    Returns:
        Multi-line string with source bodies, or empty string if nothing
        matches.
    """
    blocks: list = []
    seen: set = set()
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
                    source = fh.read()
                tree = ast.parse(source)
            except (SyntaxError, OSError):
                continue
            src_lines = source.splitlines()

            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name not in names:
                    continue
                # Deduplicate: keep the first match for each name.
                if node.name in seen:
                    continue
                seen.add(node.name)
                start = node.lineno
                end = getattr(node, "end_lineno", None) or start
                body_lines = src_lines[start - 1:end]
                if len(body_lines) > max_lines:
                    body_lines = body_lines[:max_lines]
                    body_lines.append("    # ... (truncated)")
                prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
                blocks.append(f"### {mod}.{node.name} ({prefix}def)\n"
                              f"```python\n" + "\n".join(body_lines) + "\n```")

    if not blocks:
        return ""
    text = ("SOURCE BODIES (ground truth for behavior — what these members "
            "actually do, return, and accept):\n")
    text += "\n".join(blocks)
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


def get_tests_context(root: str, max_chars: int = 6000) -> str:
    """Build a context block from the repo's tests/ directory.

    Tests are ground truth for *behavior*: they show what the API is
    expected to do, not just what symbols exist.  We extract the most
    behavior-revealing tests (those with the most assertions) and
    include them so the LLM can verify its behavioral claims.

    Generic: looks for tests/, test/, testing/ at the repo root.
    Returns "" if no test directory found.
    """
    test_dir = None
    for cand in ("tests", "test", "testing"):
        d = os.path.join(root, cand)
        if os.path.isdir(d):
            test_dir = d
            break
    if test_dir is None:
        return ""

    # Score each test file by assertion count (higher = more behavior)
    scored = []
    for f in sorted(os.listdir(test_dir)):
        if not f.startswith("test_") or not f.endswith(".py"):
            continue
        full = os.path.join(test_dir, f)
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError:
            continue
        assert_count = content.count("assert ") + content.count("assert(")
        scored.append((assert_count, f, content))

    if not scored:
        return ""

    # Sort by assertion count descending; take top 4 files
    scored.sort(key=lambda x: -x[0])
    top = scored[:4]

    lines = [
        "TEST FILES (ground truth for behavior — what the API is expected to do):"
    ]
    included = 0
    for assert_count, fname, content in top:
        if included >= 4:
            break
        # Truncate each file to keep total under budget
        excerpt = content[:2500]
        if len(content) > 2500:
            excerpt += "\n# ... (truncated)"
        lines.append(
            f"\n### {fname} ({assert_count} assertions)\n```python\n{excerpt}\n```"
        )
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


def _module_docstring_fallback(pkg_path: str, pkg_name: str, mod: str) -> str:
    """Return a one-line description for a module.

    Resolves the dotted module name to a file under ``pkg_path`` and
    extracts a description using the same fallback chain as
    ``site._extract_module_docstring``: docstring → leading # comments →
    first top-level name.
    """
    parts = mod.split(".")
    if parts and parts[0] == pkg_name:
        parts = parts[1:]
    if not parts:
        path = os.path.join(pkg_path, "__init__.py")
    else:
        path = os.path.join(pkg_path, *parts[:-1], parts[-1] + ".py")
        if not os.path.isfile(path):
            # Could be a subpackage (directory with __init__.py).
            path = os.path.join(pkg_path, *parts, "__init__.py")
    if not os.path.isfile(path):
        return ""
    return _extract_description_from_source(path)


def _name_to_phrase(name: str) -> str:
    """Convert a Python identifier to a readable phrase."""
    import re
    s = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
    s = s.replace('_', ' ')
    return s.lower()[:120]


def _extract_description_from_source(path: str) -> str:
    """Extract a one-line description from a Python source file.

    Fallback chain: docstring → leading # comments → first top-level name.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            source = f.read()
        tree = ast.parse(source)
        # 1. Docstring
        doc = ast.get_docstring(tree)
        if doc:
            first = doc.strip().split("\n")[0].strip()
            return first[:120] if len(first) > 120 else first
        # 2. Leading # comments (skip file-path-style comments)
        for line in source.split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#!"):
                continue
            if stripped.startswith("#"):
                text = stripped.lstrip("#").strip()
                if text and "/" not in text and not text.endswith(".py"):
                    return text[:120] if len(text) > 120 else text
                continue
            break
        # 3. First top-level name
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
    module_descriptions = dict(cfg.raw.get("module_descriptions") or {})

    os.makedirs(ref_dir, exist_ok=True)
    # Derive the top-level package name from pkg_path so that module
    # names are fully qualified (e.g. "click.core", not "core").
    pkg_name = os.path.basename(os.path.normpath(pkg_path))
    modules = []
    for dirpath, _, filenames in os.walk(pkg_path):
        for f in filenames:
            if not f.endswith(".py"):
                continue
            # Module names are relative to pkg_path (the package root),
            # not to repo root, so src/-layout packages work correctly.
            rel = os.path.relpath(os.path.join(dirpath, f), pkg_path)
            mod = rel[:-3].replace(os.sep, ".")
            if mod.endswith(".__init__"):
                mod = mod[:-9]
            # Prefix with the top-level package name for mkdocstrings.
            if mod == "__init__":
                mod = pkg_name
            else:
                mod = f"{pkg_name}.{mod}"
            modules.append(mod)
    modules.sort()

    rendered = []
    for mod in modules:
        # Skip modules in directories without __init__.py (not importable).
        # Strip the top-level package name (pkg_path is already the
        # package root) and check each parent dir for __init__.py.
        parts = mod.split(".")
        if parts[0] == pkg_name:
            parts = parts[1:]  # strip top-level package name
        importable = True
        for i in range(1, len(parts)):
            parent_dir = os.path.join(pkg_path, *parts[:i])
            if not os.path.isfile(os.path.join(parent_dir, "__init__.py")):
                importable = False
                break
        if not importable:
            print(f"    reference: {mod} (skipped — no __init__.py in parent)")
            continue
        print(f"    reference: {mod}")
        desc = module_descriptions.get(mod, "")
        if not desc:
            # Docstring fallback: resolve module name to file and read its
            # docstring (first line, truncated to 120 chars).
            desc = _module_docstring_fallback(pkg_path, pkg_name, mod)
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
