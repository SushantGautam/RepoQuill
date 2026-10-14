"""Regression tests: the Pi evidence pack must use the repository-root
path convention that the agent's read tools resolve against.

Historically the evidence file tree showed bare directory basenames
(`judges/`) and candidate files were package-relative
(`judges/compose.py`), while read_file resolves against the repo root —
so Pi agents on nested packages (e.g. SimpleAudit) wasted their whole
budget on "no such file" reads and never wrote the page.
"""

from __future__ import annotations

from repoquill.agents.contracts import EvidencePack, PageTask
from repoquill.agents.evidence import build_evidence_pack
from repoquill.agents.scheduler import _evidence_to_text
from repoquill.reference import get_file_tree


def _nested_pkg(tmp_path):
    root = tmp_path / "repo"
    pkg = root / "simpleaudit"
    (pkg / "judges").mkdir(parents=True)
    (pkg / "__init__.py").write_text("X = 1\n")
    (pkg / "judges" / "__init__.py").write_text("Y = 2\n")
    (pkg / "judges" / "compose.py").write_text("def compose():\n    pass\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_judges.py").write_text("def test_c(): pass\n")
    return root, pkg


def test_file_tree_root_relative_labels(tmp_path):
    root, pkg = _nested_pkg(tmp_path)
    tree = get_file_tree(str(pkg), str(root))
    assert "simpleaudit/" in tree
    assert "  simpleaudit/judges/" in tree
    assert "    simpleaudit/judges/compose.py" in tree
    # No bare, ambiguous directory label (line == 'judges/' after strip).
    bare = [ln.strip() for ln in tree.splitlines()]
    assert "judges/" not in bare


def test_file_tree_without_root_keeps_legacy_labels(tmp_path):
    root, pkg = _nested_pkg(tmp_path)
    tree = get_file_tree(str(pkg))
    assert "simpleaudit/" in tree
    assert "  judges/" in tree
    assert "    compose.py" in tree
    # Nesting is indented one level deeper than the package root.
    assert "\njudges/" not in tree


def test_file_tree_root_outside_pkg_ignored(tmp_path):
    root, pkg = _nested_pkg(tmp_path)
    other = tmp_path / "elsewhere"
    other.mkdir()
    tree = get_file_tree(str(pkg), str(other))
    assert "  judges/" in tree  # falls back to basename labels
    assert "    compose.py" in tree


def test_evidence_pack_tree_is_root_relative(tmp_path):
    root, pkg = _nested_pkg(tmp_path)
    task = PageTask(slug="custom-judges", title="Custom Judges",
                    description="d", out_path=str(tmp_path / "o.md"),
                    source_hints=["judges/compose.py"])
    pack = build_evidence_pack(task, str(pkg), str(root))
    assert "simpleaudit/judges/compose.py" in pack.file_tree
    assert "simpleaudit/judges/" in pack.file_tree


def test_evidence_text_relabels_candidate_files(tmp_path):
    root, pkg = _nested_pkg(tmp_path)
    pack = EvidencePack(
        file_tree="simpleaudit/\n  judges/\n",
        candidate_files=["judges/compose.py"],
        candidate_tests=["tests/test_judges.py"],
        api_surface="",
        coverage_checklist=[],
        readme_excerpt="",
    )
    text = _evidence_to_text(pack, pkg_prefix="simpleaudit")
    assert "- simpleaudit/judges/compose.py" in text
    assert "relative to the repository root" in text
    assert "package lives under 'simpleaudit/'" in text
    # Tests are already root-relative and must not be double-prefixed.
    assert "tests/test_judges.py" in text
    assert "- simpleaudit/tests/" not in text


def test_evidence_text_without_prefix_is_safe(tmp_path):
    pack = EvidencePack(
        file_tree="miniutil/\n",
        candidate_files=["textkit.py"],
        candidate_tests=[],
        api_surface="",
        coverage_checklist=[],
        readme_excerpt="",
    )
    text = _evidence_to_text(pack, pkg_prefix="")
    assert "- textkit.py" in text
    assert "relative to the repository root" in text


def test_evidence_text_includes_symbol_outlines(tmp_path):
    root, pkg = _nested_pkg(tmp_path)
    pack = EvidencePack(
        file_tree="simpleaudit/\n",
        candidate_files=["judges/compose.py"],
        candidate_tests=[],
        api_surface="",
        coverage_checklist=[],
        readme_excerpt="",
        symbol_outlines="simpleaudit/judges/compose.py:\n10: def compose():",
    )
    text = _evidence_to_text(pack, pkg_prefix="simpleaudit")
    assert "SYMBOL OUTLINES" in text
    assert "10: def compose():" in text
    # Packs without outlines (older shape) must not add the section.
    text2 = _evidence_to_text(
        EvidencePack(file_tree="x", candidate_files=[], candidate_tests=[],
                     api_surface="", coverage_checklist=[], readme_excerpt=""),
        pkg_prefix="")
    assert "SYMBOL OUTLINES" not in text2
