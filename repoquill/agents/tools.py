"""RepoQuill's documentation-agent tool runtime (agentic engine).

This is the ONLY component that gives the documentation agent any access to
the repository or a shell. It implements the tools declared in
:mod:`repoquill.agents.contracts` (:data:`TOOL_SCHEMAS`) behind a single
:class:`ToolRegistry` (:class:`RepoQuillTools`).

Safety invariants (enforced, not documented-only)
-------------------------------------------------
* **Reads are confined to ``ctx.repo_root``.** Every read tool
  (``list_files`` / ``read_file`` / ``search_code``) resolves its target
  through :meth:`ToolContext.resolve_read`, which raises if the path
  escapes the root. Absolute paths and ``..`` are rejected.
* **Writes are confined to the docs output directory.** The agent can only
  write ``<ctx.docs_dir>/<slug>.md`` via ``write_doc``; slugs containing
  separators or ``..`` are rejected by :meth:`ToolContext.resolve_write`.
  The tool runtime NEVER writes under ``ctx.pkg_path`` (the application
  source) or anywhere else.
* **Example execution is isolated.** ``run_example`` runs the snippet in a
  fresh ``sys.executable -I`` subprocess in a throwaway working directory,
  in its own process group, with an environment reduced to an allowlist
  (only ``PATH``, ``HOME`` and ``PYTHONPATH`` are kept — parent credentials
  are never visible) and a hard wall-clock timeout that SIGKILLs the whole
  process group (so processes the example itself spawned die too). No shell
  is used (argv list form) and no network restrictions are granted beyond
  the inherited user account (see ``_run_isolated``).
* **No tool raises.** Every execution is wrapped and returned as a
  :class:`ToolResult` (``ok=False`` + ``error``) so the agent loop can
  never be crashed by a single tool call.
* **Opt-out for execution.** When ``ctx.execute_examples`` is false,
  ``run_example`` is not offered (removed from ``schemas()``) and calling
  it directly returns a policy error.
"""

from __future__ import annotations

import fnmatch
import os
import re
import signal
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional

from .contracts import (
    TERMINAL_TOOL,
    TOOL_SCHEMAS,
    ToolContext,
    ToolRegistry,
    ToolResult,
)

# Directories never traversed by read/search tools (noise + risk).
_SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "env",
    ".env", "node_modules", ".eggs", "build", "dist", "site",
    ".pytest_cache", "htmlcov", ".mypy_cache", ".ruff_cache", ".tox",
    ".idea", ".vscode", "*.egg-info",
})

# File extensions considered "text" for search (avoids binary noise).
_TEXT_EXTS = frozenset({
    ".py", ".md", ".rst", ".txt", ".yml", ".yaml", ".json", ".toml",
    ".cfg", ".ini", ".js", ".ts", ".html", ".css", ".sh",
})

_MAX_LIST_FILES = 500
_STDOUT_LIMIT = 4000
_STDERR_LIMIT = 4000


def _is_skipped_dir(name: str) -> bool:
    if name in _SKIP_DIRS:
        return True
    return any(fnmatch.fnmatch(name, pat) for pat in _SKIP_DIRS if "*" in pat)


def _is_text_file(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    return ext in _TEXT_EXTS


class RepoQuillTools(ToolRegistry):
    """Concrete :class:`ToolRegistry` for one documentation-authoring run.

    Args:
        ctx: The :class:`ToolContext` describing roots + policy.
    """

    def __init__(self, ctx: ToolContext):
        self.ctx = ctx

    # ------------------------------------------------------------------
    # Registry interface
    # ------------------------------------------------------------------
    def schemas(self) -> List[Dict[str, Any]]:
        if self.ctx.execute_examples:
            return [dict(s) for s in TOOL_SCHEMAS]
        return [dict(s) for s in TOOL_SCHEMAS
                if s["function"]["name"] != "run_example"]

    def names(self) -> List[str]:
        return [s["function"]["name"] for s in self.schemas()]

    def execute(self, name: str, arguments: Dict[str, Any]) -> ToolResult:
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return ToolResult(name, False, None, f"unknown tool: {name!r}")
        try:
            data = handler(arguments or {})
            return ToolResult(name, True, data)
        except ValueError as e:
            return ToolResult(name, False, None, str(e))
        except Exception as e:  # noqa: BLE001 - a tool must never raise
            return ToolResult(name, False, None, f"{type(e).__name__}: {e}")

    # ------------------------------------------------------------------
    # Read tools
    # ------------------------------------------------------------------
    def _tool_list_files(self, args: Dict[str, Any]) -> Dict[str, Any]:
        sub = (args.get("path") or "").strip()
        pattern = (args.get("pattern") or "").strip()
        base = self.ctx.resolve_read(sub) if sub else self.ctx.repo_root
        files: List[str] = []
        truncated = False
        for dirpath, dirnames, filenames in os.walk(base):
            # Prune skipped directories in place.
            dirnames[:] = [d for d in dirnames if not _is_skipped_dir(d)]
            for fn in sorted(filenames):
                if pattern and not fnmatch.fnmatch(fn, pattern):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, self.ctx.repo_root)
                files.append(rel.replace(os.sep, "/"))
                if len(files) >= _MAX_LIST_FILES:
                    truncated = True
                    break
            if truncated:
                break
        return {"files": files, "count": len(files), "truncated": truncated}

    def _tool_read_file(self, args: Dict[str, Any]) -> Dict[str, Any]:
        path = args.get("path")
        if not path:
            raise ValueError("read_file requires 'path'")
        full = self.ctx.resolve_read(path)
        if not os.path.isfile(full):
            raise ValueError(f"no such file: {path}")
        with open(full, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        lines = text.splitlines()
        start = args.get("start_line")
        end = args.get("end_line")
        total = len(lines)
        s = max(1, int(start)) if start else 1
        e = min(total, int(end)) if end else total
        if s > total:
            s = total
        selected = lines[s - 1:e]
        chunk = "\n".join(selected)
        truncated_chars = False
        limit = self.ctx.max_file_chars
        if len(chunk) > limit:
            chunk = chunk[:limit] + "\n... (truncated)"
            truncated_chars = True
        return {
            "path": os.path.relpath(full, self.ctx.repo_root).replace(os.sep, "/"),
            "start_line": s,
            "end_line": e,
            "total_lines": total,
            "content": chunk,
            "truncated": truncated_chars,
        }

    def _tool_search_code(self, args: Dict[str, Any]) -> Dict[str, Any]:
        pattern = args.get("pattern")
        if not pattern:
            raise ValueError("search_code requires 'pattern'")
        use_regex = bool(args.get("regex", False))
        max_results = int(args.get("max_results") or self.ctx.max_search_results)
        sub = (args.get("path") or "").strip()
        base = self.ctx.resolve_read(sub) if sub else self.ctx.repo_root
        try:
            rx = re.compile(pattern) if use_regex else None
        except re.error as e:
            raise ValueError(f"invalid regex: {e}")
        # A file path searches just that file. (os.walk on a file yields
        # nothing, which used to report "0 results" for symbols that were
        # plainly in the file — the SimpleAudit baseline agent looped on
        # the same search 339 times because of this.) A missing path is a
        # real error, not a silent zero.
        if os.path.isfile(base):
            files = [base]
        elif not os.path.isdir(base):
            raise ValueError(f"no such file or directory: {sub or '.'}")
        else:
            files = []
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = [d for d in dirnames if not _is_skipped_dir(d)]
                for fn in sorted(filenames):
                    if _is_text_file(fn):
                        files.append(os.path.join(dirpath, fn))
        results: List[str] = []
        truncated = False
        for full in files:
            rel = os.path.relpath(full, self.ctx.repo_root).replace(os.sep, "/")
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as fh:
                    for lineno, line in enumerate(fh, start=1):
                        if use_regex:
                            hit = rx.search(line) is not None
                        else:
                            hit = pattern in line
                        if hit:
                            results.append(
                                f"{rel}:{lineno}: {line.rstrip()}")
                            if len(results) >= max_results:
                                truncated = True
                                break
            except (OSError, UnicodeDecodeError):
                continue
            if truncated:
                break
        return {"results": results, "count": len(results),
                "truncated": truncated}

    def _tool_inspect_api(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from repoquill.reference import extract_api_surface
        surface = ""
        try:
            surface = extract_api_surface(self.ctx.pkg_path) or ""
        except Exception:  # noqa: BLE001 - surface is best-effort
            surface = ""
        out: Dict[str, Any] = {"api_surface": surface}
        symbol = (args.get("symbol") or "").strip()
        if symbol:
            from repoquill.verify import build_index
            matched = [ln for ln in surface.splitlines() if symbol in ln]
            out["symbol"] = symbol
            out["symbol_matches"] = matched[:40]
            try:
                idx = build_index(self.ctx.pkg_path)
                if symbol in idx.classes:
                    out["symbol_members"] = sorted(
                        idx.class_methods.get(symbol, ()))
                elif symbol in idx.functions:
                    out["symbol_kind"] = "function"
            except Exception:  # noqa: BLE001 - members are best-effort
                pass
        return out

    def _tool_inspect_tests(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from repoquill.reference import get_tests_context
        max_chars = int(args.get("max_chars") or 6000)
        text = ""
        try:
            text = get_tests_context(self.ctx.repo_root, max_chars=max_chars) or ""
        except Exception:  # noqa: BLE001
            text = ""
        return {"tests": text}

    # ------------------------------------------------------------------
    # Execution tool (isolated)
    # ------------------------------------------------------------------
    def _tool_run_example(self, args: Dict[str, Any]) -> Dict[str, Any]:
        if not self.ctx.execute_examples:
            raise ValueError(
                "run_example is disabled by policy for this run")
        code = args.get("code")
        if not code or not code.strip():
            raise ValueError("run_example requires non-empty 'code'")
        timeout = float(args.get("timeout") or self.ctx.example_timeout)
        timeout = max(1.0, min(timeout, 120.0))
        return self._run_isolated(code, timeout)

    def _run_isolated(self, code: str, timeout: float) -> Dict[str, Any]:
        pkg_parent = os.path.dirname(os.path.abspath(self.ctx.pkg_path))
        env = {k: os.environ[k]
               for k in ("PATH", "HOME", "PYTHONPATH") if k in os.environ}
        env["PYTHONPATH"] = (
            pkg_parent + os.pathsep + env["PYTHONPATH"]
            if env.get("PYTHONPATH") else pkg_parent
        )
        with tempfile.TemporaryDirectory(prefix="repoquill-agent-") as base:
            script = os.path.join(base, "example.py")
            with open(script, "w", encoding="utf-8") as fh:
                fh.write(code)
            bootstrap = (
                "import runpy, sys; "
                f"sys.path.insert(0, {pkg_parent!r}); "
                f"runpy.run_path({script!r}, run_name='__main__')"
            )
            cmd = [sys.executable, "-I", "-c", bootstrap]
            try:
                # Own session + process group (POSIX) so the timeout can
                # kill the example AND anything it spawned.
                pg_kw = ({"start_new_session": True}
                         if hasattr(os, "killpg") else {})
                proc = subprocess.Popen(
                    cmd, cwd=base, env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, **pg_kw)
                try:
                    stdout, stderr = proc.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    self._kill_process_tree(proc)
                    # Drain whatever the example printed before the kill.
                    try:
                        stdout, stderr = proc.communicate(timeout=5)
                    except (subprocess.TimeoutExpired, ValueError):
                        stdout, stderr = "", ""
                    return {
                        "ok": False, "returncode": None,
                        "stdout": (stdout or "")[-_STDOUT_LIMIT:],
                        "stderr": (f"exceeded {timeout:g}s wall-clock "
                                   "limit; process group killed"),
                        "timed_out": True,
                    }
                return {
                    "ok": proc.returncode == 0,
                    "returncode": proc.returncode,
                    "stdout": (stdout or "")[-_STDOUT_LIMIT:],
                    "stderr": (stderr or "")[-_STDERR_LIMIT:],
                    "timed_out": False,
                }
            except Exception as e:  # noqa: BLE001 - report, don't raise
                return {
                    "ok": False, "returncode": None, "stdout": "",
                    "stderr": f"could not execute example: {e}",
                    "timed_out": False,
                }

    @staticmethod
    def _kill_process_tree(proc: "subprocess.Popen") -> None:
        """SIGKILL the example process and (POSIX) its whole process group."""
        try:
            if hasattr(os, "killpg"):
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except OSError:
                pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass

    # ------------------------------------------------------------------
    # Docs tools (the only writable surface)
    # ------------------------------------------------------------------
    def _tool_list_docs(self, args: Dict[str, Any]) -> Dict[str, Any]:
        docs = []
        if os.path.isdir(self.ctx.docs_dir):
            for fn in sorted(os.listdir(self.ctx.docs_dir)):
                if not fn.endswith(".md"):
                    continue
                slug = fn[:-3]
                first_line = ""
                try:
                    with open(os.path.join(self.ctx.docs_dir, fn), "r",
                              encoding="utf-8", errors="replace") as fh:
                        for line in fh:
                            line = line.strip()
                            if line:
                                first_line = line[:160]
                                break
                except OSError:
                    pass
                docs.append({"slug": slug, "first_line": first_line})
        return {"docs": docs, "count": len(docs)}

    def _tool_read_doc(self, args: Dict[str, Any]) -> Dict[str, Any]:
        slug = args.get("slug")
        if not slug:
            raise ValueError("read_doc requires 'slug'")
        path = self.ctx.resolve_write(slug)
        if not os.path.isfile(path):
            raise ValueError(f"no such doc: {slug}")
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
        return {"slug": slug, "content": content}

    def _tool_write_doc(self, args: Dict[str, Any]) -> Dict[str, Any]:
        slug = args.get("slug")
        content = args.get("content")
        if not slug:
            raise ValueError("write_doc requires 'slug'")
        if content is None:
            raise ValueError("write_doc requires 'content'")
        path = self.ctx.resolve_write(slug)
        os.makedirs(self.ctx.docs_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return {"slug": slug, "path": path, "chars": len(content)}


def build_tool_context(cfg, execute_examples: bool = True,
                       example_timeout: Optional[float] = None,
                       max_file_chars: Optional[int] = None) -> ToolContext:
    """Build a :class:`ToolContext` from a loaded RepoQuill config.

    Convenience for the integrator (``cli.py``): wires the repo root, the
    documented package, and the guide output directory into a context,
    applying optional agentic overrides.
    """
    return ToolContext(
        repo_root=cfg.root,
        pkg_path=cfg.pkg_path,
        docs_dir=cfg.out_guides,
        execute_examples=execute_examples,
        example_timeout=(example_timeout
                         if example_timeout is not None else 30.0),
        max_file_chars=(max_file_chars if max_file_chars is not None
                        else 16000),
    )
