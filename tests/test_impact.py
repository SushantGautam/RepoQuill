"""Tests for conservative AST-based change intelligence (core.impact /
core.dependencies).

Builds a tiny fake package (2-3 modules + ``__init__`` reexports) in
``tmp_path`` with guide pages that reference its API, then asserts the
affected-slug mapping is correct and conservative.
"""

from __future__ import annotations

import os

from repoquill.core.impact import (
    extract_api_surface,
    diff_surfaces,
    module_name_for_path,
)
from repoquill.core.dependencies import (
    page_symbols,
    build_page_dependencies,
    affected_slugs,
    diff_source_files,
)

# ---------------------------------------------------------------------------
# Fake package
# ---------------------------------------------------------------------------

INIT_OLD = "from .core import Engine\n"
INIT_NEW_REEXPORT = "from .core import Engine, helper\n"

CORE_OLD = """
class Engine:
    'Engine that runs things.'

    def __init__(self, size: int = 4):
        self.size = size

    def run(self, fast: bool = False):
        return self.size

def helper(x, y=10):
    return x + y
"""

CORE_RENAMED = CORE_OLD.replace("class Engine:", "class Motor:")

CORE_NO_HELPER = CORE_OLD.split("def helper")[0]

CORE_NEW_DEFAULT = CORE_OLD.replace("y=10", "y=20")

CORE_BROKEN = "def broken(:\n    this is not python\n"

UTILS_OLD = """
def utility(v):
    return v

def unrelated():
    pass
"""

UTILS_COMMENT = UTILS_OLD + "\n# an unrelated maintenance comment\n"

UTILS_NEW_FN = UTILS_OLD + """
def brand_new(name):
    return name
"""

PAGES = [
    {"slug": "engine", "title": "Engine", "source_files": ["pkg/core.py"]},
    {"slug": "helpers", "title": "Helpers", "source_files": ["pkg/core.py"]},
    {"slug": "pkg-api", "title": "Package API", "source_files": ["pkg/__init__.py"]},
    {"slug": "utils", "title": "Utils", "source_files": ["pkg/utils.py"]},
]

PAGE_MDS = {
    "engine.md": (
        "# Engine\n\n"
        "The `Engine` class runs things.\n\n"
        "```python\n"
        "from pkg.core import Engine\n\n"
        "e = Engine()\n"
        "e.run(fast=True)\n"
        "```\n\n"
        "See `Engine.run` for details.\n"
    ),
    "helpers.md": (
        "# Helpers\n\n"
        "The `helper` function adds numbers.\n\n"
        "```python\n"
        "from pkg.core import helper\n\n"
        "helper(1, 2)\n"
        "```\n"
    ),
    "pkg-api.md": (
        "# Package API\n\n"
        "Import from the top level:\n\n"
        "```python\n"
        "from pkg import Engine\n"
        "```\n"
    ),
    "utils.md": (
        "# Utils\n\n"
        "Use `utility` for identity.\n\n"
        "```python\n"
        "from pkg.utils import utility\n"
        "```\n"
    ),
}


def make_files(init=INIT_OLD, core=CORE_OLD, utils=UTILS_OLD) -> dict:
    files = {
        "pkg/__init__.py": init,
        "pkg/core.py": core,
        "pkg/utils.py": utils,
    }
    if utils is None:
        del files["pkg/utils.py"]
    return files


def write_guides(guides_dir: str, names=None) -> None:
    os.makedirs(guides_dir, exist_ok=True)
    for name, md in PAGE_MDS.items():
        if names is None or name in names:
            with open(os.path.join(guides_dir, name), "w") as f:
                f.write(md)


def impact(tmp_path, old_files, new_files):
    """Build deps from old (documented) state and compute affected slugs."""
    guides = str(tmp_path / "guides")
    write_guides(guides)
    old_surface = extract_api_surface(old_files)
    new_surface = extract_api_surface(new_files)
    # Symbol inventory for matching: what the docs were generated from.
    module_symbols = {}
    for mod, entry in old_surface.modules.items():
        syms = set(entry["functions"])
        for cls, cinfo in entry["classes"].items():
            syms.add(f"{mod}.{cls}")
            for m in cinfo["methods"]:
                syms.add(f"{mod}.{cls}.{m}")
        module_symbols[mod] = {s if "." in s else f"{mod}.{s}" for s in syms}
    deps = build_page_dependencies(PAGES, guides, module_symbols)
    diff = diff_surfaces(old_surface, new_surface)
    all_slugs = [p["slug"] for p in PAGES]
    return affected_slugs(diff, deps, all_slugs)


# ---------------------------------------------------------------------------
# Surface extraction
# ---------------------------------------------------------------------------

def test_module_name_for_path():
    assert module_name_for_path("pkg/foo.py") == "pkg.foo"
    assert module_name_for_path("pkg/__init__.py") == "pkg"
    assert module_name_for_path("foo.py") == "foo"
    assert module_name_for_path("pkg/sub/bar.py") == "pkg.sub.bar"


def test_extract_api_surface_records(tmp_path):
    surface = extract_api_surface(make_files())
    assert "pkg" in surface.modules
    assert "pkg.core" in surface.modules
    core = surface.modules["pkg.core"]
    assert "run" in core["classes"]["Engine"]["methods"]
    assert "helper" in core["functions"]
    # __init__ reexport
    assert "Engine" in surface.modules["pkg"]["reexports"]
    assert "pkg.core.Engine" in surface.modules["pkg"]["imports"]


def test_extract_api_surface_unparseable(tmp_path):
    surface = extract_api_surface(make_files(core=CORE_BROKEN))
    assert "pkg.core" in surface.errors
    # Other modules still extracted.
    assert "pkg.utils" in surface.modules


def test_page_symbols():
    syms = page_symbols(PAGE_MDS["engine.md"])
    assert "Engine" in syms
    assert "Engine.run" in syms
    assert "pkg.core" in syms


def test_identical_sources_produce_empty_diff(tmp_path):
    diff = diff_source_files(make_files(), make_files())
    assert diff.is_empty()
    assert diff.changed_symbols() == set()


# ---------------------------------------------------------------------------
# Affected-slug scenarios
# ---------------------------------------------------------------------------

def test_rename_class_affects_referencing_pages(tmp_path):
    affected = impact(tmp_path, make_files(), make_files(core=CORE_RENAMED))
    # Pages referencing the old name (Engine) must regenerate.
    assert "engine" in affected
    assert "pkg-api" in affected
    # Unrelated module pages must not be touched.
    assert "utils" not in affected
    # The other symbol in the same module was not referenced by `helpers`
    # beyond `helper` itself, and the rename explains the class change.
    assert "helpers" not in affected


def test_remove_function_affects_referencing_page(tmp_path):
    affected = impact(tmp_path, make_files(), make_files(core=CORE_NO_HELPER))
    assert "helpers" in affected
    # utils is an unrelated module: not affected.
    assert "utils" not in affected


def test_default_change_detected_and_affects_page(tmp_path):
    diff = diff_source_files(make_files(), make_files(core=CORE_NEW_DEFAULT))
    assert not diff.is_empty()
    assert any(
        c["module"] == "pkg.core" and c["name"] == "helper"
        and "y=10" in c["before"] and "y=20" in c["after"]
        for c in diff.signature_changes
    )
    affected = impact(tmp_path, make_files(), make_files(core=CORE_NEW_DEFAULT))
    assert "helpers" in affected
    assert "utils" not in affected


def test_added_function_referenced_by_no_page_affects_nothing(tmp_path):
    affected = impact(tmp_path, make_files(), make_files(utils=UTILS_NEW_FN))
    # Nothing on any page references `brand_new` -> no needless rewrites.
    assert affected == {}


def test_reexport_change_affects_package_importing_pages(tmp_path):
    old = make_files()
    new = make_files(init=INIT_NEW_REEXPORT)  # core.py untouched
    diff = diff_source_files(old, new)
    assert "pkg" in diff.reexport_changes
    assert diff.reexport_changes["pkg"]["added"] == ["helper"]

    affected = impact(tmp_path, old, new)
    # pkg-api imports from the package root; leaf file unchanged.
    assert "pkg-api" in affected
    # Pages that import the leaf module directly are unaffected.
    assert "engine" not in affected
    assert "utils" not in affected


def test_deleted_source_file_is_conservatively_affected(tmp_path):
    old = make_files()
    new = make_files(utils=None)
    affected = impact(tmp_path, old, new)
    assert "utils" in affected
    assert "engine" not in affected


def test_unparseable_file_marks_dependents_affected(tmp_path):
    old = make_files()
    new = make_files(core=CORE_BROKEN)
    affected = impact(tmp_path, old, new)
    assert "engine" in affected
    assert "helpers" in affected
    assert any(
        "unparseable" in reason
        for reasons in affected.values()
        for reason in reasons
    )
    assert "utils" not in affected


def test_unrelated_comment_change_affects_nothing(tmp_path):
    old = make_files()
    new = make_files(utils=UTILS_COMMENT)
    diff = diff_source_files(old, new)
    assert diff.is_empty()
    assert impact(tmp_path, old, new) == {}


def test_unknown_page_is_conservatively_affected(tmp_path):
    # A slug in the plan with no guide file on disk: unknown -> affected
    # whenever the diff is non-empty.
    old = make_files()
    new = make_files(core=CORE_NO_HELPER)
    guides = str(tmp_path / "guides")
    write_guides(guides, names=["utils.md"])
    old_s = extract_api_surface(old)
    new_s = extract_api_surface(new)
    module_symbols = {
        "pkg.core": {"pkg.core.Engine", "pkg.core.helper"},
        "pkg.utils": {"pkg.utils.utility"},
    }
    deps = build_page_dependencies(PAGES, guides, module_symbols)
    diff = diff_surfaces(old_s, new_s)
    slugs = [p["slug"] for p in PAGES] + ["mystery"]  # in plan, no page dict
    affected = affected_slugs(diff, deps, slugs)
    assert "engine" in affected    # module had a removal
    assert "utils" not in affected  # its module (pkg.utils) did not change
    assert "mystery" in affected   # no dependency record at all
    assert any("no dependency record" in r for r in affected["mystery"])


def test_diff_source_files_wrapper():
    diff = diff_source_files(make_files(), make_files(core=CORE_RENAMED))
    assert any(
        r["from"] == "Engine" and r["to"] == "Motor" for r in diff.renamed
    )
    # Renamed names still count as changed symbols (old name must
    # invalidate referencing pages).
    assert "pkg.core.Engine" in diff.changed_symbols()
