"""Static import verification for generated doc pages.

For every Python code block in a page, extract ``import X`` /
``from X import name`` statements and verify each against the
ground-truth :class:`repoquill.verify.SymbolIndex`:

* project imports (top level matches a module in the index): the module
  path must exist, every imported name must exist, and a name that only
  exists privately is flagged as not exported;
* third-party imports: only the top-level module is checked with
  ``importlib.util.find_spec`` (no import is executed); lookups that
  error are treated as unverifiable and skipped.

Deterministic, no LLM, no imports of the target package.
"""

from __future__ import annotations

import importlib.util
import os
import re
from typing import List, Optional, Tuple

from repoquill.validation.blocks import python_blocks

_FROM_RE = re.compile(r"^from\s+([\w.]+)\s+import\s+(.+)$")
_IMPORT_RE = re.compile(r"^import\s+([\w.,\s\(\)]+)$")
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _top_levels(idx) -> set:
    """Top-level module names present in the symbol index."""
    return {m.split(".")[0] for m in idx.modules}


def _parse_imports(md: str) -> List[Tuple[str, int, str, List[str]]]:
    """Yield ``(kind, file_line, module, names)`` per import statement.

    ``kind`` is ``"import"`` (names are dotted module paths) or
    ``"from"`` (names are the imported symbols, "*" included verbatim).
    Handles parenthesized multi-line import lists.
    """
    out: List[Tuple[str, int, str, List[str]]] = []
    for start, code in python_blocks(md):
        lines = code.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            m_from = _FROM_RE.match(line)
            m_import = _IMPORT_RE.match(line)
            if not (m_from or m_import):
                i += 1
                continue
            if m_from:
                module = m_from.group(1)
                names_raw = m_from.group(2)
            else:
                module = ""
                names_raw = m_import.group(1)
            stmt_idx = i  # line where the statement starts
            # Fold parenthesized continuation lines into the statement.
            while "(" in names_raw and ")" not in names_raw and i + 1 < len(lines):
                i += 1
                names_raw += " " + lines[i]
            names = []
            body = names_raw.strip().strip("()")
            for part in body.split(","):
                part = part.strip()
                if not part or part.startswith("#"):
                    continue
                part = part.split("#")[0].strip()
                if not part:
                    continue
                part = part.split(" as ")[0].strip()
                if part and part != "*":
                    names.append(part)
                elif part == "*":
                    names.append("*")
            out.append(("from" if m_from else "import",
                        start + stmt_idx, module, names))
            i += 1
    return out


def _missing_module(module: str, idx, pkg_top: str) -> str:
    """Detail for the first nonexistent prefix of *module*, or ""."""
    # SymbolIndex stores package-relative module names ("parser",
    # "sub.mod"); qualify them with the import's top-level package.
    qualified = {pkg_top} | {f"{pkg_top}.{m}" for m in idx.modules}
    parts = module.split(".")
    for n in range(1, len(parts) + 1):
        prefix = ".".join(parts[:n])
        if prefix not in qualified:
            return f"module '{prefix}' does not exist in the package"
    return ""


def _check_project(module: str, names: List[str], idx,
                   kind: str = "from") -> List[str]:
    """Findings (detail strings) for one project import statement."""
    findings = []
    if kind == "import":
        # ``import a.b.c`` — every name is a dotted module path.
        for name in names:
            detail = _missing_module(name, idx, name.split(".")[0])
            if detail:
                findings.append(detail)
        return findings
    detail = _missing_module(module, idx, module.split(".")[0])
    if detail:
        findings.append(detail)
        return findings
    for name in names:
        if name == "*":
            continue
        if name in idx.modules or f"{module}.{name}" in idx.modules:
            continue  # submodule
        if name in idx.module_symbols:
            if name.startswith("_"):
                findings.append(
                    f"'{name}' exists in '{module}' but is private "
                    f"(not exported)")
            continue
        findings.append(f"'{name}' not found in '{module}'")
    return findings


def _check_third_party(module: str) -> Optional[str]:
    """Finding detail if the top-level module cannot be located, else None."""
    top = module.split(".")[0]
    try:
        spec = importlib.util.find_spec(top)
    except Exception:  # noqa: BLE001 - lookup errors are unverifiable
        return None
    if spec is None:
        return (f"module '{top}' not found (third-party import "
                f"'{module}' is not installed or does not exist)")
    return None


def check_page_imports(page_path: str, idx, local_tops=None) -> List[dict]:
    """Check all import statements in a page against the symbol index.

    Args:
        page_path: Path to the guide page.
        idx: The :class:`repoquill.verify.SymbolIndex` for the documented
            package.
        local_tops: Optional set of top-level package names that live in the
            source repository but are NOT the documented package (e.g. the
            repo's own ``tests`` package). These are in-scope but not in the
            index, so they are treated as out-of-scope (skipped) rather than
            flagged as missing third-party libraries.

    Returns a list of findings shaped
    ``{"page": slug, "check": "import", "line": n, "detail": str}``.
    """
    slug = os.path.basename(page_path)
    if slug.endswith(".md"):
        slug = slug[:-3]
    with open(page_path, "r", encoding="utf-8") as fh:
        md = fh.read()

    project_tops = _top_levels(idx)
    local_tops = set(local_tops or ()) - project_tops
    findings = []
    for kind, line, module, names in _parse_imports(md):
        # ``import a.b.c`` is parsed with an empty module and dotted
        # module paths as names; normalize to (module, names) pairs so
        # every dotted path is routed like a from-import module.
        if kind == "import":
            pairs = [(name, []) for name in names]
        else:
            pairs = [(module, names)]
        for mod, nms in pairs:
            top = mod.split(".")[0]
            if kind == "import" and top in project_tops:
                detail = _missing_module(mod, idx, top)
                details = [detail] if detail else []
            elif top in project_tops:
                details = _check_project(mod, nms, idx, kind=kind)
            elif top in local_tops:
                # A top-level package of the source repo (e.g. its ``tests``
                # package): part of the repository, so not a third-party lib,
                # but not part of the documented index either — out of scope.
                details = []
            else:
                detail = _check_third_party(mod)
                details = [detail] if detail else []
            for detail in details:
                findings.append({"page": slug, "check": "import",
                                 "line": line,
                                 "detail": f"{kind} statement: {detail}"})
    return findings
