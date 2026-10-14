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

#: Valid values for ``documentation.engine`` (and ``--engine``).
VALID_ENGINES = ("pi", "python-agent", "legacy")


@dataclass
class AgenticConfig:
    """Settings for the agentic documentation engine (opt-in).

    When :attr:`enabled` is true (or the ``--agentic`` CLI flag is passed),
    narrative pages are authored by a bounded, tool-calling mini coding
    agent that explores the repository, inspects the API and tests, runs
    eligible examples, and writes the page — instead of the legacy
    single-shot prompt. The deterministic API reference, the independent
    verification gate, and the legacy path are all retained; agentic mode
    only changes *how* the narrative pages are produced.

    The agentic engine reuses the enclosing :class:`LLMConfig` provider
    (provider / model / base_url / api_key_env) unless overridden here, so
    any LiteLLM / OpenAI-compatible endpoint (including Qwen) works.
    """

    enabled: bool = False
    # Optional provider overrides (inherit the llm: block when unset).
    model: Optional[str] = None
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    # Loop bounds (per page) — bounded, never unbounded.
    max_steps: int = 12            # max tool-execution steps per page
    max_llm_calls: int = 16        # max LLM calls per page
    max_parallel_pages: int = 3    # pages authored concurrently
    max_page_chars: int = 60000    # reject candidate pages larger than this
    # Tool policy.
    execute_examples: bool = True  # allow the run_example tool
    example_timeout: float = 30.0  # wall-clock seconds per executed example
    max_file_chars: int = 16000    # per read_file truncation
    # Independent verification.
    coverage_threshold: float = 0.6  # semantic coverage ratio to pass
    # "unified" = one agent investigates + writes (default, low overhead);
    # "specialized" = separate investigation and writing passes.
    roles: str = "unified"
    # Pi-run bounds (used by the `pi` engine; the python-agent loop
    # ignores these and uses max_steps / max_llm_calls instead).
    timeout_s: float = 900.0   # per-page Pi deadline (large repos + slow
                               # remote endpoints routinely exceed 300s)
    max_tool_calls: int = 250  # abort the agent after this many tool calls
                               # (loop guard; over-exploring agents loop
                               # far past the point of usefulness);
                               # 0 disables the budget
    context_window: int = 32768  # contextWindow declared in the ephemeral
                               # Pi models.json; raise it to the endpoint's
                               # real window to avoid premature compaction
    compaction_keep_recent_tokens: int = 60000  # Pi compaction: recent
                               # tokens kept verbatim when the context
                               # compacts (Pi default 20000 is too small for
                               # docs runs — it made agents re-read source
                               # files after every compaction); 0 = Pi default
    max_repeat_calls: int = 6    # abort the run once the SAME tool call
                                 # (name + identical args) is issued this
                                 # many times (orbit guard; 0 disables)


@dataclass
class LLMConfig:
    """LLM provider settings (LiteLLM-backed)."""

    provider: str = "openai"
    model: str = "gpt-4o"
    api_key_env: str = "OPENAI_API_KEY"
    base_url: Optional[str] = None
    rag: Dict[str, Any] = field(default_factory=dict)
    max_concurrent: int = 1  # Max parallel LLM calls (1 = sequential)
    # Agentic documentation engine (opt-in; defaults to the legacy path).
    agentic: "AgenticConfig" = field(default_factory=AgenticConfig)

    # --- Narrative generation knobs (Layer 2) ---
    # Sampling
    temperature: float = 0.7          # new pages
    update_temperature: float = 0.3   # updating existing pages
    plan_temperature: float = 0.1     # structure planning
    max_tokens: int = 8192            # per page generation
    # Context budgets (chars)
    context_budget: int = 60000       # total source context per page
    per_file_budget: int = 12000      # per source file
    # Prompt enrichment (all generic — derived from the source tree)
    include_api_surface: bool = True  # inject AST-extracted API surface
    include_readme: bool = True       # inject README excerpt
    include_examples: bool = True     # inject examples/ listing + key files
    include_tests: bool = False       # inject top test files as behavior ground truth
    strict_prompt: bool = True        # anti-hallucination prompt variant
    # Post-generation verification (hallucination check + fix passes)
    verify_passes: int = 0            # 0 = off; 1-2 recommended
    grounding_pass: bool = False      # LLM correction pass fed by prose-checker findings
    # Quality gate + repair (autopilot P0/P1)
    validate_examples: bool = False   # execute python code blocks in a sandboxed subprocess
    repair: bool = False              # opt-in bounded docs-only LLM repair when the gate fails


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

    # Narrative engine selected in ``documentation.engine``. None means the
    # key was absent from the config file (pre-Pi configs) and the engine
    # must be resolved via the migration rule — see :func:`resolve_engine`.
    # Fresh configs written by ``repoquill init`` always set it explicitly.
    documentation_engine: Optional[str] = None

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
    # Priority: SOURCE_ROOT env var > `root:` in YAML > config dir itself.
    # The config file is typically at the repo root, so config_dir IS the root.
    root = os.environ.get("SOURCE_ROOT") or cfg_dict.get("root") or config_dir
    root = os.path.abspath(root)

    # --- LLM block ---
    llm_raw = cfg_dict.get("llm", {}) or {}
    ag_raw = llm_raw.get("agentic", {}) or {}
    agentic = AgenticConfig(
        enabled=bool(ag_raw.get("enabled", False)),
        model=ag_raw.get("model"),
        base_url=ag_raw.get("base_url"),
        api_key_env=ag_raw.get("api_key_env"),
        max_steps=int(ag_raw.get("max_steps", 12)),
        max_llm_calls=int(ag_raw.get("max_llm_calls", 16)),
        max_parallel_pages=int(ag_raw.get("max_parallel_pages", 3)),
        max_page_chars=int(ag_raw.get("max_page_chars", 60000)),
        execute_examples=bool(ag_raw.get("execute_examples", True)),
        example_timeout=float(ag_raw.get("example_timeout", 30.0)),
        max_file_chars=int(ag_raw.get("max_file_chars", 16000)),
        coverage_threshold=float(ag_raw.get("coverage_threshold", 0.6)),
        roles=str(ag_raw.get("roles", "unified")),
        timeout_s=float(ag_raw.get("timeout_s", 900.0)),
        max_tool_calls=int(ag_raw.get("max_tool_calls", 250)),
        context_window=int(ag_raw.get("context_window", 32768)),
        compaction_keep_recent_tokens=int(
            ag_raw.get("compaction_keep_recent_tokens", 60000)),
        max_repeat_calls=int(ag_raw.get("max_repeat_calls", 6)),
    )
    llm = LLMConfig(
        provider=llm_raw.get("provider", "openai"),
        model=llm_raw.get("model", "gpt-4o"),
        api_key_env=llm_raw.get("api_key_env", "OPENAI_API_KEY"),
        base_url=llm_raw.get("base_url"),
        rag=llm_raw.get("rag", {}) or {},
        max_concurrent=int(llm_raw.get("max_concurrent", 1)),
        temperature=float(llm_raw.get("temperature", 0.7)),
        update_temperature=float(llm_raw.get("update_temperature", 0.3)),
        plan_temperature=float(llm_raw.get("plan_temperature", 0.1)),
        max_tokens=int(llm_raw.get("max_tokens", 8192)),
        context_budget=int(llm_raw.get("context_budget", 60000)),
        per_file_budget=int(llm_raw.get("per_file_budget", 12000)),
        include_api_surface=bool(llm_raw.get("include_api_surface", True)),
        include_readme=bool(llm_raw.get("include_readme", True)),
        include_examples=bool(llm_raw.get("include_examples", True)),
        include_tests=bool(llm_raw.get("include_tests", False)),
        strict_prompt=bool(llm_raw.get("strict_prompt", True)),
        verify_passes=int(llm_raw.get("verify_passes", 0)),
        grounding_pass=bool(llm_raw.get("grounding_pass", False)),
        validate_examples=bool(llm_raw.get("validate_examples", False)),
        repair=bool(llm_raw.get("repair", False)),
        agentic=agentic,
    )

    # --- Documentation engine block (optional key) ---
    # Fresh configs (written by `repoquill init`) always set
    # `documentation.engine` explicitly. Existing configs without the key
    # keep today's behavior via the migration rule in `resolve_engine`.
    doc_raw = cfg_dict.get("documentation", {}) or {}
    doc_engine = doc_raw.get("engine")
    if doc_engine is not None:
        doc_engine = str(doc_engine).strip()
        if doc_engine not in VALID_ENGINES:
            raise ValueError(
                f"Unknown documentation.engine {doc_engine!r}; expected one "
                f"of: {', '.join(VALID_ENGINES)}"
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
        documentation_engine=doc_engine,
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
        pkg_path=os.path.join(root, cfg_dict.get("package_dir") or ""),
        plan_file=os.path.join(site_src, ".plan.json"),
    )
    return cfg


def resolve_engine(
    cfg: RepoQuillConfig,
    cli_engine: Optional[str] = None,
    agentic_flag: Optional[bool] = None,
) -> str:
    """Resolve the narrative engine for one run.

    Resolution order:

    1. Explicit CLI ``--engine`` (``cli_engine``) wins over everything.
       If ``--agentic`` is also given, ``--engine`` wins and a note is
       printed.
    2. ``documentation.engine`` from the config file. Fresh configs written
       by ``repoquill init`` always set it (currently ``pi``), so a fresh
       install defaults to Pi.
    3. Legacy migration rule: a config without ``documentation.engine`` but
       with ``llm.agentic.enabled: true`` maps to ``python-agent``. A
       one-line note is printed so existing consumers are never silently
       moved to a different runtime.
    4. Default: ``legacy`` — existing configs without any agentic signal
       behave exactly as before.

    ``--agentic`` (``agentic_flag=True``) is a deprecated alias for
    ``--engine python-agent`` and only applies when ``--engine`` is absent.
    ``--no-agentic`` (``agentic_flag=False``) only downgrades a resolved
    ``python-agent`` engine to ``legacy``; it never upgrades.

    ``--no-llm`` bypasses this entirely (deterministic mode, no engine).
    """
    if cli_engine:
        engine = cli_engine
        if agentic_flag is True and cli_engine != "python-agent":
            print(f"note: --engine {cli_engine} given with --agentic; "
                  f"using --engine {cli_engine} (--agentic is a "
                  f"deprecated alias for --engine python-agent)")
    elif cfg.documentation_engine:
        engine = cfg.documentation_engine
    elif cfg.llm.agentic.enabled:
        engine = "python-agent"
        print("note: llm.agentic.enabled maps to engine: python-agent; "
              "set documentation.engine explicitly to silence this")
    else:
        engine = "legacy"

    if agentic_flag is True and not cli_engine:
        if engine != "python-agent":
            print("note: --agentic is a deprecated alias for "
                  "--engine python-agent")
        engine = "python-agent"
    elif agentic_flag is False and engine == "python-agent":
        # Downgrade only; --no-agentic never upgrades a chosen engine.
        engine = "legacy"
    return engine


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
