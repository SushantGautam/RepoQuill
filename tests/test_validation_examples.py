"""Opt-in executable-example tests (repoquill.validation.examples)."""

from __future__ import annotations

import os

import pytest

from repoquill.validation.examples import run_page_examples


INIT = '''\
from .core import Widget

VERSION = "1.0"
'''

CORE = '''\
class Widget:
    def __init__(self, label):
        self.label = label

    def describe(self):
        return "Widget(" + self.label + ")"
'''


@pytest.fixture
def pkg_root(tmp_path):
    root = tmp_path / "repo"
    (root / "fakepkg").mkdir(parents=True)
    (root / "fakepkg" / "__init__.py").write_text(INIT, encoding="utf-8")
    (root / "fakepkg" / "core.py").write_text(CORE, encoding="utf-8")
    return str(root)


def _page(tmp_path, content):
    p = tmp_path / "page.md"
    p.write_text(content, encoding="utf-8")
    return str(p)


def test_passing_block(pkg_root, tmp_path):
    page = _page(tmp_path, '''\
```python
from fakepkg import Widget
w = Widget(label="x")
assert w.describe() == "Widget(x)"
```
''')
    results = run_page_examples(page, os.path.join(pkg_root, "fakepkg"))
    assert len(results) == 1
    r = results[0]
    assert r["status"] == "passed"
    assert r["returncode"] == 0
    assert r["block"] == 1


def test_required_kwarg_enforced(pkg_root, tmp_path):
    page = _page(tmp_path, '```python\nfrom fakepkg import Widget\nWidget()\n```\n')
    results = run_page_examples(page, os.path.join(pkg_root, "fakepkg"))
    assert results[0]["status"] == "failed"
    assert "label" in results[0]["detail"]


def test_failing_block_reports_stderr(pkg_root, tmp_path):
    page = _page(tmp_path, '''\
```python
x = 1 / 0
```
''')
    results = run_page_examples(page, os.path.join(pkg_root, "fakepkg"))
    assert results[0]["status"] == "failed"
    assert "ZeroDivisionError" in results[0]["detail"]
    assert len(results[0]["detail"]) <= 300


def test_mixed_blocks_per_block_results(pkg_root, tmp_path):
    page = _page(tmp_path, '''\
```python
from fakepkg import Widget
assert Widget(label="a").describe() == "Widget(a)"
```

Some prose.

```python
from fakepkg import Nope
```
''')
    results = run_page_examples(page, os.path.join(pkg_root, "fakepkg"))
    assert [r["status"] for r in results] == ["passed", "failed"]
    assert [r["block"] for r in results] == [1, 2]
    assert "Nope" in results[1]["detail"]


def test_infinite_loop_times_out_without_hang(pkg_root, tmp_path):
    page = _page(tmp_path, '```python\nwhile True:\n    pass\n```\n')
    results = run_page_examples(page, os.path.join(pkg_root, "fakepkg"),
                                timeout=2)
    assert results[0]["status"] == "timeout"
    assert "2s" in results[0]["detail"]


def test_non_python_block_skipped(pkg_root, tmp_path):
    page = _page(tmp_path,
                 "```bash\nexit 1\n```\n")
    assert run_page_examples(page, os.path.join(pkg_root, "fakepkg")) == []


def test_workdir_reused_and_preserved(pkg_root, tmp_path):
    page = _page(tmp_path, '```python\nassert 1 + 1 == 2\n```\n')
    workdir = str(tmp_path / "wd")
    results = run_page_examples(page, os.path.join(pkg_root, "fakepkg"),
                                workdir=workdir)
    assert results[0]["status"] == "passed"
    # caller-provided workdir is not cleaned up
    assert os.path.isdir(workdir)
