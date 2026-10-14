"""Tests for the documentation-agent tool runtime (repoquill.agents.tools).

Covers the security invariants that matter:
* reads are confined to the repo root (``..`` and absolute paths rejected);
* writes are confined to the docs dir (only ``<docs>/<slug>.md``);
* ``run_example`` runs in an isolated subprocess and reports pass/fail;
* ``run_example`` is hidden + refused when execution is disabled;
* no tool raises — every failure returns a ToolResult with ok=False.
"""

from __future__ import annotations

import os
import sys

import pytest

from repoquill.agents.contracts import (
    TERMINAL_TOOL,
    ToolContext,
)
from repoquill.agents.tools import RepoQuillTools


@pytest.fixture
def repo(tmp_path):
    """A tiny synthetic repo with a package + docs dir.

    Layout:
        <root>/pkg/alpha.py   (class Widget, def make_widget)
        <root>/pkg/__init__.py
        <root>/README.md
        <root>/docs/          (empty)
    """
    root = tmp_path / "root"
    pkg = root / "pkg"
    (pkg).mkdir(parents=True)
    docs = root / "docs"
    docs.mkdir()

    (pkg / "__init__.py").write_text(
        "from .alpha import Widget, make_widget\n"
        "__all__ = ['Widget', 'make_widget']\n",
        encoding="utf-8",
    )
    (pkg / "alpha.py").write_text(
        "class Widget:\n"
        "    def __init__(self, name):\n"
        "        self.name = name\n"
        "    def describe(self):\n"
        "        return 'widget:' + self.name\n\n"
        "def make_widget(name):\n"
        "    return Widget(name)\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Pkg\nA tiny package.\n", encoding="utf-8")
    ctx = ToolContext(
        repo_root=str(root),
        pkg_path=str(pkg),
        docs_dir=str(docs),
        execute_examples=True,
    )
    return {"root": str(root), "ctx": ctx, "tools": RepoQuillTools(ctx)}


def test_list_files_returns_relative_paths(repo):
    res = repo["tools"].execute("list_files", {})
    assert res.ok
    files = res.data["files"]
    assert "README.md" in files
    assert any(f.endswith("pkg/alpha.py") for f in files)


def test_list_files_pattern_filter(repo):
    res = repo["tools"].execute("list_files", {"pattern": "*.py"})
    assert res.ok
    assert all(f.endswith(".py") for f in res.data["files"])


def test_read_file_content(repo):
    res = repo["tools"].execute("read_file", {"path": "pkg/alpha.py"})
    assert res.ok
    assert "class Widget" in res.data["content"]


def test_read_file_line_range(repo):
    res = repo["tools"].execute(
        "read_file", {"path": "pkg/alpha.py", "start_line": 1, "end_line": 1})
    assert res.ok
    assert res.data["content"].startswith("class Widget")


def test_read_file_missing(repo):
    res = repo["tools"].execute("read_file", {"path": "does/not/exist.py"})
    assert not res.ok
    assert "no such file" in res.error


def test_read_file_escape_rejected(repo):
    # Parent traversal must be rejected, not read.
    res = repo["tools"].execute("read_file", {"path": "../../etc/passwd"})
    assert not res.ok
    assert "escapes" in res.error


def test_read_file_absolute_out_of_root_rejected(repo):
    res = repo["tools"].execute("read_file", {"path": "/etc/hostname"})
    assert not res.ok
    assert "escapes" in res.error


def test_search_code_finds_symbol(repo):
    res = repo["tools"].execute("search_code", {"pattern": "make_widget"})
    assert res.ok
    assert any("pkg/alpha.py" in r for r in res.data["results"])


def test_search_code_regex(repo):
    res = repo["tools"].execute(
        "search_code", {"pattern": r"def \w+widget", "regex": True})
    assert res.ok
    assert any("make_widget" in r for r in res.data["results"])


def test_search_code_bad_regex(repo):
    res = repo["tools"].execute(
        "search_code", {"pattern": "(", "regex": True})
    assert not res.ok
    assert "invalid regex" in res.error


def test_search_code_file_path_searches_that_file(repo):
    """A file path must search just that file. (os.walk on a file yields
    nothing, so a symbol plainly in the file reported 0 results — the
    SimpleAudit baseline agent looped on the same search 339x on
    ``simpleaudit/experiment.py`` because of this.)"""
    res = repo["tools"].execute(
        "search_code",
        {"pattern": "make_widget", "path": "pkg/alpha.py"})
    assert res.ok
    assert res.data["count"] >= 1
    assert all(r.startswith("pkg/alpha.py:") for r in res.data["results"])


def test_search_code_file_path_excludes_other_files(repo):
    res = repo["tools"].execute(
        "search_code", {"pattern": "make_widget", "path": "pkg/alpha.py"})
    assert all("pkg/__init__.py" not in r for r in res.data["results"])


def test_search_code_missing_path_is_error(repo):
    res = repo["tools"].execute(
        "search_code", {"pattern": "x", "path": "pkg/nope.py"})
    assert not res.ok
    assert "no such file or directory" in res.error


def test_inspect_api_surface(repo):
    res = repo["tools"].execute("inspect_api", {})
    assert res.ok
    assert "Widget" in res.data["api_surface"]


def test_inspect_api_symbol_focus(repo):
    res = repo["tools"].execute("inspect_api", {"symbol": "Widget"})
    assert res.ok
    assert res.data.get("symbol") == "Widget"
    assert "describe" in res.data.get("symbol_members", [])


def test_write_doc_creates_page(repo):
    res = repo["tools"].execute(
        "write_doc", {"slug": "alpha", "content": "## Alpha\n\nHello."})
    assert res.ok
    assert res.data["chars"] > 0
    path = os.path.join(repo["ctx"].docs_dir, "alpha.md")
    assert os.path.isfile(path)
    assert open(path, encoding="utf-8").read() == "## Alpha\n\nHello."


def test_write_doc_cannot_escape_docs(repo):
    res = repo["tools"].execute(
        "write_doc", {"slug": "../../escape", "content": "x"})
    assert not res.ok
    assert "invalid doc slug" in res.error


def test_write_doc_cannot_write_absolute(repo):
    res = repo["tools"].execute(
        "write_doc", {"slug": "/tmp/evil.md", "content": "x"})
    assert not res.ok


def test_read_doc_roundtrip(repo):
    repo["tools"].execute("write_doc", {"slug": "alpha", "content": "Body"})
    res = repo["tools"].execute("read_doc", {"slug": "alpha"})
    assert res.ok
    assert res.data["content"] == "Body"


def test_list_docs(repo):
    repo["tools"].execute("write_doc", {"slug": "alpha", "content": "## A"})
    res = repo["tools"].execute("list_docs", {})
    assert res.ok
    assert any(d["slug"] == "alpha" for d in res.data["docs"])


def test_run_example_passes(repo):
    # The importable package name is the basename of pkg_path ("pkg").
    code = "from pkg import make_widget\nw = make_widget('x')\nprint(w.describe())"
    res = repo["tools"].execute("run_example", {"code": code})
    assert res.ok
    data = res.data
    assert data["ok"] is True
    assert data["returncode"] == 0
    assert "widget:x" in data["stdout"]


def test_run_example_reports_failure(repo):
    code = "from pkg import make_widget\nprint(make_widget('x').nope())"
    res = repo["tools"].execute("run_example", {"code": code})
    assert res.ok  # the tool itself succeeded; the example failed
    data = res.data
    assert data["ok"] is False
    assert data["returncode"] != 0
    assert "nope" in data["stderr"] or "Error" in data["stderr"]


def test_run_example_timeout(repo):
    code = "import time\ntime.sleep(5)\n"
    res = repo["tools"].execute("run_example", {"code": code, "timeout": 2})
    assert res.ok
    assert res.data["timed_out"] is True
    assert res.data["ok"] is False


def test_run_example_disabled_by_policy(tmp_path):
    root = tmp_path / "root"
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    docs = root / "docs"
    docs.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    ctx = ToolContext(repo_root=str(root), pkg_path=str(pkg),
                      docs_dir=str(docs), execute_examples=False)
    tools = RepoQuillTools(ctx)
    # run_example must not be advertised...
    assert "run_example" not in tools.names()
    # ...and must be refused if called directly.
    res = tools.execute("run_example", {"code": "print(1)"})
    assert not res.ok
    assert "disabled by policy" in res.error


def test_unknown_tool_returns_error(repo):
    res = repo["tools"].execute("fly_to_moon", {})
    assert not res.ok
    assert "unknown tool" in res.error


def test_schemas_include_terminal_tool(repo):
    names = repo["tools"].names()
    assert TERMINAL_TOOL in names
    assert "read_file" in names
    assert "search_code" in names


def test_write_doc_rejects_empty_content(repo):
    res = repo["tools"].execute("write_doc", {"slug": "x"})
    assert not res.ok


# --------------------------------------------------------------------------- #
# Over-exploration loop fixes (SimpleAudit baseline: P1.2 / P1.5)
# --------------------------------------------------------------------------- #
def test_search_code_reports_total_matches(repo, tmp_path):
    """A search that hits max_results must still report the COMPLETE
    match count + matching files, so a model wanting 'all matches'
    stops escalating max_results (measured: same search re-issued
    193x walking max_results 3 -> 500)."""
    root = tmp_path / "big"
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    docs = root / "docs"
    docs.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "many.py").write_text(
        "".join(f"def f_{i}():\n    return {i}\n\n" for i in range(40)),
        encoding="utf-8")
    from repoquill.agents.tools import RepoQuillTools
    from repoquill.agents.contracts import ToolContext
    ctx = ToolContext(repo_root=str(root), pkg_path=str(pkg),
                      docs_dir=str(docs), execute_examples=False)
    tools = RepoQuillTools(ctx)
    res = tools.execute("search_code",
                        {"pattern": "def f_", "max_results": 5})
    assert res.ok
    assert res.data["count"] == 5
    assert res.data["truncated"] is True
    assert res.data["total_matches"] == 40
    assert res.data["files"] == ["pkg/many.py"]
    assert "40 total matches" in res.data["note"]
    # A search that fits: total == count, no note.
    res2 = tools.execute("search_code", {"pattern": "def f_4"})
    assert res2.ok
    assert res2.data["total_matches"] == 1
    assert res2.data["truncated"] is False
    assert "note" not in res2.data


def test_search_code_missing_path_still_a_real_error(repo):
    res = repo["tools"].execute("search_code",
                                {"pattern": "x", "path": "pkg/nope.py"})
    assert not res.ok
    assert "no such file or directory" in res.error


def _long_file_repo(tmp_path, n_lines=600):
    root = tmp_path / "root"
    pkg = root / "pkg"
    pkg.mkdir(parents=True)
    docs = root / "docs"
    docs.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "long.py").write_text(
        "".join(f"line_{i} = {i}\n" for i in range(n_lines)),
        encoding="utf-8")
    from repoquill.agents.tools import RepoQuillTools
    from repoquill.agents.contracts import ToolContext
    ctx = ToolContext(repo_root=str(root), pkg_path=str(pkg),
                      docs_dir=str(docs), execute_examples=False)
    return RepoQuillTools(ctx), root


def test_read_file_defaults_to_bounded_window(tmp_path):
    """A no-window read of a long file returns a bounded first window
    plus a continuation pointer — not the whole file (the measured
    compaction-amnesia driver: 102 full reads of ~40k chars)."""
    tools, root = _long_file_repo(tmp_path, 600)
    res = tools.execute("read_file", {"path": "pkg/long.py"})
    assert res.ok
    assert res.data["total_lines"] == 600
    assert res.data["start_line"] == 1
    assert res.data["end_line"] == 200
    assert res.data["end_of_file"] is False
    assert "line_0 =" in res.data["content"]
    assert "line_599" not in res.data["content"]
    assert "start_line=201" in res.data["note"]
    # An explicit full-file request is honored (the model chose it).
    res2 = tools.execute("read_file",
                         {"path": "pkg/long.py", "start_line": 1,
                          "end_line": 600})
    assert res2.ok
    assert res2.data["end_line"] == 600
    assert "line_599" in res2.data["content"]
    assert res2.data["end_of_file"] is True
    assert "note" not in res2.data


def test_read_file_end_of_file_semantics(repo):
    """A window reaching the last line says end_of_file, so an EOF
    ladder (end_line 584 -> 1e300) terminates on the first answer."""
    res = repo["tools"].execute(
        "read_file", {"path": "pkg/alpha.py", "start_line": 5,
                      "end_line": 10 ** 6})
    assert res.ok
    assert res.data["end_of_file"] is True
    assert res.data["end_line"] == res.data["total_lines"]
    # A middle window does not claim EOF.
    res2 = repo["tools"].execute(
        "read_file", {"path": "pkg/alpha.py", "start_line": 1,
                      "end_line": 3})
    assert res2.ok
    assert res2.data["end_of_file"] is False


def test_read_file_past_end_of_file_is_explicit(tmp_path):
    """start_line beyond the last line is an explicit empty answer,
    not a silent clamp (the measured EOF-ladder re-read)."""
    tools, _ = _long_file_repo(tmp_path, 10)
    res = tools.execute("read_file",
                        {"path": "pkg/long.py", "start_line": 11,
                         "end_line": 20})
    assert res.ok
    assert res.data["content"] == ""
    assert res.data["end_of_file"] is True
    assert "past the end of the file" in res.data["note"]
    assert "10" in res.data["note"]
