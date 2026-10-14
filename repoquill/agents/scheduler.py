"""Parallel scheduling of agentic documentation pages.

Thin orchestration over :func:`repoquill.agents.author.run_page_agent`:
authours a set of independent pages with bounded concurrency and per-page
isolation (one page's failure never stops the batch), and optionally runs
the **independent** verifier (:mod:`repoquill.agents.verify`) on each
produced page.

The scheduler does NOT write to any file other than what the author's
``write_doc`` tool already does (the docs output dir). It records
retry-safe per-page state on the page dicts (via the manifest helpers) so a
failed page is retried on the next run.

Independent verification is kept separate from the writing agent on
purpose: the author may execute examples while writing, but the
pass/fail decision comes from :mod:`repoquill.agents.verify`, which the
author never calls.
"""

from __future__ import annotations

import importlib
import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from repoquill.agents import verify as agent_verify
from repoquill.agents.author import (
    run_page_agent,
    run_page_agent_specialized,
)
from repoquill.agents.contracts import (
    AgentBudget,
    AuthorResult,
    EvidencePack,
    PageTask,
    ToolContext,
    VerificationResult,
)
from repoquill.agents.tools import RepoQuillTools
from repoquill.core.manifest import (
    record_page_failure,
    record_page_success,
)
from repoquill.plan import page_needs_regeneration


@dataclass
class PageOutcome:
    """The combined result of authoring (and optionally verifying) a page."""

    task: PageTask
    author: AuthorResult
    verification: Optional[VerificationResult] = None

    @property
    def ok(self) -> bool:
        """A page is ok when authored AND (if verified) independently passed."""
        if not self.author.ok:
            return False
        if self.verification is not None:
            return self.verification.passed
        return True

    def as_dict(self) -> Dict[str, Any]:
        d = {
            "slug": self.task.slug,
            "ok": self.ok,
            "author": self.author.as_dict(),
        }
        if self.verification is not None:
            d["verification"] = self.verification.as_dict()
        return d


def run_pages(
    tasks: List[PageTask],
    ctx: ToolContext,
    client,
    max_parallel: int = 3,
    role: str = "unified",
    verify_each: bool = False,
    run_examples: bool = True,
    coverage_threshold: float = 0.6,
    max_tokens: int = 8192,
    temperature: float = 0.3,
    budget=None,
    evidence_by_slug: Optional[Dict[str, EvidencePack]] = None,
) -> List[PageOutcome]:
    """Author *tasks* with bounded concurrency and per-page isolation.

    Args:
        tasks: The pages to author.
        ctx: The tool context (roots + policy).
        client: A duck-typed LLM client with ``chat_with_tools``.
        max_parallel: Max pages authored concurrently (1 = sequential).
        role: ``"unified"`` (default) or ``"specialized"``.
        verify_each: When true, run the independent verifier on each
            successfully authored page and attach the result.
        run_examples / coverage_threshold: Verification knobs.
        budget: Optional shared :class:`AgentBudget` template; a fresh copy
            is made per page. When None, each page gets a default budget.
        evidence_by_slug: Optional slug -> :class:`EvidencePack` map of
            deterministic starting evidence handed to each author (the
            agent confirms and extends it with live tool calls).
    """
    if not tasks:
        return []

    registry = RepoQuillTools(ctx)
    outcomes: List[PageOutcome] = [None] * len(tasks)  # type: ignore

    def _one(idx_task):
        idx, task = idx_task
        page_budget = (AgentBudget(
            max_steps=budget.max_steps, max_llm_calls=budget.max_llm_calls,
            max_page_chars=budget.max_page_chars) if budget is not None
            else AgentBudget())
        pack = (evidence_by_slug or {}).get(task.slug)
        try:
            if role == "specialized":
                author = run_page_agent_specialized(
                    task, ctx, registry, client, budget=page_budget,
                    evidence=pack, max_tokens=max_tokens)
            else:
                author = run_page_agent(
                    task, ctx, registry, client, budget=page_budget,
                    evidence=pack, max_tokens=max_tokens,
                    temperature=temperature)
        except Exception as e:  # noqa: BLE001 - isolate per page
            author = AuthorResult(slug=task.slug, ok=False,
                                  error=f"scheduler isolation: {e}")
        verification = None
        if verify_each and author.ok and os.path.isfile(task.out_path):
            try:
                verification = agent_verify.verify_page_file(
                    task.slug, task.out_path, task, ctx,
                    run_examples=run_examples,
                    coverage_threshold=coverage_threshold)
            except Exception as e:  # noqa: BLE001
                verification = agent_verify.VerificationResult(
                    slug=task.slug, passed=False,
                    summary=f"verifier error: {e}")
        return idx, PageOutcome(task=task, author=author,
                                verification=verification)

    max_workers = max(1, int(max_parallel))
    if max_workers == 1:
        for idx, task in enumerate(tasks):
            outcomes[idx] = _one((idx, task))[1]
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_one, (idx, t))
                       for idx, t in enumerate(tasks)]
            for fut in as_completed(futures):
                idx, outcome = fut.result()
                outcomes[idx] = outcome

    return outcomes


def _symbols_in_files(files: List[str], pkg_path: str) -> List[str]:
    """Public (top-level, non-underscore) symbols defined in *files*.

    Used to scope a page's semantic-coverage checklist to the source files
    that page actually documents, so a "getting started" page is not
    expected to cover the entire package.
    """
    import ast

    syms = set()
    for f in files:
        path = os.path.join(pkg_path, f)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                tree = ast.parse(fh.read())
        except (SyntaxError, OSError, ValueError):
            continue
        for node in getattr(tree, "body", []):  # top-level only
            if isinstance(node, (ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                if not node.name.startswith("_"):
                    syms.add(node.name)
    return sorted(syms)


def _page_to_task(page: Dict[str, Any], cfg, out_path: str) -> PageTask:
    from repoquill.agents import evidence as agent_evidence

    source_files = list(page.get("source_files", []))
    task = PageTask(
        slug=page["slug"],
        title=page.get("title", page["slug"]),
        description=page.get("description", ""),
        source_hints=source_files,
        out_path=out_path,
    )
    # Coverage checklist: scoped to the page's own source files when they
    # are known (reasonable per-page expectation); otherwise the package's
    # public symbols as a broader default.
    if source_files:
        task.coverage_checklist = _symbols_in_files(source_files, cfg.pkg_path)
    if not task.coverage_checklist:
        try:
            task.coverage_checklist = agent_evidence.coverage_checklist(
                task, cfg.pkg_path)
        except Exception:  # noqa: BLE001
            task.coverage_checklist = []
    return task


def run_agentic_generation(
    pages: List[Dict[str, Any]],
    cfg,
    client,
    agentic_cfg,
    old_hashes: Optional[Dict[str, str]] = None,
    new_hashes: Optional[Dict[str, str]] = None,
    force_slugs: Optional[set] = None,
    verify_each: bool = False,
) -> List[str]:
    """Author the narrative pages that need (re)generation, in parallel.

    This is the agentic drop-in for the legacy
    :func:`repoquill.narrative.generate_all_pages`: it honors the same
    incremental skip logic (via :func:`page_needs_regeneration` +
    ``force_slugs``), records retry-safe per-page state on the page dicts,
    and returns the list of successfully authored slugs.

    Args:
        pages: The plan's page dicts (mutated in place for manifest state).
        cfg: A loaded :class:`repoquill.config.RepoQuillConfig`.
        client: A duck-typed LLM client with ``chat_with_tools``.
        agentic_cfg: The :class:`repoquill.config.AgenticConfig`.
        old_hashes / new_hashes: Source hashes for incremental skipping.
        force_slugs: Slugs to force-regenerate (cross-file impact).
        verify_each: When true, attach independent verification results
            (the CLI normally runs verification centrally instead).

    Returns:
        List of slugs that were (re)generated successfully.
    """
    from repoquill.agents import evidence as agent_evidence
    from repoquill.agents.tools import build_tool_context

    old_hashes = old_hashes or {}
    new_hashes = new_hashes or {}

    ctx = build_tool_context(
        cfg,
        execute_examples=agentic_cfg.execute_examples,
        example_timeout=agentic_cfg.example_timeout,
        max_file_chars=agentic_cfg.max_file_chars,
    )

    to_generate: List[PageTask] = []
    evidence_by_slug: Dict[str, EvidencePack] = {}
    for page in pages:
        slug = page["slug"]
        out_path = os.path.join(cfg.out_guides, f"{slug}.md")
        forced = force_slugs is not None and slug in force_slugs
        if not forced and not page_needs_regeneration(
                page, old_hashes, new_hashes, out_path):
            print(f"  {page.get('title', slug)} — SKIP (source unchanged)")
            continue
        task = _page_to_task(page, cfg, out_path)
        try:
            pack = agent_evidence.build_evidence_pack(
                task, cfg.pkg_path, cfg.root)
        except Exception:  # noqa: BLE001 - evidence is a starting hint only
            pack = None
        if pack is not None:
            evidence_by_slug[slug] = pack
            # Never replace a scoped (source-file) checklist with the
            # broader package-level one; only fill in when empty.
            if not task.coverage_checklist:
                task.coverage_checklist = list(pack.coverage_checklist)
        to_generate.append(task)

    if not to_generate:
        return []

    print(f"  Agentic generation: {len(to_generate)} page(s), "
          f"{max(1, agentic_cfg.max_parallel_pages)} worker(s), "
          f"role={agentic_cfg.roles}")
    outcomes = run_pages(
        to_generate, ctx, client,
        max_parallel=agentic_cfg.max_parallel_pages,
        role=agentic_cfg.roles,
        verify_each=verify_each,
        run_examples=agentic_cfg.execute_examples,
        coverage_threshold=agentic_cfg.coverage_threshold,
        budget=AgentBudget(
            max_steps=agentic_cfg.max_steps,
            max_llm_calls=agentic_cfg.max_llm_calls,
            max_page_chars=agentic_cfg.max_page_chars,
        ),
        evidence_by_slug=evidence_by_slug,
    )

    generated: List[str] = []
    for outcome in outcomes:
        task = outcome.task
        page = next((p for p in pages if p["slug"] == task.slug), None)
        ok = outcome.ok
        if ok:
            out_path = os.path.join(cfg.out_guides, f"{task.slug}.md")
            if page is not None:
                record_page_success(page, out_path)
            generated.append(task.slug)
            vinfo = ""
            if outcome.verification is not None:
                vinfo = (f", coverage "
                         f"{outcome.verification.coverage.ratio:.2f}")
            print(f"    {task.slug}: OK "
                  f"(steps={outcome.author.steps}, "
                  f"llm_calls={outcome.author.llm_calls}{vinfo})")
        else:
            if outcome.author.ok and outcome.verification is not None:
                reason = ("independent verification failed: "
                          + outcome.verification.summary)
            else:
                reason = outcome.author.error or "agentic author failed"
            if page is not None:
                record_page_failure(page, reason)
            print(f"    {task.slug}: FAILED — {reason}")

    return generated


# --------------------------------------------------------------------------- #
# Pi engine (M2): one real Pi process per page, docs-only, staged output
# --------------------------------------------------------------------------- #
def build_pi_system_prompt(
    *,
    title: str,
    description: str,
    staged_path: str,
    allow_example_exec: bool = False,
) -> str:
    """Docs-only authoring system prompt for one Pi page task.

    The prompt references the vetted tool set and the single staged output
    path the page must end up at. Kept module-level (no closure) so it can
    be unit-tested directly.
    """
    tools = ("list_files, read_file, search_code, inspect_api, "
             "inspect_tests, write_doc")
    if allow_example_exec:
        tools += ", run_example"
    desc = f" Description: {description}." if description else ""
    return (
        "You are a documentation author working on exactly one page of a "
        "documentation site.\n\n"
        f"PAGE: {title}.{desc}\n\n"
        "Rules:\n"
        f"- You may write ONLY the single file at exactly this path: "
        f"{staged_path}\n"
        f"- Ground every claim in the repository using: {tools}. Never "
        "invent APIs, arguments, or behavior.\n"
        "- Source files are read-only; writing anywhere else is forbidden.\n"
        "- When finished, the page must exist at that exact path as "
        "Markdown."
    )


def _evidence_to_text(pack) -> str:
    """Flatten an :class:`EvidencePack` into plain text for a PiTask."""
    if pack is None:
        return ""
    parts: List[str] = []
    if pack.file_tree:
        parts.append("FILE TREE:\n" + pack.file_tree)
    if pack.candidate_files:
        parts.append("CANDIDATE FILES:\n"
                     + "\n".join(f"- {f}" for f in pack.candidate_files))
    if pack.api_surface:
        parts.append("API SURFACE:\n" + pack.api_surface)
    if pack.candidate_tests:
        parts.append("CANDIDATE TESTS:\n"
                     + "\n".join(f"- {t}" for t in pack.candidate_tests))
    if pack.readme_excerpt:
        parts.append("README EXCERPT:\n" + pack.readme_excerpt)
    return "\n\n".join(parts)


def _start_bridge(server_cls, *, source_root: str, staging_dir: str,
                  slug: str, execute_examples: bool):
    """Construct (and start, if it exposes ``start``) one PiBridgeServer
    scoped to a single task.

    The bridge module is a parallel workstream landing at the same time;
    this adapter accepts the documented shape
    ``(source_root, staged_docs_dir, slug, execute_examples)`` with
    keyword or positional arguments.
    """
    try:
        server = server_cls(source_root=source_root,
                            staging_docs_dir=staging_dir, slug=slug,
                            allow_example_exec=execute_examples)
    except TypeError:
        try:
            server = server_cls(source_root=source_root,
                                staged_docs_dir=staging_dir, slug=slug,
                                execute_examples=execute_examples)
        except TypeError:
            server = server_cls(source_root, staging_dir, slug,
                                execute_examples)
    start = getattr(server, "start", None)
    if callable(start):
        start()
    return server


def _stop_bridge(server) -> None:
    """Best-effort teardown of a bridge server."""
    for name in ("close", "stop", "shutdown"):
        fn = getattr(server, name, None)
        if callable(fn):
            try:
                fn()
            except Exception:  # noqa: BLE001 - teardown is best effort
                pass
            break


def run_pi_generation(
    pages: List[Dict[str, Any]],
    cfg,
    *,
    old_hashes: Optional[Dict[str, str]] = None,
    new_hashes: Optional[Dict[str, str]] = None,
    force_slugs: Optional[set] = None,
    verify_each: bool = True,
) -> List[str]:
    """Author the narrative pages that need (re)generation via **Pi**.

    Drop-in counterpart of :func:`run_agentic_generation`: same
    incremental skip logic (``page_needs_regeneration`` + ``force_slugs``
    — unchanged pages cost zero Pi spawns), same retry-safe per-page
    manifest state on the page dicts, and the same return contract (list
    of successfully generated slugs).

    Each page gets its **own** Pi process and its own bridge server
    (per-task isolation); the ephemeral agent dir is built once per
    invocation and cleaned up in ``finally``. Pages are staged to a
    per-run temp directory and copied into ``cfg.out_guides`` only after
    the independent verifier passes (``verify_each``).

    Fail-closed: if the Pi binary cannot be resolved, a
    :class:`repoquill.pi.contracts.PiNotInstalledError` (or other
    :class:`PiError`) is raised BEFORE any page file is touched.
    Per-page failures are recorded on the page dict and do not stop the
    batch.

    All ``repoquill.pi`` imports are lazy so importing this module never
    requires Node/Pi to be present.
    """
    # Lazy: importing repoquill.agents.scheduler must not require Node/Pi.
    from repoquill.pi import bootstrap as pi_bootstrap
    from repoquill.pi import models as pi_models
    from repoquill.pi import contracts as pi_contracts
    from repoquill.pi.bridge import PiBridgeServer
    from repoquill.pi.rpc import PiRpcBackend
    from repoquill.agents import evidence as agent_evidence
    from repoquill.agents.tools import build_tool_context

    PiError = pi_contracts.PiError
    PiTask = pi_contracts.PiTask

    old_hashes = old_hashes or {}
    new_hashes = new_hashes or {}

    # --- Fail closed before any work: the Pi binary must exist ---------
    # find_pi() never raises; it returns None when nothing works.
    install = pi_bootstrap.find_pi()
    if install is None:
        raise pi_contracts.PiNotInstalledError(
            "Pi is not installed or not runnable. "
            f"Install the pinned runtime: npm install --prefix "
            f"{pi_contracts.DEFAULT_PI_CACHE_DIR} "
            f"{pi_contracts.PI_PACKAGE}@{pi_contracts.PI_PINNED_VERSION} "
            "(Node >= 18 required), or point "
            f"{pi_contracts.PI_BIN_ENV} at an existing pi executable. "
            "`repoquill doctor` shows readiness; --no-llm needs no Pi at "
            "all.")
    pi_bin = getattr(install, "binary", install)
    if (getattr(install, "version", None)
            and install.version != pi_contracts.PI_PINNED_VERSION):
        print(f"  warning: pi version {install.version} does not match "
              f"pinned {pi_contracts.PI_PINNED_VERSION}")
    pi_pkg = importlib.import_module("repoquill.pi")
    extension_path = os.path.join(os.path.dirname(pi_pkg.__file__),
                                  "extension.ts")

    agent_dir: Optional[str] = None
    staging_root: Optional[str] = None
    try:
        agent_dir = pi_models.build_ephemeral_agent_dir(cfg.llm)
        model = pi_models.model_pattern(cfg.llm)
        # The ephemeral models.json provider is keyed by slug (host-derived),
        # NOT by the user's llm.provider name. Pi's --provider must match the
        # slug embedded in the model pattern, otherwise Pi resolves the
        # built-in provider (e.g. "openai") and fails with "No API key found".
        pi_provider = model.split("/", 1)[0] if "/" in model else cfg.llm.provider
        staging_root = tempfile.mkdtemp(prefix="repoquill-pi-")

        ag = cfg.llm.agentic
        ag_raw = ((cfg.raw or {}).get("llm", {}) or {})
        ag_raw = ag_raw.get("agentic", {}) or {}
        execute_examples = bool(ag_raw.get("execute_examples", False))
        max_workers = max(1, int(ag_raw.get("parallelism", 4)))

        ctx = build_tool_context(
            cfg,
            execute_examples=execute_examples,
            example_timeout=ag.example_timeout,
            max_file_chars=ag.max_file_chars,
        )

        # --- Select the pages that actually need (re)generation --------
        to_generate: List[Dict[str, Any]] = []
        evidence_by_slug: Dict[str, Any] = {}
        for page in pages:
            slug = page["slug"]
            out_path = os.path.join(cfg.out_guides, f"{slug}.md")
            forced = force_slugs is not None and slug in force_slugs
            if not forced and not page_needs_regeneration(
                    page, old_hashes, new_hashes, out_path):
                print(f"  {page.get('title', slug)} — SKIP (source unchanged)")
                continue
            task = _page_to_task(page, cfg, out_path)
            try:
                pack = agent_evidence.build_evidence_pack(
                    task, cfg.pkg_path, cfg.root)
            except Exception:  # noqa: BLE001 - evidence is a starting hint
                pack = None
            if pack is not None:
                evidence_by_slug[slug] = pack
                if not task.coverage_checklist:
                    task.coverage_checklist = list(pack.coverage_checklist)
            to_generate.append(page)

        if not to_generate:
            return []

        print(f"  Pi generation: {len(to_generate)} page(s), "
              f"{max_workers} worker(s), 1 Pi process per page")

        # --- One Pi process per page ----------------------------------
        def _one(page: Dict[str, Any]):
            slug = page["slug"]
            out_path = os.path.join(cfg.out_guides, f"{slug}.md")
            task = _page_to_task(page, cfg, out_path)
            staged_path = os.path.join(staging_root, f"{slug}.md")
            prompt = build_pi_system_prompt(
                title=task.title,
                description=task.description,
                staged_path=staged_path,
                allow_example_exec=execute_examples,
            )
            pi_task = PiTask(
                slug=slug,
                title=task.title,
                description=task.description,
                evidence=_evidence_to_text(evidence_by_slug.get(slug)),
                source_root=cfg.root,
                staged_docs_dir=staging_root,
                provider=pi_provider,
                model=model,
                allow_example_exec=execute_examples,
                system_prompt=prompt,
                coverage_checklist=list(task.coverage_checklist),
            )
            server = None
            try:
                server = _start_bridge(
                    PiBridgeServer,
                    source_root=cfg.root,
                    staging_dir=staging_root,
                    slug=slug,
                    execute_examples=execute_examples,
                )
                # The Pi child must reach THIS page's bridge socket (per-
                # instance env, not os.environ — parallel pages each have
                # their own bridge).
                bridge_env = {
                    pi_contracts.BRIDGE_SOCKET_ENV: server.socket_path,
                    "REPOQUILL_ALLOW_EXAMPLE_EXEC":
                        "1" if execute_examples else "0",
                }
                backend = PiRpcBackend(pi_bin, extension_path,
                                       agent_dir=agent_dir,
                                       extra_env=bridge_env)
                result = backend.run(pi_task)
            except PiError as e:
                return slug, False, str(e)
            except Exception as e:  # noqa: BLE001 - isolate per page
                return slug, False, f"pi run error: {e}"
            finally:
                if server is not None:
                    _stop_bridge(server)

            if not result.ok:
                return slug, False, ("; ".join(result.errors)
                                     or "pi run did not complete")
            staged = result.output_path or staged_path
            if not os.path.isfile(staged):
                return slug, False, "staged file missing after pi run"

            # Independent verification BEFORE anything is published.
            if verify_each:
                try:
                    vres = agent_verify.verify_page_file(
                        slug, staged, task, ctx,
                        run_examples=execute_examples,
                        coverage_threshold=ag.coverage_threshold)
                except Exception as e:  # noqa: BLE001
                    return slug, False, f"verifier error: {e}"
                if not vres.passed:
                    return slug, False, (
                        "independent verification failed: "
                        + vres.summary)

            shutil.copyfile(staged, out_path)
            return slug, True, ""

        results: Dict[str, tuple] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_one, p): p["slug"]
                       for p in to_generate}
            for fut in as_completed(futures):
                slug, ok, detail = fut.result()
                results[slug] = (ok, detail)

        generated: List[str] = []
        for page in pages:
            slug = page["slug"]
            if slug not in results:
                continue
            ok, detail = results[slug]
            if ok:
                out_path = os.path.join(cfg.out_guides, f"{slug}.md")
                record_page_success(page, out_path)
                generated.append(slug)
                print(f"    {slug}: OK")
            else:
                record_page_failure(page, detail or "pi run failed")
                print(f"    {slug}: FAILED — {detail}")
        return generated
    finally:
        if agent_dir:
            try:
                pi_models.cleanup(agent_dir)
            except Exception:  # noqa: BLE001 - cleanup is best effort
                pass
        if staging_root:
            shutil.rmtree(staging_root, ignore_errors=True)
