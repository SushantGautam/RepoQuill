"""E12 — Deterministic example-validity + cross-page consistency checker.

AST-parses every fenced ```python block in the generated guide docs and checks:
  1. Constructor kwargs: every kwarg passed to a known class's constructor
     must be a real parameter of that class's __init__.
  2. Required args: every required (no-default) parameter of __init__ must
     be provided in the constructor call (unless it's a common alias).
  3. Imports: `from simpleaudit import X` must resolve to a name in
     __all__ or a submodule.
  4. Properties-as-methods: calling a @property as a method is flagged.
  5. Cross-page conflicts: the same class constructed with different
     param sets across pages.

Output: example_check.json with broken_examples count and per-finding detail.

Usage: example_check.py <pkg_path> <guides_dir> <output_json>
"""
from __future__ import annotations
import ast, json, os, re, sys
from collections import defaultdict
from pathlib import Path


def extract_python_blocks(md_text: str) -> list[str]:
    """Extract all fenced python code blocks from markdown.

    E28: Strip leading indentation from each block before returning. The LLM
    sometimes indents the entire code block (including the fence), which causes
    a spurious "unexpected indent" syntax error at line 1. The code itself is
    correct — the formatting is wrong. This is a de-Goodhart fix: the metric
    should measure code correctness, not markdown formatting.
    """
    import textwrap
    blocks = []
    for m in re.finditer(r'```python\n(.*?)```', md_text, re.DOTALL):
        blocks.append(textwrap.dedent(m.group(1)))
    return blocks


def _is_signature_block(block: str) -> bool:
    """Detect API signature snippets that are documentation, not executable code.

    Signature blocks are patterns like:
      - ModelAuditor(model: str, provider: str, ...)
      - run(scenarios: Union[str, List[Dict[str, Any]]], max_turns: Optional[int] = None)
      - get_scenarios(pack_name: str) -> List[Dict[str, Any]]
      - ModelAuditor(
          model: str,
          provider: str,
          ...
        )

    These are NOT valid Python (annotations in call args, bare signatures without def),
    but they're a legitimate documentation pattern for showing API signatures.

    Detection strategy:
    1. Must fail to parse as valid Python
    2. Must start with Name( (a call expression)
    3. Must contain type annotations (: type)
    4. Must NOT be a def statement
    5. Must NOT contain assignment statements (name = value outside of defaults)
    """
    stripped = block.strip()

    # Quick reject: empty or too short
    if not stripped or len(stripped) < 10:
        return False

    # Quick reject: real function definitions
    if stripped.startswith('def ') or stripped.startswith('async def '):
        return False

    # Must start with Name( or Name.Name( pattern (call expression)
    if not re.match(r'^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*\s*\(', stripped):
        return False

    # Must fail to parse as valid Python
    try:
        ast.parse(stripped)
        return False  # Valid Python, not a signature
    except SyntaxError:
        pass

    # Must contain type annotations
    if not re.search(r'\w+\s*:\s*[A-Za-z_\[\'\"]', stripped):
        return False

    # Must NOT contain assignment statements
    # Check each line: if a line starts with name = (not name: type = default), it's an assignment
    for line in stripped.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        # Skip lines that are just closing parens or return types
        if line in (')', '->') or line.startswith('->'):
            continue
        # Check for assignment: name = value (not annotation: name: type = default)
        # An assignment line starts with identifier followed by =
        # An annotation line starts with identifier followed by :
        if re.match(r'^[A-Za-z_]\w*\s*=', line):
            return False  # Assignment, not a signature

    return True


def build_class_index(pkg_path: str) -> dict:
    """Build a class -> {init_params, required_params, properties, methods} index.

    Scans all .py files in the package for class definitions.
    """
    classes = {}
    for py in Path(pkg_path).rglob("*.py"):
        try:
            tree = ast.parse(py.read_text())
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            cls = node.name
            info = {
                "file": str(py),
                "init_params": {},   # param_name -> has_default (bool)
                "properties": set(),
                "methods": set(),
                "classmethods": set(),
            }
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    fname = item.name
                    if fname == "__init__":
                        # Extract params (skip self/cls)
                        for arg in item.args.args:
                            if arg.arg in ("self", "cls"):
                                continue
                            # Check if it has a default
                            has_default = False
                            n_defaults = len(item.args.defaults)
                            n_args = len(item.args.args)
                            # defaults are right-aligned
                            arg_idx = n_args - n_defaults
                            if n_defaults > 0 and item.args.args.index(arg) >= arg_idx:
                                has_default = True
                            # Also check vararg/keyword
                            if item.args.vararg or item.args.kwarg:
                                # **kwargs means any kwarg is accepted
                                info["init_params"]["**kwargs"] = True
                            info["init_params"][arg.arg] = has_default
                    else:
                        # Check for @property
                        is_prop = any(
                            (isinstance(d, ast.Name) and d.id == "property") or
                            (isinstance(d, ast.Attribute) and d.attr == "property")
                            for d in item.decorator_list
                        )
                        is_cmethod = any(
                            (isinstance(d, ast.Name) and d.id == "classmethod") or
                            (isinstance(d, ast.Attribute) and d.attr == "classmethod")
                            for d in item.decorator_list
                        )
                        if is_prop:
                            info["properties"].add(fname)
                        if is_cmethod:
                            info["classmethods"].add(fname)
                        else:
                            info["methods"].add(fname)
            classes[cls] = info
    return classes


def extract_all_names(pkg_path: str) -> set:
    """Extract all names in __all__ + all module names + all class/func names."""
    names = set()
    init = Path(pkg_path) / "__init__.py"
    if init.exists():
        try:
            tree = ast.parse(init.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name) and t.id == "__all__":
                            if isinstance(node.value, (ast.List, ast.Tuple)):
                                for elt in node.value.elts:
                                    if isinstance(elt, ast.Constant):
                                        names.add(elt.value)
        except Exception:
            pass
    # All class and function names in the package
    for py in Path(pkg_path).rglob("*.py"):
        try:
            tree = ast.parse(py.read_text())
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                names.add(node.name)
    # Module names (submodules)
    for py in Path(pkg_path).rglob("*.py"):
        names.add(py.stem)
    return names


# Sentinel values that indicate a non-runnable placeholder.
_PLACEHOLDER_PATTERNS = (
    "<REQUIRED>", "<REQUIRED", "TODO", "FIXME", "PLACEHOLDER",
    "...", "<value>", "<arg>", "<name>",
)


def _is_placeholder(value_node: ast.AST) -> bool:
    """Return True if the AST node is a placeholder sentinel value."""
    if isinstance(value_node, ast.Constant):
        if isinstance(value_node.value, str):
            v = value_node.value.upper()
            for pat in _PLACEHOLDER_PATTERNS:
                if pat in v:
                    return True
        return False
    # Ellipsis (...)
    if isinstance(value_node, ast.Ellipsis):
        return True
    return False


def check_constructor_call(call_node: ast.Call, classes: dict) -> list[dict]:
    """Check a constructor call against the class index. Returns findings."""
    findings = []
    # Get the class name
    if isinstance(call_node.func, ast.Name):
        cls_name = call_node.func.id
    elif isinstance(call_node.func, ast.Attribute):
        cls_name = call_node.func.attr
    else:
        return findings

    if cls_name not in classes:
        return findings

    cls_info = classes[cls_name]
    init_params = cls_info["init_params"]
    if not init_params:
        return findings

    has_kwargs = "**kwargs" in init_params

    # Check kwargs
    for kw in call_node.keywords:
        if kw.arg is None:  # **kwargs expansion
            continue
        # Check for placeholder values
        if _is_placeholder(kw.value):
            findings.append({
                "type": "placeholder_value",
                "class": cls_name,
                "kwarg": kw.arg,
                "detail": f"{cls_name}() kwarg '{kw.arg}' has a placeholder "
                          f"value — the example is not runnable as written",
            })
        if not has_kwargs and kw.arg not in init_params:
            findings.append({
                "type": "invalid_kwarg",
                "class": cls_name,
                "kwarg": kw.arg,
                "detail": f"{cls_name}() called with '{kw.arg}' which is not a "
                          f"parameter of {cls_name}.__init__",
            })

    # Check required args (no default) are provided
    if not has_kwargs:
        provided = {kw.arg for kw in call_node.keywords if kw.arg}
        # Also count positional args
        n_pos = len(call_node.args)
        required = [p for p, has_def in init_params.items() if not has_def]
        # First n_pos required params are satisfied by positional args
        for i, req in enumerate(required):
            if i < n_pos:
                continue  # satisfied by positional
            if req not in provided:
                findings.append({
                    "type": "missing_required",
                    "class": cls_name,
                    "param": req,
                    "detail": f"{cls_name}() missing required parameter '{req}'",
                })
    return findings


def check_imports(tree: ast.Module, all_names: set, pkg_name: str) -> list[dict]:
    """Check `from <pkg> import X` statements resolve."""
    findings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            # Only check imports from the package itself
            if node.module == pkg_name or node.module.startswith(pkg_name + "."):
                for alias in node.names:
                    name = alias.name
                    if name == "*":
                        continue
                    if name not in all_names:
                        findings.append({
                            "type": "unresolved_import",
                            "name": name,
                            "module": node.module,
                            "detail": f"from {node.module} import {name} — "
                                      f"'{name}' not found in package",
                        })
    return findings


def check_property_calls(tree: ast.Module, classes: dict) -> list[dict]:
    """Check for @property being called as a method (e.g. results.passed())."""
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        method_name = node.func.attr
        # Get the object type (heuristic: look at the variable name)
        # We can't fully type-infer, so check if method_name is a property
        # on any known class
        for cls_name, cls_info in classes.items():
            if method_name in cls_info["properties"]:
                # Flag it — but only if it's being called (has parens)
                findings.append({
                    "type": "property_called_as_method",
                    "class": cls_name,
                    "property": method_name,
                    "detail": f"'{method_name}' is a @property on {cls_name}, "
                              f"but is called as a method: obj.{method_name}()",
                })
    return findings


def check_cross_page(page_findings: dict[str, dict]) -> list[dict]:
    """Detect cross-page constructor conflicts for the same class."""
    conflicts = []
    # Collect per-class kwarg sets across pages
    class_kwargs = defaultdict(lambda: defaultdict(set))  # cls -> kwarg -> pages
    for page, findings in page_findings.items():
        for f in findings:
            if f["type"] == "invalid_kwarg":
                class_kwargs[f["class"]][f["kwarg"]].add(page)
            if f["type"] == "missing_required":
                class_kwargs[f["class"]]["__missing:" + f["param"]].add(page)

    for cls, kwargs in class_kwargs.items():
        if len(kwargs) > 3:
            conflicts.append({
                "type": "cross_page_conflict",
                "class": cls,
                "detail": f"{cls} constructed with {len(kwargs)} different "
                          f"param sets across pages: {dict(kwargs)}",
            })
    return conflicts


def main():
    if len(sys.argv) < 3:
        print("Usage: example_check.py <pkg_path> <guides_dir> [output_json]")
        sys.exit(1)

    pkg_path = sys.argv[1]
    guides_dir = sys.argv[2]
    out_path = sys.argv[3] if len(sys.argv) > 3 else None
    pkg_name = os.path.basename(pkg_path)

    classes = build_class_index(pkg_path)
    all_names = extract_all_names(pkg_path)

    all_findings = []
    page_findings = {}
    total_blocks = 0
    broken_blocks = 0

    for md_file in sorted(Path(guides_dir).glob("*.md")):
        text = md_file.read_text()
        blocks = extract_python_blocks(text)
        total_blocks += len(blocks)
        page_findings[md_file.name] = []

        for block in blocks:
            # Skip API signature snippets — they're documentation, not executable code
            if _is_signature_block(block):
                continue

            try:
                tree = ast.parse(block)
            except SyntaxError:
                # Block has placeholders or incomplete code — flag it
                all_findings.append({
                    "page": md_file.name,
                    "type": "syntax_error",
                    "detail": f"Python block has syntax error (likely placeholder)",
                })
                page_findings[md_file.name].append({"type": "syntax_error"})
                broken_blocks += 1
                continue

            block_findings = []
            # Constructor calls
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    block_findings.extend(
                        check_constructor_call(node, classes))
            # Imports
            block_findings.extend(
                check_imports(tree, all_names, pkg_name))
            # Property-as-method
            block_findings.extend(
                check_property_calls(tree, classes))

            if block_findings:
                broken_blocks += 1
            for f in block_findings:
                f["page"] = md_file.name
                all_findings.append(f)
                page_findings[md_file.name].append(f)

    # Cross-page conflicts
    conflicts = check_cross_page(page_findings)
    for c in conflicts:
        c["page"] = "cross-page"
        all_findings.append(c)

    # Summary
    by_type = defaultdict(int)
    for f in all_findings:
        by_type[f["type"]] += 1

    summary = {
        "total_python_blocks": total_blocks,
        "broken_blocks": broken_blocks,
        "broken_pct": round(100 * broken_blocks / max(total_blocks, 1), 1),
        "total_findings": len(all_findings),
        "by_type": dict(by_type),
    }

    result = {
        "_summary": summary,
        "findings": all_findings,
        "cross_page_conflicts": conflicts,
    }

    print(json.dumps(summary, indent=2))
    if out_path:
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2)
        print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
