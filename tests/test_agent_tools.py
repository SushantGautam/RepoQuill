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
