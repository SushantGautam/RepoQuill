"""Tests for repoquill.agents.evidence (deterministic evidence discovery)."""
import pytest

from repoquill.agents.contracts import EvidencePack, PageTask
from repoquill.agents.evidence import (
    build_evidence_pack,
    candidate_source_files,
    candidate_tests,
    coverage_checklist,
)


ALPHA_PY = '''
class Widget:
    "A widget."

    def __init__(self, size=1):
        self.size = size

    def spin(self):
        "Spin the widget."
        return self.size * 2


def make_widget(size=1):
    "Create a widget."
    return Widget(size)


def _private_helper():
    "Not public."
    return 0
'''

BETA_PY = '''
def total(values):
    "Add values."
    return sum(values)


def _internal():
    return 1
'''


@pytest.fixture
def pkg_root(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from .alpha import Widget\n")
    (pkg / "alpha.py").write_text(ALPHA_PY)
    (pkg / "beta.py").write_text(BETA_PY)
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_alpha.py").write_text(
        "from pkg.alpha import make_widget\n\n"
        "def test_spin():\n    assert make_widget(2).spin() == 4\n"
    )
    (tmp_path / "README.md").write_text("# Demo Package\n\nA demo package.\n")
    return tmp_path


def _task(**kw):
    defaults = dict(slug="alpha-widget", title="Alpha Widget", description="")
    defaults.update(kw)
    return PageTask(**defaults)


def test_build_evidence_pack(pkg_root):
    pkg_path = str(pkg_root / "pkg")
    task = _task()
    pack = build_evidence_pack(task, pkg_path, str(pkg_root))

    assert isinstance(pack, EvidencePack)
    assert pack.file_tree and "alpha.py" in pack.file_tree
    assert "Widget" in pack.api_surface
    assert "Widget" in pack.coverage_checklist
    assert "make_widget" in pack.coverage_checklist
    assert not any(n.startswith("_") for n in pack.coverage_checklist)
    assert pack.candidate_files  # heuristic found something
    assert "tests/test_alpha.py" in pack.candidate_tests
    assert pack.readme_excerpt.startswith("# Demo Package")


def test_candidate_source_files_hints(pkg_root):
    pkg_path = str(pkg_root / "pkg")
    task = _task(source_hints=["alpha.py", "missing.py"])
    assert candidate_source_files(task, pkg_path) == ["alpha.py"]


def test_candidate_source_files_fallback(pkg_root):
    pkg_path = str(pkg_root / "pkg")
    task = _task(slug="alpha", title="Alpha")
    files = candidate_source_files(task, pkg_path)
    assert "alpha.py" in files
    assert len(files) <= 12

    # No topical match at all -> top-level modules fallback
    generic = _task(slug="zzz-qqq", title="Unrelated Zzz")
    fb = candidate_source_files(generic, pkg_path)
    assert "alpha.py" in fb and "beta.py" in fb


def test_candidate_tests(pkg_root):
    task = _task()
    tests = candidate_tests(task, str(pkg_root))
    assert "tests/test_alpha.py" in tests
    # The matching file (shares "alpha") ranks first
    assert tests[0] == "tests/test_alpha.py"
    assert all(t.startswith("tests/") for t in tests)
    assert len(tests) <= 8


def test_coverage_checklist_public_only(pkg_root):
    task = _task()
    checklist = coverage_checklist(task, str(pkg_root / "pkg"))
    assert "Widget" in checklist
    assert "make_widget" in checklist
    assert "_private_helper" not in checklist
    assert "_internal" not in checklist
    assert not any(n.startswith("_") for n in checklist)
    assert checklist == sorted(checklist)


def test_coverage_checklist_scoped_to_page_files(pkg_root):
    """Regression: the checklist must be scoped to the page's candidate
    files, not the whole package (a page covering alpha must not be
    required to mention beta's symbols)."""
    pkg_path = str(pkg_root / "pkg")
    scoped = _task(slug="alpha-widget", source_hints=["alpha.py"])
    assert "total" not in coverage_checklist(scoped, pkg_path)

    beta = _task(slug="beta-total", source_hints=["beta.py"])
    assert "total" in coverage_checklist(beta, pkg_path)
    assert "Widget" not in coverage_checklist(beta, pkg_path)


def test_task_checklist_overrides(pkg_root):
    pkg_path = str(pkg_root / "pkg")
    task = _task(coverage_checklist=["Widget"])
    pack = build_evidence_pack(task, pkg_path, str(pkg_root))
    assert pack.coverage_checklist == ["Widget"]


# --------------------------------------------------------------------------- #
# Symbol outlines (outline-first: shape before deep reads)
# --------------------------------------------------------------------------- #
def test_symbol_outlines_lists_symbols_with_line_numbers(pkg_root):
    from repoquill.agents.evidence import symbol_outlines
    pkg_path = str(pkg_root / "pkg")
    task = _task(source_hints=["alpha.py"])
    outlines = symbol_outlines(task, pkg_path)
    assert "alpha.py:" in outlines
    assert "class Widget" in outlines
    assert "def spin" in outlines
    assert "def make_widget(size)" in outlines
    # Line numbers are real: 'class Widget' is on line 2 of ALPHA_PY.
    assert "2: class Widget" in outlines
    # A file with no top-level defs/classes produces no block.
    empty = _task(source_hints=["beta.py"])
    assert "def total" in symbol_outlines(empty, pkg_path)


def test_symbol_outlines_skip_unparseable_files(tmp_path):
    from repoquill.agents.evidence import symbol_outlines
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "broken.py").write_text("class Broken(:\n")
    (pkg / "good.py").write_text("def ok():\n    return 1\n")
    task = _task(source_hints=["broken.py", "good.py"])
    outlines = symbol_outlines(task, str(pkg))
    assert "good.py:" in outlines
    assert "def ok()" in outlines
    assert "broken.py" not in outlines


def test_evidence_pack_carries_symbol_outlines(pkg_root):
    pkg_path = str(pkg_root / "pkg")
    task = _task(source_hints=["alpha.py"])
    pack = build_evidence_pack(task, pkg_path, str(pkg_root))
    assert pack.symbol_outlines
    assert "class Widget" in pack.symbol_outlines
