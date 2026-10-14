"""Structured symbol-check tests (repoquill.validation.symbols)."""

from __future__ import annotations

import pytest

from repoquill.verify import build_index
from repoquill.validation.symbols import check_page_symbols


INIT = '''\
VERSION = "1.0"
'''

CORE = '''\
class Widget:
    def __init__(self, label):
        self.label = label
'''

UTIL = '''\
def area(width, height):
    return width * height
'''


@pytest.fixture
def idx(tmp_path):
    root = tmp_path / "fakepkg"
    root.mkdir()
    (root / "__init__.py").write_text(INIT, encoding="utf-8")
    (root / "core.py").write_text(CORE, encoding="utf-8")
    (root / "util.py").write_text(UTIL, encoding="utf-8")
    return build_index(str(root))


def _page(tmp_path, content):
    p = tmp_path / "page.md"
    p.write_text(content, encoding="utf-8")
    return str(p)


def test_valid_symbols_no_findings(idx, tmp_path):
    page = _page(tmp_path,
                 "The `Widget` class and `area` function expose `VERSION`.\n")
    assert check_page_symbols(page, idx) == []


def test_nonexistent_backtick_symbol_flagged(idx, tmp_path):
    page = _page(tmp_path,
                 "See the `DoesNotExist` class for details.\n")
    findings = check_page_symbols(page, idx)
    assert len(findings) == 1
    f = findings[0]
    assert f["check"] == "symbol"
    assert f["page"] == "page"
    assert "DoesNotExist" in f["detail"]
    assert f["line"] == 1


def test_nonexistent_constant_flagged(idx, tmp_path):
    page = _page(tmp_path, "Set the `MAX_RETRY_COUNT` parameter.\n")
    findings = check_page_symbols(page, idx)
    assert len(findings) == 1
    assert "MAX_RETRY_COUNT" in findings[0]["detail"]
