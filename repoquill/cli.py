"""RepoQuill command-line interface.

Commands:
    repoquill plan      Show the page plan (which pages, which sources).
    repoquill generate  Run Layer 1 (reference) + Layer 2 (narrative).
    repoquill build     Generate + run ``mkdocs build`` to produce site/.

Flags:
    --config PATH       Path to repoquill.yml (default: ./repoquill.yml).
    --no-llm            Skip Layer 2 (deterministic reference only).
    --force             Full re-plan + regenerate everything.
    --build             Also run ``mkdocs build`` after generating.
    --source-root PATH  Override the source repo root.
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


def _run_mkdocs_build(cfg) -> None:
    """Run `mkdocs build` in the config directory."""
    print("\n[build] Running mkdocs build...")
    subprocess.run(
        [sys.executable, "-m", "mkdocs", "build"],
        cwd=cfg.config_dir, check=True,
    )
    print("  Site built to site/ ✓")


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
    build_index_md(cfg, pages, reference_modules)
    print("  index.md")

    nav = build_nav(cfg, pages, reference_modules)
    build_mkdocs_yml(cfg, nav)
    print("  mkdocs.yml")

    build_llms_txt(cfg, pages, reference_modules)
    build_llms_full_txt(cfg, pages, reference_modules)

    build_skill_md(cfg)

    _copy_images(cfg)

    n_guides = len([f for f in os.listdir(cfg.out_guides) if f.endswith(".md")])
    n_ref = len([f for f in os.listdir(cfg.ref_dir) if f.endswith(".md")])
    print(f"\nDone. {n_guides} guide pages + {n_ref} reference pages in {cfg.site_src}")

    if args.build:
        _run_mkdocs_build(cfg)
    return 0


def _cmd_build(args) -> int:
    args.build = True
    return _cmd_generate(args)


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
    common.add_argument("--config", default=None, help="Path to repoquill.yml")
    common.add_argument(
        "--source-root", default=None, help="Override the source repo root"
    )

    sub.add_parser("plan", parents=[common], help="Show the page plan")
    gen = sub.add_parser("generate", parents=[common], help="Generate docs")
    gen.add_argument("--no-llm", action="store_true", help="Skip LLM layer")
    gen.add_argument("--force", action="store_true", help="Full regenerate")
    gen.add_argument("--build", action="store_true", help="Also run mkdocs build")

    build = sub.add_parser("build", parents=[common], help="Generate + mkdocs build")
    build.add_argument("--no-llm", action="store_true", help="Skip LLM layer")
    build.add_argument("--force", action="store_true", help="Full regenerate")

    args = parser.parse_args(argv)

    try:
        if args.command == "plan":
            return _cmd_plan(args)
        elif args.command == "generate":
            return _cmd_generate(args)
        elif args.command == "build":
            return _cmd_build(args)
        else:
            parser.error(f"Unknown command: {args.command}")
            return 2
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"error: mkdocs build failed (exit {e.returncode})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
