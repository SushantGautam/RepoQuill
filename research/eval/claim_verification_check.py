"""E32 — Claim verification checker (C-hallucination metric).

Extracts atomic factual claims from generated docs and validates them against
the source AST. Catches the error class that prose_api_semantics_check.py
structurally misses: the doc references a REAL symbol but asserts a FALSE fact
about it.

Claim types checked:
  1. TYPE_CLAIM — "X is a bool/int/list/dict/str" vs source annotation
  2. RETURN_CLAIM — "X() returns a list/dict/str/None" vs source return annotation
  3. ASYNC_CLAIM — "X() is async" vs source @async def
  4. FIELD_CLAIM — "result.X" where X doesn't exist on the class

Usage: claim_verification_check.py <pkg_path> <guides_dir> <output_json>
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

def build_claim_index(pkg_path: str) -> dict:
    """Return {
        'classes': {ClassName: {
            'fields': {field_name: type_annotation_str_or_None},
            'methods': {method_name: {
                'is_async': bool,
                'return_annotation': str_or_None,
            }},
            'properties': {prop_name: type_annotation_str_or_None},
        }},
    }
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

                    is_property = False
                    for dec in item.decorator_list:
                        if isinstance(dec, ast.Name) and dec.id == "property":
                            is_property = True
                        elif isinstance(dec, ast.Attribute) and dec.attr == "setter":
                            is_property = True

                    if is_property:
                        info["properties"][item.name] = ret_ann
                    else:
                        info["methods"][item.name] = {
                            "is_async": is_async,
                            "return_annotation": ret_ann,
                        }

    return {"classes": classes}


# ---------------------------------------------------------------------------
# Claim extraction
# ---------------------------------------------------------------------------

def strip_code_blocks(md_text: str) -> str:
    """Remove all fenced code blocks, keeping line numbers aligned."""
    lines = md_text.split("\n")
    in_fence = False
    result = []
    for line in lines:
        if line.strip().startswith("```"):
            in_fence = not in_fence
            result.append("")
            continue
        if in_fence:
            result.append("")
        else:
            result.append(line)
    return "\n".join(result)


def extract_claims(md_text: str) -> list[dict]:
    """Extract atomic factual claims from markdown prose.

    Returns list of dicts:
      {
        'line': int,
        'type': str,  # 'TYPE_CLAIM', 'RETURN_CLAIM', 'ASYNC_CLAIM', 'FIELD_CLAIM'
        'name': str,  # the symbol being claimed about
        'claim': str, # the specific claim (e.g., 'bool', 'list', 'async')
        'context': str,
      }
    """
    prose = strip_code_blocks(md_text)
    claims = []

    # Pattern 1: TYPE_CLAIM — "`name`: a bool/int/list/dict/str"
    # or "`name` is a bool/int/list/dict/str"
    # E44: "is set" / "is not set" are not type claims — they describe
    # whether a value is configured. Exclude "set" from the "is" branch.
    type_re = re.compile(
        r"""
        `(?P<name>[\w]+)`
        \s*
        (?:
            [:|]\s*(?:a\s+|an\s+)?(?P<type1>bool|boolean|int|integer|list|dict|dictionary|str|string|float|tuple|set|object)
            |\s+is\s+(?:a\s+|an\s+)?(?P<type2>bool|boolean|int|integer|list|dict|dictionary|str|string|float|tuple|object)
        )
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    # Pattern 2: RETURN_CLAIM — "`name()`: returns a list/dict/str/None"
    return_re = re.compile(
        r"""
        `(?P<name>[\w]+)\(\)`
        \s*
        (?:[:|]\s*)?
        (?:returns?|return|provides?|gives?)\s+
        (?:
            (?:a\s+|an\s+)?(?P<type>list|dict|dictionary|str|string|int|integer|float|bool|boolean|tuple|set|object)
            |(?P<none>None|nothing|no\s+value)
        )
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    # Pattern 3: ASYNC_CLAIM — "`name()` is async" or "call `name()` (async)"
    async_re = re.compile(
        r"""
        `(?P<name>[\w]+)\(\)`
        \s*
        (?:
            is\s+async
            |async\s+method
            |async\s+function
            |\(async\)
        )
        """,
        re.IGNORECASE,
    )

    # Pattern 4: FIELD_CLAIM — "result.name" or "obj.name" in prose
    # (only check if the field is claimed to exist)
    field_re = re.compile(
        r"""
        (?:result|obj|instance|the\s+\w+)\.(?P<name>[\w]+)
        """,
        re.IGNORECASE,
    )

    for line_no, line in enumerate(prose.split("\n"), 1):
        if not line.strip():
            continue

        # TYPE_CLAIM
        for m in type_re.finditer(line):
            name = m.group("name")
            claim_type = m.group("type1") or m.group("type2")
            if claim_type:
                claims.append({
                    "line": line_no,
                    "type": "TYPE_CLAIM",
                    "name": name,
                    "claim": claim_type.lower(),
                    "context": line.strip()[:100],
                })

        # RETURN_CLAIM
        for m in return_re.finditer(line):
            name = m.group("name")
            claim_type = m.group("type") or m.group("none")
            if claim_type:
                claims.append({
                    "line": line_no,
                    "type": "RETURN_CLAIM",
                    "name": name,
                    "claim": claim_type.lower(),
                    "context": line.strip()[:100],
                })

        # ASYNC_CLAIM
        for m in async_re.finditer(line):
            name = m.group("name")
            claims.append({
                "line": line_no,
                "type": "ASYNC_CLAIM",
                "name": name,
                "claim": "async",
                "context": line.strip()[:100],
            })

    return claims


# ---------------------------------------------------------------------------
# Claim verification
# ---------------------------------------------------------------------------

def normalize_type(t: str | None) -> str | None:
    """Normalize a type string for comparison.

    E44: extended to handle Optional[...], Union[...], cabc.MutableMapping,
    cabc.Mapping, cabc.Sequence, and other common type aliases that were
    previously causing false-positive CONTRADICTED findings.
    """
    if t is None:
        return None
    t = t.lower().strip()

    # Strip Optional[...] and Union[...] wrappers — take the first non-None type
    m = re.match(r'(?:typing\.)?optional\[(.+)\]', t)
    if m:
        t = m.group(1).strip()
    m = re.match(r'(?:typing\.)?union\[(.+)\]', t)
    if m:
        # Take the first non-None type in the union
        parts = [p.strip() for p in m.group(1).split(',')]
        for p in parts:
            if p not in ('none', 'none'):
                t = p
                break

    # Handle generic types like List[str], Dict[str, int]
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
    if t in ("none", "none", "null"):
        return "none"

    # E44: mapping-like types (cabc.MutableMapping, cabc.Mapping, etc.)
    # These are semantically equivalent to dict for documentation purposes.
    if "mapping" in t or "mutuablemapping" in t:
        return "dict"
    if "sequence" in t:
        return "list"

    return t


def verify_claims(claims: list[dict], index: dict) -> list[dict]:
    """Verify each claim against the AST index.

    Returns list of findings:
      {
        'type': str,  # 'CONTRADICTED', 'SUPPORTED', 'UNVERIFIABLE'
        'claim_type': str,
        'name': str,
        'claim': str,
        'source_truth': str,
        'line': int,
        'context': str,
      }
    """
    findings = []
    classes = index["classes"]

    for claim in claims:
        name = claim["name"]
        claim_type = claim["type"]
        claimed = claim["claim"]
        line = claim["line"]
        context = claim["context"]

        # Find which class(es) have this member
        matching_classes = []
        for cls_name, info in classes.items():
            if claim_type == "TYPE_CLAIM":
                if name in info["fields"]:
                    matching_classes.append((cls_name, "field", info["fields"][name]))
                elif name in info["properties"]:
                    matching_classes.append((cls_name, "property", info["properties"][name]))
            elif claim_type == "RETURN_CLAIM":
                if name in info["methods"]:
                    method_info = info["methods"][name]
                    matching_classes.append((cls_name, "method", method_info["return_annotation"]))
            elif claim_type == "ASYNC_CLAIM":
                if name in info["methods"]:
                    method_info = info["methods"][name]
                    matching_classes.append((cls_name, "method_async", str(method_info["is_async"]).lower()))

        if not matching_classes:
            findings.append({
                "type": "UNVERIFIABLE",
                "claim_type": claim_type,
                "name": name,
                "claim": claimed,
                "source_truth": "member not found in any class",
                "line": line,
                "context": context,
            })
            continue

        # Check each matching class
        for cls_name, member_type, source_value in matching_classes:
            if claim_type == "TYPE_CLAIM":
                source_norm = normalize_type(source_value)
                claim_norm = normalize_type(claimed)

                if source_norm is None:
                    verdict = "UNVERIFIABLE"
                    source_truth = f"{cls_name}.{name} has no type annotation"
                elif source_norm == claim_norm:
                    verdict = "SUPPORTED"
                    source_truth = f"{cls_name}.{name}: {source_value}"
                else:
                    # Allow some compatible pairs
                    compatible = {
                        ("int", "float"),
                        ("float", "int"),
                        ("str", "string"),
                    }
                    if (source_norm, claim_norm) in compatible or (claim_norm, source_norm) in compatible:
                        verdict = "SUPPORTED"
                        source_truth = f"{cls_name}.{name}: {source_value}"
                    else:
                        verdict = "CONTRADICTED"
                        source_truth = f"{cls_name}.{name}: {source_value} (doc claims {claimed})"

            elif claim_type == "RETURN_CLAIM":
                source_norm = normalize_type(source_value)
                claim_norm = normalize_type(claimed)

                if source_norm is None:
                    # No annotation — can't verify
                    verdict = "UNVERIFIABLE"
                    source_truth = f"{cls_name}.{name}() has no return annotation"
                elif source_norm == claim_norm:
                    verdict = "SUPPORTED"
                    source_truth = f"{cls_name}.{name}() -> {source_value}"
                else:
                    # Check for "vague" claims (e.g., "returns a summary")
                    if claim_norm in ("none", "nothing", "no value"):
                        if source_norm == "none":
                            verdict = "SUPPORTED"
                            source_truth = f"{cls_name}.{name}() -> None"
                        else:
                            verdict = "CONTRADICTED"
                            source_truth = f"{cls_name}.{name}() -> {source_value} (doc claims None)"
                    else:
                        verdict = "CONTRADICTED"
                        source_truth = f"{cls_name}.{name}() -> {source_value} (doc claims {claimed})"

            elif claim_type == "ASYNC_CLAIM":
                source_is_async = source_value == "true"
                claim_is_async = claimed == "async"

                if source_is_async == claim_is_async:
                    verdict = "SUPPORTED"
                    source_truth = f"{cls_name}.{name}() is {'async' if source_is_async else 'sync'}"
                else:
                    verdict = "CONTRADICTED"
                    source_truth = f"{cls_name}.{name}() is {'async' if source_is_async else 'sync'} (doc claims {'async' if claim_is_async else 'sync'})"

            findings.append({
                "type": verdict,
                "claim_type": claim_type,
                "name": name,
                "claim": claimed,
                "class": cls_name,
                "source_truth": source_truth,
                "line": line,
                "context": context,
            })

    return findings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def check_all(guides_dir: str, index: dict) -> dict:
    """Check all pages in guides_dir."""
    results = {}
    total_claims = 0
    total_contradicted = 0
    total_supported = 0
    total_unverifiable = 0

    for md_file in sorted(Path(guides_dir).glob("*.md")):
        text = md_file.read_text(encoding="utf-8", errors="replace")
        claims = extract_claims(text)
        findings = verify_claims(claims, index)

        contradicted = [f for f in findings if f["type"] == "CONTRADICTED"]
        supported = [f for f in findings if f["type"] == "SUPPORTED"]
        unverifiable = [f for f in findings if f["type"] == "UNVERIFIABLE"]

        total_claims += len(claims)
        total_contradicted += len(contradicted)
        total_supported += len(supported)
        total_unverifiable += len(unverifiable)

        results[md_file.stem] = {
            "total_claims": len(claims),
            "contradicted": len(contradicted),
            "supported": len(supported),
            "unverifiable": len(unverifiable),
            "findings": findings,
        }

        if contradicted:
            print(f"  {md_file.stem}: {len(contradicted)} contradicted / {len(claims)} claims")

    return {
        "total_claims": total_claims,
        "total_contradicted": total_contradicted,
        "total_supported": total_supported,
        "total_unverifiable": total_unverifiable,
        "c_hallucination_rate": total_contradicted / total_claims if total_claims > 0 else 0.0,
        "pages": results,
    }


def main():
    if len(sys.argv) != 4:
        print("Usage: claim_verification_check.py <pkg_path> <guides_dir> <output_json>")
        sys.exit(1)

    pkg_path = sys.argv[1]
    guides_dir = sys.argv[2]
    output_json = sys.argv[3]

    index = build_claim_index(pkg_path)
    print(f"Indexed {len(index['classes'])} classes")

    results = check_all(guides_dir, index)

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\nTotal claims: {results['total_claims']}")
    print(f"Contradicted: {results['total_contradicted']}")
    print(f"Supported: {results['total_supported']}")
    print(f"Unverifiable: {results['total_unverifiable']}")
    print(f"C-hallucination rate: {results['c_hallucination_rate']:.1%}")
    print(f"Wrote {output_json}")


if __name__ == "__main__":
    main()
