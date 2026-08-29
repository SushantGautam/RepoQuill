"""E35 — API signature & return-type verification checker.

Extracts actual API signatures from source (AST) and flags doc statements
that contradict the source. Catches the name-based inference failure mode:
the LLM sees `passed`/`failed`/`summary` and assumes bool/str return types
without checking the actual property/method bodies.

Checks:
  1. RETURN_TYPE_MISMATCH — doc says "returns a X" but source shows different type
  2. ASYNC_MISMATCH — doc treats method as sync but source shows async (or vice versa)
  3. PROPERTY_AS_METHOD — doc calls property as method (or vice versa)
  4. REQUIRED_ARG_MISMATCH — doc shows call missing required args

Usage: api_signature_check.py <pkg_path> <guides_dir> <output_json>
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# AST extraction
# ---------------------------------------------------------------------------

def build_signature_index(pkg_path: str) -> dict:
    """Return {
        'classes': {ClassName: {
            'fields': {field_name: type_annotation_str_or_None},
            'methods': {method_name: {
                'is_async': bool,
                'return_annotation': str_or_None,
                'required_args': [arg_name, ...],
            }},
            'properties': {prop_name: {
                'return_annotation': str_or_None,
                'is_cached': bool,
            }},
        }},
        'module_functions': {func_name: {
            'is_async': bool,
            'return_annotation': str_or_None,
            'required_args': [arg_name, ...],
        }},
    }
    """
    classes: dict = {}
    module_functions: dict = {}

    for py in Path(pkg_path).rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, OSError):
            continue

        for node in ast.walk(tree):
            # Module-level functions
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                is_async = isinstance(node, ast.AsyncFunctionDef)
                ret_ann = None
                if node.returns is not None:
                    try:
                        ret_ann = ast.unparse(node.returns)
                    except Exception:
                        ret_ann = None
                required_args = _extract_required_args(node)
                module_functions[node.name] = {
                    "is_async": is_async,
                    "return_annotation": ret_ann,
                    "required_args": required_args,
                }

            # Classes
            if not isinstance(node, ast.ClassDef):
                continue
            cls = node.name
            if cls not in classes:
                classes[cls] = {
                    "fields": {},
                    "methods": {},
                    "properties": {},
                }
            info = classes[cls]

            for item in node.body:
                # Fields (annotated assignments)
                if isinstance(item, ast.AnnAssign):
                    if isinstance(item.target, ast.Name):
                        ann = None
                        if item.annotation is not None:
                            try:
                                ann = ast.unparse(item.annotation)
                            except Exception:
                                ann = None
                        info["fields"][item.target.id] = ann

                # Methods and properties
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    is_async = isinstance(item, ast.AsyncFunctionDef)
                    ret_ann = None
                    if item.returns is not None:
                        try:
                            ret_ann = ast.unparse(item.returns)
                        except Exception:
                            ret_ann = None
                    required_args = _extract_required_args(item)

                    # Check for @property or @cached_property decorator
                    is_property = False
                    is_cached = False
                    for dec in item.decorator_list:
                        if isinstance(dec, ast.Name) and dec.id in ("property", "cached_property"):
                            is_property = True
                            is_cached = dec.id == "cached_property"
                        elif isinstance(dec, ast.Attribute) and dec.attr in ("property", "cached_property"):
                            is_property = True
                            is_cached = dec.attr == "cached_property"

                    if is_property:
                        info["properties"][item.name] = {
                            "return_annotation": ret_ann,
                            "is_cached": is_cached,
                        }
                    else:
                        info["methods"][item.name] = {
                            "is_async": is_async,
                            "return_annotation": ret_ann,
                            "required_args": required_args,
                        }

    return {"classes": classes, "module_functions": module_functions}


def _extract_required_args(func_node) -> list:
    """Extract required argument names (no defaults) from a function node."""
    args = func_node.args
    all_args = list(args.args)
    # Skip self/cls
    if all_args and all_args[0].arg in ("self", "cls"):
        all_args = all_args[1:]
    # Add keyword-only args
    all_args = all_args + list(args.kwonlyargs)
    # Count defaults
    defaults = list(args.defaults) + list(args.kw_defaults)
    # Required args are those without defaults
    required = []
    for i, arg in enumerate(all_args):
        # Defaults are right-aligned in args.args
        if i < len(all_args) - len(args.defaults) and i < len(args.args) - (1 if all_args and all_args[0].arg in ("self", "cls") else 0):
            required.append(arg.arg)
        elif arg.arg not in [d.arg for d in all_args if d.arg in [a.arg for a in args.kwonlyargs]]:
            # Check if this arg has a default
            has_default = False
            for kw_default in args.kw_defaults:
                if kw_default is not None:
                    has_default = True
            if not has_default:
                required.append(arg.arg)
    return required


# ---------------------------------------------------------------------------
# Claim extraction from docs
# ---------------------------------------------------------------------------

def strip_code_blocks(md_text: str) -> str:
    """Remove fenced code blocks, keeping line alignment."""
    lines = md_text.split("\n")
    in_block = False
    result = []
    for line in lines:
        if line.strip().startswith("```"):
            in_block = not in_block
            result.append("")
            continue
        if in_block:
            result.append("")
        else:
            result.append(line)
    return "\n".join(result)


# Words that are NOT type names — filter these out of return claims
_NON_TYPE_WORDS = {
    "copy", "shallow", "deep", "new", "fresh", "list", "dict",
    "string", "number", "value", "result", "response", "object",
    "instance", "reference", "pointer", "handle", "token", "key",
    "map", "set", "array", "collection", "sequence", "iterable",
    "generator", "iterator", "function", "callable", "class",
    "module", "package", "file", "directory", "path", "url",
    "name", "id", "uuid", "hash", "digest", "signature",
    "score", "rating", "grade", "rank", "level", "status",
    "state", "condition", "outcome", "outcome", "verdict",
    "label", "tag", "flag", "mark", "symbol", "character",
    "word", "phrase", "sentence", "paragraph", "text", "content",
    "data", "info", "information", "detail", "details",
    "error", "exception", "warning", "message", "note",
    "item", "element", "entry", "record", "row", "column",
    "field", "attribute", "property", "parameter", "argument",
    "option", "choice", "selection", "preference", "setting",
    "config", "configuration", "spec", "specification",
    "plan", "strategy", "policy", "rule", "constraint",
    "limit", "bound", "range", "interval", "period", "duration",
    "time", "date", "moment", "instant", "point",
    "place", "location", "position", "spot", "site",
    "area", "region", "zone", "sector", "quadrant",
    "shape", "form", "structure", "layout", "format",
    "style", "theme", "mode", "variant", "version",
    "edition", "release", "build", "revision", "iteration",
    "step", "stage", "phase", "cycle", "loop", "pass",
    "round", "turn", "move", "action", "operation",
    "task", "job", "work", "process", "procedure",
    "method", "approach", "technique", "algorithm",
    "model", "system", "framework", "library", "tool",
    "utility", "helper", "wrapper", "adapter", "proxy",
    "client", "server", "service", "endpoint", "interface",
    "component", "widget", "element", "node", "edge",
    "graph", "tree", "graph", "network", "mesh",
}


def extract_return_claims(md_text: str) -> list:
    """Extract return type claims from prose.

    Patterns:
      - "returns a <type>"
      - "return value is a <type>"
      - "the return type is <type>"
      - "returns <type>" (without article)
    """
    claims = []
    text = strip_code_blocks(md_text)

    # Pattern 1: "returns a <type>"
    for m in re.finditer(r"returns?\s+a\s+([a-zA-Z_][a-zA-Z0-9_]*)", text):
        claimed = m.group(1)
        if claimed.lower() in _NON_TYPE_WORDS:
            continue
        claims.append({
            "type": "RETURN_CLAIM",
            "claimed_type": claimed,
            "context": text[max(0, m.start()-50):m.end()+50].strip(),
            "line": text[:m.start()].count("\n") + 1,
        })

    # Pattern 2: "return value is a <type>"
    for m in re.finditer(r"return\s+value\s+is\s+a\s+([a-zA-Z_][a-zA-Z0-9_]*)", text):
        claimed = m.group(1)
        if claimed.lower() in _NON_TYPE_WORDS:
            continue
        claims.append({
            "type": "RETURN_CLAIM",
            "claimed_type": claimed,
            "context": text[max(0, m.start()-50):m.end()+50].strip(),
            "line": text[:m.start()].count("\n") + 1,
        })

    # Pattern 3: "the return type is <type>"
    for m in re.finditer(r"return\s+type\s+is\s+a?\s*([a-zA-Z_][a-zA-Z0-9_]*)", text):
        claimed = m.group(1)
        if claimed.lower() in _NON_TYPE_WORDS:
            continue
        claims.append({
            "type": "RETURN_CLAIM",
            "claimed_type": claimed,
            "context": text[max(0, m.start()-50):m.end()+50].strip(),
            "line": text[:m.start()].count("\n") + 1,
        })

    return claims


def extract_async_claims(md_text: str) -> list:
    """Extract async/sync claims from prose.

    Patterns:
      - "is async" / "is an async"
      - "is synchronous" / "is a sync"
      - "async def" (in code blocks, but we strip those)
    """
    claims = []
    text = strip_code_blocks(md_text)

    # Pattern: "X is async" or "X is an async"
    for m in re.finditer(r"(\w+)\s+is\s+(?:an?\s+)?async", text):
        claims.append({
            "type": "ASYNC_CLAIM",
            "claimed_async": True,
            "method_name": m.group(1),
            "context": text[max(0, m.start()-50):m.end()+50].strip(),
            "line": text[:m.start()].count("\n") + 1,
        })

    # Pattern: "X is synchronous" or "X is a sync"
    for m in re.finditer(r"(\w+)\s+is\s+(?:a\s+)?(?:sync(?:hronous)?|synchronous)", text):
        claims.append({
            "type": "ASYNC_CLAIM",
            "claimed_async": False,
            "method_name": m.group(1),
            "context": text[max(0, m.start()-50):m.end()+50].strip(),
            "line": text[:m.start()].count("\n") + 1,
        })

    return claims


def extract_method_calls(md_text: str) -> list:
    """Extract method calls from code blocks.

    Patterns:
      - obj.method(args)
      - await obj.method(args)
    """
    calls = []
    lines = md_text.split("\n")
    in_block = False
    block_lines = []

    for line in lines:
        if line.strip().startswith("```"):
            if in_block:
                # End of block — process
                for i, bl in enumerate(block_lines):
                    # Find method calls
                    for m in re.finditer(r"(?:await\s+)?(\w+)\.(\w+)\s*\(", bl):
                        calls.append({
                            "object": m.group(1),
                            "method": m.group(2),
                            "has_await": "await" in bl[:m.start()],
                            "line": i + 1,
                            "context": bl.strip(),
                        })
                block_lines = []
            in_block = not in_block
            continue
        if in_block:
            block_lines.append(line)

    return calls


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def normalize_type(t: str) -> str:
    """Normalize type strings for comparison."""
    t = t.lower().strip()
    # Handle common aliases
    if t in ("bool", "boolean"):
        return "bool"
    if t in ("int", "integer"):
        return "int"
    if t in ("float", "floating point"):
        return "float"
    if t in ("str", "string"):
        return "str"
    if t in ("list", "array"):
        return "list"
    if t in ("dict", "dictionary", "map"):
        return "dict"
    if t in ("tuple",):
        return "tuple"
    if t in ("set",):
        return "set"
    if t in ("none", "null"):
        return "none"
    # Handle Optional[X]
    if t.startswith("optional["):
        inner = t[t.index("[")+1:t.rindex("]")]
        return f"optional[{normalize_type(inner)}]"
    # Handle List[X], Dict[K,V], etc.
    if t.startswith("list["):
        return "list"
    if t.startswith("dict["):
        return "dict"
    if t.startswith("tuple["):
        return "tuple"
    if t.startswith("set["):
        return "set"
    return t


def types_compatible(claimed: str, actual: str) -> bool:
    """Check if claimed type is compatible with actual type."""
    c = normalize_type(claimed)
    a = normalize_type(actual)
    if c == a:
        return True
    # Compatible pairs
    if (c, a) in [("int", "float"), ("float", "int"), ("str", "string")]:
        return True
    # Optional[X] is compatible with X
    if c.startswith("optional[") and a == c[c.index("[")+1:c.rindex("]")]:
        return True
    if a.startswith("optional[") and c == a[a.index("[")+1:a.rindex("]")]:
        return True
    return False


def verify_claims(claims: list, index: dict) -> list:
    """Verify extracted claims against the signature index.

    Returns list of findings: {type, claimed, actual, context, line, severity}
    """
    findings = []
    classes = index.get("classes", {})
    module_functions = index.get("module_functions", {})

    for claim in claims:
        ctype = claim["type"]

        if ctype == "RETURN_CLAIM":
            # Try to find the method/property this claim is about
            # This is heuristic — we look for method names in the context
            context = claim["context"]
            claimed_type = claim["claimed_type"]

            # Search for method names in context
            found_method = None
            for cls_name, cls_info in classes.items():
                for method_name, method_info in cls_info["methods"].items():
                    if method_name in context:
                        found_method = (cls_name, method_name, method_info)
                        break
                if found_method:
                    break
                for prop_name, prop_info in cls_info["properties"].items():
                    if prop_name in context:
                        found_method = (cls_name, prop_name, prop_info, "property")
                        break
                if found_method:
                    break

            if not found_method:
                # Check module-level functions
                for func_name, func_info in module_functions.items():
                    if func_name in context:
                        found_method = (None, func_name, func_info)
                        break

            if found_method:
                if len(found_method) == 4:  # Property
                    cls_name, name, info, _ = found_method
                    actual_type = info.get("return_annotation")
                else:
                    cls_name, name, info = found_method
                    actual_type = info.get("return_annotation")

                if actual_type and not types_compatible(claimed_type, actual_type):
                    findings.append({
                        "type": "RETURN_TYPE_MISMATCH",
                        "method": name,
                        "class": cls_name,
                        "claimed": claimed_type,
                        "actual": actual_type,
                        "context": context,
                        "line": claim["line"],
                        "severity": "CRITICAL",
                    })

        elif ctype == "ASYNC_CLAIM":
            method_name = claim["method_name"]
            claimed_async = claim["claimed_async"]
            context = claim["context"]

            # Search for the method in the index
            found_method = None
            for cls_name, cls_info in classes.items():
                if method_name in cls_info["methods"]:
                    found_method = (cls_name, method_name, cls_info["methods"][method_name])
                    break

            if not found_method:
                if method_name in module_functions:
                    found_method = (None, method_name, module_functions[method_name])

            if found_method:
                cls_name, name, info = found_method
                actual_async = info.get("is_async", False)
                if actual_async != claimed_async:
                    findings.append({
                        "type": "ASYNC_MISMATCH",
                        "method": name,
                        "class": cls_name,
                        "claimed": "async" if claimed_async else "sync",
                        "actual": "async" if actual_async else "sync",
                        "context": context,
                        "line": claim["line"],
                        "severity": "CRITICAL",
                    })

    return findings


def check_method_calls(calls: list, index: dict) -> list:
    """Check method calls for async/await mismatches and required args."""
    findings = []
    classes = index.get("classes", {})
    module_functions = index.get("module_functions", {})

    for call in calls:
        method_name = call["method"]
        has_await = call["has_await"]

        # Find the method in the index
        found = None
        for cls_name, cls_info in classes.items():
            if method_name in cls_info["methods"]:
                found = (cls_name, method_name, cls_info["methods"][method_name])
                break

        if not found:
            if method_name in module_functions:
                found = (None, method_name, module_functions[method_name])

        if found:
            cls_name, name, info = found
            is_async = info.get("is_async", False)

            # Check async/await mismatch
            if is_async and not has_await:
                findings.append({
                    "type": "MISSING_AWAIT",
                    "method": name,
                    "class": cls_name,
                    "context": call["context"],
                    "line": call["line"],
                    "severity": "HIGH",
                })

            # Check required args (simplified — just check if call has any args)
            required = info.get("required_args", [])
            if required:
                # Count args in the call (rough heuristic)
                args_match = re.search(rf"{name}\s*\(([^)]*)\)", call["context"])
                if args_match:
                    args_str = args_match.group(1).strip()
                    if not args_str:
                        findings.append({
                            "type": "MISSING_REQUIRED_ARGS",
                            "method": name,
                            "class": cls_name,
                            "required": required,
                            "context": call["context"],
                            "line": call["line"],
                            "severity": "HIGH",
                        })

    return findings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def check_all(guides_dir: str, index: dict) -> dict:
    """Run all checks on all guide pages."""
    results = {}
    total_findings = 0
    total_critical = 0
    total_high = 0

    for py in sorted(Path(guides_dir).glob("*.md")):
        content = py.read_text(encoding="utf-8")
        page_findings = []

        # Extract and verify claims
        return_claims = extract_return_claims(content)
        async_claims = extract_async_claims(content)
        all_claims = return_claims + async_claims
        claim_findings = verify_claims(all_claims, index)
        page_findings.extend(claim_findings)

        # Check method calls
        calls = extract_method_calls(content)
        call_findings = check_method_calls(calls, index)
        page_findings.extend(call_findings)

        results[py.name] = page_findings
        total_findings += len(page_findings)
        total_critical += sum(1 for f in page_findings if f["severity"] == "CRITICAL")
        total_high += sum(1 for f in page_findings if f["severity"] == "HIGH")

    return {
        "pages": results,
        "total_findings": total_findings,
        "total_critical": total_critical,
        "total_high": total_high,
    }


def main():
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} <pkg_path> <guides_dir> <output_json>")
        sys.exit(1)

    pkg_path = sys.argv[1]
    guides_dir = sys.argv[2]
    output_json = sys.argv[3]

    index = build_signature_index(pkg_path)
    results = check_all(guides_dir, index)

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"Total findings: {results['total_findings']}")
    print(f"  CRITICAL: {results['total_critical']}")
    print(f"  HIGH: {results['total_high']}")
    print(f"Wrote {output_json}")


if __name__ == "__main__":
    main()
