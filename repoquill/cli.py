"""RepoQuill command-line interface.

Commands:
    repoquill init      Scaffold repoquill.yml + GitHub Actions workflow.
    repoquill plan      Show the page plan (which pages, which sources).
    repoquill generate  Run Layer 1 (reference) + Layer 2 (narrative).
    repoquill build     Generate + run ``mkdocs build`` to produce site/.
    repoquill serve     Generate + run ``mkdocs serve`` for local preview.

Flags:
    --config PATH       Path to repoquill.yml, a directory of configs, or a
                        comma-separated list of config paths.
                        Default: ./repoquill.yml (or ./configs/ if it exists).
    --no-llm            Skip Layer 2 (deterministic reference only).
    --force             Full re-plan + regenerate everything.
    --build             Also run ``mkdocs build`` after generating.
    --source-root PATH  Override the source repo root.
    --port PORT         Port for ``mkdocs serve`` (default: 8000).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

from repoquill.config import load_config
from repoquill.llm import LLMClient
from repoquill.narrative import determine_structure, generate_all_pages
from repoquill.plan import (
    cleanup_stale_pages,
    compute_file_hashes,
    load_plan,
    store_plan,
)
from repoquill.reference import build_api_reference, get_source_files
from repoquill.site import (
    build_index_md,
    build_llms_full_txt,
    build_llms_txt,
    build_mkdocs_yml,
    build_nav,
    build_skill_md,
    cross_link_guides,
)


def _get_trackable_files(cfg) -> dict:
    """Map of relative path -> content for ALL files tracked for change detection."""
    exts = (".py", ".md", ".toml", ".txt", ".json", ".yaml", ".yml")
    files = {}
    for dirpath, _, filenames in os.walk(cfg.pkg_path):
        for f in filenames:
            if f.endswith(exts):
                full = os.path.join(dirpath, f)
                rel = os.path.relpath(full, cfg.root)
                with open(full, "r", encoding="utf-8", errors="replace") as fh:
                    files[rel] = fh.read()
    for f in ("README.md", "pyproject.toml", "FAQ.md"):
        full = os.path.join(cfg.root, f)
        if os.path.exists(full):
            with open(full, "r", encoding="utf-8", errors="replace") as fh:
                files[f] = fh.read()
    return files


def _copy_images(cfg) -> None:
    """Copy package images/ into site_src/images/ if present."""
    img_src = os.path.join(cfg.pkg_path, "images")
    img_dst = os.path.join(cfg.site_src, "images")
    if os.path.isdir(img_src):
        os.makedirs(img_dst, exist_ok=True)
        for f in os.listdir(img_src):
            if f.endswith(".png"):
                shutil.copy2(os.path.join(img_src, f), os.path.join(img_dst, f))
        print(f"  images/ ({len(os.listdir(img_dst))} files)")


def _copy_theme_assets(cfg) -> None:
    """Copy theme logo/favicon from config_dir into site_src/ if specified.

    Updates the theme config to use the basename (relative to docs_dir)
    so mkdocs.yml references the file correctly.
    """
    theme_cfg = cfg.theme
    for key in ("logo", "favicon"):
        val = theme_cfg.get(key)
        if val and not val.startswith("http"):
            src = os.path.join(cfg.config_dir, val)
            if os.path.isfile(src):
                dst = os.path.join(cfg.site_src, os.path.basename(val))
                shutil.copy2(src, dst)
                theme_cfg[key] = os.path.basename(val)
                print(f"  {key}: {os.path.basename(val)}")


def _mkdocs_cwd(cfg) -> str:
    """Return the working directory for mkdocs commands.

    When output_dir is set (same-repo integration), mkdocs.yml lives in
    site_src/. Otherwise it's in config_dir/.
    """
    if cfg.raw.get("output_dir"):
        return cfg.site_src
    return cfg.config_dir


def _run_mkdocs_build(cfg, skill_content: str | None = None) -> None:
    """Run `mkdocs build` in the correct directory."""
    print("\n[build] Running mkdocs build...")
    subprocess.run(
        [sys.executable, "-m", "mkdocs", "build"],
        cwd=_mkdocs_cwd(cfg), check=True,
    )
    site_dir = cfg.build.get("site_dir", "site")
    site_path = os.path.join(_mkdocs_cwd(cfg), site_dir)

    # Write SKILL.md as a raw plain-text file into the site output.
    # We don't put it in site_src because MkDocs would render it to HTML.
    if skill_content:
        skill_dst = os.path.join(site_path, "SKILL.md")
        with open(skill_dst, "w") as f:
            f.write(skill_content)
        print("  SKILL.md written as raw text ✓")

    print(f"  Site built to {site_dir}/ ✓")


def _run_mkdocs_serve(cfg, port: int = 8000) -> None:
    """Run `mkdocs serve` for local preview."""
    print(f"\n[serve] Starting mkdocs serve on http://localhost:{port} ...")
    print("  Press Ctrl+C to stop.\n")
    subprocess.run(
        [sys.executable, "-m", "mkdocs", "serve", "-p", str(port)],
        cwd=_mkdocs_cwd(cfg),
    )


def _resolve_configs(config_arg: str | None) -> list[str]:
    """Resolve the --config argument into a list of config file paths.

    Accepts:
      - A single file path: ``repoquill.yml``
      - A directory: ``configs/`` (all ``*.yml`` / ``*.yaml`` inside)
      - A comma-separated list: ``a.yml,b.yml``
      - None: looks for ``./repoquill.yml``, then ``./configs/``
    """
    if config_arg:
        # Comma-separated list
        if "," in config_arg:
            paths = [p.strip() for p in config_arg.split(",") if p.strip()]
            for p in paths:
                if not os.path.isfile(p):
                    raise FileNotFoundError(f"Config file not found: {p}")
            return paths
        # Directory
        if os.path.isdir(config_arg):
            files = sorted(
                f for f in os.listdir(config_arg)
                if f.endswith((".yml", ".yaml"))
            )
            if not files:
                raise FileNotFoundError(
                    f"No .yml/.yaml files found in {config_arg}/"
                )
            return [os.path.join(config_arg, f) for f in files]
        # Single file
        if not os.path.isfile(config_arg):
            raise FileNotFoundError(f"Config file not found: {config_arg}")
        return [os.path.abspath(config_arg)]

    # Default: look for repoquill.yml, then configs/
    default = os.path.join(os.getcwd(), "repoquill.yml")
    if os.path.isfile(default):
        return [default]
    configs_dir = os.path.join(os.getcwd(), "configs")
    if os.path.isdir(configs_dir):
        files = sorted(
            f for f in os.listdir(configs_dir)
            if f.endswith((".yml", ".yaml"))
        )
        if files:
            return [os.path.join(configs_dir, f) for f in files]
    raise FileNotFoundError(
        "No config found. Create repoquill.yml in the repo root, "
        "create a configs/ directory, or pass --config PATH."
    )


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

# Providers that run locally and never need an API key.
_LOCAL_PROVIDERS = {"ollama", "lm_studio", "vllm", "local"}

# Providers that authenticate via OAuth / device-code instead of an API key.
# LiteLLM handles the login and caches the token locally.
_OAUTH_PROVIDERS = {"github_copilot"}

# Providers offered in the interactive picker, in display order.
# Everything else in litellm.provider_list is still usable by typing it.
_FEATURED_PROVIDERS = [
    "openai",
    "anthropic",
    "github_copilot",
    "openrouter",
    "groq",
    "together_ai",
    "mistral",
    "xai",
    "deepseek",
    "huggingface",
    "cohere",
    "ollama",
]


def _litellm_catalog() -> dict:
    """Build a provider -> {models, default} catalog from LiteLLM data.

    Derived entirely from ``litellm.model_cost`` (no curation). For each
    provider, collects the chat-mode models, strips any provider prefix,
    and picks a sensible default (short, non-fine-tuned, non-dated).

    Returns:
        Dict mapping provider name to ``{"models": [...], "default": str}``.
    """
    try:
        import litellm
    except ImportError:
        return {}

    from collections import defaultdict

    prov_models: dict = defaultdict(list)
    for model, info in litellm.model_cost.items():
        if not isinstance(info, dict) or info.get("mode") != "chat":
            continue
        provider = info.get("litellm_provider")
        if not provider:
            continue
        name = model
        for pref in (provider + "/", provider.replace("_", "-") + "/"):
            if name.startswith(pref):
                name = name[len(pref):]
                break
        prov_models[provider].append(name)

    catalog: dict = {}
    for provider, models in prov_models.items():
        catalog[provider] = {
            "models": sorted(set(models)),
            "default": _pick_default_model(models),
        }
    return catalog


def _pick_default_model(models: list) -> str:
    """Pick a sensible default model from a provider's chat-model list.

    Prefers short, non-fine-tuned, non-dated names.
    """
    if not models:
        return ""

    def score(m: str) -> int:
        s = 0
        if m.startswith("ft:"):
            s += 1000
        parts = m.split("-")
        if len(parts) >= 2 and parts[-1].isdigit() and len(parts[-1]) >= 8:
            s += 500  # dated snapshot
        s += len(m)  # prefer short
        return s

    return sorted(set(models), key=score)[0]


def _provider_api_key_env(provider: str) -> str:
    """Derive the API-key env var name for a provider.

    Convention: ``{PROVIDER.upper()}_API_KEY`` (e.g. openai -> OPENAI_API_KEY,
    together_ai -> TOGETHER_AI_API_KEY). LiteLLM reads this automatically.
    """
    return f"{provider.upper()}_API_KEY"


def _needs_api_key(provider: str) -> bool:
    """True if the provider requires an API key (not local, not OAuth)."""
    return provider not in _LOCAL_PROVIDERS and provider not in _OAUTH_PROVIDERS


def _prompt_choice(prompt: str, options: list, default: str) -> str:
    """Interactive numbered picker. Returns the chosen option string.

    Falls back to ``default`` on EOF / non-interactive stdin.
    """
    if not options:
        return default
    print(prompt)
    for i, opt in enumerate(options, 1):
        marker = " (default)" if opt == default else ""
        print(f"  {i}. {opt}{marker}")
    try:
        raw = input(f"Select [1-{len(options)}] (default: {options.index(default) + 1 if default in options else 1}): ").strip()
    except (EOFError, KeyboardInterrupt):
        return default
    if not raw:
        return default
    if raw.isdigit() and 1 <= int(raw) <= len(options):
        return options[int(raw) - 1]
    # Allow typing a value not in the list (e.g. a custom provider)
    return raw


def _prompt_text(prompt: str, default: str) -> str:
    """Interactive text input with a default. Falls back to default on EOF."""
    try:
        raw = input(f"{prompt} [{default}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        return default
    return raw or default


def _check_repo_accessible(repo_name: str) -> bool:
    """Check if a GitHub repo is accessible (public or authenticated).

    Uses the GitHub API (no auth needed for public repos). Returns True
    if the repo exists and is readable, False otherwise.
    """
    import urllib.request
    import urllib.error

    api_url = f"https://api.github.com/repos/{repo_name}"
    req = urllib.request.Request(api_url, headers={"Accept": "application/vnd.github+json", "User-Agent": "RepoQuill"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"  ✗ Repo not found or is private: {repo_name}")
        elif e.code == 403:
            print(f"  ✗ Access forbidden (rate limit or private): {repo_name}")
        else:
            print(f"  ✗ GitHub API error {e.code}: {repo_name}")
        return False
    except (urllib.error.URLError, OSError) as e:
        print(f"  ✗ Network error checking {repo_name}: {e}")
        return False


def _prompt_repo_source() -> str:
    """Ask user whether to document the current repo or provide a URL.

    Returns:
        "current" for the current repo, or a URL string if the user
        provided one. Falls back to "current" on non-TTY / EOF.
    """
    if not sys.stdin.isatty():
        return "current"

    print()
    print("  Which repo should RepoQuill document?")
    print("  [1] Current repo (default)")
    print("  [2] Provide a repo URL")
    try:
        choice = input("  Choose [1/2] (default: 1): ").strip() or "1"
    except (EOFError, KeyboardInterrupt):
        return "current"

    if choice == "2":
        while True:
            try:
                url = input("  Repo URL (e.g. https://github.com/owner/repo): ").strip()
            except (EOFError, KeyboardInterrupt):
                return "current"
            if not url:
                return "current"

            # Parse owner/repo from URL
            clean = url.rstrip("/")
            if clean.endswith(".git"):
                clean = clean[:-4]
            if "github.com" in clean:
                path = clean.split("github.com", 1)[1].lstrip("/")
                parts = path.split("/")
                if len(parts) >= 2:
                    repo_name = f"{parts[0]}/{parts[1]}"
                else:
                    print("  ✗ Could not parse owner/repo from URL. Try again.")
                    continue
            else:
                print("  ✗ Only GitHub URLs are supported. Try again.")
                continue

            # Verify the repo is accessible
            print(f"  Checking access to {repo_name}...")
            if _check_repo_accessible(repo_name):
                print(f"  ✓ {repo_name} is accessible")
                return url
            else:
                retry = input("  Retry with a different URL? [Y/n]: ").strip().lower()
                if retry in ("n", "no"):
                    return "current"
                continue
    return "current"


def _test_llm_connection(provider: str, model: str, api_key_env: str) -> bool:
    """Fire one tiny completion to verify the configured provider works.

    Returns True on success, False on failure (prints the reason).
    """
    import litellm

    model_str = model if provider == "openai" else f"{provider}/{model}"
    kwargs = {"model": model_str, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5}
    if api_key_env and _needs_api_key(provider):
        key = os.environ.get(api_key_env)
        if key:
            kwargs["api_key"] = key
    try:
        litellm.completion(**kwargs)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  connection test failed: {e}")
        return False


_WORKFLOW_TEMPLATE = """\
name: Docs

{on_block}
jobs:
  docs:
    uses: SushantGautam/RepoQuill/.github/workflows/reusable.yml@main
    with:
      config: repoquill.yml
      api_key_secret: LLM_API_KEY
      api_key_env: {api_key_env}
      deploy_branch: gh-pages
      deploy_path: site
    secrets:
      LLM_API_KEY: ${{{{ secrets.LLM_API_KEY }}}}
"""


def _workflow_on_block(trigger: str, branch: str = "main") -> str:
    """Build the ``on:`` block for the generated workflow.

    Args:
        trigger: One of ``manual``, ``push_main``, ``push_all``, ``release``.
        branch: Branch name for ``push_main`` (default ``main``).

    Returns:
        The indented ``on:`` block (no trailing newline).
    """
    if trigger == "push_all":
        return (
            "on:\n"
            "  push:\n"
            "  pull_request:\n"
            "  workflow_dispatch:\n"
        )
    if trigger == "release":
        return (
            "on:\n"
            "  push:\n"
            "    tags:\n"
            "      - 'v*'\n"
            "  workflow_dispatch:\n"
        )
    if trigger == "push_main":
        return (
            "on:\n"
            f"  push:\n"
            f"    branches: [{branch}]\n"
            "  workflow_dispatch:\n"
        )
    # manual (default): only runs when triggered from the Actions UI
    return (
        "on:\n"
        "  workflow_dispatch:\n"
        "  # To auto-run on push, uncomment one of:\n"
        "  #   push:\n"
        "  #     branches: [main]\n"
        "  #   push:            # all branches\n"
        "  #   push:\n"
        "  #     tags: ['v*']   # on release\n"
    )

_CONFIG_TEMPLATE = """\
# RepoQuill configuration
# Docs: https://github.com/SushantGautam/RepoQuill#config

project_name: {project_name}
package_dir: {package_dir}

llm:
  provider: {provider}
  model: {model}
{api_key_env_line}
site:
  name: {project_name}
  description: "{description}"
  url: https://{site_owner}.github.io/{site_slug}/
  repo_url: https://github.com/{repo_name}
  repo_name: {repo_name}

narrative_sections:
  - title: Getting Started
    slugs: [quickstart, installation]
  - title: Core Concepts
    slugs: [architecture, key-ideas]

reference_sections:
{reference_block}

index:
  tagline: "{description}"
{index_block}
"""


def _detect_package_dir() -> str:
    """Find the top-level Python package in the current directory."""
    for entry in sorted(os.listdir(".")):
        if (
            os.path.isdir(entry)
            and not entry.startswith((".", "_"))
            and os.path.isfile(os.path.join(entry, "__init__.py"))
        ):
            return entry
    return ""


def _detect_project_name() -> str:
    """Read the project name from pyproject.toml if present."""
    for toml in ("pyproject.toml", "setup.cfg"):
        if os.path.isfile(toml):
            try:
                with open(toml, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("name") and "=" in line:
                            val = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if val:
                                return val
            except OSError:
                pass
    return os.path.basename(os.getcwd())


def _detect_repo_name() -> str:
    """Detect owner/repo from the git remote, falling back to cwd name."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            # Handle both https://github.com/owner/repo.git and git@github.com:owner/repo.git
            if "github.com" in url:
                path = url.split("github.com", 1)[1].lstrip("/").rstrip("/")
                if path.endswith(".git"):
                    path = path[:-4]
                parts = path.split("/")
                if len(parts) >= 2:
                    return f"{parts[0]}/{parts[1]}"
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.basename(os.getcwd())


def _load_existing_config(config_path: str) -> dict:
    """Load an existing repoquill.yml and return its raw dict (or {})."""
    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _prompt_existing_config(config_path: str, args) -> dict:
    """Show existing config values and let the user choose what to do.

    Returns a dict with keys:
        project_name, package_dir, description, provider, model,
        api_key_env, trigger, site (dict), narrative_sections (list),
        reference_sections (list), index (dict)
    """
    raw = _load_existing_config(config_path)
    llm_raw = raw.get("llm", {}) or {}
    site_raw = raw.get("site", {}) or {}

    print(f"\nExisting {config_path} found:")
    print(f"  project_name:   {raw.get('project_name', '(not set)')}")
    print(f"  package_dir:    {raw.get('package_dir', '(not set)')}")
    print(f"  provider:       {llm_raw.get('provider', '(not set)')}")
    print(f"  model:          {llm_raw.get('model', '(not set)')}")
    print(f"  api_key_env:    {llm_raw.get('api_key_env', '(not set)')}")
    if site_raw:
        print(f"  site.url:       {site_raw.get('url', '(not set)')}")
        print(f"  site.repo_name: {site_raw.get('repo_name', '(not set)')}")
    if raw.get("narrative_sections"):
        print(f"  narrative:      {len(raw['narrative_sections'])} section(s)")
    if raw.get("reference_sections"):
        print(f"  reference:      {len(raw['reference_sections'])} section(s)")
    print()

    # If not interactive, just keep everything
    if not sys.stdin.isatty():
        return {
            "project_name": raw.get("project_name", ""),
            "package_dir": raw.get("package_dir", ""),
            "description": site_raw.get("description", ""),
            "provider": llm_raw.get("provider", "openai"),
            "model": llm_raw.get("model", "gpt-4o"),
            "api_key_env": llm_raw.get("api_key_env", ""),
            "trigger": "manual",
            "site": site_raw,
            "narrative_sections": raw.get("narrative_sections", []),
            "reference_sections": raw.get("reference_sections", []),
            "index": raw.get("index", {}),
        }

    print("  [1] Keep all existing values")
    print("  [2] Change some values")
    print("  [3] Reset all (start fresh)")
    choice = input("  Choose [1/2/3] (default: 1): ").strip() or "1"

    if choice == "3":
        # Reset: use detected defaults, re-prompt everything
        return None  # Signal: start fresh

    if choice == "2":
        # Change some: show each value, ask to keep or change
        project_name = raw.get("project_name", _detect_project_name())
        package_dir = raw.get("package_dir", _detect_package_dir())
        provider = llm_raw.get("provider", "openai")
        model = llm_raw.get("model", "gpt-4o")
        api_key_env = llm_raw.get("api_key_env", "")
        description = site_raw.get("description", f"Documentation for {project_name}")

        print()
        print("  For each value, press Enter to keep, or type a new value:")
        print()

        new_name = input(f"  project_name  [{project_name}]: ").strip()
        if new_name:
            project_name = new_name

        new_pkg = input(f"  package_dir   [{package_dir}]: ").strip()
        if new_pkg:
            package_dir = new_pkg

        new_prov = input(f"  provider      [{provider}]: ").strip()
        if new_prov:
            provider = new_prov
            # Re-derive api_key_env if provider changed
            if provider not in _LOCAL_PROVIDERS and provider not in _OAUTH_PROVIDERS:
                api_key_env = _provider_api_key_env(provider)

        new_model = input(f"  model         [{model}]: ").strip()
        if new_model:
            model = new_model

        new_key_env = input(f"  api_key_env   [{api_key_env or '(none)'}]: ").strip()
        if new_key_env:
            api_key_env = new_key_env

        new_desc = input(f"  description   [{description}]: ").strip()
        if new_desc:
            description = new_desc

        # Trigger
        trigger = _capture_trigger(args)

        return {
            "project_name": project_name,
            "package_dir": package_dir,
            "description": description,
            "provider": provider,
            "model": model,
            "api_key_env": api_key_env,
            "trigger": trigger,
            "site": site_raw,
            "narrative_sections": raw.get("narrative_sections", []),
            "reference_sections": raw.get("reference_sections", []),
            "index": raw.get("index", {}),
        }

    # Default: keep all
    return {
        "project_name": raw.get("project_name", ""),
        "package_dir": raw.get("package_dir", ""),
        "description": site_raw.get("description", ""),
        "provider": llm_raw.get("provider", "openai"),
        "model": llm_raw.get("model", "gpt-4o"),
        "api_key_env": llm_raw.get("api_key_env", ""),
        "trigger": "manual",
        "site": site_raw,
        "narrative_sections": raw.get("narrative_sections", []),
        "reference_sections": raw.get("reference_sections", []),
        "index": raw.get("index", {}),
    }


def _cmd_init(args) -> int:
    """Scaffold repoquill.yml and a GitHub Actions workflow."""
    config_path = os.path.join(os.getcwd(), "repoquill.yml")

    # --- Check for existing config ---
    existing = None
    if os.path.exists(config_path):
        if args.force:
            print(f"  --force: overwriting {config_path}")
        else:
            existing = _prompt_existing_config(config_path, args)
            if existing is None:
                # User chose "reset all" — fall through to fresh init
                existing = None
            else:
                # User kept or changed values — use them
                project_name = existing["project_name"] or _detect_project_name()
                package_dir = existing["package_dir"] or _detect_package_dir()
                provider = existing["provider"]
                model = existing["model"]
                api_key_env = existing["api_key_env"]
                trigger = existing["trigger"]
                description = existing["description"] or f"Documentation for {project_name}"

                # Write config with existing values
                repo_name = _detect_repo_name()
                repo_owner, _, repo_slug = repo_name.partition("/")
                if not repo_slug:
                    repo_owner, repo_slug = "", repo_name

                if api_key_env:
                    api_key_env_line = f"  api_key_env: {api_key_env}\n"
                else:
                    api_key_env_line = "  # api_key_env: (not needed — " + (
                        "local provider" if provider in _LOCAL_PROVIDERS else "OAuth login"
                    ) + ")\n"

                # Build config content, preserving existing sections
                site = existing.get("site") or {}
                site_name = site.get("name", project_name)
                site_url = site.get("url", f"https://{repo_owner}.github.io/{repo_slug}/")
                site_repo_url = site.get("repo_url", f"https://github.com/{repo_name}")
                site_repo_name = site.get("repo_name", repo_name)
                site_desc = site.get("description", description)

                narrative = existing.get("narrative_sections") or [
                    {"title": "Getting Started", "slugs": ["quickstart", "installation"]},
                    {"title": "Core Concepts", "slugs": ["architecture", "key-ideas"]},
                ]
                if existing.get("reference_sections"):
                    reference = existing["reference_sections"]
                elif package_dir:
                    reference = [{"title": "Core", "modules": [package_dir]}]
                else:
                    reference = []
                if existing.get("index"):
                    index = existing["index"]
                elif package_dir:
                    index = {"tagline": description, "quick_start": {"install": f"pip install {package_dir}"}}
                else:
                    index = {"tagline": description}

                # Serialize sections to YAML
                import yaml
                narrative_yaml = yaml.dump(narrative, default_flow_style=False, sort_keys=False).strip()
                reference_yaml = yaml.dump(reference, default_flow_style=False, sort_keys=False).strip()
                index_yaml = yaml.dump(index, default_flow_style=False, sort_keys=False).strip()

                config_content = (
                    f"# RepoQuill configuration\n"
                    f"# Docs: https://github.com/SushantGautam/RepoQuill#config\n"
                    f"\n"
                    f"project_name: {project_name}\n"
                    f"package_dir: {package_dir}\n"
                    f"\n"
                    f"llm:\n"
                    f"  provider: {provider}\n"
                    f"  model: {model}\n"
                    f"{api_key_env_line}"
                    f"site:\n"
                    f"  name: {site_name}\n"
                    f"  description: \"{site_desc}\"\n"
                    f"  url: {site_url}\n"
                    f"  repo_url: {site_repo_url}\n"
                    f"  repo_name: {site_repo_name}\n"
                    f"\n"
                    f"narrative_sections:\n"
                    f"{narrative_yaml}\n"
                    f"\n"
                    f"reference_sections:\n"
                    f"{reference_yaml}\n"
                    f"\n"
                    f"index:\n"
                    f"{index_yaml}\n"
                )
                with open(config_path, "w", encoding="utf-8") as f:
                    f.write(config_content)
                print(f"  updated {config_path}")

                # Write workflow if it doesn't exist
                wf_dir = os.path.join(os.getcwd(), ".github", "workflows")
                wf_path = os.path.join(wf_dir, "docs.yml")
                if not os.path.exists(wf_path):
                    os.makedirs(wf_dir, exist_ok=True)
                    on_block = _workflow_on_block(trigger)
                    wf_content = _WORKFLOW_TEMPLATE.format(
                        api_key_env=api_key_env or "LLM_API_KEY",
                        on_block=on_block,
                    )
                    with open(wf_path, "w", encoding="utf-8") as f:
                        f.write(wf_content)
                    print(f"  created {wf_path}")
                else:
                    print(f"  kept existing {wf_path}")

                print()
                print("Next steps:")
                print("  1. Edit repoquill.yml — set site.url, narrative_sections, etc.")
                print("  2. Run: repoquill build")
                print("  3. Local preview: repoquill serve")
                return 0

    # --- Fresh init (no existing config, or user chose reset) ---
    repo_source = _prompt_repo_source()
    if repo_source != "current":
        # User provided a repo URL (already validated as accessible)
        url = repo_source.rstrip("/")
        if url.endswith(".git"):
            url = url[:-4]
        if "github.com" in url:
            path = url.split("github.com", 1)[1].lstrip("/")
            parts = path.split("/")
            if len(parts) >= 2:
                repo_name = f"{parts[0]}/{parts[1]}"
            else:
                repo_name = _detect_repo_name()
        else:
            repo_name = _detect_repo_name()
        print(f"  (documenting remote repo: {repo_name})")
    else:
        repo_name = _detect_repo_name()

    project_name = args.name or _detect_project_name()
    package_dir = args.package or _detect_package_dir()
    description = args.description or f"Documentation for {project_name}"

    # --- Capture LLM config (provider / model / auth) ---
    provider, model, api_key_env = _capture_llm_config(args)

    # --- Capture workflow trigger mode ---
    trigger = _capture_trigger(args)

    # --- Summary of auto-detected values ---
    print(f"  project:  {project_name}")
    print(f"  package:  {package_dir or '(none — non-Python project)'}")
    print(f"  repo:     {repo_name}")
    print(f"  llm:      {provider}/{model}")
    print(f"  trigger:  {trigger}")

    # --- Write repoquill.yml ---
    if os.path.exists(config_path) and not args.force:
        print(f"error: {config_path} already exists (use --force to overwrite)", file=sys.stderr)
        return 1

    # site.url is derived from the CURRENT repo's git remote (where the site
    # is published), NOT from the target repo being documented.
    site_repo = _detect_repo_name()
    site_owner, _, site_slug = site_repo.partition("/")
    if not site_slug:
        site_owner, site_slug = "", site_repo

    if api_key_env:
        api_key_env_line = f"  api_key_env: {api_key_env}\n"
    else:
        api_key_env_line = "  # api_key_env: (not needed — " + (
            "local provider" if provider in _LOCAL_PROVIDERS else "OAuth login"
        ) + ")\n"

    # Build conditional blocks based on whether package_dir is set
    if package_dir:
        reference_block = f"  - title: Core\n    modules: [{package_dir}]"
        index_block = f'  quick_start:\n    install: "pip install {package_dir}"'
    else:
        reference_block = "  # Add reference sections here (e.g. for Python packages)"
        index_block = "  # Add quick_start here (e.g. install command)"

    config_content = _CONFIG_TEMPLATE.format(
        project_name=project_name,
        package_dir=package_dir,
        description=description,
        repo_name=repo_name,
        site_owner=site_owner,
        site_slug=site_slug,
        provider=provider,
        model=model,
        api_key_env_line=api_key_env_line,
        reference_block=reference_block,
        index_block=index_block,
    )
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(config_content)
    print(f"  created {config_path}")

    # --- Write GitHub Actions workflow ---
    wf_dir = os.path.join(os.getcwd(), ".github", "workflows")
    wf_path = os.path.join(wf_dir, "docs.yml")
    if os.path.exists(wf_path) and not args.force:
        print(f"  skipped {wf_path} (already exists)")
    else:
        os.makedirs(wf_dir, exist_ok=True)
        on_block = _workflow_on_block(trigger)
        wf_content = _WORKFLOW_TEMPLATE.format(
            api_key_env=api_key_env or "LLM_API_KEY",
            on_block=on_block,
        )
        with open(wf_path, "w", encoding="utf-8") as f:
            f.write(wf_content)
        print(f"  created {wf_path}")

    # --- Optional connection test ---
    if args.test:
        print("\n[init] Testing LLM connection...")
        ok = _test_llm_connection(provider, model, api_key_env)
        print(f"  {'OK' if ok else 'FAILED'} — {provider}/{model}")

    print()
    print("Next steps:")
    print("  1. Edit repoquill.yml — set site.url, narrative_sections, etc.")

    # Auth setup (path A: local, path B: GitHub Actions)
    if provider in _OAUTH_PROVIDERS:
        print("  2. Log in once (device-code flow) — happens automatically on the")
        print("     first `repoquill generate`. No API key needed.")
    elif provider in _LOCAL_PROVIDERS:
        print(f"  2. Make sure your local model server is running ({provider}).")
    else:
        local_key = os.environ.get(api_key_env, "")
        if local_key and shutil.which("gh") and sys.stdin.isatty():
            print("  2. Your local " + api_key_env + " is set.")
            answer = input(
                "     Set the LLM_API_KEY GitHub secret now (via gh)? [y/N] "
            ).strip().lower()
            if answer in ("y", "yes"):
                result = subprocess.run(
                    ["gh", "secret", "set", "LLM_API_KEY"],
                    input=local_key, text=True, capture_output=True,
                )
                if result.returncode == 0:
                    print("     ✓ Done — LLM_API_KEY GitHub secret is set.")
                else:
                    err = (result.stderr or result.stdout or "").strip()
                    print("     ✗ Failed to set the GitHub secret.")
                    if err:
                        print("       " + err.splitlines()[0])
                    print("     Set it manually: Settings → Secrets → Actions")
                    print("       → New repository secret → Name: LLM_API_KEY")
            else:
                print("     Set it later: Settings → Secrets → Actions")
                print("       → New repository secret → Name: LLM_API_KEY")
        else:
            print("  2. Set your LLM API key:")
            print("     • Local:  export " + api_key_env + "=sk-...")
            print("     • GitHub Actions: Settings → Secrets → New repository secret")
            print("       Name: LLM_API_KEY   Value: sk-...")

    # Trigger / deploy
    if trigger == "manual":
        print("  3. Build locally:  repoquill build   (or `repoquill serve` to preview)")
        print("     Or run the workflow from the Actions UI (it's set to manual).")
    elif trigger == "push_main":
        print("  3. Push to main — docs build + deploy to GitHub Pages automatically.")
    elif trigger == "push_all":
        print("  3. Push to any branch / open a PR — docs build automatically.")
    else:  # release
        print("  3. Tag a release (v*) — docs build + deploy automatically.")

    print("  4. Local preview anytime:  repoquill serve")
    return 0


def _capture_llm_config(args):
    """Capture provider / model / api_key_env.

    Minimal by default: uses sensible defaults (openai/gpt-4o) unless the
    user passes --provider/--model or is in an interactive TTY where they
    want to choose. Returns a (provider, model, api_key_env) tuple.
    """
    catalog = _litellm_catalog()

    # --- Provider ---
    if getattr(args, "provider", None):
        provider = args.provider
    elif sys.stdin.isatty():
        featured = [p for p in _FEATURED_PROVIDERS if p in catalog or p in _LOCAL_PROVIDERS or p in _OAUTH_PROVIDERS]
        provider = _prompt_choice("Which LLM provider?", featured, "openai")
    else:
        provider = "openai"

    # --- Model ---
    default_model = catalog.get(provider, {}).get("default", "")
    if not default_model:
        default_model = {"ollama": "llama3.1", "lm_studio": "local-model", "vllm": "local-model", "local": "local-model"}.get(provider, "gpt-4o")
    if getattr(args, "model", None):
        model = args.model
    elif sys.stdin.isatty():
        model = _prompt_text("Model", default_model)
    else:
        model = default_model

    # --- Auth ---
    if provider in _LOCAL_PROVIDERS or provider in _OAUTH_PROVIDERS:
        api_key_env = ""
    else:
        api_key_env = _provider_api_key_env(provider)
        if os.environ.get(api_key_env):
            print(f"  (detected {api_key_env} in your environment)")

    return provider, model, api_key_env


def _capture_trigger(args) -> str:
    """Capture the workflow trigger mode.

    Minimal by default: uses ``manual`` unless the user passes --trigger
    or is in an interactive TTY. Returns one of: ``manual``, ``push_main``,
    ``push_all``, ``release``.
    """
    if getattr(args, "trigger", None):
        return args.trigger
    if not sys.stdin.isatty():
        return "manual"
    options = [
        "manual",       # default: only via Actions UI (dormant on:)
        "push_main",    # on every push to main
        "push_all",     # on every push (all branches) + PRs
        "release",      # on version tags (v*)
    ]
    labels = {
        "manual": "manual (default — run from the Actions UI)",
        "push_main": "on every push to main",
        "push_all": "on every push (all branches) + pull requests",
        "release": "on release (version tags v*)",
    }
    # Show friendly labels but return the key
    display = [labels[o] for o in options]
    choice = _prompt_choice("When should the docs workflow run?", display, labels["manual"])
    # Map the label back to the key
    for key, label in labels.items():
        if choice == label:
            return key
    return "manual"


def _scaffold_config(cfg, client) -> bool:
    """Ask the LLM to fill in missing config sections (narrative_sections,
    reference_sections, index) for a minimal config.

    Returns True if the config was updated and written back.
    """
    import yaml

    # Check if config is minimal (missing key sections)
    needs_narrative = not cfg.narrative_sections
    needs_reference = not cfg.raw.get("reference_sections")
    needs_index = not cfg.index or not cfg.index.get("tagline")

    if not (needs_narrative or needs_reference or needs_index):
        return False  # Config is already complete

    # Gather context for the LLM
    from repoquill.reference import get_file_tree
    tree = ""
    if cfg.package_dir and os.path.isdir(cfg.pkg_path):
        tree = get_file_tree(cfg.pkg_path)
    readme_path = os.path.join(cfg.root, "README.md")
    readme = ""
    if os.path.exists(readme_path):
        with open(readme_path, "r", encoding="utf-8", errors="replace") as f:
            readme = f.read()[:2000]

    # List available modules for reference_sections
    modules = []
    if cfg.package_dir and os.path.isdir(cfg.pkg_path):
        for dirpath, _, filenames in os.walk(cfg.pkg_path):
            for f in filenames:
                if f.endswith(".py"):
                    rel = os.path.relpath(os.path.join(dirpath, f), cfg.root)
                    mod = rel[:-3].replace(os.sep, ".")
                    if mod.endswith(".__init__"):
                        mod = mod[:-9]
                    modules.append(mod)
        modules.sort()

    prompt = f"""You are a documentation architect. Given this project's structure, generate the missing documentation config sections.

PROJECT: {cfg.project_name}
PACKAGE: {cfg.package_dir or '(non-Python project)'}
README (excerpt):
{readme or '(no README found)'}

FILE TREE:
{tree or '(no Python package)'}

AVAILABLE MODULES:
{', '.join(modules) if modules else '(none)'}

Return a JSON object with these keys (only include keys that are needed):
{{
  "narrative_sections": [{{"title": "Section Title", "slugs": ["slug1", "slug2"]}}],
  "reference_sections": [{{"title": "Section Title", "modules": ["module.name"]}}],
  "index": {{"tagline": "One-line description", "quick_start": {{"install": "pip install pkg"}}}}
}}

Rules:
- narrative_sections: 2-4 sections grouping the narrative guide pages (e.g. "Getting Started", "Core Concepts", "Advanced Usage")
- reference_sections: group the available modules into logical sections (e.g. "Core", "CLI", "Utilities")
- index.tagline: a concise one-line description of the project
- index.quick_start: only include if this is an installable package
- Return ONLY the JSON object, no markdown fences"""

    result = client.chat(
        [{"role": "user", "content": prompt}],
        max_tokens=1024, temperature=0.1,
    )
    from repoquill.llm import strip_code_fences
    data = json.loads(strip_code_fences(result))

    # Merge into existing config
    updated = False
    if needs_narrative and data.get("narrative_sections"):
        cfg.raw["narrative_sections"] = data["narrative_sections"]
        cfg.narrative_sections = data["narrative_sections"]
        updated = True
    if needs_reference and data.get("reference_sections"):
        cfg.raw["reference_sections"] = data["reference_sections"]
        updated = True
    if needs_index and data.get("index"):
        # Merge index fields
        existing_index = cfg.raw.get("index", {}) or {}
        existing_index.update(data["index"])
        cfg.raw["index"] = existing_index
        cfg.index = existing_index
        updated = True

    if updated:
        # Write back to config file
        config_path = os.path.join(cfg.config_dir, "repoquill.yml")
        with open(config_path, "r", encoding="utf-8") as f:
            raw_config = yaml.safe_load(f) or {}

        if "narrative_sections" in cfg.raw:
            raw_config["narrative_sections"] = cfg.raw["narrative_sections"]
        if "reference_sections" in cfg.raw:
            raw_config["reference_sections"] = cfg.raw["reference_sections"]
        if "index" in cfg.raw:
            raw_config["index"] = cfg.raw["index"]

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(raw_config, f, default_flow_style=False, sort_keys=False)

        print(f"  ✓ Scaffolded config sections from LLM")
        return True
    return False


def _cmd_plan(args) -> int:
    cfg = load_config(args.config)
    if args.source_root:
        cfg.root = os.path.abspath(args.source_root)
        cfg.pkg_path = os.path.join(cfg.root, cfg.package_dir)

    print(f"Project: {cfg.project_name}")
    print(f"Package: {cfg.package_dir} ({cfg.pkg_path})")
    print()

    client = LLMClient(cfg.llm)
    pages = determine_structure(cfg, client)
    print(f"Planned {len(pages)} pages:")
    for p in pages:
        srcs = ", ".join(p.get("source_files", [])) or "(no sources)"
        print(f"  - {p['title']} ({p['slug']}) — {srcs}")
    return 0


def _cmd_generate(args) -> int:
    cfg = load_config(args.config)
    if args.source_root:
        cfg.root = os.path.abspath(args.source_root)
        cfg.pkg_path = os.path.join(cfg.root, cfg.package_dir)

    os.makedirs(cfg.out_guides, exist_ok=True)
    os.makedirs(cfg.ref_dir, exist_ok=True)

    print("=== RepoQuill Generator ===")
    print(f"Project: {cfg.project_name}")
    print(f"Package: {cfg.package_dir} ({cfg.pkg_path})")
    print(f"Site source: {cfg.site_src}")
    if not args.no_llm:
        print(f"LLM backend: {cfg.llm.provider}/{cfg.llm.model}")
    print()

    # Scaffold missing config sections via LLM (minimal config → full config)
    if not args.no_llm and not getattr(args, "no_scaffold", False):
        client = LLMClient(cfg.llm)
        if _scaffold_config(cfg, client):
            print()

    print("[1/6] Loading source files...")
    source_files = get_source_files(cfg.pkg_path)
    trackable_files = _get_trackable_files(cfg)
    new_hashes = compute_file_hashes(trackable_files)
    print(f"  Loaded {len(source_files)} Python files, tracking {len(trackable_files)} files")
    print()

    print("[2/6] Building API reference (Griffe)...")
    # build_api_reference returns [(module_name, slug), ...]; the site
    # assembly functions want plain module-name strings.
    reference_modules = [m for m, _ in build_api_reference(cfg)]
    print(f"  {len(reference_modules)} modules documented")
    print()

    old_plan = None if args.force else load_plan(cfg.plan_file)
    old_hashes = old_plan.get("file_hashes", {}) if old_plan else {}

    if args.no_llm:
        print("[3/6] Narrative pages — SKIPPED (--no-llm)")
        pages = old_plan.get("pages", []) if old_plan else []
        if not pages:
            print("  No stored plan found; index will list guides as they appear.")
    else:
        client = LLMClient(cfg.llm)
        if old_plan and not args.force:
            structure_valid = set(old_hashes.keys()) == set(new_hashes.keys())
            if structure_valid:
                pages = old_plan.get("pages", [])
                print(f"[3/6] Reusing stored plan ({len(pages)} narrative pages)")
            else:
                added = set(new_hashes.keys()) - set(old_hashes.keys())
                removed = set(old_hashes.keys()) - set(new_hashes.keys())
                print("[3/6] Source file set changed — re-planning structure...")
                if added:
                    print(f"  Added: {', '.join(sorted(added))}")
                if removed:
                    print(f"  Removed: {', '.join(sorted(removed))}")
                pages = determine_structure(cfg, client)
                print(f"  Planned {len(pages)} pages:")
                for p in pages:
                    print(f"    - {p['title']} ({p['slug']})")
        else:
            label = "--force: re-planning" if args.force else "First run — planning"
            print(f"[3/6] {label} documentation structure...")
            pages = determine_structure(cfg, client)
            print(f"  Planned {len(pages)} pages:")
            for p in pages:
                print(f"    - {p['title']} ({p['slug']})")
            old_hashes = {}

        print()
        print("[4/6] Generating narrative pages...")
        generated = generate_all_pages(
            pages, source_files, client, cfg, old_hashes, new_hashes
        )

        stale = cleanup_stale_pages({p["slug"] for p in pages}, cfg.out_guides)
        if stale:
            print(f"  Removed {len(stale)} stale pages: {', '.join(stale)}")

        store_plan(cfg.plan_file, pages, new_hashes)

    print()
    print("[5/6] Cross-linking guide pages...")
    cross_link_guides(cfg, pages)

    print()
    print("[6/6] Assembling MkDocs site...")
    _copy_theme_assets(cfg)
    build_index_md(cfg, pages, reference_modules)
    print("  index.md")

    nav = build_nav(cfg, pages, reference_modules)
    build_mkdocs_yml(cfg, nav)
    print("  mkdocs.yml")

    build_llms_txt(cfg, pages, reference_modules)
    build_llms_full_txt(cfg, pages, reference_modules)

    # Build SKILL.md content (don't write to site_src — MkDocs would
    # render it to HTML). We'll write it to the site output after build.
    skill_content = build_skill_md(cfg)
    print(f"  SKILL.md ({len(skill_content)} chars)")

    _copy_images(cfg)

    n_guides = len([f for f in os.listdir(cfg.out_guides) if f.endswith(".md")])
    n_ref = len([f for f in os.listdir(cfg.ref_dir) if f.endswith(".md")])
    print(f"\nDone. {n_guides} guide pages + {n_ref} reference pages in {cfg.site_src}")

    if args.build:
        _run_mkdocs_build(cfg, skill_content)
    return 0


def _cmd_build(args) -> int:
    args.build = True
    return _cmd_generate(args)


def _cmd_serve(args) -> int:
    """Generate docs and start a local preview server."""
    config_paths = _resolve_configs(args.config)
    if len(config_paths) > 1:
        print(
            f"warning: serve works with a single config; using first: {config_paths[0]}",
            file=sys.stderr,
        )
    args.config = config_paths[0]
    # Generate without building (serve will handle the build)
    _cmd_generate(args)
    # Reload config to get the correct paths for mkdocs serve
    cfg = load_config(args.config)
    if args.source_root:
        cfg.root = os.path.abspath(args.source_root)
        cfg.pkg_path = os.path.join(cfg.root, cfg.package_dir)
    _run_mkdocs_serve(cfg, port=args.port)
    return 0


def main(argv=None) -> int:
    """Entry point for the ``repoquill`` console script.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code (0 on success).
    """
    parser = argparse.ArgumentParser(
        prog="repoquill",
        description="Generic two-layer developer-docs generator.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--config", default=None,
        help="Path to repoquill.yml, a directory of configs, or "
             "comma-separated list. Default: ./repoquill.yml or ./configs/",
    )
    common.add_argument(
        "--source-root", default=None, help="Override the source repo root"
    )

    init = sub.add_parser("init", help="Scaffold repoquill.yml + GitHub Actions workflow")
    init.add_argument("--name", default=None, help="Project name (default: from pyproject.toml)")
    init.add_argument("--package", default=None, help="Python package directory (default: auto-detect)")
    init.add_argument("--description", default=None, help="One-line project description")
    init.add_argument("--provider", default=None, help="LLM provider (default: interactive prompt)")
    init.add_argument("--model", default=None, help="LLM model (default: provider's default)")
    init.add_argument(
        "--trigger", default=None,
        choices=["manual", "push_main", "push_all", "release"],
        help="When the docs workflow runs (default: interactive prompt; 'manual' = Actions UI only)",
    )
    init.add_argument("--test", action="store_true", help="Test the LLM connection after init")
    init.add_argument("--force", action="store_true", help="Overwrite existing files")

    sub.add_parser("plan", parents=[common], help="Show the page plan")
    gen = sub.add_parser("generate", parents=[common], help="Generate docs")
    gen.add_argument("--no-llm", action="store_true", help="Skip LLM layer")
    gen.add_argument("--no-scaffold", action="store_true", help="Skip LLM config scaffolding")
    gen.add_argument("--force", action="store_true", help="Full regenerate")
    gen.add_argument("--build", action="store_true", help="Also run mkdocs build")

    build = sub.add_parser("build", parents=[common], help="Generate + mkdocs build")
    build.add_argument("--no-llm", action="store_true", help="Skip LLM layer")
    build.add_argument("--no-scaffold", action="store_true", help="Skip LLM config scaffolding")
    build.add_argument("--force", action="store_true", help="Full regenerate")

    serve = sub.add_parser("serve", parents=[common], help="Generate + local preview")
    serve.add_argument("--no-llm", action="store_true", help="Skip LLM layer")
    serve.add_argument("--no-scaffold", action="store_true", help="Skip LLM config scaffolding")
    serve.add_argument("--force", action="store_true", help="Full regenerate")
    serve.add_argument("--port", type=int, default=8000, help="Port (default 8000)")

    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            return _cmd_init(args)
        elif args.command == "plan":
            return _cmd_plan(args)
        elif args.command == "generate":
            return _cmd_generate_multi(args)
        elif args.command == "build":
            return _cmd_build_multi(args)
        elif args.command == "serve":
            return _cmd_serve(args)
        else:
            parser.error(f"Unknown command: {args.command}")
            return 2
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"error: mkdocs build failed (exit {e.returncode})", file=sys.stderr)
        return 1


def _cmd_generate_multi(args) -> int:
    """Run generate for one or more config files."""
    config_paths = _resolve_configs(args.config)
    if len(config_paths) == 1:
        args.config = config_paths[0]
        return _cmd_generate(args)
    # Multiple configs: run each in sequence
    exit_code = 0
    for i, cp in enumerate(config_paths, 1):
        print(f"\n{'=' * 60}")
        print(f"Config {i}/{len(config_paths)}: {cp}")
        print(f"{'=' * 60}\n")
        args.config = cp
        try:
            _cmd_generate(args)
        except Exception as e:
            print(f"error: {cp}: {e}", file=sys.stderr)
            exit_code = 1
    if len(config_paths) > 1:
        print(f"\n{'=' * 60}")
        print(f"Processed {len(config_paths)} configs "
              f"({'all OK' if exit_code == 0 else 'with errors'})")
    return exit_code


def _cmd_build_multi(args) -> int:
    """Run build (generate + mkdocs build) for one or more config files."""
    args.build = True
    return _cmd_generate_multi(args)


if __name__ == "__main__":
    raise SystemExit(main())
