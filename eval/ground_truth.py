"""Build a ground-truth symbol index from a Python package.

Extracts every public class, function, method, and module-level constant
name via AST (no imports, no execution). Used by the hallucination checker
to verify that doc pages only reference symbols that actually exist.
"""
from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass, field


@dataclass
class SymbolIndex:
    """Ground-truth symbol index for a package."""

    pkg_path: str
    # module (relative, dot-separated) -> set of top-level names
    module_symbols: dict = field(default_factory=dict)
    # class name -> set of method names (across all modules)
    class_methods: dict = field(default_factory=dict)
    # all top-level function names (any module)
    functions: set = field(default_factory=set)
    # all class names (any module)
    classes: set = field(default_factory=set)
    # all module-level constant names
    constants: set = field(default_factory=set)
    # module names (dot-separated, e.g. "simpleaudit.model_auditor")
    modules: set = field(default_factory=set)
    # raw source text of every file (for substring checks)
    sources: dict = field(default_factory=dict)
    # all string literals found in the package (env var names, dict keys, etc.)
    string_literals: set = field(default_factory=set)
    # all function/method parameter names (across the package)
    function_params: set = field(default_factory=set)

    def all_names(self) -> set:
        names = set()
        for syms in self.module_symbols.values():
            names |= syms
        names |= self.functions
        names |= self.classes
        names |= self.constants
        return names


def build_index(pkg_path: str) -> SymbolIndex:
    """Walk pkg_path and build the symbol index."""
    idx = SymbolIndex(pkg_path=pkg_path)
    pkg_name = os.path.basename(os.path.normpath(pkg_path))

    for dirpath, dirnames, filenames in os.walk(pkg_path):
        dirnames.sort()
        for f in sorted(filenames):
            if not f.endswith(".py"):
                continue
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, pkg_path)
            # module name: simpleaudit/model_auditor.py -> simpleaudit.model_auditor
            mod = rel[:-3].replace(os.sep, ".")
            if mod.endswith(".__init__"):
                mod = mod[: -len(".__init__")]
            idx.modules.add(mod)
            try:
                with open(full, encoding="utf-8", errors="replace") as fh:
                    src = fh.read()
            except OSError:
                continue
            idx.sources[mod] = src
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    v = node.value
                    if 3 <= len(v) <= 80 and re.fullmatch(r"[A-Za-z0-9_\-]+", v):
                        idx.string_literals.add(v)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    args = node.args
                    for a in list(args.args) + list(args.posonlyargs) + list(args.kwonlyargs):
                        if a.arg not in ("self", "cls"):
                            idx.function_params.add(a.arg)
                    if args.vararg:
                        idx.function_params.add(args.vararg.arg)
                    if args.kwarg:
                        idx.function_params.add(args.kwarg.arg)

            mod_syms = set()
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    idx.classes.add(node.name)
                    mod_syms.add(node.name)
                    methods = set()
                    for sub in node.body:
                        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            methods.add(sub.name)
                    idx.class_methods.setdefault(node.name, set()).update(methods)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    idx.functions.add(node.name)
                    mod_syms.add(node.name)
                elif isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            idx.constants.add(t.id)
                            mod_syms.add(t.id)
                elif isinstance(node, ast.AnnAssign):
                    if isinstance(node.target, ast.Name):
                        idx.constants.add(node.target.id)
                        mod_syms.add(node.target.id)
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    if isinstance(node, ast.Import):
                        for a in node.names:
                            mod_syms.add((a.asname or a.name).split(".")[0])
                    else:
                        for a in node.names:
                            mod_syms.add(a.asname or a.name)
            idx.module_symbols[mod] = mod_syms
    return idx


# ---------------------------------------------------------------------------
# Extraction of candidate references from markdown
# ---------------------------------------------------------------------------

# `Name` in backticks
_RE_BACKTICK = re.compile(r"`([^`\n]+)`")
# import statements
_RE_IMPORT_FROM = re.compile(r"^\s*from\s+([\w.]+)\s+import\s+(.+)$", re.M)
_RE_IMPORT_AS = re.compile(r"^\s*import\s+([\w.]+)(?:\s+as\s+(\w+))?$", re.M)
# python code blocks
_RE_PYBLOCK = re.compile(r"```python\n(.*?)```", re.S)


def extract_code_blocks(md: str) -> list[str]:
    return [m.group(1) for m in _RE_PYBLOCK.finditer(md)]


def extract_imports(md: str) -> list[tuple[str, str]]:
    """Return (module, name) pairs from import statements in code blocks."""
    pairs = []
    for block in extract_code_blocks(md):
        for m in _RE_IMPORT_FROM.finditer(block):
            mod = m.group(1)
            names = m.group(2).strip()
            for part in names.split(","):
                part = part.strip()
                if not part or part == "*":
                    continue
                name = part.split(" as ")[0].strip()
                pairs.append((mod, name))
        for m in _RE_IMPORT_AS.finditer(block):
            mod = m.group(1)
            name = mod.split(".")[-1]
            # Skip bare package imports (e.g. "import click" → name == mod).
            # These are valid package imports, not "from click import click".
            if name != mod:
                pairs.append((mod, name))
    return pairs


def extract_backtick_symbols(md: str) -> list[str]:
    """Backticked tokens that look like Python identifiers (not paths/flags)."""
    out = []
    for m in _RE_BACKTICK.finditer(md):
        tok = m.group(1).strip()
        if not tok or len(tok) > 60:
            continue
        # skip shell-ish, paths, URLs, options
        if any(c in tok for c in " /\\=:\"'`$(){}[]<>|;&*~#"):
            continue
        if tok.startswith("-"):
            continue
        if re.fullmatch(r"[\w.]+", tok):
            out.append(tok)
    return out


def extract_method_calls(md: str) -> list[tuple[str, str]]:
    """Find `obj.method(...)` patterns in code blocks -> (obj_type_guess, method).

    We can't do full type inference, so we collect (receiver_name, method)
    pairs; the checker matches method names against the union of all
    class methods (a method name that exists on ANY class is considered
    grounded; a method name that exists on NO class is a hallucination
    candidate).
    """
    out = []
    for block in extract_code_blocks(md):
        for m in re.finditer(r"(\w+)\.(\w+)\s*\(", block):
            recv, meth = m.group(1), m.group(2)
            if recv in ("self", "cls", "print", "len", "range", "str", "int",
                        "float", "list", "dict", "set", "tuple", "open",
                        "super", "type", "isinstance", "enumerate", "zip",
                        "map", "filter", "sorted", "reversed", "any", "all",
                        "min", "max", "sum", "abs", "round", "repr", "id",
                        "hash", "iter", "next", "vars", "dir", "getattr",
                        "setattr", "hasattr", "callable", "bool", "bytes",
                        "chr", "ord", "input", "exit", "quit", "help",
                        "memoryview", "property", "staticmethod", "classmethod",
                        "object", "Exception", "ValueError", "TypeError",
                        "KeyError", "IndexError", "RuntimeError", "OSError",
                        "ImportError", "AttributeError", "StopIteration",
                        "NotImplementedError", "AssertionError", "NameError",
                        "ZeroDivisionError", "FileNotFoundError",
                        "json", "os", "sys", "re", "time", "math", "random",
                        "argparse", "logging", "subprocess", "shutil",
                        "pathlib", "typing", "collections", "itertools",
                        "functools", "dataclasses", "abc", "enum", "uuid",
                        "datetime", "http", "urllib", "base64", "hashlib",
                        "pickle", "copy", "io", "textwrap", "string",
                        "unicodedata", "warnings", "traceback", "inspect",
                        "importlib", "contextlib", "concurrent", "threading",
                        "multiprocessing", "asyncio", "socket", "ssl",
                        "struct", "codecs", "locale", "gettext", "glob",
                        "fnmatch", "fileinput", "tempfile", "tarfile",
                        "zipfile", "gzip", "bz2", "lzma", "zlib",
                        "configparser", "csv", "code", "compileall",
                        "dis", "ast", "tokenize", "token", "keyword",
                        "symtable", "linecache", "pydoc", "platform",
                        "errno", "ctypes", "marshal", "posixpath",
                        "ntpath", "genericpath", "operator", "reprlib",
                        "pprint", "numbers", "cmath", "decimal", "fractions",
                        "random", "statistics", "secrets", "array",
                        "heapq", "bisect", "queue", "heapq",
                        ):
                continue
            out.append((recv, meth))
    return out
