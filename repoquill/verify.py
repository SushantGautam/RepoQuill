"""Post-generation verification: hallucination check + LLM fix passes.

After narrative pages are generated, this module:

1. Builds a ground-truth symbol index from the package source (pure AST —
   classes, methods, functions, constants, string literals, function
   parameters).
2. Scans each generated page for identifiers (imports, backtick symbols,
   method calls) that do not exist in the source.
3. For pages with findings, sends the page + findings back to the LLM and
   asks it to remove or correct the invented symbols.

This is generic: it works for any Python package, with no project-specific
knowledge. The symbol index is derived from the AST of the actual source.
"""

from __future__ import annotations

import ast
import builtins
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

#: Builtins referenced in prose (e.g. ``str``, ``None``, ``TypeError``)
#: are not hallucinated package APIs.
_BUILTIN_NAMES = set(dir(builtins))

#: Backtick spans that are never API references: JSON/JS/Python literals
#: and the conventional placeholder name. (Confirmed FP class: docs quote
#: `null` in JSON examples and `_` as a throwaway.)
_NON_SYMBOL_NAMES = frozenset({
    "null", "true", "false", "none", "undefined", "nan", "inf", "_",
})


# ---------------------------------------------------------------------------
# Ground-truth symbol index (AST-based)
# ---------------------------------------------------------------------------

@dataclass
class SymbolIndex:
    """Ground-truth symbols extracted from package source via AST."""

    module_symbols: Set[str] = field(default_factory=set)   # class/func names
    class_methods: Dict[str, Set[str]] = field(default_factory=dict)
    functions: Set[str] = field(default_factory=set)
    classes: Set[str] = field(default_factory=set)
    constants: Set[str] = field(default_factory=set)
    modules: Set[str] = field(default_factory=set)
    sources: Set[str] = field(default_factory=set)
    string_literals: Set[str] = field(default_factory=set)
    function_params: Set[str] = field(default_factory=set)
    #: Class-level attribute names (typed fields, pydantic/dataclass
    #: fields, plain class assignments). Docs legitimately reference
    #: these in backticks (e.g. `` `confidence_threshold` ``); flagging
    #: them as invented symbols was a confirmed false-positive source.
    attributes: Set[str] = field(default_factory=set)
    #: Identifiers that appear in the package's own docstrings
    #: (including doctests). Documentation written from those
    #: docstrings legitimately quotes the same names (`` `temperature`
    #: `` is documented in reframing's docstring; `` `acepted` `` is a
    #: doctest example of a MIS-spelled key). Ground truth is source
    #: text, not just the def/class/assign structure.
    docstring_names: Set[str] = field(default_factory=set)
    #: EVERY identifier-shaped token found anywhere in the package
    #: source (code, docstrings, comments, string literals). A page is
    #: verified against the repository's ground truth, not just the
    #: def/class/assign skeleton: names documented by sibling modules
    #: (`` SEVERITY_RESPONSE_SCHEMA `` lives in judges/compose.py while
    #: the page covers model_auditor) and external-protocol names the
    #: code talks about (OTLP `` AnyValue ``) must not be flagged as
    #: invented. A genuinely hallucinated name exists nowhere in the
    #: tree and is still flagged.
    source_tokens: Set[str] = field(default_factory=set)


def build_index(pkg_path: str) -> SymbolIndex:
    """Walk the package and extract all public symbols via AST."""
    idx = SymbolIndex()
    pkg_name = os.path.basename(os.path.normpath(pkg_path))
    idx.modules.add(pkg_name)

    for dirpath, _, filenames in os.walk(pkg_path):
        for f in filenames:
            if not f.endswith(".py"):
                continue
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, pkg_path)
            mod = rel[:-3].replace(os.sep, ".")
            if mod.endswith(".__init__"):
                mod = mod[:-9]
            idx.modules.add(mod)
            idx.modules.add(mod.split(".")[0])
            with open(full, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            # Whole-file ground-truth harvest (runs even on parse failure).
            for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,79}", text):
                idx.source_tokens.add(tok)
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue

            # Module-level assignments are referenceable globals even when
            # the walk below would treat them as locals: ALL_CAPS globals
            # (``SEVERITY_RESPONSE_SCHEMA: Dict[str, Any] = {...}``,
            # ``FINDING_SEVERITY: Dict[str, str] = {...}``) are constants,
            # and Capitalized ones (``Transform = Callable[...]``) are type
            # aliases docs quote by name.
            for stmt in tree.body:
                targets = []
                if isinstance(stmt, ast.Assign):
                    targets = stmt.targets
                elif isinstance(stmt, ast.AnnAssign) and isinstance(
                        stmt.target, ast.Name):
                    targets = [stmt.target]
                for tgt in targets:
                    if not isinstance(tgt, ast.Name):
                        continue
                    if tgt.id.isupper():
                        idx.constants.add(tgt.id)
                    idx.module_symbols.add(tgt.id)

            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) \
                        and isinstance(node.value, str) \
                        and len(node.value) > 30:
                    # Docstrings (and other long strings, e.g. prompts
                    # containing doctests): harvest identifier-shaped
                    # tokens so pages quoting documented names pass.
                    for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,79}",
                                          node.value):
                        idx.docstring_names.add(tok)
                if isinstance(node, ast.ClassDef):
                    idx.classes.add(node.name)
                    idx.module_symbols.add(node.name)
                    idx.class_methods.setdefault(node.name, set())
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            idx.class_methods[node.name].add(item.name)
                            # Full signature: ``def __init__(self, *args,
                            # correctness_judge="checklist", **kwargs)``
                            # keeps its keyword-only names out of
                            # ``args.args`` — they are API surface too.
                            a = item.args
                            for p in (list(a.posonlyargs) + list(a.args)
                                      + list(a.kwonlyargs)):
                                idx.function_params.add(p.arg)
                            if a.vararg:
                                idx.function_params.add(a.vararg.arg)
                            if a.kwarg:
                                idx.function_params.add(a.kwarg.arg)
                        elif isinstance(item, ast.AnnAssign):
                            # ``field: Type`` — dataclass / pydantic field
                            if isinstance(item.target, ast.Name):
                                idx.attributes.add(item.target.id)
                        elif isinstance(item, ast.Assign):
                            # class-level assignment (``default = 0.5``)
                            for tgt in item.targets:
                                if isinstance(tgt, ast.Name):
                                    idx.attributes.add(tgt.id)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    idx.functions.add(node.name)
                    idx.module_symbols.add(node.name)
                    # Full public signature: positional-only, positional,
                    # keyword-only, *args and **kwargs are all names docs
                    # legitimately reference (``f(*, min_chars=20)`` etc.).
                    args = node.args
                    for a in (list(args.posonlyargs) + list(args.args)
                              + list(args.kwonlyargs)):
                        idx.function_params.add(a.arg)
                    if args.vararg:
                        idx.function_params.add(args.vararg.arg)
                    if args.kwarg:
                        idx.function_params.add(args.kwarg.arg)
                elif isinstance(node, ast.Assign):
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name) and tgt.id.isupper():
                            # ALL_CAPS names are constants by convention at
                            # ANY scope: function-local response schemas
                            # (``SEVERITY_RESPONSE_SCHEMA = {...}`` inside a
                            # builder function) are real, referenceable API
                            # surface that docs quote. Lowercase local
                            # assignments are NOT allowed (too broad: they
                            # would whitelist arbitrary invented names).
                            idx.constants.add(tgt.id)
                            idx.module_symbols.add(tgt.id)
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    v = node.value
                    if 3 <= len(v) <= 80 and re.match(r"^[A-Za-z0-9_./-]+$", v):
                        idx.string_literals.add(v)
    return idx


# ---------------------------------------------------------------------------
# Page scanning
# ---------------------------------------------------------------------------

def extract_code_blocks(md: str) -> List[str]:
    return re.findall(r"```[a-zA-Z]*\n(.*?)```", md, re.DOTALL)


def extract_imports_typed(
        md: str,
) -> List[Tuple[str, str, "Optional[str]"]]:
    """Extract imports from code blocks as ``(kind, name, parent)``.

    * ``("module", dotted_path, None)`` for ``import x.y`` / the parent
      module of ``from x.y import Z``;
    * ``("symbol", Z, "x.y")`` for the imported name in
      ``from x.y import Z``.

    Handling parenthesized imports spanning multiple lines
    (``from pkg import (\\n  A,\\n  B\\n)``): the open/close parens are
    consumed, and only well-formed identifiers are recorded as symbols —
    fence fragments like ``(A`` or ``B)`` must not be mistaken for
    imported names (a confirmed false-positive source).
    """
    found: List[Tuple[str, str, "Optional[str]"]] = []
    for block in extract_code_blocks(md):
        lines = block.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            m = re.match(r"^(from|import)\s+([\w.]+)\s*(.*)$", line)
            if m:
                kind, module, rest = m.groups()
                found.append(("module", module, None))
                if kind == "from":
                    rest = rest.split("import", 1)[1] if "import" in rest else ""
                    # Close a parenthesized import that spans lines.
                    while (rest.count("(") > rest.count(")")
                             and i + 1 < len(lines)):
                        i += 1
                        rest = rest + " " + lines[i].strip()
                    for sym in rest.replace("(", " ").replace(")", " ") \
                            .split(","):
                        sym = sym.strip().split(" as ")[0].strip()
                        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", sym):
                            found.append(("symbol", sym, module))
            i += 1
    return found


def extract_imports(md: str) -> List[str]:
    """Flat list of module paths and imported symbols (back-compat)."""
    return [name for _, name, _ in extract_imports_typed(md)]


def extract_backtick_symbols(md: str) -> List[str]:
    """Extract identifiers from inline code spans (backticks)."""
    out = []
    for span in re.findall(r"`([^`\n]+)`", md):
        span = span.strip()
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", span):
            out.append(span)
    return out


def extract_method_calls(md: str) -> List[tuple]:
    """Extract (object_name, method_name) pairs from code blocks."""
    out = []
    for block in extract_code_blocks(md):
        for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\s*\(", block):
            out.append((m.group(1), m.group(2)))
    return out


def check_page(page_md: str, idx: SymbolIndex, pkg_name: str) -> List[dict]:
    """Check one page for hallucinated symbols. Returns list of findings."""
    findings = []
    all_methods = set()
    for methods in idx.class_methods.values():
        all_methods |= methods

    # 1. Imports
    # Scoped by design: only imports that reference the DOCUMENTED package
    # are verified against its symbol index. Stdlib/third-party imports
    # (`import asyncio`, `import opentelemetry...`) cannot be checked from
    # the package index and are out of scope — flagging them was a
    # confirmed false-positive class (tracing page: `asyncio`, `base64`).
    # A hallucinated import of the package itself
    # (`from simpleaudit import Bogus`) is still flagged.
    bare_module_names = {m.split(".")[-1] for m in idx.modules}
    for kind, imp, parent in extract_imports_typed(page_md):
        if kind == "symbol":
            # `from <parent> import <imp>` — an imported NAME. Known
            # package symbols pass; an unknown name imported from the
            # documented package is a hallucinated import; one imported
            # from an external module is out of scope.
            if imp in idx.module_symbols or imp in idx.modules:
                continue
            top = (parent or "").split(".")[0]
            if top != pkg_name and top not in idx.modules:
                continue  # external parent: not verifiable here
            findings.append({"symbol": imp, "kind": "import",
                             "severity": "high"})
            continue
        # `import <imp>` — a module path. Stdlib/third-party imports
        # (`import asyncio`, `import opentelemetry.proto...`) cannot be
        # checked from the package index and are out of scope; a path
        # into the documented package must exist.
        if imp in idx.modules or imp in idx.module_symbols:
            continue
        top = imp.split(".")[0]
        if top != pkg_name and top not in idx.modules:
            continue  # external module: not verifiable here
        parts = imp.split(".")
        if parts[-1] in bare_module_names:
            continue  # valid submodule path
        findings.append({"symbol": imp, "kind": "import",
                         "severity": "medium"})

    # 2. Backtick identifiers
    for sym in extract_backtick_symbols(page_md):
        # Language/JSON literals and the conventional throwaway name are
        # not API references: docs write `null` in JSON, `_` for
        # placeholders. (Confirmed FP class: `null`, `_`.)
        if sym.lower() in _NON_SYMBOL_NAMES:
            continue
        # Third-party libraries are out of scope, for the same reason
        # external imports are: the symbol index only covers the
        # documented package. A backtick name that resolves to an
        # installed distribution (`` `matplotlib` `` in a plotting page)
        # is a reference to that library, not an invented package symbol.
        # Hallucinated CamelCase class names almost never match an
        # importable top-level module, so this does not weaken the
        # hallucination check in practice.
        try:
            import importlib.util
            if importlib.util.find_spec(sym) is not None:
                continue
        except (ImportError, ValueError, ModuleNotFoundError):
            pass
        # Attributes and method names are real API surface too: docs
        # reference fields (`` `name` ``) and methods in backticks just
        # like functions and classes.
        if sym in idx.module_symbols or sym in idx.string_literals \
                or sym in idx.function_params or sym in idx.constants \
                or sym in idx.attributes or sym in all_methods \
                or sym in idx.docstring_names or sym in idx.source_tokens \
                or sym in idx.modules or sym in bare_module_names \
                or sym in _BUILTIN_NAMES:
            continue
        if sym.isupper():
            findings.append({"symbol": sym, "kind": "constant",
                             "severity": "high"})
        elif sym[0].isupper():
            findings.append({"symbol": sym, "kind": "class",
                             "severity": "high"})
        else:
            findings.append({"symbol": sym, "kind": "function",
                             "severity": "medium"})

    # 3. Method calls
    for obj, meth in extract_method_calls(page_md):
        if meth in all_methods or meth in idx.string_literals:
            continue
        if obj in idx.classes and meth in idx.class_methods.get(obj, set()):
            continue
        findings.append({"symbol": f"{obj}.{meth}()", "kind": "method_call",
                         "severity": "low"})

    # Dedupe
    seen = set()
    unique = []
    for f in findings:
        key = (f["symbol"], f["kind"])
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def check_all(guides_dir: str, idx: SymbolIndex, pkg_name: str) -> Dict[str, List[dict]]:
    """Check all guide pages. Returns {filename: findings}."""
    results = {}
    for f in sorted(os.listdir(guides_dir)):
        if not f.endswith(".md"):
            continue
        with open(os.path.join(guides_dir, f), "r", encoding="utf-8") as fh:
            md = fh.read()
        findings = check_page(md, idx, pkg_name)
        if findings:
            results[f] = findings
    return results


# ---------------------------------------------------------------------------
# LLM fix pass
# ---------------------------------------------------------------------------

def _fix_page(page_path: str, findings: List[dict], api_surface: str,
              client, llm_cfg) -> bool:
    """Send a page + its findings to the LLM and ask it to fix them."""
    with open(page_path, "r", encoding="utf-8") as f:
        content = f.read()

    findings_text = "\n".join(
        f"- {f['symbol']} ({f['kind']}, severity: {f['severity']})"
        for f in findings
    )

    prompt = f"""You are fixing a documentation page that was flagged by an automated hallucination checker.

The following symbols in this page do NOT exist in the source code:
{findings_text}

REAL API SURFACE (the only symbols that exist):
{api_surface}

PAGE TO FIX:
<page>
{content}
</page>

INSTRUCTIONS:
- Remove or correct every flagged symbol. If a code example uses a flagged symbol, rewrite the example using only symbols from the REAL API SURFACE, or remove the example if no real equivalent exists.
- If a flagged symbol is actually a user-defined variable name in an example (not a library API), you may keep it ONLY if it is clearly a local variable (e.g. `result = auditor.run(...)` where `result` is the user's variable).
- Do not change anything else. Preserve structure, tone, and all accurate content.
- Return ONLY the complete fixed markdown page, no preamble."""

    try:
        fixed = client.chat(
            [{"role": "user", "content": prompt}],
            max_tokens=getattr(llm_cfg, "max_tokens", 8192),
            temperature=0.1,
        )
        # Strip code fences if the model wrapped the whole page
        from repoquill.llm import strip_code_fences
        fixed = strip_code_fences(fixed)
        if fixed.strip() and len(fixed) > 100:
            with open(page_path, "w", encoding="utf-8") as f:
                f.write(fixed)
            return True
    except Exception as e:  # noqa: BLE001
        print(f"    fix failed for {os.path.basename(page_path)}: {e}")
    return False


def verify_pages(cfg, client) -> dict:
    """Run verification passes over generated guide pages.

    Args:
        cfg: A :class:`repoquill.config.RepoQuillConfig`.
        client: An :class:`repoquill.llm.LLMClient`.

    Returns:
        Summary dict: {pages_checked, pages_fixed, findings_before, findings_after}.
    """
    passes = getattr(cfg.llm, "verify_passes", 0)
    if passes <= 0:
        return {"pages_checked": 0, "pages_fixed": 0,
                "findings_before": 0, "findings_after": 0}

    from repoquill.reference import extract_api_surface

    idx = build_index(cfg.pkg_path)
    pkg_name = os.path.basename(os.path.normpath(cfg.pkg_path))
    api_surface = extract_api_surface(cfg.pkg_path)

    summary = {"pages_checked": 0, "pages_fixed": 0,
               "findings_before": 0, "findings_after": 0}

    for p in range(passes):
        results = check_all(cfg.out_guides, idx, pkg_name)
        total = sum(len(v) for v in results.values())
        if p == 0:
            summary["findings_before"] = total
        print(f"  verify pass {p + 1}/{passes}: {total} findings in {len(results)} pages")
        if not results:
            break

        for fname, findings in results.items():
            # Only fix high/medium severity (low = method calls, often user vars)
            serious = [f for f in findings if f["severity"] in ("high", "medium")]
            if not serious:
                continue
            page_path = os.path.join(cfg.out_guides, fname)
            print(f"    fixing {fname} ({len(serious)} serious findings)...")
            if _fix_page(page_path, serious, api_surface, client, cfg.llm):
                summary["pages_fixed"] += 1

    # Final count
    final = check_all(cfg.out_guides, idx, pkg_name)
    summary["findings_after"] = sum(len(v) for v in final.values())
    summary["pages_checked"] = len([f for f in os.listdir(cfg.out_guides)
                                    if f.endswith(".md")])
    return summary


# ---------------------------------------------------------------------------
# Deterministic type-claim verification (E47)
# ---------------------------------------------------------------------------

def _build_type_index(pkg_path: str) -> dict:
    """Return {
        'classes': {ClassName: {
            'fields': {field_name: type_annotation_str_or_None},
            'methods': {method_name: {'return_annotation': str_or_None}},
            'properties': {prop_name: type_annotation_str_or_None},
        }},
    }
    """
    from pathlib import Path
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
            if cls not in classes:
                classes[cls] = {"fields": {}, "methods": {}, "properties": {}}
            info = classes[cls]
            for item in node.body:
                if isinstance(item, ast.AnnAssign):
                    if isinstance(item.target, ast.Name):
                        ann = None
                        if item.annotation is not None:
                            try:
                                ann = ast.unparse(item.annotation)
                            except Exception:
                                ann = None
                        info["fields"][item.target.id] = ann
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    ret_ann = None
                    if item.returns is not None:
                        try:
                            ret_ann = ast.unparse(item.returns)
                        except Exception:
                            ret_ann = None
                    is_property = any(
                        (isinstance(d, ast.Name) and d.id == "property")
                        or (isinstance(d, ast.Attribute) and d.attr == "setter")
                        for d in item.decorator_list
                    )
                    if is_property:
                        info["properties"][item.name] = ret_ann
                    else:
                        info["methods"][item.name] = {"return_annotation": ret_ann}
    return {"classes": classes}


def _normalize_type(t: str | None) -> str | None:
    if t is None:
        return None
    t = t.lower().strip()
    m = re.match(r"(?:typing\.)?optional\[(.+)\]", t)
    if m:
        t = m.group(1).strip()
    m = re.match(r"(?:typing\.)?union\[(.+)\]", t)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        for p in parts:
            if p != "none":
                t = p
                break
    if t.startswith("list") or t.startswith("typing.list"):
        return "list"
    if t.startswith("dict") or t.startswith("typing.dict"):
        return "dict"
    if t.startswith("str") or t.startswith("typing.str"):
        return "str"
    if t.startswith("int") or t.startswith("typing.int"):
        return "int"
    if t.startswith("float") or t.startswith("typing.float"):
        return "float"
    if t.startswith("bool") or t.startswith("typing.bool"):
        return "bool"
    if t.startswith("tuple") or t.startswith("typing.tuple"):
        return "tuple"
    if t.startswith("set") or t.startswith("typing.set"):
        return "set"
    if t in ("none", "null"):
        return "none"
    if "mapping" in t:
        return "dict"
    if "sequence" in t:
        return "list"
    return t


_TYPE_CLAIM_RE = re.compile(
    r"""
    `(?P<name>[\w]+)`
    \s*
    (?:
        [:|]\s*(?:a\s+|an\s+)?(?P<type1>bool|boolean|int|integer|list|dict|dictionary|str|string|float|tuple|set|object)\b
        |\s+is\s+(?:a\s+|an\s+)?(?P<type2>bool|boolean|int|integer|list|dict|dictionary|str|string|float|tuple|object)\b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_RETURN_CLAIM_RE = re.compile(
    r"""
    `(?P<name>[\w]+)\(\)`
    \s*
    (?:[:|]\s*)?
    (?:returns?|return|provides?|gives?)\s+
    (?:
        (?:a\s+|an\s+)?(?P<type>list|dict|dictionary|str|string|int|integer|float|bool|boolean|tuple|set|object)\b
        |(?P<none>None|nothing|no\s+value)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

_TYPE_WORD = {
    "int": "int", "integer": "int", "float": "float",
    "str": "str", "string": "str", "bool": "bool", "boolean": "bool",
    "list": "list", "dict": "dict", "dictionary": "dict",
    "tuple": "tuple", "set": "set", "object": "object",
}

_COMPATIBLE = {("int", "float"), ("float", "int"), ("str", "string")}


def _find_source_type(name: str, claimed_norm: str, idx: dict) -> str | None:
    """Return canonical source type for *name* if it contradicts *claimed_norm*,
    else None (supported or unverifiable)."""
    for cls_name, info in idx["classes"].items():
        if name in info["methods"]:
            src_norm = _normalize_type(info["methods"][name]["return_annotation"])
            if src_norm is None or src_norm == claimed_norm:
                continue
            if (src_norm, claimed_norm) in _COMPATIBLE or (claimed_norm, src_norm) in _COMPATIBLE:
                continue
            return src_norm
        if name in info["fields"]:
            src_norm = _normalize_type(info["fields"][name])
            if src_norm is None or src_norm == claimed_norm:
                continue
            if (src_norm, claimed_norm) in _COMPATIBLE or (claimed_norm, src_norm) in _COMPATIBLE:
                continue
            return src_norm
        if name in info["properties"]:
            src_norm = _normalize_type(info["properties"][name])
            if src_norm is None or src_norm == claimed_norm:
                continue
            if (src_norm, claimed_norm) in _COMPATIBLE or (claimed_norm, src_norm) in _COMPATIBLE:
                continue
            return src_norm
    return None


def fix_type_claims(content: str, pkg_path: str) -> str:
    """Replace incorrect type claims in prose with the actual AST type.

    Only fixes TYPE_CLAIM and RETURN_CLAIM patterns where the claimed type
    is contradicted by the source annotation.  Returns the corrected content
    (unchanged if no contradictions found).
    """
    idx = _build_type_index(pkg_path)
    lines = content.split("\n")
    in_fence = False

    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        for m in _TYPE_CLAIM_RE.finditer(line):
            name = m.group("name")
            grp = "type1" if m.group("type1") else "type2"
            claimed = m.group(grp).lower()
            claimed_norm = _normalize_type(claimed)
            src_norm = _find_source_type(name, claimed_norm, idx)
            if src_norm is not None:
                correct_word = _TYPE_WORD.get(src_norm, src_norm)
                lines[i] = line[: m.start(grp)] + correct_word + line[m.end(grp):]
                line = lines[i]

        for m in _RETURN_CLAIM_RE.finditer(lines[i]):
            name = m.group("name")
            grp = "type" if m.group("type") else "none"
            claimed = m.group(grp).lower()
            claimed_norm = _normalize_type(claimed)
            src_norm = _find_source_type(name, claimed_norm, idx)
            if src_norm is not None:
                correct_word = _TYPE_WORD.get(src_norm, src_norm)
                lines[i] = lines[i][: m.start(grp)] + correct_word + lines[i][m.end(grp):]

    return "\n".join(lines)
