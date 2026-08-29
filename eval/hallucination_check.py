"""Hallucination checker: verify doc pages only reference real symbols.

Checks performed per page:
  1. import checks: `from X import Y` — X must be a real module (or stdlib),
     Y must exist in that module's symbol set.
  2. backtick identifier checks: `Name` tokens that look like project
     symbols (CamelCase classes, snake_case functions/constants) must exist
     in the ground-truth index.
  3. method-call checks: `recv.method(` in code blocks — method must exist
     on at least one known class (heuristic; receiver type unknown).

Outputs a JSON report: per-page hallucinated symbols with evidence.
"""
from __future__ import annotations

import json
import os
import re
import sys

from ground_truth import (
    SymbolIndex,
    build_index,
    extract_backtick_symbols,
    extract_code_blocks,
    extract_imports,
    extract_method_calls,
)

# Modules that are stdlib or common third-party (not project modules).
_KNOWN_NON_PROJECT = {
    "os", "sys", "re", "json", "time", "math", "random", "argparse",
    "logging", "subprocess", "shutil", "pathlib", "typing", "collections",
    "itertools", "functools", "dataclasses", "abc", "enum", "uuid",
    "datetime", "http", "urllib", "base64", "hashlib", "pickle", "copy",
    "io", "textwrap", "string", "warnings", "traceback", "inspect",
    "importlib", "contextlib", "concurrent", "threading", "multiprocessing",
    "asyncio", "socket", "ssl", "struct", "codecs", "locale", "glob",
    "fnmatch", "tempfile", "tarfile", "zipfile", "gzip", "bz2", "lzma",
    "zlib", "configparser", "csv", "dis", "ast", "tokenize", "token",
    "keyword", "linecache", "pydoc", "platform", "errno", "ctypes",
    "marshal", "operator", "reprlib", "pprint", "numbers", "cmath",
    "decimal", "fractions", "statistics", "secrets", "array", "heapq",
    "bisect", "queue", "unittest", "test", "doctest", "pdb", "profile",
    "cProfile", "timeit", "benchmarks", "gc", "weakref", "types",
    "sre_compile", "sre_parse", "sre_constants", "_thread", "_weakref",
    "openai", "anthropic", "requests", "httpx", "aiohttp", "litellm",
    "tiktoken", "pydantic", "yaml", "numpy", "pandas", "matplotlib",
    "seaborn", "plotly", "bokeh", "altair", "streamlit", "gradio",
    "fastapi", "flask", "django", "uvicorn", "gunicorn", "click",
    "typer", "rich", "tqdm", "colorama", "termcolor", "tabulate",
    "pandas", "scipy", "sklearn", "torch", "tensorflow", "transformers",
    "datasets", "sentence_transformers", "griffe", "mkdocs", "mkdocstrings",
    "pytest", "mock", "freezegun", "responses", "vcr", "faker",
    "dotenv", "toml", "tomli", "packaging", "setuptools", "pip",
    "wheel", "virtualenv", "conda", "uv", "pipenv", "poetry",
    "webbrowser", "getpass", "getopt", "shlex", "stat", "filecmp",
    "fileinput", "formatter", "difflib", "difflib", "difflib",
    "pprint", "difflib", "difflib",
    "builtins", "__future__", "collections.abc", "typing.io",
    "typing.re", "concurrent.futures", "collections.abc",
    "urllib.request", "urllib.parse", "urllib.error",
    "pathlib", "dataclasses", "enum", "abc",
    "json", "os.path", "sys", "re",
    "matplotlib.pyplot", "numpy", "pandas",
    "simpleaudit",  # handled specially: project root
}


def _is_project_module(mod: str, idx: SymbolIndex) -> bool:
    """True if mod (or a prefix of it) is a project module."""
    if mod in idx.modules:
        return True
    # check prefix: simpleaudit.scenarios.health
    parts = mod.split(".")
    for i in range(len(parts), 0, -1):
        if ".".join(parts[:i]) in idx.modules:
            return True
    return False


def check_page(page_md: str, idx: SymbolIndex, pkg_name: str) -> dict:
    """Check one markdown page. Returns report dict."""
    hallucinations = []
    grounded = []

    # --- 1. import checks ---
    for mod, name in extract_imports(page_md):
        # skip stdlib / third-party
        top = mod.split(".")[0]
        if top in _KNOWN_NON_PROJECT and not _is_project_module(mod, idx):
            continue
        if not _is_project_module(mod, idx):
            # unknown module — could be hallucinated project module
            if top == pkg_name or mod.startswith(pkg_name):
                hallucinations.append({
                    "type": "import_module",
                    "symbol": mod,
                    "evidence": f"from {mod} import {name}",
                    "severity": "high",
                })
            continue
        # module exists — check the name
        # resolve to the deepest known module
        parts = mod.split(".")
        target_mod = None
        for i in range(len(parts), 0, -1):
            cand = ".".join(parts[:i])
            if cand in idx.module_symbols:
                target_mod = cand
                break
        if target_mod is None:
            continue
        syms = idx.module_symbols.get(target_mod, set())
        if name not in syms:
            # maybe it's a submodule
            if mod in idx.modules:
                grounded.append(f"import {mod}")
                continue
            hallucinations.append({
                "type": "import_name",
                "symbol": f"{mod}.{name}",
                "evidence": f"from {mod} import {name}",
                "severity": "high",
            })
        else:
            grounded.append(f"import {mod}.{name}")

    # --- 2. backtick identifier checks ---
    all_names = idx.all_names()
    str_lits = idx.string_literals
    for tok in extract_backtick_symbols(page_md):
        # only check tokens that look like Python identifiers
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", tok):
            continue
        # skip common words / markdown noise
        if tok.lower() in {
            "python", "bash", "shell", "json", "yaml", "yml", "toml",
            "md", "txt", "html", "css", "js", "ts", "api", "cli", "llm",
            "llms", "rag", "http", "https", "url", "uri", "id", "ok",
            "true", "false", "none", "null", "self", "cls", "str", "int",
            "float", "bool", "list", "dict", "set", "tuple", "bytes",
            "object", "type", "value", "key", "name", "type", "data",
            "input", "output", "result", "results", "error", "errors",
            "warning", "warnings", "info", "debug", "log", "logs",
            "test", "tests", "example", "examples", "config", "configs",
            "file", "files", "path", "paths", "dir", "dirs", "folder",
            "module", "modules", "package", "packages", "function",
            "functions", "class", "classes", "method", "methods",
            "parameter", "parameters", "argument", "arguments", "option",
            "options", "flag", "flags", "command", "commands", "arg",
            "args", "env", "envs", "variable", "variables", "value",
            "values", "default", "defaults", "required", "optional",
            "return", "returns", "raise", "raises", "exception",
            "exceptions", "property", "properties", "attribute",
            "attributes", "instance", "instances", "object", "objects",
            "string", "strings", "number", "numbers", "integer",
            "boolean", "array", "arrays", "table", "tables", "row",
            "rows", "column", "columns", "cell", "cells", "header",
            "headers", "footer", "footers", "section", "sections",
            "page", "pages", "document", "documents", "doc", "docs",
            "site", "sites", "theme", "themes", "plugin", "plugins",
            "build", "builds", "serve", "serves", "run", "runs",
            "start", "starts", "stop", "stops", "create", "creates",
            "update", "updates", "delete", "deletes", "add", "adds",
            "remove", "removes", "get", "gets", "set", "sets", "load",
            "loads", "save", "saves", "read", "reads", "write",
            "writes", "open", "opens", "close", "closes", "check",
            "checks", "validate", "validates", "verify", "verifies",
            "parse", "parses", "format", "formats", "convert",
            "converts", "transform", "transforms", "generate",
            "generates", "compute", "computes", "calculate",
            "calculates", "evaluate", "evaluates", "measure",
            "measures", "score", "scores", "judge", "judges", "audit",
            "audits", "scenario", "scenarios", "model", "models",
            "provider", "providers", "client", "clients", "server",
            "servers", "endpoint", "endpoints", "request", "requests",
            "response", "responses", "token", "tokens", "prompt",
            "prompts", "message", "messages", "chat", "chats", "complet",
            "completion", "completions", "stream", "streams", "batch",
            "batches", "retry", "retries", "timeout", "timeouts",
            "limit", "limits", "max", "min", "avg", "mean", "median",
            "std", "var", "count", "sum", "total", "average",
            "percentage", "percent", "ratio", "rate", "score",
            "pass", "fail", "passed", "failed", "success", "failure",
            "ok", "good", "bad", "high", "low", "medium", "large",
            "small", "big", "tiny", "fast", "slow", "quick", "easy",
            "hard", "simple", "complex", "basic", "advanced", "full",
            "partial", "complete", "incomplete", "empty", "nonempty",
            "valid", "invalid", "active", "inactive", "enabled",
            "disabled", "available", "unavailable", "supported",
            "unsupported", "compatible", "incompatible", "local",
            "remote", "online", "offline", "public", "private",
            "protected", "internal", "external", "global", "local",
            "static", "dynamic", "async", "sync", "parallel",
            "sequential", "concurrent", "single", "multiple", "first",
            "last", "next", "previous", "current", "previous", "new",
            "old", "original", "updated", "changed", "unchanged",
            "added", "removed", "deleted", "created", "modified",
            "same", "different", "equal", "unequal", "similar",
            "unique", "duplicate", "primary", "secondary", "main",
            "sub", "parent", "child", "root", "leaf", "node", "edge",
            "graph", "tree", "list", "map", "set", "hash", "index",
            "key", "value", "pair", "tuple", "record", "entry", "item",
            "element", "member", "component", "part", "piece", "chunk",
            "block", "line", "lines", "char", "chars", "byte", "bytes",
            "bit", "bits", "word", "words", "sentence", "sentences",
            "paragraph", "paragraphs", "text", "string", "str",
            "number", "num", "int", "float", "double", "decimal",
            "fraction", "ratio", "percentage", "percent",
        }:
            continue
        # UPPER_CASE (env vars, constants in strings) -> ground via literals
        if re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", tok):
            if tok in idx.constants or tok in str_lits:
                grounded.append(f"const {tok}")
            elif pkg_name.lower().replace("-", "") in tok.lower():
                hallucinations.append({
                    "type": "constant",
                    "symbol": tok,
                    "evidence": f"`{tok}`",
                    "severity": "high",
                })
            continue
        # CamelCase -> must be a known class
        if re.fullmatch(r"[A-Z][A-Za-z0-9_]*", tok):
            if tok in idx.classes:
                grounded.append(f"class {tok}")
            elif tok in all_names:
                grounded.append(tok)
            elif tok in str_lits:
                grounded.append(f"literal {tok}")
            else:
                # could be a stdlib/third-party class — only flag if it
                # looks project-ish (contains pkg name) or is unusual
                if pkg_name.lower().replace("-", "") in tok.lower():
                    hallucinations.append({
                        "type": "class",
                        "symbol": tok,
                        "evidence": f"`{tok}`",
                        "severity": "high",
                    })
                # else: assume external class, don't flag
            continue
        # snake_case -> must be a known function/constant/method/module
        if re.fullmatch(r"[a-z_][a-z0-9_]*", tok):
            if tok in idx.functions or tok in idx.constants:
                grounded.append(f"func {tok}")
            elif tok in idx.class_methods.get(tok, set()) or any(
                tok in ms for ms in idx.class_methods.values()
            ):
                grounded.append(f"method {tok}")
            elif tok in all_names:
                grounded.append(tok)
            elif tok in str_lits:
                grounded.append(f"literal {tok}")
            elif tok in idx.function_params:
                grounded.append(f"param {tok}")
            elif any(m.split(".")[-1] == tok for m in idx.modules):
                grounded.append(f"module {tok}")
            else:
                # flag only if it looks like a project API (not a common word)
                if len(tok) >= 4 and "_" in tok:
                    hallucinations.append({
                        "type": "function_or_constant",
                        "symbol": tok,
                        "evidence": f"`{tok}`",
                        "severity": "medium",
                    })
                elif len(tok) >= 6:
                    hallucinations.append({
                        "type": "function_or_constant",
                        "symbol": tok,
                        "evidence": f"`{tok}`",
                        "severity": "low",
                    })

    # --- 3. method-call checks ---
    all_methods = set()
    for ms in idx.class_methods.values():
        all_methods |= ms
    for recv, meth in extract_method_calls(page_md):
        if meth in all_methods:
            grounded.append(f"method {meth}")
        elif meth in idx.functions or meth in idx.constants:
            grounded.append(meth)
        else:
            # heuristic: flag only if receiver looks like a project object
            recv_lower = recv.lower()
            if pkg_name.lower().replace("-", "") in recv_lower or \
               any(c.lower() in recv_lower for c in idx.classes):
                hallucinations.append({
                    "type": "method_call",
                    "symbol": f"{recv}.{meth}()",
                    "evidence": f"{recv}.{meth}(",
                    "severity": "medium",
                })

    n_high = sum(1 for h in hallucinations if h["severity"] == "high")
    n_med = sum(1 for h in hallucinations if h["severity"] == "medium")
    n_low = sum(1 for h in hallucinations if h["severity"] == "low")
    return {
        "hallucinations": hallucinations,
        "n_high": n_high,
        "n_medium": n_med,
        "n_low": n_low,
        "n_grounded": len(grounded),
        "grounded_sample": grounded[:20],
    }


def check_all(guides_dir: str, idx: SymbolIndex, pkg_name: str) -> dict:
    report = {}
    total_high = total_med = total_low = total_grounded = 0
    for f in sorted(os.listdir(guides_dir)):
        if not f.endswith(".md"):
            continue
        with open(os.path.join(guides_dir, f), encoding="utf-8") as fh:
            md = fh.read()
        r = check_page(md, idx, pkg_name)
        report[f] = r
        total_high += r["n_high"]
        total_med += r["n_medium"]
        total_low += r["n_low"]
        total_grounded += r["n_grounded"]
    report["_summary"] = {
        "pages": len(report) - 1,
        "total_high": total_high,
        "total_medium": total_med,
        "total_low": total_low,
        "total_grounded": total_grounded,
        "hallucination_rate": (
            (total_high + total_med) / max(1, total_grounded + total_high + total_med)
        ),
    }
    return report


if __name__ == "__main__":
    pkg_path = sys.argv[1]
    guides_dir = sys.argv[2]
    out = sys.argv[3] if len(sys.argv) > 3 else None
    pkg_name = os.path.basename(os.path.normpath(pkg_path))
    idx = build_index(pkg_path)
    report = check_all(guides_dir, idx, pkg_name)
    text = json.dumps(report, indent=2)
    if out:
        with open(out, "w") as fh:
            fh.write(text)
        print(f"Report written to {out}")
    print(json.dumps(report["_summary"], indent=2))
