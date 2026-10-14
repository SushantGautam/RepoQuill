"""Conservative AST-based change intelligence for documentation impact.

The file-hash plan cache in ``repoquill.plan`` misses cross-file behavioral
dependencies: a guide page documents class ``Foo``, ``foo.py`` is unchanged,
but ``__init__.py`` re-exported a different ``Foo``. This module extracts a
deterministic, pure-stdlib (``ast``) API surface from a package source tree
and diffs two surfaces to produce the set of qualified symbols that changed.

Downstream (``repoquill.core.dependencies``) maps guide pages to the symbols
they reference and derives the conservative affected-page set. Unknown
(never parseable) files are surfaced in :pyattr:`ApiSurface.errors` so that
callers can fail toward "affected" rather than silently toward "safe".

No LLM, no third-party dependencies. Output is fully deterministic for a
given input (iterations over sorted key sets).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

__all__ = [
    "ApiSurface",
    "ApiDiff",
    "extract_api_surface",
    "diff_surfaces",
    "module_name_for_path",
]


# ---------------------------------------------------------------------------
# Path -> module name
# ---------------------------------------------------------------------------

def module_name_for_path(relpath: str) -> str:
    """Derive the dotted module name from a package-relative file path.

    ``pkg/foo.py`` -> ``pkg.foo``; ``pkg/__init__.py`` -> ``pkg``;
    ``foo.py`` -> ``foo``.

    Args:
        relpath: Package-relative file path (``/`` or OS separator).

    Returns:
        Dotted module name.
    """
    p = relpath.replace("\\", "/").strip("/")
    if p.endswith(".py"):
        p = p[:-3]
    parts = [x for x in p.split("/") if x]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _src(node: ast.AST, source: str) -> str:
    """Source text of a node, falling back to ``ast.unparse``."""
    try:
        seg = ast.get_source_segment(source, node)
        if seg is not None:
            return seg.strip()
    except Exception:
        pass
    return ast.unparse(node)


def _arg_name(arg: ast.arg, source: str) -> str:
    name = arg.arg
    if arg.annotation is not None:
        name += ": " + _src(arg.annotation, source)
    return name


def _signature(node, source: str) -> str:
    """Deterministic canonical signature string for a function node.

    Captures positional/kw-only argument names, ``*args``/``**kwargs``,
    annotations and defaults (defaults via their source text, so both
    literals and expressions compare stably).
    """
    a = node.args
    parts: List[str] = []
    pos = list(a.posonlyargs) + list(a.args)
    n_defaulted = len(a.defaults)
    defaults: List[Optional[ast.expr]] = [None] * (len(pos) - n_defaulted) + list(a.defaults)
    for arg, dflt in zip(pos, defaults):
        p = _arg_name(arg, source)
        if dflt is not None:
            p += "=" + _src(dflt, source)
        parts.append(p)
    if a.vararg is not None:
        parts.append("*" + _arg_name(a.vararg, source))
    for arg, dflt in zip(a.kwonlyargs, a.kw_defaults):
        p = _arg_name(arg, source)
        if dflt is not None:
            p += "=" + _src(dflt, source)
        parts.append(p)
    if a.kwarg is not None:
        parts.append("**" + _arg_name(a.kwarg, source))
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    return prefix + "(" + ", ".join(parts) + ")"


def _resolve_from(module_name: str, node: ast.ImportFrom, is_package: bool) -> Optional[str]:
    """Resolve an ``import from`` target to an absolute module name.

    Returns None when the module target is unknown (e.g. a top-level file
    with a relative import that cannot be anchored).
    """
    if node.level == 0:
        return node.module
    parts = module_name.split(".") if module_name else []
    if is_package:
        # ``pkg/__init__.py`` IS the package ``pkg``; level 1 stays here.
        anchor = list(parts)
    else:
        # Plain module ``a.b``: the package is its parent ``a``.
        anchor = parts[:-1]
    up = max(0, node.level - 1)
    if up > len(anchor):
        return None
    base = ".".join(anchor[: len(anchor) - up]) if up else ".".join(anchor)
    if node.module:
        base = base + "." + node.module if base else node.module
    return base or None


# ---------------------------------------------------------------------------
# Surface extraction
# ---------------------------------------------------------------------------

def _empty_module() -> dict:
    return {
        "functions": {},
        "classes": {},
        "reexports": set(),
        "imports": set(),
    }


@dataclass
class ApiSurface:
    """Per-module API surface of a package source tree.

    Attributes:
        modules: Mapping ``{module_name: {"functions": {name: sig},
            "classes": {name: {"methods": {name: sig}}},
            "reexports": set[str], "imports": set[str]}}``.
        errors: Module names whose source could not be parsed. Callers
            must treat these as "unknown", never as "safe".
    """

    modules: Dict[str, dict] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def module(self, name: str) -> Optional[dict]:
        return self.modules.get(name)


def _extract_module(relpath: str, content: str) -> dict:
    """Extract one module's surface entry. Raises on syntax error."""
    module_name = module_name_for_path(relpath)
    is_package = relpath.replace("\\", "/").endswith("__init__.py")
    tree = ast.parse(content)
    entry = _empty_module()

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            entry["functions"][node.name] = _signature(node, content)
        elif isinstance(node, ast.ClassDef):
            methods: Dict[str, str] = {}
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods[sub.name] = _signature(sub, content)
            entry["classes"][node.name] = {"methods": methods}
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                entry["reexports"].add(bound)
                entry["imports"].add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from(module_name, node, is_package)
            for alias in node.names:
                if alias.name == "*":
                    if base:
                        entry["imports"].add(base + ".*")
                    continue
                bound = alias.asname or alias.name
                entry["reexports"].add(bound)
                if base:
                    entry["imports"].add(base + "." + alias.name)

    return entry


def extract_api_surface(source_files: Dict[str, str]) -> ApiSurface:
    """Extract the API surface from ``{relative_path: content}``.

    Unparseable files are recorded in :pyattr:`ApiSurface.errors` (by module
    name) and processing continues for the remaining files.

    Args:
        source_files: Mapping of package-relative path (``pkg/foo.py``) to
            file content.

    Returns:
        The :class:`ApiSurface`.
    """
    surface = ApiSurface()
    for relpath in sorted(source_files):
        module_name = module_name_for_path(relpath)
        try:
            surface.modules[module_name] = _extract_module(relpath, source_files[relpath])
        except (SyntaxError, ValueError) as exc:
            surface.modules.setdefault(module_name, _empty_module())
            surface.errors.append(module_name)
    surface.errors.sort()
    return surface


# ---------------------------------------------------------------------------
# Diffing
# ---------------------------------------------------------------------------

@dataclass
class ApiDiff:
    """Structural diff between two API surfaces.

    Attributes:
        added: Qualified names new in ``new`` (``mod.Name``,
            ``mod.Name.method``).
        removed: Qualified names present in ``old`` but gone in ``new``.
            Renamed pairs are excluded here (see :pyattr:`renamed`).
        renamed: ``[{"module", "from", "to"}]`` — heuristic pairing of a
            removed and an added top-level symbol in the same module with
            an identical signature (see limitations).
        signature_changes: ``[{"module", "name", "field", "before",
            "after"}]`` where ``name`` may be ``Class.method`` and
            ``field`` is ``"signature"``.
        reexport_changes: ``{module: {"added": [...], "removed": [...]}}``
            for modules whose set of import-bound names changed.
        removed_modules: Modules with at least one removed symbol.
        errors: Module names that failed to parse in either surface; the
            diff for these modules is unknown and callers must treat
            dependents as affected.
    """

    added: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    renamed: List[dict] = field(default_factory=list)
    signature_changes: List[dict] = field(default_factory=list)
    reexport_changes: Dict[str, dict] = field(default_factory=dict)
    removed_modules: Set[str] = field(default_factory=set)
    errors: List[str] = field(default_factory=list)
    _changed_cache: Optional[Set[str]] = field(default=None, repr=False, compare=False)

    def changed_symbols(self) -> Set[str]:
        """Qualified names any page might reference that changed."""
        if self._changed_cache is None:
            s: Set[str] = set(self.added) | set(self.removed)
            for c in self.signature_changes:
                s.add(f"{c['module']}.{c['name']}")
            for r in self.renamed:
                s.add(f"{r['module']}.{r['from']}")
                s.add(f"{r['module']}.{r['to']}")
            self._changed_cache = s
        return self._changed_cache

    def is_empty(self) -> bool:
        """True when nothing structural changed and nothing is unknown.

        Parse errors make the diff non-empty: an unknown difference must
        never be reported as "no change".
        """
        return not (
            self.added or self.removed or self.renamed
            or self.signature_changes or self.reexport_changes
            or self.errors
        )


def _pair_renames(module: str, o: dict, n: dict) -> List[dict]:
    """Heuristic: pair removed/added top-level symbols with identical signatures."""
    renamed: List[dict] = []
    added_funcs = {
        name: n["functions"][name]
        for name in n["functions"] if name not in o["functions"]
    }
    added_classes = {
        name: tuple(sorted(n["classes"][name]["methods"].items()))
        for name in n["classes"] if name not in o["classes"]
    }
    for name in sorted(o["functions"]):
        if name in n["functions"]:
            continue
        sig = o["functions"][name]
        for new_name in sorted(added_funcs):
            if added_funcs[new_name] == sig:
                renamed.append({"module": module, "from": name, "to": new_name})
                del added_funcs[new_name]
                break
    for name in sorted(o["classes"]):
        if name in n["classes"]:
            continue
        old_methods = tuple(sorted(o["classes"][name]["methods"].items()))
        for new_name in sorted(added_classes):
            if added_classes[new_name] == old_methods:
                renamed.append({"module": module, "from": name, "to": new_name})
                del added_classes[new_name]
                break
    return renamed


def diff_surfaces(old: ApiSurface, new: ApiSurface) -> ApiDiff:
    """Diff two surfaces into an :class:`ApiDiff` (deterministic order)."""
    diff = ApiDiff()
    all_modules = sorted(set(old.modules) | set(new.modules))
    for mod in all_modules:
        o = old.modules.get(mod, _empty_module())
        n = new.modules.get(mod, _empty_module())
        removed_here: List[str] = []

        # --- top-level functions ---
        added_funcs_here: List[str] = []
        for name in sorted(set(o["functions"]) | set(n["functions"])):
            in_o, in_n = name in o["functions"], name in n["functions"]
            if in_o and not in_n:
                removed_here.append(f"{mod}.{name}")
            elif in_n and not in_o:
                added_funcs_here.append(f"{mod}.{name}")
            elif o["functions"][name] != n["functions"][name]:
                diff.signature_changes.append({
                    "module": mod, "name": name, "field": "signature",
                    "before": o["functions"][name],
                    "after": n["functions"][name],
                })
        # --- top-level classes ---
        added_classes_here: List[str] = []
        for name in sorted(set(o["classes"]) | set(n["classes"])):
            in_o, in_n = name in o["classes"], name in n["classes"]
            if in_o and not in_n:
                removed_here.append(f"{mod}.{name}")
            elif in_n and not in_o:
                added_classes_here.append(f"{mod}.{name}")
            else:
                om = o["classes"][name]["methods"]
                nm = n["classes"][name]["methods"]
                for mname in sorted(set(om) | set(nm)):
                    qual = f"{mod}.{name}.{mname}"
                    if mname in om and mname not in nm:
                        removed_here.append(qual)
                    elif mname in nm and mname not in om:
                        diff.added.append(qual)
                    elif om[mname] != nm[mname]:
                        diff.signature_changes.append({
                            "module": mod, "name": f"{name}.{mname}",
                            "field": "signature",
                            "before": om[mname], "after": nm[mname],
                        })

        # --- rename heuristic (top-level only) ---
        renamed_here = _pair_renames(mod, o, n)
        for r in renamed_here:
            diff.renamed.append(r)
            old_q = f"{mod}.{r['from']}"
            new_q = f"{mod}.{r['to']}"
            if old_q in removed_here:
                removed_here.remove(old_q)
            if new_q in added_funcs_here:
                added_funcs_here.remove(new_q)
            if new_q in added_classes_here:
                added_classes_here.remove(new_q)

        diff.added.extend(added_funcs_here)
        diff.added.extend(added_classes_here)
        diff.removed.extend(removed_here)
        if removed_here:
            diff.removed_modules.add(mod)

        # --- reexports ---
        ra = n["reexports"] - o["reexports"]
        rr = o["reexports"] - n["reexports"]
        if ra or rr:
            diff.reexport_changes[mod] = {"added": sorted(ra), "removed": sorted(rr)}

    diff.errors = sorted(set(old.errors) | set(new.errors))
    return diff
