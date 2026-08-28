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

_WORKFLOW_TEMPLATE = """\
name: Docs

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  docs:
    uses: SushantGautam/RepoQuill/.github/workflows/reusable.yml@main
    with:
      config: repoquill.yml
      api_key_secret: LLM_API_KEY
      api_key_env: {api_key_env}
      deploy_branch: gh-pages
      deploy_path: site
    secrets: inherit
"""

_CONFIG_TEMPLATE = """\
# RepoQuill configuration
# Docs: https://github.com/SushantGautam/RepoQuill#config

project_name: {project_name}
package_dir: {package_dir}

llm:
  provider: openai
  model: gpt-4o
  api_key_env: OPENAI_API_KEY
  temperature: 0.3
  max_tokens: 8192

site:
  name: {project_name}
  description: "{description}"
  url: https://{repo_owner}.github.io/{repo_slug}/
  repo_url: https://github.com/{repo_name}
  repo_name: {repo_name}

narrative_sections:
  - title: Getting Started
    slugs: [quickstart, installation]
  - title: Core Concepts
    slugs: [architecture, key-ideas]

reference_sections:
  - title: Core
    modules: [{package_dir}]

index:
  tagline: "{description}"
  quick_start:
    install: "pip install {package_dir}"
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


def _cmd_init(args) -> int:
    """Scaffold repoquill.yml and a GitHub Actions workflow."""
    project_name = args.name or _detect_project_name()
    package_dir = args.package or _detect_package_dir()
    repo_name = _detect_repo_name()
    description = args.description or f"Documentation for {project_name}"

    if not package_dir:
        print(
            "error: could not detect a Python package. "
            "Pass --package NAME or create a package with __init__.py.",
            file=sys.stderr,
        )
        return 1

    # --- Write repoquill.yml ---
    config_path = os.path.join(os.getcwd(), "repoquill.yml")
    if os.path.exists(config_path) and not args.force:
        print(f"error: {config_path} already exists (use --force to overwrite)", file=sys.stderr)
        return 1

    repo_owner, _, repo_slug = repo_name.partition("/")
    if not repo_slug:
        repo_owner, repo_slug = "", repo_name

    config_content = _CONFIG_TEMPLATE.format(
        project_name=project_name,
        package_dir=package_dir,
        description=description,
        repo_name=repo_name,
        repo_owner=repo_owner,
        repo_slug=repo_slug,
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
        wf_content = _WORKFLOW_TEMPLATE.format(api_key_env="OPENAI_API_KEY")
        with open(wf_path, "w", encoding="utf-8") as f:
            f.write(wf_content)
        print(f"  created {wf_path}")

    print()
    print("Next steps:")
    print(f"  1. Edit repoquill.yml — set site.url, narrative_sections, etc.")
    print("  2. Add your LLM API key as a GitHub secret:")
    print("     Settings → Secrets and variables → Actions → New repository secret")
    print("     Name: LLM_API_KEY   Value: sk-...")
    print("  3. Push to main — docs will build automatically.")
    print("  4. Local preview:  repoquill serve")
    return 0


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
    init.add_argument("--force", action="store_true", help="Overwrite existing files")

    sub.add_parser("plan", parents=[common], help="Show the page plan")
    gen = sub.add_parser("generate", parents=[common], help="Generate docs")
    gen.add_argument("--no-llm", action="store_true", help="Skip LLM layer")
    gen.add_argument("--force", action="store_true", help="Full regenerate")
    gen.add_argument("--build", action="store_true", help="Also run mkdocs build")

    build = sub.add_parser("build", parents=[common], help="Generate + mkdocs build")
    build.add_argument("--no-llm", action="store_true", help="Skip LLM layer")
    build.add_argument("--force", action="store_true", help="Full regenerate")

    serve = sub.add_parser("serve", parents=[common], help="Generate + local preview")
    serve.add_argument("--no-llm", action="store_true", help="Skip LLM layer")
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
