"""Opt-in executable checks for Python examples in generated doc pages.

Each Python code block is executed in a *subprocess* — never in-process
— as an isolated interpreter (``sys.executable -I``) with:

* a fresh temporary working directory (or a caller-provided one);
* an environment stripped of credentials: only ``PATH``, ``HOME`` and
  ``PYTHONPATH`` are kept;
* a wall-clock timeout; the child is killed on exceed;
* the target package made importable by a tiny ``sys.path`` bootstrap
  (needed because ``-I`` ignores ``PYTHONPATH`` and, on Python 3.11+,
  also drops the script directory from ``sys.path``).

This is OFF by default in the quality gate — call
:func:`run_page_examples` (or ``run_gate(..., run_examples=True)``)
explicitly to opt in.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from typing import List, Optional

from repoquill.validation.blocks import python_blocks

#: Env vars preserved for the example subprocess (credentials stripped).
_KEEP_ENV = ("PATH", "HOME", "PYTHONPATH")

_STDERR_LIMIT = 300


def _make_env(pkg_path: str) -> dict:
    env = {k: os.environ[k] for k in _KEEP_ENV if k in os.environ}
    parent = os.path.dirname(os.path.abspath(pkg_path))
    env["PYTHONPATH"] = (parent + os.pathsep + env["PYTHONPATH"]
                         if env.get("PYTHONPATH") else parent)
    return env


def run_page_examples(page_path: str, pkg_path: str, timeout: int = 15,
                      workdir: Optional[str] = None) -> List[dict]:
    """Execute every Python code block in *page_path* and report results.

    Returns one dict per block:
    ``{"page", "block", "line", "status", "returncode", "detail"}``
    where ``status`` is ``"passed"``, ``"failed"``, or ``"timeout"``.
    For failures, ``detail`` is the *tail* of stderr (the last ~300
    chars) — the exception message is the final line of a traceback,
    so keeping the tail keeps it visible.
    """
    slug = os.path.basename(page_path)
    if slug.endswith(".md"):
        slug = slug[:-3]
    with open(page_path, "r", encoding="utf-8") as fh:
        md = fh.read()

    blocks = python_blocks(md)
    pkg_name = os.path.basename(os.path.normpath(pkg_path))
    env = _make_env(pkg_path)

    own_dir = workdir is None
    base = workdir or tempfile.mkdtemp(prefix="repoquill-ex-")
    os.makedirs(base, exist_ok=True)

    # Bootstrap that makes the package importable while keeping -I
    # isolation (no user site, no PYTHON* env vars).
    parent = os.path.dirname(os.path.abspath(pkg_path))
    bootstrap = (
        "import runpy, sys; "
        f"sys.path.insert(0, {parent!r}); "
        "runpy.run_path({script!r}, run_name='__main__')"
    )

    results: List[dict] = []
    try:
        for i, (start, code) in enumerate(blocks, start=1):
            if not code.strip():
                continue
            script = os.path.join(base, f"example_{i}.py")
            with open(script, "w", encoding="utf-8") as fh:
                fh.write(code)
            cmd = [sys.executable, "-I", "-c",
                   bootstrap.replace("{script!r}", repr(script))]
            entry = {"page": slug, "block": i, "line": start,
                     "check": "example", "status": "failed",
                     "returncode": None, "detail": ""}
            try:
                proc = subprocess.run(
                    cmd, cwd=base, env=env, capture_output=True,
                    text=True, timeout=timeout)
                if proc.returncode == 0:
                    entry["status"] = "passed"
                    entry["detail"] = ""
                else:
                    entry["status"] = "failed"
                    entry["detail"] = (proc.stderr or proc.stdout or "").strip()[-_STDERR_LIMIT:]
                entry["returncode"] = proc.returncode
            except subprocess.TimeoutExpired:
                entry["status"] = "timeout"
                entry["detail"] = f"exceeded {timeout}s wall-clock limit"
            except Exception as e:  # noqa: BLE001 - report, don't raise
                entry["status"] = "failed"
                entry["detail"] = f"could not execute example: {e}"[:_STDERR_LIMIT]
            results.append(entry)
    finally:
        if own_dir:
            shutil.rmtree(base, ignore_errors=True)
    return results
