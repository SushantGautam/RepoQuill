"""Config loading for RepoQuill.

Loads ``repoquill.yml`` from the consuming repository and exposes a
normalized :class:`RepoQuillConfig` with all derived paths and values.

The config file is the single source of truth for everything
project-specific: package name, site identity, LLM provider, narrative
sections, index content, and build options.

Config file location:
    ``repoquill.yml`` in the current working directory (the repo root),
    or the path given by the ``--config`` CLI flag / ``REPOQUILL_CONFIG``
    env var.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class LLMConfig:
    """LLM provider settings (LiteLLM-backed)."""

    provider: str = "openai"
    model: str = "gpt-4o"
    api_key_env: str = "OPENAI_API_KEY"
    base_url: Optional[str] = None
    rag: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RepoQuillConfig:
    """Normalized RepoQuill configuration with derived paths."""

    # Raw config dict (for advanced access)
    raw: Dict[str, Any] = field(default_factory=dict)

    # Project identity
    project_name: str = "Project"

    # Package discovery
    package_dir: str = ""
    root: str = ""

    # Source repo (for docs-only repos where source lives elsewhere)
    source_repo: str = ""
    source_ref: str = ""

    # LLM
    llm: LLMConfig = field(default_factory=LLMConfig)

    # Site identity
    site: Dict[str, Any] = field(default_factory=dict)

    # Narrative sections (Layer 2)
    narrative_sections: List[Dict[str, Any]] = field(default_factory=list)

    # Index page content
    index: Dict[str, Any] = field(default_factory=dict)

    # Build options
    build: Dict[str, Any] = field(default_factory=dict)

    # Theme / plugins / markdown extensions (passed through to mkdocs.yml)
    theme: Dict[str, Any] = field(default_factory=dict)
    plugins: List[Dict[str, Any]] = field(default_factory=list)
    markdown_extensions: List[str] = field(default_factory=list)

    # --- Derived paths (set by load_config) ---
    config_dir: str = ""
    site_src: str = ""
    out_guides: str = ""
    ref_dir: str = ""
    pkg_path: str = ""
    plan_file: str = ""

    @property
    def site_name(self) -> str:
        return self.site.get("name", self.project_name)

    @property
    def site_url(self) -> str:
        return self.site.get("url", "")

    @property
    def repo_url(self) -> str:
        return self.site.get("repo_url", "")

    @property
    def repo_name(self) -> str:
        return self.site.get("repo_name", "")


def load_config(config_path: Optional[str] = None) -> RepoQuillConfig:
    """Load and normalize a ``repoquill.yml`` config file.

    Args:
        config_path: Explicit path to the config file. If None, looks for
            ``repoquill.yml`` in the current working directory, then the
            ``REPOQUILL_CONFIG`` env var.

    Returns:
        A normalized :class:`RepoQuillConfig`.

    Raises:
        FileNotFoundError: If no config file can be located.
    """
    path = _resolve_config_path(config_path)
    cfg_dict = _load_yaml(path)

    config_dir = os.path.dirname(os.path.abspath(path))

    # --- Root of the source repo ---
    # Priority: SOURCE_ROOT env var > `root:` in YAML > parent of config dir.
    root = os.environ.get("SOURCE_ROOT") or cfg_dict.get("root") or os.path.dirname(config_dir)
    root = os.path.abspath(root)

    # --- LLM block ---
    llm_raw = cfg_dict.get("llm", {}) or {}
    llm = LLMConfig(
        provider=llm_raw.get("provider", "openai"),
        model=llm_raw.get("model", "gpt-4o"),
        api_key_env=llm_raw.get("api_key_env", "OPENAI_API_KEY"),
        base_url=llm_raw.get("base_url"),
        rag=llm_raw.get("rag", {}) or {},
    )

    # --- Build block ---
    build = cfg_dict.get("build", {}) or {}
    docs_dir = build.get("docs_dir", "docs")

    # site_src resolution (priority high to low):
    #   1. Explicit `site_src:` key in YAML
    #   2. `output_dir:` key (same-repo integration: all artifacts in one folder)
    #   3. <config_dir>/<docs_dir> (default: <config_dir>/docs)
    if cfg_dict.get("site_src"):
        site_src = os.path.abspath(cfg_dict["site_src"])
    elif cfg_dict.get("output_dir"):
        # Same-repo integration: everything (site_src, site, plan) lives
        # inside output_dir/. The mkdocs.yml is written to output_dir/ and
        # the built site goes to output_dir/site/.
        site_src = os.path.abspath(os.path.join(config_dir, cfg_dict["output_dir"]))
    else:
        site_src = os.path.abspath(os.path.join(config_dir, docs_dir))

    cfg = RepoQuillConfig(
        raw=cfg_dict,
        project_name=cfg_dict.get("project_name", "Project"),
        package_dir=cfg_dict.get("package_dir", ""),
        root=root,
        source_repo=cfg_dict.get("source_repo", "") or "",
        source_ref=cfg_dict.get("source_ref", "") or "",
        llm=llm,
        site=cfg_dict.get("site", {}) or {},
        narrative_sections=cfg_dict.get("narrative_sections", []) or [],
        index=cfg_dict.get("index", {}) or {},
        build=build,
        theme=cfg_dict.get("theme", {}) or {},
        plugins=cfg_dict.get("plugins", []) or [],
        markdown_extensions=cfg_dict.get("markdown_extensions", []) or [],
        config_dir=config_dir,
        site_src=site_src,
        out_guides=os.path.join(site_src, "guides"),
        ref_dir=os.path.join(site_src, "reference"),
        pkg_path=os.path.join(root, cfg_dict.get("package_dir", "")),
        plan_file=os.path.join(site_src, ".plan.json"),
    )
    return cfg


def _resolve_config_path(config_path: Optional[str]) -> str:
    """Resolve the config file path from arg, env var, or cwd."""
    if config_path:
        path = os.path.abspath(config_path)
    elif os.environ.get("REPOQUILL_CONFIG"):
        path = os.path.abspath(os.environ["REPOQUILL_CONFIG"])
    else:
        path = os.path.abspath(os.path.join(os.getcwd(), "repoquill.yml"))
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"RepoQuill config file not found: {path}\n"
            "Create a repoquill.yml in the repo root, pass --config PATH, "
            "or set the REPOQUILL_CONFIG env var."
        )
    return path


def _load_yaml(path: str) -> Dict[str, Any]:
    """Load a YAML file. Uses PyYAML if available, else a minimal parser."""
    try:
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        return data or {}
    except ImportError:
        return _minimal_yaml_parse(path)


def _minimal_yaml_parse(path: str) -> Dict[str, Any]:
    """Very small YAML subset parser (no external deps).

    Handles: scalars, nested dicts, lists of scalars, lists of dicts,
    block scalars (| and >). Sufficient for repoquill.yml.
    """
    with open(path) as f:
        lines = f.readlines()

    def parse_block(lines, indent=0):
        result = {}
        i = 0
        while i < len(lines):
            raw = lines[i]
            if not raw.strip() or raw.strip().startswith("#"):
                i += 1
                continue
            cur_indent = len(raw) - len(raw.lstrip())
            if cur_indent < indent:
                break
            stripped = raw.strip()
            if stripped.startswith("- "):
                if not isinstance(result, list):
                    result = []
                item_val = stripped[2:].strip()
                if ":" in item_val and not item_val.startswith('"'):
                    d = {}
                    key, _, val = item_val.partition(":")
                    d[key.strip()] = val.strip().strip('"')
                    i += 1
                    while i < len(lines):
                        cont = lines[i]
                        if not cont.strip() or cont.strip().startswith("#"):
                            i += 1
                            continue
                        cont_indent = len(cont) - len(cont.lstrip())
                        if cont_indent <= cur_indent:
                            break
                        cs = cont.strip()
                        if cs.startswith("- "):
                            key2 = "slugs"
                            if key2 not in d:
                                d[key2] = []
                            d[key2].append(cs[2:].strip().strip('"'))
                            i += 1
                        elif ":" in cs:
                            k2, _, v2 = cs.partition(":")
                            v2 = v2.strip()
                            if v2.startswith("["):
                                items = v2.strip("[]").split(",")
                                d[k2.strip()] = [x.strip().strip('"') for x in items if x.strip()]
                            else:
                                d[k2.strip()] = v2.strip('"')
                            i += 1
                        else:
                            i += 1
                    result.append(d)
                else:
                    result.append(item_val.strip('"'))
                    i += 1
                continue
            if ":" in stripped:
                key, _, val = stripped.partition(":")
                key = key.strip()
                val = val.strip()
                if val == "" or val == "|" or val == ">":
                    block_lines = []
                    i += 1
                    while i < len(lines):
                        bl = lines[i]
                        if not bl.strip():
                            block_lines.append("")
                            i += 1
                            continue
                        bl_indent = len(bl) - len(bl.lstrip())
                        if bl_indent <= cur_indent:
                            break
                        block_lines.append(bl.strip())
                        i += 1
                    if val in ("|", ">"):
                        joiner = "\n" if val == "|" else " "
                        result[key] = joiner.join(block_lines).strip()
                    else:
                        sub = []
                        for bl in block_lines:
                            if bl.startswith("- "):
                                sub.append(bl[2:].strip().strip('"'))
                        if sub and all(":" not in s for s in sub):
                            result[key] = sub
                        else:
                            nested = {}
                            for bl in block_lines:
                                if ":" in bl:
                                    nk, _, nv = bl.partition(":")
                                    nv = nv.strip().strip('"')
                                    if nv.startswith("["):
                                        items = nv.strip("[]").split(",")
                                        nested[nk.strip()] = [x.strip().strip('"') for x in items if x.strip()]
                                    else:
                                        nested[nk.strip()] = nv
                            result[key] = nested
                elif val.startswith("["):
                    items = val.strip("[]").split(",")
                    result[key] = [x.strip().strip('"') for x in items if x.strip()]
                else:
                    result[key] = val.strip('"')
                i += 1
                continue
            i += 1
        return result

    return parse_block(lines)
