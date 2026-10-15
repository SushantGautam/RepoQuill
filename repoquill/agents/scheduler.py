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
import re
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
    pkg_name = os.path.basename(os.path.normpath(pkg_path))
    for f in files:
        # Planners may emit package-relative ("judges/x.py") or
        # repo-root-relative ("pkg/judges/x.py") paths; normalize to
        # package-relative.
        f_norm = f.replace(os.sep, "/")
        if f_norm.startswith(pkg_name + "/"):
            f_norm = f_norm[len(pkg_name) + 1:]
        path = os.path.join(pkg_path, *f_norm.split("/"))
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
    siblings: Optional[List[tuple]] = None,
) -> str:
    """Docs-only authoring system prompt for one Pi page task.

    The prompt references the vetted tool set, the single staged output
    path the page must end up at, and (when *siblings* is given) the
    other pages of the site so cross-links are concrete. Kept
    module-level (no closure) so it can be unit-tested directly.

    *siblings*: iterable of ``(slug, title)`` for the OTHER pages of
    this documentation site (used for the mandatory "Where to go next"
    section; sibling cross-links use the page-relative ``<slug>.md``
    form, because every guide lives in the same ``docs/guides/`` dir).
    """
    tools = ("list_files, read_file, search_code, inspect_api, "
             "inspect_tests, write_doc")
    if allow_example_exec:
        tools += ", run_example"
    desc = f" Description: {description}." if description else ""
    siblings_note = ""
    if siblings:
        listing = "; ".join(
            f"'{s}' ({t})" for s, t in siblings if s)
        siblings_note = (
            "\n- SIBLING PAGES of this site (cross-link with "
            "page-relative links of the form `<slug>.md` — e.g. link to "
            "the sibling slug 'quickstart' as `quickstart.md`, NOT "
            "`guides/quickstart.md`; this page and every sibling live in "
            f"the same directory): {listing}.\n")
    return (
        "You are a documentation author working on exactly one page of a "
        "documentation site.\n\n"
        f"PAGE: {title}.{desc}\n\n"
        "Rules:\n"
        f"- You may write ONLY the single file at exactly this path: "
        f"{staged_path}\n"
        f"- Ground every claim in the repository using: {tools}. Never "
        "invent APIs, arguments, or behavior.\n"
        "- VERIFY every API reference against the source before you "
        "assert it: for each symbol you reference, confirm the exact "
        "parameter names, the exact method signature, and the exact "
        "attribute names (via inspect_api / inspect_tests and the "
        "files you read). Do not paraphrase or guess from a similar "
        "API; do not attribute a parameter or attribute to a method "
        "that does not take it; and if you cannot confirm a claim "
        "from source, do not state it.\n"
        "- Every fenced code example must be RUNNABLE AS DISPLAYED: "
        "construct or define every variable it uses (no elided "
        "objects), wrap async calls appropriately (e.g. "
        "asyncio.run(...)), and never rely on state that was not "
        "shown in the example.\n"
        "- If the package supports offline or fake usage (fakes, fake "
        "clients, deterministic no-network paths — check tests/ and "
        "examples/ for them), include a short 'Offline usage (no API "
        "key)' section showing the no-key path.\n"
        "- Do not duplicate another page's primary topic: if a symbol "
        "is covered by a sibling page, link to that page instead of "
        "re-explaining it, and link out to related pages where "
        "natural.\n"
        "- The page MUST end with a 'Where to go next' section of "
        "real hyperlinks to the sibling pages relevant to a reader "
        "who just finished this page.\n"
        + siblings_note
        + "- Source files are read-only; writing anywhere else is "
        "forbidden.\n"
        "- When finished, the page must exist at that exact path as "
        "Markdown."
    )


def _evidence_to_text(pack, pkg_prefix: str = "") -> str:
    """Flatten an :class:`EvidencePack` into plain text for a PiTask.

    ``pkg_prefix`` is the package directory's path relative to the
    repository root (e.g. ``"simpleaudit"``); candidate source files are
    package-relative in the pack and are re-labeled repo-root-relative
    here, because the agent's read tools resolve paths against the
    repository root.
    """
    if pack is None:
        return ""
    parts: List[str] = [
        "All file paths below are relative to the repository root"
        + (f" (the package lives under '{pkg_prefix}/')"
           if pkg_prefix else "")
        + ".",
    ]
    if pack.file_tree:
        parts.append("FILE TREE:\n" + pack.file_tree)
    if pack.candidate_files:
        pre = f"{pkg_prefix}/" if pkg_prefix else ""
        parts.append("CANDIDATE FILES:\n"
                     + "\n".join(f"- {pre}{f}" for f in pack.candidate_files))
    if pack.api_surface:
        parts.append("API SURFACE:\n" + pack.api_surface)
    if getattr(pack, "symbol_outlines", ""):
        parts.append(
            "SYMBOL OUTLINES (line numbers of the page's planned "
            "source files — you know each file's shape now; read only "
            "the ranges around the symbols you will document, not "
            "whole files):\n" + pack.symbol_outlines)
    if pack.candidate_tests:
        parts.append("CANDIDATE TESTS:\n"
                     + "\n".join(f"- {t}" for t in pack.candidate_tests))
    if pack.readme_excerpt:
        parts.append("README EXCERPT:\n" + pack.readme_excerpt)
    return "\n\n".join(parts)


def _start_bridge(server_cls, *, source_root: str, staging_dir: str,
                  slug: str, execute_examples: bool,
                  max_tool_calls: int = 0, timeout_s: float = 0.0):
    """Construct (and start, if it exposes ``start``) one PiBridgeServer
    scoped to a single task.

    ``max_tool_calls`` / ``timeout_s`` are the page's budget and
    deadline; the bridge uses them to enforce write-only mode (read/
    search calls refused once the exploration budget is spent) — the
    hard backstop behind the RPC progress nudge. Older bridge shapes
    without these kwargs are still supported (write-only enforcement
    simply absent).
    """
    try:
        server = server_cls(source_root=source_root,
                            staging_docs_dir=staging_dir, slug=slug,
                            allow_example_exec=execute_examples,
                            max_tool_calls=max_tool_calls,
                            timeout_s=timeout_s)
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


def _pi_activity_summary(result: Any) -> str:
    """Compact, evidence-based activity summary for a Pi run result.

    Answers the questions a reviewer needs after a FAILED page: how many
    tool calls the agent made, whether it ever reached ``write_doc``,
    peak token usage, and the redacted stderr tail (if any). Used to make
    per-page failure reasons diagnostic instead of generic.
    """
    calls = result.tool_calls
    wrote = any(tc.name == "write_doc" and not tc.is_error for tc in calls)
    parts = [
        "%d tool call(s), write_doc=%s"
        % (len(calls), "yes" if wrote else "no"),
        "total_tokens=%d" % result.usage.total_tokens,
    ]
    tail = (getattr(result, "stderr_tail", "") or "").strip()
    if tail:
        parts.append("stderr tail: " + tail[-300:])
    return "; ".join(parts)


#: Endpoint status codes that indicate a provider-side (not authoring)
#: failure and are worth exactly one retry.
_ENDPOINT_ERR_RE = re.compile(r"\b(?:429|5\d{2})\b")


def _is_transient_endpoint_failure(error_text: str,
                                   result: Any = None) -> bool:
    """Decide whether a page failure is a transient ENDPOINT failure
    where exactly one retry from a fresh context is cheap and sensible.

    Two conditions (nothing else is retried):

    * the error text carries an endpoint status (429/5xx);
    * the model ended with ``stopReason=error`` while consuming nothing
      (0 tool calls, 0 tokens): the endpoint refused the very first
      model response. Measured case: a valid key received one transient
      401 from a proxy, which Pi surfaced as a bare
      ``message_end stopReason=error`` with no status code at all — the
      status regex above cannot match it, but the zero-consumption
      shape is unambiguous and the retry is nearly free because nothing
      was consumed yet.
    """
    if _ENDPOINT_ERR_RE.search(error_text):
        return True
    if (result is not None and "stopReason=error" in error_text
            and not result.tool_calls
            and not result.usage.total_tokens):
        return True
    return False


def _is_deadline_exhaustion(error_text: str) -> bool:
    """True when a run died on its deadline WITHOUT writing the page
    (the ``scenarios`` class: 241 calls / 179k tokens / 900s, no
    write_doc). Matches only the mid-run deadline error (the
    "did not reach agent_settled" message), not the startup timeout
    ("timed out waiting for the Pi RPC stream"), which says nothing
    about authoring progress.
    """
    return "did not reach agent_settled" in (error_text or "")


def _is_over_exploration_failure(errors) -> bool:
    """True when a run died by over-exploring without producing a page.

    Two measured failure classes: the tool-call budget running out
    ("tool-call budget of N exceeded") and the repeat-call orbit breaker
    ("the agent is orbiting", fired when the identical tool call is issued
    ``max_repeat_calls`` times). Both mean the page was not written, and a
    fresh-context retry with source excerpts pre-loaded (so the retry needs
    far fewer tool calls and is less likely to re-loop) is cheap and wins
    often. Endpoint / deadline / verification failures are NOT over-
    exploration and are handled by their own branches.
    """
    for e in errors or []:
        if "tool-call budget" in e or "orbiting" in e:
            return True
    return False


#: Per-file / total caps for the retry's pre-loaded source excerpts:
#: enough to write the page from, small enough to stay in the prompt.
_RETRY_EXCERPT_FILES = 6
_RETRY_EXCERPT_PER_FILE_CHARS = 6000
_RETRY_EXCERPT_TOTAL_CHARS = 20000


def _source_excerpts_text(
    task: "PageTask",
    pack: Optional[Any],
    pkg_prefix: str,
    root: str,
    pkg_path: str,
) -> str:
    """Concise source excerpts for the page's planned source files.

    Pre-loaded into the RETRY attempt's task prompt after a
    budget/timeout failure so the retry needs far fewer tool calls
    (measured: quickstart succeeded on its retry at 18/24 calls; with
    the excerpts pre-loaded the target is <10). Generic: the planned
    files come from the evidence pack's candidate files (falling back
    to the page's own source hints), and only the head of each file is
    taken — the retry is expected to read more only if genuinely
    missing.
    """
    files: List[str] = []
    if pack is not None and getattr(pack, "candidate_files", None):
        pre = f"{pkg_prefix}/" if pkg_prefix else ""
        files = [f"{pre}{f}" for f in pack.candidate_files]
    if not files:
        pkg_name = os.path.basename(os.path.normpath(pkg_path))
        pre = f"{pkg_prefix}/" if pkg_prefix else ""
        for hint in task.source_hints:
            norm = str(hint).replace(os.sep, "/")
            if norm.startswith(pkg_name + "/"):
                norm = norm[len(pkg_name) + 1:]
            files.append(f"{pre}{norm}")
    blocks: List[str] = []
    total = 0
    for rel in files[:_RETRY_EXCERPT_FILES]:
        full = os.path.join(root, *rel.split("/"))
        if not os.path.isfile(full):
            continue
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        if len(text) > _RETRY_EXCERPT_PER_FILE_CHARS:
            text = text[:_RETRY_EXCERPT_PER_FILE_CHARS] + \
                "\n# ... (excerpt ends; read_file this path for more)"
        blocks.append(f"### {rel}\n```\n{text}\n```")
        total += len(text)
        if total >= _RETRY_EXCERPT_TOTAL_CHARS:
            break
    if not blocks:
        return ""
    return (
        "SOURCE EXCERPTS — PRE-LOADED FOR THIS RETRY ATTEMPT:\n"
        "The source of the page's planned files is included below so "
        "you do NOT have to re-read it. Verify from these excerpts; "
        "only read_file / search_code what they do not cover. Your "
        "goal is to call write_doc within the next few tool calls.\n\n"
        + "\n\n".join(blocks)
    )


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
            "(Node >= 22.19.0 required), or point "
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
        ag = cfg.llm.agentic
        ag_raw = ((cfg.raw or {}).get("llm", {}) or {})
        ag_raw = ag_raw.get("agentic", {}) or {}
        # Declare the endpoint's real context window to Pi. The product
        # default (32768) is conservative: over-declaring would surface
        # hard 4xx context-limit errors on smaller endpoints, while
        # under-declaring makes Pi compact early and the agent re-reads
        # files it has already seen (observed in the SimpleAudit baseline:
        # repeated greps of the same test files after ~32k tokens).
        # getattr: some call sites/tests pass duck-typed agentic
        # configs (SimpleNamespace) that predate these keys.
        context_window = int(ag_raw.get(
            "context_window", getattr(ag, "context_window", 32768)))
        keep_recent = int(ag_raw.get(
            "compaction_keep_recent_tokens",
            getattr(ag, "compaction_keep_recent_tokens", 60000)))
        agent_dir = pi_models.build_ephemeral_agent_dir(
            cfg.llm, context_window=context_window,
            compaction_keep_recent_tokens=keep_recent)
        model = pi_models.model_pattern(cfg.llm)
        # The ephemeral models.json provider is keyed by slug (host-derived),
        # NOT by the user's llm.provider name. Pi's --provider must match the
        # slug embedded in the model pattern, otherwise Pi resolves the
        # built-in provider (e.g. "openai") and fails with "No API key found".
        pi_provider = model.split("/", 1)[0] if "/" in model else cfg.llm.provider
        staging_root = tempfile.mkdtemp(prefix="repoquill-pi-")

        execute_examples = bool(ag_raw.get("execute_examples", False))
        max_workers = max(1, int(ag_raw.get("parallelism", 4)))
        # Per-page Pi deadline: large repos + slow remote endpoints can
        # exceed 300s, so the product default is 900s; configurable via
        # llm.agentic.timeout_s.
        pi_timeout_s = float(ag_raw.get(
            "timeout_s", getattr(ag, "timeout_s", 900.0)))
        # Per-attempt tool-call budget (loop guard); 0 disables. The
        # product default (80) is small on purpose: a failing attempt
        # should die by ~call 80 so the fresh-context retry (with
        # pre-loaded source excerpts) has time and budget to write the
        # page instead of orbiting 250 calls a second time.
        max_tool_calls = int(ag_raw.get(
            "max_tool_calls", getattr(ag, "max_tool_calls", 80)))
        # Repeat-call guard (orbit guard); 0 disables it.
        max_repeat_calls = int(ag_raw.get(
            "max_repeat_calls", getattr(ag, "max_repeat_calls", 6)))
        # Candidate source files in the evidence pack are
        # package-relative; the agent's read tools are repo-root-relative.
        try:
            pkg_prefix = os.path.relpath(
                os.path.abspath(cfg.pkg_path),
                os.path.abspath(cfg.root),
            ).replace(os.sep, "/")
        except ValueError:  # different drives (Windows) — no prefix
            pkg_prefix = ""
        if pkg_prefix.startswith(".."):
            pkg_prefix = ""

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
        # Endpoint-flakiness guard: when a page's Pi run fails with a
        # transient endpoint error (see _is_transient_endpoint_failure),
        # exactly one retry is made before the failure is recorded.

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
                siblings=[(p["slug"], p.get("title", p["slug"]))
                          for p in pages if p["slug"] != slug],
            )
            pack = evidence_by_slug.get(slug)
            evidence_text = _evidence_to_text(pack, pkg_prefix=pkg_prefix)

            def _attempt(retry: bool = False):
                """Spawn one Pi process for this page; (result, error).

                ``retry=True`` builds the UPGRADED retry task: the same
                evidence plus pre-loaded source excerpts, so a retry
                after a budget/timeout failure needs far fewer tool
                calls than the attempt it replaces.
                """
                evidence = evidence_text
                if retry:
                    excerpts = _source_excerpts_text(
                        task, pack, pkg_prefix, cfg.root, cfg.pkg_path)
                    if excerpts:
                        evidence = (evidence_text + "\n\n" + excerpts)
                pi_task = PiTask(
                    slug=slug,
                    title=task.title,
                    description=task.description,
                    evidence=evidence,
                    source_root=cfg.root,
                    staged_docs_dir=staging_root,
                    provider=pi_provider,
                    model=model,
                    allow_example_exec=execute_examples,
                    timeout_s=pi_timeout_s,
                    system_prompt=prompt,
                    coverage_checklist=list(task.coverage_checklist),
                    max_tool_calls=max_tool_calls,
                    max_repeat_calls=max_repeat_calls,
                )
                server = None
                try:
                    server = _start_bridge(
                        PiBridgeServer,
                        source_root=cfg.root,
                        staging_dir=staging_root,
                        slug=slug,
                        execute_examples=execute_examples,
                        max_tool_calls=max_tool_calls,
                        timeout_s=pi_timeout_s,
                    )
                    # The Pi child must reach THIS page's bridge socket
                    # (per-instance env, not os.environ — parallel pages
                    # each have their own bridge).
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
                    return None, str(e)
                except Exception as e:  # noqa: BLE001 - isolate per page
                    return None, f"pi run error: {e}"
                finally:
                    if server is not None:
                        _stop_bridge(server)
                return result, None

            result, run_error = _attempt()
            if run_error is not None:
                # Match endpoint codes on the base error only: the
                # bracketed activity diagnostics may contain numbers
                # (token totals, call counts) that look like 5xx/429.
                base_error = run_error.split(" [", 1)[0]
                if _is_transient_endpoint_failure(base_error):
                    print(f"    {slug}: endpoint error "
                          f"({run_error[:120]}) — one retry")
                    result, run_error = _attempt()
                elif _is_deadline_exhaustion(base_error):
                    # Deadline hit with real consumption and no page:
                    # retry from a fresh context with the source
                    # excerpts pre-loaded (target: <10 tool calls).
                    print(f"    {slug}: deadline hit without a page "
                          f"({run_error[:120]}) — one retry with "
                          f"pre-loaded source excerpts")
                    result, run_error = _attempt(retry=True)
            if run_error is not None:
                return slug, False, run_error
            if not result.ok:
                detail = ("; ".join(result.errors)
                          or "pi run did not complete")
                detail += " [%s]" % _pi_activity_summary(result)
                # Search only the recorded errors for endpoint codes:
                # activity counters (token counts, call counts) must not
                # look like a 5xx/429 status.
                if _is_transient_endpoint_failure("; ".join(result.errors),
                                                  result):
                    print(f"    {slug}: endpoint error ({detail[:120]}) "
                          f"— one retry")
                    result, run_error = _attempt()
                    if run_error is not None:
                        return slug, False, run_error
                    if result.ok:
                        # Recovered by the retry: continue as a success.
                        pass
                    else:
                        return slug, False, (
                            ("; ".join(result.errors)
                             or "pi run did not complete")
                            + " (after retry) [%s]"
                              % _pi_activity_summary(
                                  result))
                elif _is_over_exploration_failure(result.errors):
                    # Over-exploration failure: the tool-call budget ran
                    # out, or the repeat-call orbit breaker fired (the
                    # agent looped on an identical call). One retry from a
                    # fresh context, UPGRADED: the source excerpts are
                    # pre-loaded into the retry's task prompt so it needs
                    # far fewer tool calls and is less likely to re-loop on
                    # the same read (measured: quickstart succeeded on
                    # budget retry at 18/24 calls).
                    print(f"    {slug}: over-explored/orbiting "
                          f"— one retry with pre-loaded source excerpts")
                    result, run_error = _attempt(retry=True)
                    if run_error is not None:
                        return slug, False, run_error
                    if result.ok:
                        # Recovered by the retry: continue as a success.
                        pass
                    else:
                        return slug, False, (
                            ("; ".join(result.errors)
                             or "pi run did not complete")
                            + " (after over-exploration retry) [%s]"
                              % _pi_activity_summary(result))
                else:
                    return slug, False, detail
            staged = result.output_path or staged_path
            if not os.path.isfile(staged):
                return slug, False, (
                    "staged file missing after pi run "
                    "[%s]" % _pi_activity_summary(result))

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
