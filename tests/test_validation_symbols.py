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


# --------------------------------------------------------------------------- #
# Regression: pydantic-style fields, class attributes, and parenthesized
# imports must not be flagged as invented symbols (confirmed false-positive
# mode from the cross-repo evaluation).
# --------------------------------------------------------------------------- #

PYD = '''\
from dataclasses import dataclass, field
from typing import List


@dataclass
class JudgeMeta:
    """Typed metadata (pydantic-style fields)."""

    name: str
    version: int = 1
    tags: List[str] = field(default_factory=list)

    DEFAULT_WEIGHT = 0.5

    def summary(self):
        return self.name
'''


@pytest.fixture
def pyd_idx(tmp_path):
    root = tmp_path / "metapkg"
    root.mkdir()
    (root / "__init__.py").write_text("", encoding="utf-8")
    (root / "pyd.py").write_text(PYD, encoding="utf-8")
    return build_index(str(root))


def test_typed_fields_and_class_attributes_indexed(pyd_idx):
    assert {"name", "version", "tags", "DEFAULT_WEIGHT"} <= pyd_idx.attributes


def test_pydantic_style_page_no_false_positives(pyd_idx, tmp_path):
    page = _page(
        tmp_path,
        "A `JudgeMeta` carries the `name`, `version` and `tags` fields, "
        "with `DEFAULT_WEIGHT` as the default.\n\n"
        "```python\n"
        "from metapkg.pyd import (\n"
        "    JudgeMeta,\n"
        ")\n"
        "\n"
        "meta = JudgeMeta(name=\"safety\")\n"
        "print(meta.summary())\n"
        "```\n")
    assert check_page_symbols(page, pyd_idx) == []


def test_method_name_in_backticks_not_flagged(pyd_idx, tmp_path):
    page = _page(tmp_path, "Call `summary` on the metadata object.\n")
    assert check_page_symbols(page, pyd_idx) == []


def test_paren_import_fence_artifacts_not_flagged(pyd_idx, tmp_path):
    """Multi-line ``import (`` fences must not yield ``(JudgeMeta``-style
    fake import symbols."""
    page = _page(
        tmp_path,
        "```python\n"
        "from metapkg.pyd import (\n"
        "    JudgeMeta,\n"
        ")\n"
        "```\n")
    assert check_page_symbols(page, pyd_idx) == []


def test_invented_names_still_flagged_after_attribute_index(pyd_idx,
                                                            tmp_path):
    """The attribute/method allow-set must not swallow real hallucinations:
    invented field-like and class-like names are still reported."""
    page = _page(
        tmp_path,
        "Set the `confidence_bogus` field on the `InventedThing` model.\n")
    findings = check_page_symbols(page, pyd_idx)
    symbols = {f["detail"] for f in findings}
    assert len(findings) == 2
    assert any("confidence_bogus" in s for s in symbols)
    assert any("InventedThing" in s for s in symbols)


# --------------------------------------------------------------------------- #
# Regression (SimpleAudit baseline run-3): module-level constants and type
# aliases, keyword-only parameters, docstring-documented names, JSON
# literals, external imports/libraries — all were flagged as invented
# symbols although every one of them exists in the source (or is
# legitimately out of the package's scope). The hallucination checks must
# stay intact (see the final test).
# --------------------------------------------------------------------------- #

RUN3 = '''\
from typing import Callable, Dict, Tuple

# ALL_CAPS module constant via AnnAssign (was missed).
SEVERITY_SCHEMA: Dict[str, str] = {"low": "1"}

# Capitalized module-level type alias (was missed).
Transform = Callable[[int], int]

SUPPORTED_LANGUAGES: Tuple[str, ...] = ("English",)


def find_span(
    span: str,
    texts,
    *,
    min_chars: int = 3,
) -> int:
    """Docs quote ``temperature`` here and a mis-spelled ``acepted`` key."""
    if len(span) < min_chars:
        return -1
    return 0


class Auditor:
    def __init__(
        self,
        *args,
        correctness_judge: str = "checklist",
        **kwargs,
    ) -> None:
        # instance attribute assigned in __init__ (kwonly param above is
        # the API surface docs reference).
        self.correctness_judge = correctness_judge
'''


@pytest.fixture
def run3_idx(tmp_path):
    root = tmp_path / "auditpkg"
    root.mkdir()
    (root / "__init__.py").write_text("", encoding="utf-8")
    (root / "engine.py").write_text(RUN3, encoding="utf-8")
    return build_index(str(root))


def test_run3_module_constants_type_alias_kwonly_docstrings_indexed(run3_idx):
    assert "SEVERITY_SCHEMA" in run3_idx.constants
    assert "SUPPORTED_LANGUAGES" in run3_idx.constants
    assert "Transform" in run3_idx.module_symbols
    assert "min_chars" in run3_idx.function_params
    assert "correctness_judge" in run3_idx.function_params
    assert {"temperature", "acepted"} <= run3_idx.docstring_names


def test_run3_page_names_no_false_positives(run3_idx, tmp_path):
    """The exact run-3 finding shapes must pass: module constants, the
    type alias, kwonly params, docstring-documented names, JSON literals
    and the placeholder name."""
    page = _page(
        tmp_path,
        "Configure `SEVERITY_SCHEMA` and pick one of `SUPPORTED_LANGUAGES`.\n"
        "Maps use the `Transform` type; pass `min_chars` and set "
        "`correctness_judge` on the `Auditor`.\n\n"
        "The sampler never sets `temperature`; JSON answers use `null`, "
        "and `_` marks a placeholder. A mis-spelled `acepted` key raises.\n"
    )
    assert check_page_symbols(page, run3_idx) == []


def test_run3_external_imports_and_libraries_out_of_scope(run3_idx, tmp_path):
    """Stdlib/third-party imports and third-party library names in
    backticks are out of the documented package's scope (tracing page:
    `import asyncio`, `import base64`, plotting page: `matplotlib`)."""
    page = _page(
        tmp_path,
        "```python\n"
        "import asyncio\n"
        "import base64\n"
        "```\n\n"
        "Charts use `matplotlib` when available.\n"
    )
    # Stdlib imports (asyncio, base64) are out of the documented package's
    # scope, and `matplotlib` is a standard third-party library (in the
    # ecosystem-tooling allowlist), so none of these are invented package
    # APIs regardless of whether matplotlib happens to be installed here.
    assert check_page_symbols(page, run3_idx) == []


def test_run3_real_hallucinations_still_flagged(run3_idx, tmp_path):
    """Nothing above may weaken the core check: invented constant-, class-
    and function-shaped names, and invented imports of the documented
    package itself, are still reported."""
    page = _page(
        tmp_path,
        "Set `BOLT_SEVERITY_SCHEMA` on the `InventedAuditor` via "
        "`compute_severity()`.\n\n"
        "```python\n"
        "from auditpkg.engine import NotARealSymbol\n"
        "```\n"
    )
    findings = {f["detail"] for f in check_page_symbols(page, run3_idx)}
    assert any("BOLT_SEVERITY_SCHEMA" in d for d in findings)
    assert any("InventedAuditor" in d for d in findings)
    assert any("NotARealSymbol" in d for d in findings)


# --------------------------------------------------------------------------- #
# Regression: names that exist ANYWHERE in the package source tree (code,
# docstrings, comments) are ground truth — sibling-module constants and
# external-protocol names the code documents must not be flagged.
# --------------------------------------------------------------------------- #

TREE = '''\
def run_checks(results):
    # The schema dict lives in a sibling module (schemas.py).
    from .schemas import SEVERITY_RESPONSE_SCHEMA
    severity = results.get("severity")
    if severity not in SEVERITY_RESPONSE_SCHEMA:
        raise ValueError("bad severity: " + str(severity))
    return severity
'''


@pytest.fixture
def tree_idx(tmp_path):
    root = tmp_path / "treepkg"
    root.mkdir()
    (root / "__init__.py").write_text(
        'SEVERITY_RESPONSE_SCHEMA = {"low": 1}\n', encoding="utf-8")
    (root / "engine.py").write_text(TREE, encoding="utf-8")
    return build_index(str(root))


def test_names_anywhere_in_source_tree_are_ground_truth(tree_idx, tmp_path):
    page = _page(
        tmp_path,
        "Results use `SEVERITY_RESPONSE_SCHEMA` for grading, and the "
        "engine reads the `severity` field.\n")
    assert check_page_symbols(page, tree_idx) == []


def test_names_nowhere_in_source_tree_still_flagged(tree_idx, tmp_path):
    page = _page(
        tmp_path,
        "Grading uses the `BOLT_SEVERITY_RESPONSE_SCHEMA` table and the "
        "unknown `severity`-like knob `calibration_floor`.\n")
    findings = {f["detail"] for f in check_page_symbols(page, tree_idx)}
    assert any("BOLT_SEVERITY_RESPONSE_SCHEMA" in d for d in findings)
    assert any("calibration_floor" in d for d in findings)


# ---------------------------------------------------------------------------
# Out-of-scope names: a language keyword, standard ecosystem tooling, a real
# test-suite helper, and a declared dependency are NOT hallucinated package
# APIs. These were confirmed false-positive classes from the SimpleAudit Pi
# evaluation (a page quoting `in`, an offline example using `FakeClient`, and
# an installation page referencing the `grpcio` / `ruff` deps). The core
# hallucination check must still catch names that exist nowhere in the repo,
# its tests, or its declared stack.
# ---------------------------------------------------------------------------


@pytest.fixture
def idx_with_tests(tmp_path):
    """A package with a sibling test suite + declared dependencies."""
    root = tmp_path / "fakepkg"
    root.mkdir()
    (root / "__init__.py").write_text(INIT, encoding="utf-8")
    (root / "core.py").write_text(CORE, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "fakes.py").write_text(
        "class FakeClient:\n"
        "    def __call__(self, *a, **k):\n"
        "        pass\n"
        "class ScriptedClient:\n"
        "    pass\n"
        "def make_auditor(target, judge):\n"
        "    return None\n"
        "def fixed_target(text):\n"
        "    return FakeClient()\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "fakepkg"\nversion = "0.0.0"\n'
        'dependencies = ["mycustomdep>=1.0", "grpcio>=1.60"]\n'
        "[project.optional-dependencies]\n"
        'tracing = ["otherdep>=2"]\n',
        encoding="utf-8")
    return build_index(str(root))


def test_python_keyword_in_backticks_not_flagged(idx, tmp_path):
    page = _page(tmp_path,
                 "Iterate with `for`, test membership with `in`, and `await` "
                 "inside an `async` function.\n")
    assert check_page_symbols(page, idx) == []


def test_standard_tooling_names_not_flagged(idx, tmp_path):
    page = _page(tmp_path,
                 "Lint with `ruff`, install with `uv` or `pip`, test with "
                 "`pytest`.\n")
    assert check_page_symbols(page, idx) == []


def test_real_test_helpers_not_flagged(idx_with_tests, tmp_path):
    page = _page(tmp_path,
                 "Offline audits use `FakeClient`, `ScriptedClient` and the "
                 "`make_auditor` / `fixed_target` test helpers.\n")
    assert check_page_symbols(page, idx_with_tests) == []


def test_declared_dependencies_and_extras_not_flagged(idx_with_tests, tmp_path):
    page = _page(tmp_path,
                 "Install the `tracing` extra to enable `mycustomdep` and "
                 "`otherdep`; `grpcio` is required for the gRPC receiver.\n")
    assert check_page_symbols(page, idx_with_tests) == []


def test_invented_name_outside_repo_tests_and_deps_still_flagged(
        idx_with_tests, tmp_path):
    page = _page(tmp_path,
                 "Configure the `BogusHelper` client and the "
                 "`calibration_floor` knob with `InventedGadget`.\n")
    findings = {f["detail"] for f in check_page_symbols(page, idx_with_tests)}
    assert any("BogusHelper" in d for d in findings)
    assert any("calibration_floor" in d for d in findings)
    assert any("InventedGadget" in d for d in findings)


def test_single_letter_placeholders_not_flagged(idx, tmp_path):
    # Single uppercase letters used as symbols in a worked example (the
    # custom-judges page scored with `S`, `R`, `V`) are placeholders, not
    # invented ALL_CAPS constants.
    page = _page(tmp_path,
                 "Score the response as `S`, with `R` for rationale and "
                 "`V` for verdict; loop over `x`.\n")
    assert check_page_symbols(page, idx) == []


def test_credential_envvars_not_flagged(idx, tmp_path):
    # Standard LLM-provider env vars in an installation guide are env-var
    # references, not package constants.
    page = _page(tmp_path,
                 "Set `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` and, for "
                 "self-hosting, `HUGGINGFACE_TOKEN`.\n")
    assert check_page_symbols(page, idx) == []


def test_real_multiword_constant_still_flagged(idx, tmp_path):
    # A multi-word ALL_CAPS name that is not a credential env-var and not in
    # the package is still flagged (the env-var rule must not over-broaden).
    page = _page(tmp_path, "Configure the `MAX_RETRIES_BUDGET` constant.\n")
    findings = check_page_symbols(page, idx)
    assert any("MAX_RETRIES_BUDGET" in f["detail"] for f in findings)
