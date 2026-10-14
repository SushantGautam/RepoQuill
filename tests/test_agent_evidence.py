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
    assert "total" in checklist
    assert "_private_helper" not in checklist
    assert "_internal" not in checklist
    assert not any(n.startswith("_") for n in checklist)
    assert checklist == sorted(checklist)


def test_task_checklist_overrides(pkg_root):
    pkg_path = str(pkg_root / "pkg")
    task = _task(coverage_checklist=["Widget"])
    pack = build_evidence_pack(task, pkg_path, str(pkg_root))
    assert pack.coverage_checklist == ["Widget"]
