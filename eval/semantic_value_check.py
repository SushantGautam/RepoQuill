#!/usr/bin/env python3
"""Semantic value checker: catches wrong string literals and missing caveats.

E20 experiment: closes the last major C-hallucination blind spot identified
by RETRO3. The current checkers (example_check, hallucination_check,
prose_api_semantics_check) catch API misuse but NOT:
1. Wrong string literal values (e.g. language="en" when source default is "English")
2. Missing behavioral caveats (e.g. run() raises RuntimeError in active event loop)

Usage:
    python semantic_value_check.py <pkg_path> <guides_dir> <output_json>

Finding types:
    STRING_VALUE_MISMATCH — code block uses a string literal that differs from
        the source parameter's default
    MISSING_CAVEAT — a method that raises an exception under a specific runtime
        condition is documented without mentioning the condition
"""

import ast
import json
import os
import re
import sys
from typing import Dict, List, Set, Tuple


def build_param_defaults(pkg_path: str) -> Dict[str, Dict[str, str]]:
    """Walk the package and extract string-typed parameter defaults.

    Returns:
        Dict mapping "ClassName" -> {param_name: default_value_str}
        for all params with string defaults (across all methods, not just __init__).
    """
    defaults: Dict[str, Dict[str, str]] = {}
    for root, _dirs, files in os.walk(pkg_path):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    source = f.read()
                tree = ast.parse(source)
            except (SyntaxError, UnicodeDecodeError):
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    class_name = node.name
                    for item in node.body:
                        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            continue
                        # Look at all methods, not just __init__
                        for arg in item.args.args:
                            if arg.arg == "self":
                                continue
                            # Find the default for this arg
                            arg_index = item.args.args.index(arg)
                            num_defaults = len(item.args.defaults)
                            # Defaults are right-aligned
                            offset = len(item.args.args) - num_defaults
                            default_index = arg_index - offset
                            if default_index >= 0 and default_index < len(item.args.defaults):
                                default_node = item.args.defaults[default_index]
                                if isinstance(default_node, ast.Constant) and isinstance(default_node.value, str):
                                    if class_name not in defaults:
                                        defaults[class_name] = {}
                                    defaults[class_name][arg.arg] = default_node.value
    return defaults


def _resolve_raise_msg(msg_node: ast.AST, func_node: ast.AST) -> str:
    """Resolve a raise message to a string, handling both direct constants
    and variable references to string constants assigned in the same function."""
    if isinstance(msg_node, ast.Constant) and isinstance(msg_node.value, str):
        return msg_node.value
    # Handle variable reference: look for a matching assignment in the function
    if isinstance(msg_node, ast.Name):
        var_name = msg_node.id
        for sub in ast.walk(func_node):
            if isinstance(sub, ast.Assign):
                for target in sub.targets:
                    if isinstance(target, ast.Name) and target.id == var_name:
                        val = sub.value
                        if isinstance(val, ast.Constant) and isinstance(val.value, str):
                            return val.value
                        # Handle string concatenation: ("a" "b" "c")
                        if isinstance(val, ast.JoinedStr):
                            # f-string — extract the constant parts
                            parts = []
                            for v in val.values:
                                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                                    parts.append(v.value)
                            if parts:
                                return "".join(parts)
    return ""


def build_caveat_methods(pkg_path: str) -> Dict[str, List[str]]:
    """Walk the package and find methods that raise exceptions under runtime conditions.

    Returns:
        Dict mapping "ClassName.method_name" -> list of caveat descriptions
    """
    caveats: Dict[str, List[str]] = {}
    condition_patterns = [
        "event loop",
        "active event",
        "thread",
        "asyncio",
    ]
    for root, _dirs, files in os.walk(pkg_path):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    source = f.read()
                tree = ast.parse(source)
            except (SyntaxError, UnicodeDecodeError):
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    class_name = node.name
                    for item in node.body:
                        if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            continue
                        if item.name == "__init__":
                            continue
                        method_name = item.name
                        # Look for raise statements that mention runtime conditions
                        for sub in ast.walk(item):
                            if isinstance(sub, ast.Raise):
                                exc = sub.exc
                                if isinstance(exc, ast.Call) and exc.args:
                                    msg = _resolve_raise_msg(exc.args[0], item)
                                    if not msg:
                                        continue
                                    for pattern in condition_patterns:
                                        if pattern in msg.lower():
                                            key = f"{class_name}.{method_name}"
                                            if key not in caveats:
                                                caveats[key] = []
                                            if msg not in caveats[key]:
                                                caveats[key].append(msg)
                                            break
    return caveats


def extract_code_blocks(content: str) -> List[str]:
    """Extract all fenced code blocks from markdown."""
    blocks = []
    in_block = False
    current = []
    for line in content.split("\n"):
        if line.strip().startswith("```"):
            if in_block:
                blocks.append("\n".join(current))
                current = []
                in_block = False
            else:
                in_block = True
        elif in_block:
            current.append(line)
    return blocks


def build_global_param_defaults(
    param_defaults: Dict[str, Dict[str, str]],
) -> Dict[str, List[str]]:
    """Flatten per-class param defaults into a global {param_name: [defaults]} map.

    This allows matching string kwargs against any known default for that param
    name, regardless of which class the doc's call is written against. This is
    necessary because docs may use a class name that doesn't exist in the source
    (a hallucination caught by the hallucination checker) or reference a param
    that lives on a different class than the one being called.
    """
    global_defaults: Dict[str, List[str]] = {}
    for class_name, defaults in param_defaults.items():
        for param, default in defaults.items():
            if param not in global_defaults:
                global_defaults[param] = []
            if default not in global_defaults[param]:
                global_defaults[param].append(default)
    return global_defaults


def check_string_values(
    content: str,
    global_defaults: Dict[str, List[str]],
    page: str,
) -> List[dict]:
    """Check string literal values in code blocks against source defaults.

    Uses a global param-name -> defaults map so that a string kwarg in ANY
    call is checked against all known defaults for that param name. This is
    generic: it catches docs that abbreviate a string default (e.g.
    language="en" when the source default is "English") regardless of which
    class the doc's call is written against.
    """
    findings = []
    code_blocks = extract_code_blocks(content)

    for block in code_blocks:
        # Find all calls with kwargs: ClassName(...) or instance.method(...)
        call_pattern = re.compile(
            r"(\w+(?:\.\w+)?)\s*\(([^)]*)\)", re.DOTALL
        )
        for match in call_pattern.finditer(block):
            call_name = match.group(1)
            args_str = match.group(2)

            # Parse kwargs from the args string
            kwarg_pattern = re.compile(
                r"(\w+)\s*=\s*['\"]([^'\"]*)['\"]"
            )
            for kw_match in kwarg_pattern.finditer(args_str):
                param_name = kw_match.group(1)
                value = kw_match.group(2)

                if param_name not in global_defaults:
                    continue

                for source_default in global_defaults[param_name]:
                    # Only flag if the doc value is a strict prefix/abbreviation
                    # of the source default (e.g. "en" is a prefix of "English").
                    # This avoids false positives on multi-choice params like
                    # provider where the default is just one of several valid options.
                    if value != source_default and (
                        source_default.lower().startswith(value.lower())
                        or value.lower().startswith(source_default.lower())
                    ) and len(value) < len(source_default):
                        line_num = block[:kw_match.start()].count("\n") + 1
                        findings.append({
                            "type": "STRING_VALUE_MISMATCH",
                            "page": page,
                            "call": call_name,
                            "param": param_name,
                            "doc_value": value,
                            "source_default": source_default,
                            "line": line_num,
                            "detail": (
                                f"{call_name}({param_name}={value!r}) but source "
                                f"default is {source_default!r} (doc value is a "
                                f"prefix/abbreviation)"
                            ),
                        })
                        break  # one finding per kwarg
    return findings


def build_global_caveat_methods(
    caveat_methods: Dict[str, List[str]],
) -> Dict[str, List[str]]:
    """Flatten per-class caveat methods into a global {method_name: [caveat_msgs]} map.

    This allows matching method calls in docs (which may be instance calls like
    `auditor.run(...)`) against caveats on any class's method with that name.
    """
    global_caveats: Dict[str, List[str]] = {}
    for method_key, caveat_msgs in caveat_methods.items():
        # method_key is "ClassName.method_name"
        parts = method_key.split(".", 1)
        if len(parts) != 2:
            continue
        method_name = parts[1]
        if method_name not in global_caveats:
            global_caveats[method_name] = []
        for msg in caveat_msgs:
            if msg not in global_caveats[method_name]:
                global_caveats[method_name].append(msg)
    return global_caveats


def check_missing_caveats(
    content: str,
    global_caveats: Dict[str, List[str]],
    page: str,
) -> List[dict]:
    """Check if documented method calls have their caveats mentioned.

    Uses a global method-name -> caveats map so that an instance call like
    `auditor.run(...)` is checked against caveats on any class's `.run` method.
    This is generic: it catches docs that call a method with a known runtime
    caveat without mentioning the caveat.
    """
    findings = []

    # Find all method references in the content (instance.method( or Class.method()
    method_pattern = re.compile(r"\.\s*(\w+)\s*\(")
    mentioned_method_names = set()
    for match in method_pattern.finditer(content):
        mentioned_method_names.add(match.group(1))

    for method_name, caveat_msgs in global_caveats.items():
        if method_name not in mentioned_method_names:
            continue

        # Check if any caveat key phrase appears in the content
        caveat_mentioned = False
        key_phrases = [
            "event loop",
            "RuntimeError",
            "active event",
            "thread",
            "asyncio",
        ]
        for phrase in key_phrases:
            if phrase.lower() in content.lower():
                caveat_mentioned = True
                break

        if not caveat_mentioned:
            findings.append({
                "type": "MISSING_CAVEAT",
                "page": page,
                "method": method_name,
                "caveat": caveat_msgs[0] if caveat_msgs else "Unknown",
                "detail": (
                    f".{method_name}() raises an exception under specific "
                    f"runtime conditions but the docs don't mention it"
                ),
            })
    return findings


def main():
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <pkg_path> <guides_dir> <output_json>")
        sys.exit(1)

    pkg_path = sys.argv[1]
    guides_dir = sys.argv[2]
    output_json = sys.argv[3]

    # Build indexes
    param_defaults = build_param_defaults(pkg_path)
    global_defaults = build_global_param_defaults(param_defaults)
    caveat_methods = build_caveat_methods(pkg_path)
    global_caveats = build_global_caveat_methods(caveat_methods)

    all_findings = []
    total_claims = 0

    for fname in sorted(os.listdir(guides_dir)):
        if not fname.endswith(".md"):
            continue
        page = fname[:-3]  # strip .md
        fpath = os.path.join(guides_dir, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()

        # String value check
        sv_findings = check_string_values(content, global_defaults, page)
        all_findings.extend(sv_findings)

        # Missing caveat check
        mc_findings = check_missing_caveats(content, global_caveats, page)
        all_findings.extend(mc_findings)

    # Build output
    findings_by_type = {}
    for f in all_findings:
        t = f["type"]
        findings_by_type[t] = findings_by_type.get(t, 0) + 1

    result = {
        "total_claims": total_claims,
        "total_findings": len(all_findings),
        "findings_by_type": findings_by_type,
        "findings": all_findings,
        "_summary": {
            "string_value_mismatches": findings_by_type.get("STRING_VALUE_MISMATCH", 0),
            "missing_caveats": findings_by_type.get("MISSING_CAVEAT", 0),
        },
    }

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"Semantic value check: {len(all_findings)} findings "
          f"({findings_by_type.get('STRING_VALUE_MISMATCH', 0)} string mismatches, "
          f"{findings_by_type.get('MISSING_CAVEAT', 0)} missing caveats)")


if __name__ == "__main__":
    main()
