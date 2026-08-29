"""E18 — Prose API semantics checker.

Extracts API-usage claims from markdown PROSE (outside ```python blocks) and
validates them against the AST class index. Catches the error class that
example_check.py structurally misses:

  1. PROSE_PROPERTY_AS_METHOD  — doc writes `name()` but source has @property name
  2. PROSE_METHOD_AS_PROPERTY  — doc writes bare `name` but source has a regular method
  3. RETURN_TYPE_MISMATCH      — doc says "returns a list/dict/int/..." but source annotation disagrees
  4. ARG_TYPE_MISMATCH         — doc says a free function takes type X but source annotates Y
  5. CROSS_PAGE_CONFLICT       — same member written as method on one page, property on another

Usage: prose_api_semantics_check.py <pkg_path> <guides_dir> <output_json>
"""
from __future__ import annotations

import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Extended class index (adds return annotations + free functions)
# ---------------------------------------------------------------------------

def build_extended_index(pkg_path: str) -> dict:
    """Return {
        'classes': {ClassName: {
            'properties': {name: return_annotation_str_or_None},
            'methods': {name: return_annotation_str_or_None},
            'init_params': {param: has_default},
        }},
        'free_functions': {func_name: {param: annotation_str_or_None}},
    }
    """
    classes: dict = {}
    free_functions: dict = {}

    for py in Path(pkg_path).rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, OSError):
            continue

        # Free functions (module-level FunctionDef)
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                params = {}
                for arg in node.args.args:
                    if arg.arg in ("self", "cls"):
                        continue
                    ann = None
                    if arg.annotation is not None:
                        try:
                            ann = ast.unparse(arg.annotation)
                        except Exception:
                            ann = None
                    params[arg.arg] = ann
                free_functions[node.name] = params

        # Classes
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            cls = node.name
            if cls not in classes:
                classes[cls] = {
                    "properties": {},
                    "methods": {},
                    "init_params": {},
                }
            info = classes[cls]
            for item in node.body:
                if not isinstance(item, ast.FunctionDef):
                    continue
                if item.name == "__init__":
                    all_args = list(item.args.args)
                    if all_args and all_args[0].arg in ("self", "cls"):
                        all_args = all_args[1:]
                    all_args = all_args + item.args.kwonlyargs
                    defaults = list(item.args.defaults) + list(item.args.kw_defaults)
                    n_args = len(all_args)
                    n_defaults = len(defaults)
                    for i, a in enumerate(all_args):
                        has_def = (n_args - n_defaults + i) >= n_args - n_defaults
                        info["init_params"][a.arg] = has_def
                    continue

                # Get return annotation
                ret_ann = None
                if item.returns is not None:
                    try:
                        ret_ann = ast.unparse(item.returns)
                    except Exception:
                        ret_ann = None

                # Check for @property decorator
                is_property = False
                for dec in item.decorator_list:
                    if isinstance(dec, ast.Name) and dec.id == "property":
                        is_property = True
                    elif isinstance(dec, ast.Attribute) and dec.attr == "setter":
                        is_property = True  # setter also means it's a property

                # Check if method has required args (no defaults)
                has_required_args = False
                if not is_property:
                    all_args = list(item.args.args)
                    if all_args and all_args[0].arg in ("self", "cls"):
                        all_args = all_args[1:]
                    all_args = all_args + list(item.args.kwonlyargs)
                    defaults = list(item.args.defaults) + list(item.args.kw_defaults)
                    if all_args and len(all_args) > len(defaults):
                        has_required_args = True

                if is_property:
                    info["properties"][item.name] = ret_ann
                else:
                    info["methods"][item.name] = (ret_ann, has_required_args)

    return {"classes": classes, "free_functions": free_functions}


# ---------------------------------------------------------------------------
# Prose extraction
# ---------------------------------------------------------------------------

def strip_code_blocks(md_text: str) -> str:
    """Remove all fenced code blocks, keeping line numbers aligned."""
    lines = md_text.split("\n")
    in_fence = False
    result = []
    for line in lines:
        if line.strip().startswith("```"):
            in_fence = not in_fence
            result.append("")  # placeholder to keep line count
            continue
        if in_fence:
            result.append("")
        else:
            result.append(line)
    return "\n".join(result)


def extract_prose_claims(md_text: str) -> list[dict]:
    """Extract API-usage claims from markdown prose.

    Returns list of dicts:
      {
        'line': int,
        'name': str,          # the API member name
        'is_method_call': bool,  # True if written with ()
        'return_claim': str|None,  # 'list', 'dict', 'int', 'str', 'None', etc.
        'arg_type_claims': {param_name: type_str},  # for free functions
        'context': str,       # surrounding text for debugging
      }
    """
    prose = strip_code_blocks(md_text)
    claims = []

    # Pattern 1: bullet/table claims like `name()`: description
    # Matches: * `score()`: Returns...  | `passed()` | Returns...
    # Also: **`summary()`**: Provides...
    bullet_re = re.compile(
        r"""
        (?:\*|\||-)?\s*  # optional bullet/table prefix
        (?:\*\*)?         # optional bold
        `(?P<name>[\w]+)(?P<call>\(\))?`  # backtick-wrapped name, optional ()
        (?:\*\*)?
        \s*[:|]           # colon or table separator
        \s*(?P<desc>.+)   # description
        """,
        re.VERBOSE,
    )

    # Pattern 2: inline prose mentions like "the `passed` property" or
    # "call `score()` to get..."
    inline_re = re.compile(
        r"""
        `(?P<name>[\w]+)(?P<call>\(\))?`  # backtick-wrapped name
        """,
    )

    # Return-type claim patterns
    # Two categories:
    #   1. Explicit type words: "returns a list", "returns a dictionary", etc.
    #   2. "returns a <noun>" where noun is not a type word — this is a
    #      VAGUE claim. We can't validate it against a specific type, but we
    #      CAN flag it if the source returns None (method only prints).
    return_type_re = re.compile(
        r"""
        (?:returns?|return)\s+
        (?:
            a\s+(?:list|dictionary|dict|integer|int|string|str|float|boolean|bool|tuple|set|object)
            |an?\s+(?:list|dictionary|dict|integer|int|string|str|float|boolean|bool|tuple|set|object)
            |lists?
            |dictionaries?
            |dicts?
            |integers?
            |ints?
            |strings?
            |strs?
            |booleans?
            |bools?
            |tuples?
            |sets?
            |objects?
            |a\s+count
            |a\s+number
            |a\s+value
            |nothing
            |None
        )
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    # "Returns a <noun>" — vague return claim (e.g. "Returns a high-level summary")
    # We can't validate the type, but if source returns None, this is wrong.
    vague_return_re = re.compile(
        r"""
        (?:returns?|return|provides?|gives?)\s+
        a\s+\w+  # "a summary", "a count", "a breakdown", etc.
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    # Argument type claims — three patterns that match real doc phrasing:
    # 1. "The `func` function requires `Type` objects" (prose)
    func_requires_re = re.compile(
        r"""
        `(?P<func>[\w]+)`\s+function\s+
        (?:requires?|accepts?|takes?|expects?)\s+
        (?:a\s+|an\s+)?
        `(?P<type>[\w]+)`
        """,
        re.IGNORECASE,
    )
    # 2. Table row: | `param_name` | `Type` | description |
    #    (handled inline below)
    # 3. Bullet with colon: `param_a`, `param_b`: `Type` objects.
    #    (handled inline below)

    # Track the most recent function heading (e.g. "#### Function: `compare_judges`")
    # so param bullets can be associated with the correct function.
    current_func = None
    current_func_line = 0

    for line_no, line in enumerate(prose.split("\n"), 1):
        if not line.strip():
            continue

        # Detect function headings: "#### Function: `name`" or "### `name`"
        func_heading = re.match(r'^#{1,6}\s+(?:Function|function|method|Method)[:\s]+`(\w+)`', line)
        if func_heading:
            current_func = func_heading.group(1)
            current_func_line = line_no
            continue

        # Try bullet/table pattern first (higher precision)
        for m in bullet_re.finditer(line):
            name = m.group("name")
            is_call = m.group("call") is not None
            desc = m.group("desc")

            # Extract return type claim from description
            rt_match = return_type_re.search(desc)
            return_claim = None
            if rt_match:
                raw = rt_match.group(0).lower()
                if "list" in raw:
                    return_claim = "list"
                elif "dict" in raw or "dictionar" in raw:
                    return_claim = "dict"
                elif "int" in raw and "integer" not in raw:
                    return_claim = "int"
                elif "integer" in raw:
                    return_claim = "int"
                elif "str" in raw:
                    return_claim = "str"
                elif "float" in raw:
                    return_claim = "float"
                elif "bool" in raw:
                    return_claim = "bool"
                elif "tuple" in raw:
                    return_claim = "tuple"
                elif "set" in raw:
                    return_claim = "set"
                elif "none" in raw or "nothing" in raw:
                    return_claim = "None"
                elif "count" in raw or "number" in raw:
                    return_claim = "int"
            else:
                # Check for vague return claims: "Returns a summary", "Provides a breakdown"
                # These assert the function returns *something* — if source returns None, flag it.
                if vague_return_re.search(desc):
                    return_claim = "vague"  # means "claims to return something"

            # Extract argument type claims (three patterns)
            arg_types: dict[str, str] = {}

            # Pattern 3: bullet with colon — `param_a`, `param_b`: `Type` objects
            # The colon is consumed by bullet_re, so search the FULL LINE.
            # Backtick names before the first colon (outside backticks) are
            # param names; CamelCase backtick names after it are claimed types.
            in_bt = False
            colon_pos = -1
            for ci, ch in enumerate(line):
                if ch == '`':
                    in_bt = not in_bt
                elif ch == ':' and not in_bt:
                    colon_pos = ci
                    break
            if colon_pos > 0 and current_func:
                before = line[:colon_pos]
                after = line[colon_pos + 1:]
                param_names = re.findall(r'`(\w+)', before)
                claimed_types = re.findall(r'`([A-Z]\w*)`', after)
                if param_names and claimed_types:
                    arg_types['__func__'] = current_func
                    for pn in param_names:
                        arg_types[pn] = claimed_types[0]

            # Pattern 2: table row — | `param` | `Type` | description |
            # (bullet_re already matched a `name` cell; check if desc starts with |)
            if desc.lstrip().startswith('|'):
                cells = [c.strip() for c in desc.split('|')]
                # cells[0] is empty (before first |), cells[1] = name, cells[2] = type
                if len(cells) >= 3:
                    name_cell = cells[1]
                    type_cell = cells[2]
                    nm = re.match(r'^`(\w+)`$', name_cell)
                    tm = re.match(r'^`([A-Z]\w*)`$', type_cell)
                    if nm and tm:
                        arg_types[nm.group(1)] = tm.group(1)

            # Pattern 1: "The `func` function requires `Type`" (whole line)
            for fm in func_requires_re.finditer(line):
                # This claim is about the function itself; the type applies to
                # all its params. We store it under a special key that
                # validate_claims resolves against free_functions.
                arg_types['__func_requires__'] = f"{fm.group('func')}:{fm.group('type')}"

            claims.append({
                "line": line_no,
                "name": name,
                "is_method_call": is_call,
                "return_claim": return_claim,
                "arg_type_claims": arg_types,
                "context": line.strip()[:200],
            })

        # Also scan for inline mentions that look like API references
        # (lower precision, only flag if the name is in the class index)
        # We'll handle cross-page consistency separately

    return claims


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def normalize_type(ann: str | None) -> str | None:
    """Normalize a Python type annotation to a canonical form."""
    if ann is None:
        return None
    ann = ann.lower().strip()
    # Handle generic types: Dict[str, Any] -> dict, List[str] -> list
    if ann.startswith("dict") or ann.startswith("dictionary"):
        return "dict"
    if ann.startswith("list") or ann.startswith("tuple") or ann.startswith("set"):
        return ann.split("[")[0].strip()
    if ann in ("int", "float", "str", "bool", "bytes"):
        return ann
    if ann == "none":
        return "None"
    # For class names, keep as-is (lowercased)
    return ann


def validate_claims(claims: list[dict], index: dict) -> list[dict]:
    """Validate extracted claims against the class index.

    Returns list of findings:
      {
        'type': str,
        'page': str,
        'line': int,
        'name': str,
        'detail': str,
        'source_truth': str,
      }
    """
    findings = []
    classes = index["classes"]
    free_functions = index["free_functions"]

    # Build reverse lookup: member_name -> list of (class_name, is_property, ret_ann, has_required_args)
    # Deduped: if multiple classes have the same member name, keep only the
    # first occurrence to avoid one sentence generating N findings.
    member_lookup: dict[str, list[tuple[str, bool, str | None, bool]]] = defaultdict(list)
    seen_members: set[tuple[str, str]] = set()  # (member_name, class_name)
    for cls_name, info in classes.items():
        for prop_name, ret_ann in info["properties"].items():
            key = (prop_name, cls_name)
            if key not in seen_members:
                seen_members.add(key)
                member_lookup[prop_name].append((cls_name, True, ret_ann, False))
        for meth_name, (ret_ann, has_required_args) in info["methods"].items():
            key = (meth_name, cls_name)
            if key not in seen_members:
                seen_members.add(key)
                member_lookup[meth_name].append((cls_name, False, ret_ann, has_required_args))

    # Also dedupe across classes: if the same member name appears in multiple
    # classes with identical (is_property, ret_ann, has_required_args), keep only one entry.
    deduped: dict[str, list[tuple[str, bool, str | None, bool]]] = {}
    for name, entries in member_lookup.items():
        unique: list[tuple[str, bool, str | None, bool]] = []
        seen: set[tuple[bool, str | None, bool]] = set()
        for entry in entries:
            sig = (entry[1], entry[2], entry[3])
            if sig not in seen:
                seen.add(sig)
                unique.append(entry)
        deduped[name] = unique
    member_lookup = deduped

    for claim in claims:
        name = claim["name"]
        is_call = claim["is_method_call"]
        return_claim = claim["return_claim"]
        line = claim["line"]
        context = claim["context"]

        # Check if this name is a known class member
        if name in member_lookup:
            for cls_name, is_property, ret_ann, has_required_args in member_lookup[name]:
                source_type = "property" if is_property else "method"

                # Property-vs-method check
                if is_property and is_call:
                    findings.append({
                        "type": "PROSE_PROPERTY_AS_METHOD",
                        "line": line,
                        "name": name,
                        "class": cls_name,
                        "detail": f"Doc writes `{name}()` but source has @property {name}",
                        "source_truth": f"@property {name} on {cls_name}",
                        "context": context,
                    })
                elif not is_property and not is_call:
                    # Method written as bare property — only flag if it takes
                    # required args (otherwise it's ambiguous)
                    if has_required_args:
                        findings.append({
                            "type": "PROSE_METHOD_AS_PROPERTY",
                            "line": line,
                            "name": name,
                            "class": cls_name,
                            "detail": f"Doc writes bare `{name}` but source has method {name}() with required args",
                            "source_truth": f"method {name}() on {cls_name}",
                            "context": context,
                        })

                # Return-type check
                if return_claim:
                    source_norm = normalize_type(ret_ann)
                    claim_norm = normalize_type(return_claim)

                    # Special case: "vague" return claim (e.g. "Returns a summary")
                    # Only flag if the source EXPLICITLY returns None (annotated
                    # -> None). A missing annotation is ambiguous — the method
                    # might return something unannotated. Don't flag on ambiguity.
                    if return_claim == "vague":
                        if source_norm == "None":
                            findings.append({
                                "type": "RETURN_TYPE_MISMATCH",
                                "line": line,
                                "name": name,
                                "class": cls_name,
                                "detail": f"Doc claims '{name}' returns a value but source annotates -> None (method only prints)",
                                "source_truth": f"-> None on {cls_name}.{name}",
                                "context": context,
                            })
                        continue

                    # Explicit type claims require a source annotation to compare
                    if ret_ann is None:
                        continue

                    if source_norm and claim_norm and source_norm != claim_norm:
                        # Allow some compatible pairs
                        compatible = {
                            ("int", "float"),
                            ("float", "int"),
                            ("str", "string"),
                        }
                        if (source_norm, claim_norm) not in compatible and \
                           (claim_norm, source_norm) not in compatible:
                            findings.append({
                                "type": "RETURN_TYPE_MISMATCH",
                                "line": line,
                                "name": name,
                                "class": cls_name,
                                "detail": f"Doc claims '{return_claim}' but source annotates -> {ret_ann}",
                                "source_truth": f"-> {ret_ann} on {cls_name}.{name}",
                                "context": context,
                            })

        # Free function argument-type check
        # Two entry points:
        #   1. name is the function itself (e.g. from "The `compare_judges` function requires...")
        #   2. arg_type_claims has '__func__' (param bullet under a function heading)
        arg_claims = claim["arg_type_claims"]

        # Case 1: the claim's name IS a free function
        if name in free_functions:
            func_params = free_functions[name]
            for param, claimed_type in arg_claims.items():
                if param == "__func_requires__":
                    # "The `func` function requires `Type`" — check all params
                    _, claimed = claimed_type.split(":", 1)
                    for pname, source_type in func_params.items():
                        if source_type and claimed:
                            source_norm = normalize_type(source_type)
                            claim_norm = normalize_type(claimed)
                            if source_norm and claim_norm and source_norm != claim_norm:
                                findings.append({
                                    "type": "ARG_TYPE_MISMATCH",
                                    "line": line,
                                    "name": name,
                                    "param": pname,
                                    "detail": f"Doc says {name}() requires {claimed} but source annotates {pname}: {source_type}",
                                    "source_truth": f"{name}({pname}: {source_type})",
                                    "context": context,
                                })
                    continue
                if param in func_params:
                    source_type = func_params[param]
                    if source_type and claimed_type:
                        source_norm = normalize_type(source_type)
                        claim_norm = normalize_type(claimed_type)
                        if source_norm and claim_norm and source_norm != claim_norm:
                            findings.append({
                                "type": "ARG_TYPE_MISMATCH",
                                "line": line,
                                "name": name,
                                "param": param,
                                "detail": f"Doc says {name}({param}) takes {claimed_type} but source annotates {source_type}",
                                "source_truth": f"{name}({param}: {source_type})",
                                "context": context,
                            })

        # Case 2: param bullet under a function heading (__func__ key)
        if "__func__" in arg_claims:
            func_name = arg_claims["__func__"]
            if func_name in free_functions:
                func_params = free_functions[func_name]
                for param, claimed_type in arg_claims.items():
                    if param.startswith("__"):
                        continue
                    if param in func_params:
                        source_type = func_params[param]
                        if source_type and claimed_type:
                            source_norm = normalize_type(source_type)
                            claim_norm = normalize_type(claimed_type)
                            if source_norm and claim_norm and source_norm != claim_norm:
                                findings.append({
                                    "type": "ARG_TYPE_MISMATCH",
                                    "line": line,
                                    "name": func_name,
                                    "param": param,
                                    "detail": f"Doc says {func_name}({param}) takes {claimed_type} but source annotates {source_type}",
                                    "source_truth": f"{func_name}({param}: {source_type})",
                                    "context": context,
                                })

    return findings


def check_cross_page_consistency(guides_dir: str, index: dict) -> list[dict]:
    """Check for cross-page method/property inconsistencies.

    For each (class, member) pair, collect how each page writes it.
    Flag if one page writes it as method and another as property.
    """
    classes = index["classes"]
    # Build member -> is_property lookup
    member_is_property: dict[str, dict[str, bool]] = {}
    for cls_name, info in classes.items():
        for prop_name in info["properties"]:
            member_is_property.setdefault(prop_name, {})[cls_name] = True
        for meth_name in info["methods"]:
            member_is_property.setdefault(meth_name, {})[cls_name] = False

    # Collect per-page usage
    page_usage: dict[str, dict[str, dict[str, list[bool]]]] = {}
    # page_usage[page][member_name][class_name] = [is_method_call, ...]

    for md_file in sorted(Path(guides_dir).glob("*.md")):
        page = md_file.stem
        text = md_file.read_text(encoding="utf-8", errors="replace")
        prose = strip_code_blocks(text)

        for line in prose.split("\n"):
            if not line.strip():
                continue
            for m in re.finditer(r'`(\w+)(\(\))?`', line):
                name = m.group(1)
                is_call = m.group(2) is not None
                if name in member_is_property:
                    for cls_name in member_is_property[name]:
                        page_usage.setdefault(page, {}).setdefault(name, {}).setdefault(
                            cls_name, []
                        ).append(is_call)

    findings = []
    for page, members in page_usage.items():
        for name, by_class in members.items():
            for cls_name, calls in by_class.items():
                has_method = any(calls)
                has_property = not any(calls)
                if has_method and has_property:
                    findings.append({
                        "type": "CROSS_PAGE_CONFLICT",
                        "page": page,
                        "name": name,
                        "class": cls_name,
                        "detail": f"Page '{page}' uses `{name}` as both method and property",
                        "source_truth": f"{'property' if member_is_property[name][cls_name] else 'method'} on {cls_name}",
                    })

    return findings


def check_install_requirements(pkg_path: str, guides_dir: str) -> list[dict]:
    """Check that install instructions mention all required extras.

    For each [extra] in pyproject.toml, flag pages that:
      1. show `pip install <pkg>` WITHOUT `[extra]`, AND
      2. document features that require that extra (by keyword).

    Feature keywords are derived from the extra's dependency module names:
      fastapi/uvicorn → serve, server, export-html, visualize
      matplotlib      → plot, chart, graph
    """
    findings = []

    extras: dict[str, list[str]] = {}
    pyproject = Path(pkg_path).parent / "pyproject.toml"
    if pyproject.exists():
        try:
            import tomllib
            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
            extras = data.get("project", {}).get("optional-dependencies", {})
        except Exception:
            pass

    if not extras:
        return findings

    pkg_name = Path(pkg_path).name

    for extra_name, deps in extras.items():
        dep_modules = set()
        for dep in deps:
            mod = dep.split(">=")[0].split("<=")[0].split("==")[0].split("[")[0].strip()
            dep_modules.add(mod.lower())

        # Derive feature keywords from dep module names
        feature_keywords: set[str] = set()
        if "fastapi" in dep_modules or "uvicorn" in dep_modules:
            feature_keywords.update(["server", "serve", "export-html", "export_html", "visualize"])
        if "matplotlib" in dep_modules:
            feature_keywords.update(["plot", "chart", "graph"])

        if not feature_keywords:
            continue

        for md_file in sorted(Path(guides_dir).glob("*.md")):
            text = md_file.read_text(encoding="utf-8", errors="replace")

            # Does the page show pip install <pkg> WITHOUT [extra]?
            pip_install_re = re.compile(
                rf'pip\s+install\s+{re.escape(pkg_name)}(?!\[{re.escape(extra_name)}\])',
                re.IGNORECASE,
            )
            if not pip_install_re.search(text):
                continue

            # Does the page document features that require this extra?
            has_feature = False
            for kw in feature_keywords:
                # Keyword in a heading
                if re.search(rf'^#{{1,6}}\s+.*{re.escape(kw)}', text, re.IGNORECASE | re.MULTILINE):
                    has_feature = True
                    break
                # Keyword near "command" / "subcommand" / "CLI"
                if re.search(rf'\b{re.escape(kw)}\b.*?(?:command|subcommand|CLI)', text, re.IGNORECASE):
                    has_feature = True
                    break

            if has_feature:
                findings.append({
                    "type": "MISSING_INSTALL_EXTRA",
                    "page": md_file.stem,
                    "extra": extra_name,
                    "detail": f"Page documents features requiring [{extra_name}] extra but install instructions say 'pip install {pkg_name}' without it",
                    "source_truth": f"pyproject.toml defines [{extra_name}] extra with deps: {deps}",
                })

    return findings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 4:
        print("Usage: prose_api_semantics_check.py <pkg_path> <guides_dir> <output_json>")
        sys.exit(1)

    pkg_path = sys.argv[1]
    guides_dir = sys.argv[2]
    output_json = sys.argv[3]

    index = build_extended_index(pkg_path)
    print(f"Indexed {len(index['classes'])} classes, {len(index['free_functions'])} free functions")

    all_findings = []
    total_claims = 0

    for md_file in sorted(Path(guides_dir).glob("*.md")):
        page = md_file.stem
        text = md_file.read_text(encoding="utf-8", errors="replace")
        claims = extract_prose_claims(text)
        total_claims += len(claims)

        findings = validate_claims(claims, index)
        for f in findings:
            f["page"] = page
        all_findings.extend(findings)
        if findings:
            print(f"  {page}: {len(findings)} findings ({len(claims)} claims)")

    # Cross-page consistency
    cross_findings = check_cross_page_consistency(guides_dir, index)
    for f in cross_findings:
        all_findings.append(f)
    if cross_findings:
        print(f"  cross-page: {len(cross_findings)} conflicts")

    # Install extras check
    install_findings = check_install_requirements(pkg_path, guides_dir)
    all_findings.extend(install_findings)
    if install_findings:
        print(f"  install-extras: {len(install_findings)} findings")

    # Summary
    by_type = defaultdict(int)
    for f in all_findings:
        by_type[f["type"]] += 1

    result = {
        "total_claims": total_claims,
        "total_findings": len(all_findings),
        "findings_by_type": dict(by_type),
        "findings": all_findings,
    }

    with open(output_json, "w") as fh:
        json.dump(result, fh, indent=2)
    print(f"\nTotal: {total_claims} claims, {len(all_findings)} findings")
    print(f"Wrote {output_json}")


if __name__ == "__main__":
    main()
