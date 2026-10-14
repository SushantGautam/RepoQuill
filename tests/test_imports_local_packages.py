"""Regression: a source repo's own top-level packages (e.g. its ``tests``
package) must not be flagged as missing third-party imports by the quality
gate. Previously ``from tests.fakes import ...`` produced a false
``module 'tests' not found (third-party import ...)`` finding, which
silently dropped otherwise-valid guide pages from the published nav.
"""
import os
import textwrap

from repoquill.validation import run_gate
from repoquill.validation.imports import _local_package_tops


def _setup(tmp_path):
    src = tmp_path / "src"
    (src / "mymod").mkdir(parents=True)
    (src / "mymod" / "__init__.py").write_text("VALUE = 1\n")
    (src / "tests").mkdir(parents=True)
    (src / "tests" / "__init__.py").write_text("")
    (src / "tests" / "fakes.py").write_text("class FakeClient:\n    pass\n")
    (src / "pyproject.toml").write_text("[project]\nname = 'm'\n")
    guides = tmp_path / "guides"
    guides.mkdir()
    page = textwrap.dedent(
        """\
        # Test

        ```python
        from mymod import VALUE
        from tests.fakes import FakeClient
        from not_a_real_third_party import X
        ```
        """
    )
    (guides / "test.md").write_text(page)
    return str(src / "mymod"), str(guides)


def test_source_local_tests_package_not_flagged(tmp_path):
    pkg_path, guides = _setup(tmp_path)
    result = run_gate(guides, pkg_path)
    details = " | ".join(f.detail for f in result.findings
                         if f.check == "import")
    # Documented-package symbol resolves fine.
    assert "VALUE" not in details
    # The repo's own tests package is in-scope, not a missing library.
    assert "tests" not in details
    # A genuine unknown third-party import is still flagged (fail closed).
    assert "not_a_real_third_party" in details


def test_local_package_tops_detects_sibling_packages():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "src")
        os.makedirs(os.path.join(src, "mymod"))
        open(os.path.join(src, "mymod", "__init__.py"), "w").close()
        os.makedirs(os.path.join(src, "tests"))
        open(os.path.join(src, "tests", "fakes.py"), "w").close()
        open(os.path.join(src, "pyproject.toml"), "w").close()
        tops = _local_package_tops(os.path.join(src, "mymod"))
    assert "tests" in tops
    assert "mymod" in tops


def test_local_package_tops_src_layout():
    """Root detection walks up past a src/ layout to the project root."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root = os.path.join(d, "repo")
        os.makedirs(os.path.join(root, "src", "mymod"))
        open(os.path.join(root, "src", "mymod", "__init__.py"), "w").close()
        os.makedirs(os.path.join(root, "tests"))
        open(os.path.join(root, "tests", "fakes.py"), "w").close()
        open(os.path.join(root, "pyproject.toml"), "w").close()
        tops = _local_package_tops(os.path.join(root, "src", "mymod"))
    assert "tests" in tops
