"""Tests for repoquill.agents.verify (independent page verification)."""
import pytest

from repoquill.agents.contracts import PageTask, ToolContext
from repoquill.agents.verify import verify_page, verify_page_file


PKG_INIT = (
    "class Widget:\n"
    "    def __init__(self, name):\n"
    "        self.name = name\n"
    "    def describe(self):\n"
    "        return 'Widget: ' + self.name\n"
    "\n"
    "def make_widget(name):\n"
    "    return Widget(name)\n"
)

GOOD_PAGE = """# Alpha

Alpha provides `Widget` and `make_widget`.

## Widget

Create one with `make_widget`:

```python
from alpha import Widget, make_widget
w = make_widget("x")
assert w.describe()
```
"""

BAD_PAGE = """# Alpha

Alpha provides a NonexistentThing for nothing.

```python
import alpha.nonexistent_module
from alpha import does_not_exist
print(does_not_exist)
```
"""

COVERAGE_PAGE = """# Alpha

Alpha provides `Widget`.

```python
from alpha import Widget
w = Widget("x")
assert w.describe()
```
"""


@pytest.fixture
def pkg(tmp_path):
    """A tiny synthetic package at <tmp>/alpha plus a ToolContext."""
    pkg_dir = tmp_path / "alpha"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text(PKG_INIT, encoding="utf-8")
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    ctx = ToolContext(
        repo_root=str(tmp_path),
        pkg_path=str(pkg_dir),
        docs_dir=str(docs_dir),
    )
    task = PageTask(
        slug="alpha",
        title="Alpha",
        coverage_checklist=["Widget", "make_widget"],
        out_path=str(docs_dir / "alpha.md"),
    )
    return ctx, task


def test_good_page_passes(pkg):
    ctx, task = pkg
    result = verify_page("alpha", GOOD_PAGE, task, ctx)
    assert result.passed is True
    assert result.coverage.ratio == 1.0
    assert result.coverage.missing == []
    assert result.examples_ok is True
    assert result.import_findings == []
    assert result.symbol_findings == []
    assert len(result.example_findings) == 1
    assert result.example_findings[0]["status"] == "passed"


def test_bad_page_fails(pkg):
    ctx, task = pkg
    result = verify_page("alpha", BAD_PAGE, task, ctx)
    assert result.passed is False
    assert (
        result.import_findings
        or result.symbol_findings
        or any(f["status"] != "passed" for f in result.example_findings)
    )
    # The import of a nonexistent module must be flagged.
    assert result.import_findings


def test_coverage_below_threshold_fails(pkg):
    ctx, task = pkg
    result = verify_page(
        "alpha", COVERAGE_PAGE, task, ctx, coverage_threshold=0.9)
    assert result.coverage_ok is False
    assert result.passed is False
    assert "make_widget" in result.coverage.missing
    assert result.coverage.covered == ["Widget"]


def test_run_examples_disabled(pkg):
    ctx, task = pkg
    result = verify_page("alpha", GOOD_PAGE, task, ctx, run_examples=False)
    assert result.example_findings == []
    assert result.examples_ok is True
    assert result.passed is True


def test_empty_checklist_gives_full_coverage(pkg):
    ctx, task = pkg
    task.coverage_checklist = []
    result = verify_page("alpha", "No symbols here.\n", task, ctx)
    assert result.coverage.ratio == 1.0
    assert result.coverage_ok is True


def test_verify_page_file(tmp_path, pkg):
    ctx, task = pkg
    page_path = tmp_path / "alpha.md"
    page_path.write_text(GOOD_PAGE, encoding="utf-8")
    result = verify_page_file("alpha", str(page_path), task, ctx)
    assert result.passed is True
    assert result.coverage.ratio == 1.0
