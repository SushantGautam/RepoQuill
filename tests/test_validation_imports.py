"""Static import-check tests (repoquill.validation.imports)."""

from __future__ import annotations

import os

import pytest

from repoquill.verify import build_index
from repoquill.validation.imports import check_page_imports


INIT = '''\
from .core import Widget
from .util import area

VERSION = "1.0"
_secret = "hidden"
'''

CORE = '''\
class Widget:
    def __init__(self, label):
        self.label = label

    def describe(self):
        return "Widget(" + self.label + ")"
'''

UTIL = '''\
def area(width, height):
    return width * height


def _hidden():
    return 42
'''


@pytest.fixture
def pkg(tmp_path):
    root = tmp_path / "fakepkg"
    root.mkdir()
    (root / "__init__.py").write_text(INIT, encoding="utf-8")
    (root / "core.py").write_text(CORE, encoding="utf-8")
    (root / "util.py").write_text(UTIL, encoding="utf-8")
    return str(root)


def _page(tmp_path, content):
    p = tmp_path / "page.md"
    p.write_text(content, encoding="utf-8")
    return str(p)


def test_valid_imports_no_findings(pkg, tmp_path):
    page = _page(tmp_path, '''\
# Guide

```python
import os
from fakepkg import Widget
from fakepkg.util import area
import fakepkg.core

w = Widget(label="x")
```
''')
    assert check_page_imports(page, build_index(pkg)) == []


def test_missing_symbol_flagged(pkg, tmp_path):
    page = _page(tmp_path, '```python\nfrom fakepkg import DoesNotExist\n```\n')
    findings = check_page_imports(page, build_index(pkg))
    assert len(findings) == 1
    f = findings[0]
    assert f["check"] == "import"
    assert f["page"] == "page"
    assert "DoesNotExist" in f["detail"]
    # 'from fakepkg import DoesNotExist' is line 2 of the file
    assert f["line"] == 2


def test_missing_module_flagged(pkg, tmp_path):
    page = _page(tmp_path, '```python\nimport fakepkg.nonexistent_mod\n```\n')
    findings = check_page_imports(page, build_index(pkg))
    assert len(findings) == 1
    assert "nonexistent_mod" in findings[0]["detail"]


def test_private_name_flagged_not_exported(pkg, tmp_path):
    page = _page(tmp_path,
                 '```python\nfrom fakepkg.util import _hidden\n```\n')
    findings = check_page_imports(page, build_index(pkg))
    assert len(findings) == 1
    assert "_hidden" in findings[0]["detail"]
    assert "not exported" in findings[0]["detail"]


def test_third_party_missing_flagged(pkg, tmp_path):
    page = _page(tmp_path,
                 "```python\nimport definitely_not_a_real_pkg_xyz_123\n```\n")
    findings = check_page_imports(page, build_index(pkg))
    assert len(findings) == 1
    assert "definitely_not_a_real_pkg_xyz_123" in findings[0]["detail"]


def test_alias_and_multiline_from_import(pkg, tmp_path):
    page = _page(tmp_path, '''\
```python
from fakepkg.util import (
    area,
    does_not_exist,
)
from fakepkg import Widget as W
```
''')
    findings = check_page_imports(page, build_index(pkg))
    assert len(findings) == 1
    assert "does_not_exist" in findings[0]["detail"]
    # statement starts at line 2 of the page
    assert findings[0]["line"] == 2


def test_non_python_blocks_ignored(pkg, tmp_path):
    page = _page(tmp_path, '''\
```bash
from fakepkg import DoesNotExist
```
''')
    assert check_page_imports(page, build_index(pkg)) == []
