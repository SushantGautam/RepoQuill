"""Tests for build_skill_md — P0-3: the generated SKILL.md must be
evidence-derived and domain-generic.

Fixtures are two synthetic, unrelated packages (a date-formatting
library and a queue library) built with the real ``load_config`` path.
The skill must contain only project name, documented module names,
page pointers, and generic usage guidance — no SimpleAudit/auditing
language, no invented capabilities, and no leakage between projects.
"""

from __future__ import annotations

import os

from repoquill.config import load_config
from repoquill.site import build_skill_md

# Substrings that must never appear in a generated SKILL.md (case-insensitive).
LEAK_TERMS = [
    "audit",
    "fraud",
    "judge",
    "verdict",
    "scenario",
    "risk score",
    "simpleaudit",
    "litigant",
    "evidence review",
]


def _make_package(root, pkg_name, modules):
    """Create a minimal Python package with one docstring per module."""
    pkg_dir = os.path.join(str(root), pkg_name)
    os.makedirs(pkg_dir, exist_ok=True)
    with open(os.path.join(pkg_dir, "__init__.py"), "w") as f:
        f.write(f'"""{pkg_name}: minimal synthetic test package."""\n')
    for mod, doc in modules:
        with open(os.path.join(pkg_dir, f"{mod}.py"), "w") as f:
            f.write(f'"""{doc}"""\n\n\n')
    return pkg_dir


def _build_cfg(tmp_path, project_name, modules):
    """Write repoquill.yml + package sources, then load via the real path."""
    _make_package(tmp_path, project_name, modules)
    yml = f"project_name: {project_name}\npackage_dir: {project_name}\n"
    cfg_path = os.path.join(str(tmp_path), "repoquill.yml")
    with open(cfg_path, "w") as f:
        f.write(yml)
    return load_config(cfg_path)


def _datefmt(tmp_path):
    cfg = _build_cfg(
        tmp_path / "datefmt_repo",
        "datefmt",
        [
            ("parser", "Parse date strings into normalized components."),
            ("formatter", "Format date components for display."),
        ],
    )
    return cfg, ["datefmt.parser", "datefmt.formatter"]


def _qstore(tmp_path):
    cfg = _build_cfg(
        tmp_path / "qstore_repo",
        "qstore",
        [
            ("queue", "FIFO queue with persistent backends."),
            ("priority", "Priority queue ordered by task rank."),
        ],
    )
    return cfg, ["qstore.queue", "qstore.priority"]


def _assert_no_domain_leak(content):
    low = content.lower()
    for term in LEAK_TERMS:
        assert term not in low, f"SKILL.md contains domain-leaked term: {term!r}"


def test_datefmt_contains_name_and_modules(tmp_path):
    cfg, mods = _datefmt(tmp_path)
    content = build_skill_md(cfg, mods)
    assert "datefmt" in content
    assert "datefmt.parser" in content
    assert "datefmt.formatter" in content
    # Docstring-derived description surfaces (evidence, not invention).
    assert "Parse date strings" in content
    _assert_no_domain_leak(content)


def test_qstore_contains_name_and_modules(tmp_path):
    cfg, mods = _qstore(tmp_path)
    content = build_skill_md(cfg, mods)
    assert "qstore" in content
    assert "qstore.queue" in content
    assert "qstore.priority" in content
    assert "Priority queue" in content
    _assert_no_domain_leak(content)


def test_no_cross_project_leakage(tmp_path):
    datefmt_content = build_skill_md(*_datefmt(tmp_path))
    qstore_content = build_skill_md(*_qstore(tmp_path))
    for term in ("qstore", "priority"):
        assert term not in datefmt_content.lower(), f"datefmt SKILL.md leaks {term!r}"
    for term in ("datefmt", "formatter"):
        assert term not in qstore_content.lower(), f"qstore SKILL.md leaks {term!r}"


def test_deterministic_output(tmp_path):
    cfg, mods = _datefmt(tmp_path)
    assert build_skill_md(cfg, mods) == build_skill_md(cfg, mods)
    cfg2, mods2 = _qstore(tmp_path)
    assert build_skill_md(cfg2, mods2) == build_skill_md(cfg2, mods2)


def test_page_pointers_and_generic_guidance(tmp_path):
    cfg, mods = _datefmt(tmp_path)
    content = build_skill_md(cfg, mods)
    # Pointer section: API reference and guide locations derived from cfg.
    assert "API reference pages" in content
    assert "reference/" in content
    # Generic how-to-use guidance present.
    assert "Never invent APIs" in content
    # Environment facts come from the config.
    assert "datefmt_repo" in content  # root/package path evidence


def test_neutral_purpose_fallback_when_no_tagline(tmp_path):
    cfg, mods = _datefmt(tmp_path)
    content = build_skill_md(cfg, mods)
    # No tagline/description in the fixture config → neutral one-liner,
    # and no invented purpose claims.
    assert "is the package documented in this repository" in content


def test_config_tagline_used_as_purpose(tmp_path):
    cfg, mods = _datefmt(tmp_path)
    cfg.index = {"tagline": "Format and parse dates across calendars."}
    content = build_skill_md(cfg, mods)
    assert "Format and parse dates across calendars." in content
