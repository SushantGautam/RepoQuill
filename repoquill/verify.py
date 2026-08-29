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
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Set


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
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as fh:
                    tree = ast.parse(fh.read())
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    idx.classes.add(node.name)
                    idx.module_symbols.add(node.name)
                    idx.class_methods.setdefault(node.name, set())
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            idx.class_methods[node.name].add(item.name)
                            for a in item.args.args:
                                idx.function_params.add(a.arg)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    idx.functions.add(node.name)
                    idx.module_symbols.add(node.name)
                    for a in node.args.args:
                        idx.function_params.add(a.arg)
                elif isinstance(node, ast.Assign):
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name) and tgt.id.isupper():
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


def extract_imports(md: str) -> List[str]:
    """Extract module paths and symbols from import statements in code blocks."""
    found = []
    for block in extract_code_blocks(md):
        for line in block.splitlines():
            line = line.strip()
            m = re.match(r"^(?:from|import)\s+([\w.]+)", line)
            if m:
                found.append(m.group(1))
                if line.startswith("from"):
                    rest = line.split("import", 1)[1].strip()
                    for sym in rest.split(","):
                        sym = sym.strip().split(" as ")[0].strip()
                        if sym and sym != "*":
                            found.append(sym)
    return found


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
    for imp in extract_imports(page_md):
        if imp in idx.modules or imp in idx.module_symbols:
            continue
        top = imp.split(".")[0]
        if top == pkg_name or top in idx.modules:
            # from pkg.sub import X — check X
            parts = imp.split(".")
            if len(parts) > 1 and parts[-1] not in idx.module_symbols:
                findings.append({"symbol": imp, "kind": "import",
                                 "severity": "medium"})
        else:
            findings.append({"symbol": imp, "kind": "import",
                             "severity": "high"})

    # 2. Backtick identifiers
    # Build a set of bare module names (last part of each module path)
    bare_module_names = {m.split(".")[-1] for m in idx.modules}
    for sym in extract_backtick_symbols(page_md):
        if sym in idx.module_symbols or sym in idx.string_literals \
                or sym in idx.function_params or sym in idx.constants \
                or sym in idx.modules or sym in bare_module_names:
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
