"""Fail-closed quality gate tests (repoquill.validation.gate)."""

from __future__ import annotations

import json
import os
import pathlib

import pytest

from repoquill.validation import (
    GateFinding,
    GateResult,
    check_page_imports,
    run_gate,
    run_page_examples,
)


INIT = 'VERSION = "1.0"\nfrom fakepkg.core import Widget\n'
CORE = '''\
class Widget:
    def __init__(self, label):
        self.label = label
'''
UTIL = 'def area(w, h):\n    return w * h\n'


GOOD_PAGE = '''\
# Good page

```python
from fakepkg import Widget
from fakepkg.util import area
w = Widget(label="x")
assert area(2, 3) == 6
```

Use the `Widget` class with the `VERSION` constant.
'''

BAD_IMPORT_PAGE = '''\
# Bad import

```python
from fakepkg import DoesNotExist
```
'''

BAD_SYMBOL_PAGE = '''\
# Bad symbol

Use the `PhantomClass` everywhere.
'''

FAILING_EXAMPLE_PAGE = '''\
# Failing example

```python
from fakepkg import Widget
assert Widget(label="x").label == "y"
```
'''


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "fakepkg").mkdir(parents=True)
    (root / "fakepkg" / "__init__.py").write_text(INIT, encoding="utf-8")
    (root / "fakepkg" / "core.py").write_text(CORE, encoding="utf-8")
    (root / "fakepkg" / "util.py").write_text(UTIL, encoding="utf-8")
    return root


def _guides(root, name, content):
    d = root / "guides"
    d.mkdir(exist_ok=True)
    p = d / name
    p.write_text(content, encoding="utf-8")
    return str(d)


def test_gate_passes_on_good_pages(repo):
    guides = _guides(repo, "good.md", GOOD_PAGE)
    result = run_gate(guides, str(repo / "fakepkg"))
    assert result.passed is True
    assert result.findings == []
    assert "import" in result.checks_run
    assert "symbol" in result.checks_run
    assert "example" in result.checks_skipped
    assert "PASSED" in result.summary()


def test_gate_fails_on_bad_import(repo):
    guides = _guides(repo, "bad.md", BAD_IMPORT_PAGE)
    result = run_gate(guides, str(repo / "fakepkg"))
    assert result.passed is False
    import_findings = [f for f in result.findings if f.check == "import"]
    assert len(import_findings) == 1
    assert "DoesNotExist" in import_findings[0].detail
    assert import_findings[0].page == "bad"


def test_gate_fails_on_bad_symbol(repo):
    guides = _guides(repo, "bad.md", BAD_SYMBOL_PAGE)
    result = run_gate(guides, str(repo / "fakepkg"))
    assert result.passed is False
    sym = [f for f in result.findings if f.check == "symbol"]
    assert len(sym) == 1
    assert "PhantomClass" in sym[0].detail


def test_gate_examples_off_by_default(repo):
    guides = _guides(repo, "fail.md", FAILING_EXAMPLE_PAGE)
    result = run_gate(guides, str(repo / "fakepkg"))
    assert result.passed is True
    assert "example" in result.checks_skipped


def test_gate_examples_opt_in_fails_on_failing_block(repo):
    guides = _guides(repo, "fail.md", FAILING_EXAMPLE_PAGE)
    result = run_gate(guides, str(repo / "fakepkg"),
                      run_examples=True, example_timeout=15)
    assert result.passed is False
    assert "example" in result.checks_run
    ex = [f for f in result.findings if f.check == "example"]
    assert len(ex) == 1
    assert "failed" in ex[0].detail
    assert "AssertionError" in ex[0].detail


def test_gate_examples_opt_in_passes_on_good_page(repo):
    guides = _guides(repo, "good.md", GOOD_PAGE)
    result = run_gate(guides, str(repo / "fakepkg"),
                      run_examples=True, example_timeout=15)
    assert result.passed is True


def test_gate_missing_guides_dir_fails_closed(repo):
    result = run_gate(str(repo / "no_such_dir"), str(repo / "fakepkg"))
    assert result.passed is False
    assert result.findings[0].check == "internal-error"
    assert "guides" in result.findings[0].detail


def test_gate_missing_pkg_path_fails_closed(repo, tmp_path):
    guides = _guides(repo, "good.md", GOOD_PAGE)
    result = run_gate(guides, str(repo / "no_pkg"))
    assert result.passed is False
    assert result.findings[0].check == "internal-error"


def test_gate_check_exception_fails_closed(repo, monkeypatch):
    import repoquill.validation.gate as gate_mod
    guides = _guides(repo, "good.md", GOOD_PAGE)

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(gate_mod, "check_page_imports", boom)
    result = run_gate(guides, str(repo / "fakepkg"))
    assert result.passed is False
    errs = [f for f in result.findings if f.check == "internal-error"]
    assert len(errs) == 1
    assert "boom" in errs[0].detail
    # the broken check is recorded as attempted, not silently skipped
    assert "import" in result.checks_run


def test_as_dict_json_round_trip(repo):
    guides = _guides(repo, "bad.md", BAD_IMPORT_PAGE)
    result = run_gate(guides, str(repo / "fakepkg"))
    data = result.as_dict()
    assert data["passed"] is False
    restored = json.loads(json.dumps(data))
    assert restored["passed"] is False
    assert restored["checks_run"] == result.checks_run
    assert restored["checks_skipped"] == result.checks_skipped
    assert restored["summary"] == result.summary()
    assert restored["findings"][0]["check"] == "import"
    assert restored["findings"][0]["detail"] == \
        result.findings[0].detail


def test_gate_finding_to_dict_shape():
    f = GateFinding(page="p", check="import", detail="d", line=7)
    d = f.to_dict()
    assert d == {"page": "p", "check": "import", "detail": "d", "line": 7}
    assert json.loads(json.dumps(d))["line"] == 7


def test_gate_result_construction_defaults():
    r = GateResult()
    assert r.passed is True
    assert r.findings == []
    assert "PASSED" in r.summary()


def test_public_api_reexports():
    import repoquill.validation as v
    assert v.run_gate is run_gate
    assert v.GateResult is GateResult
    assert v.GateFinding is GateFinding
    assert v.check_page_imports is check_page_imports
    assert v.run_page_examples is run_page_examples


def test_genericity_against_unrelated_package(tmp_path):
    """Sanity: the gate works against repoquill itself, not just the
    fake fixture package (no SimpleAudit-style hardcoding)."""
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    guides = tmp_path / "guides"
    guides.mkdir()
    (guides / "page.md").write_text(
        "```python\nimport repoquill\n"
        "import repoquill.verify\n```\n"
        "The `build_index` function exists.\n",
        encoding="utf-8")
    result = run_gate(str(guides), str(repo_root / "repoquill"))
    assert result.passed is True, [f.to_dict() for f in result.findings]
