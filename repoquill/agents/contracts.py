"""Shared contracts for RepoQuill's agentic documentation engine.

This module is the **single source of truth** for the data shapes and the
tool surface shared across the agentic engine:

* :mod:`repoquill.agents.tools` — the tool runtime (implements the tools
  declared in :data:`TOOL_SCHEMAS`);
* :mod:`repoquill.agents.author` — the multi-step tool-calling author loop;
* :mod:`repoquill.agents.evidence` — deterministic evidence discovery;
* :mod:`repoquill.agents.verify` — independent verification;
* :mod:`repoquill.agents.scheduler` — parallel page scheduling;
* :class:`repoquill.llm.LLMClient` — :meth:`chat_with_tools` returns a
  :class:`ChatResult`.

Design rules this module encodes
--------------------------------
* **No LLM, no network, no heavy I/O.** Only the standard library is used,
  so every worker can import it with zero risk of circular imports or
  environment drift.
* **Docs-only write surface.** The agent may *read* anywhere under the repo
  root, but may *write* only under the docs output directory. The tool
  runtime enforces this; the contracts make the two roots explicit
  (:class:`ToolContext.read_root` vs :class:`ToolContext.docs_dir`).
* **Deterministic verification is separate from the writing agent.**
  :class:`VerificationResult` is produced by the verify module, never by
  the author.

All payloads crossing a tool boundary are JSON-safe (str / int / float /
bool / None / list / dict).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Tool surface (OpenAI function-calling schemas)
# ---------------------------------------------------------------------------
# The canonical list of tools the documentation agent may call. The tool
# runtime (:mod:`repoquill.agents.tools`) implements one executor per name
# and returns :data:`TOOL_SCHEMAS` (filtered by policy) from
# :meth:`ToolRegistry.schemas`. The author sends these schemas to the model
# and dispatches the model's ``tool_calls`` back through the registry.

#: Terminal tool: the author persists a page by calling ``write_doc``.
TERMINAL_TOOL = "write_doc"

TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "List files in the repository (relative paths). Use this to "
                "explore the layout before reading specific files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "Subdirectory relative to the repo root to list. "
                            "Defaults to the repo root."
                        ),
                    },
                    "pattern": {
                        "type": "string",
                        "description": (
                            "Optional glob to filter file names, e.g. '*.py'."
                        ),
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read the contents of a file (read-only). Use it to inspect "
                "source, tests, or an existing documentation page."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path from the repo root.",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "1-based inclusive start line (optional).",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "1-based inclusive end line (optional).",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": (
                "Search file contents for a literal or regex pattern. "
                "Returns matching lines as 'relpath:line: text'. Use it to "
                "find where a symbol is defined or how it is used."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Literal string or regex to search for.",
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "Restrict the search to a subdirectory (relative). "
                            "Defaults to the repo root."
                        ),
                    },
                    "regex": {
                        "type": "boolean",
                        "description": "Treat pattern as a regex. Default false.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Cap on the number of results.",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_api",
            "description": (
                "Return the AST-extracted public API surface of the package "
                "(or a single module): classes, functions, methods, "
                "properties and signatures. This is the authoritative list "
                "of symbols that actually exist — do not document anything "
                "that is not here."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "module": {
                        "type": "string",
                        "description": (
                            "Restrict to one module (dot-separated). "
                            "Defaults to the whole package."
                        ),
                    },
                    "symbol": {
                        "type": "string",
                        "description": "Focus on one class or function name.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_tests",
            "description": (
                "Discover the repository's test files and return their paths "
                "plus optional excerpts. Tests are behavioral ground truth: "
                "if a test asserts something, the docs may state it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "module": {
                        "type": "string",
                        "description": "Restrict to tests of one module (optional).",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Cap on the amount of returned text.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_example",
            "description": (
                "Execute a Python snippet in an isolated, credential-free "
                "subprocess with a wall-clock timeout. Use it to verify that "
                "a code example actually works BEFORE you document it. Never "
                "use it for anything other than documentation examples."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The Python code to execute.",
                    },
                    "timeout": {
                        "type": "number",
                        "description": "Wall-clock seconds. Defaults to the context value.",
                    },
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_docs",
            "description": (
                "List the existing documentation pages (slug + first line). "
                "Use it to see what is already documented."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_doc",
            "description": (
                "Read an existing documentation page by slug (kebab-case, no .md)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slug": {"type": "string", "description": "The page slug."},
                },
                "required": ["slug"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": TERMINAL_TOOL,
            "description": (
                "Write (create or overwrite) a documentation page by slug. "
                "This is the ONLY file you may write. Provide the complete "
                "markdown page. Call this once you are finished, then stop "
                "calling tools."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slug": {
                        "type": "string",
                        "description": "Page slug (kebab-case, no .md extension).",
                    },
                    "content": {
                        "type": "string",
                        "description": "The complete markdown page content.",
                    },
                },
                "required": ["slug", "content"],
            },
        },
    },
]

#: Names of every tool, in schema order (useful for tests and prompts).
TOOL_NAMES: List[str] = [s["function"]["name"] for s in TOOL_SCHEMAS]


# ---------------------------------------------------------------------------
# LLM tool-calling result
# ---------------------------------------------------------------------------

@dataclass
class ToolCall:
    """A single tool invocation requested by the model.

    Attributes:
        id: The provider-assigned tool-call id (echoed back in the
            ``tool``-role message).
        name: The tool function name.
        arguments: Parsed JSON arguments (a dict; ``{}`` if absent).
    """

    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatResult:
    """The result of one :meth:`repoquill.llm.LLMClient.chat_with_tools` call.

    Attributes:
        content: The assistant's text, or ``None`` if the model only
            requested tool calls.
        tool_calls: The tool calls the model requested (empty list when the
            model is done and has produced its final answer).
        usage: Optional provider usage/accounting dict.
        model: The model id the provider actually used, if reported.
    """

    content: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    usage: Optional[Dict[str, Any]] = None
    model: Optional[str] = None

    @property
    def done(self) -> bool:
        """True when the model produced a final answer (no tool calls)."""
        return not self.tool_calls


# ---------------------------------------------------------------------------
# Tool runtime context + results
# ---------------------------------------------------------------------------

@dataclass
class ToolContext:
    """Immutable policy describing what the tool runtime may touch.

    Attributes:
        repo_root: Absolute path of the repository root. Every **read**
            (``list_files`` / ``read_file`` / ``search_code``) is confined to
            this directory.
        pkg_path: Absolute path of the documented Python package (a
            subdirectory of ``repo_root``). ``inspect_api`` operates here.
        docs_dir: Absolute path of the docs output directory (the guide
            folder). This is the **only writable** root: ``write_doc`` may
            only create/overwrite ``<docs_dir>/<slug>.md``.
        execute_examples: Whether ``run_example`` is allowed at all. When
            false, the tool returns a policy error (and the author should
            fall back to static reasoning).
        example_timeout: Default wall-clock seconds for ``run_example``.
        max_file_chars: Maximum characters returned by a single
            ``read_file`` call (larger reads are truncated with a marker).
        max_search_results: Default cap for ``search_code`` results.
    """

    repo_root: str
    pkg_path: str
    docs_dir: str
    execute_examples: bool = True
    example_timeout: float = 30.0
    max_file_chars: int = 16000
    max_search_results: int = 40

    # --- read safety ------------------------------------------------------
    def resolve_read(self, rel_path: str) -> str:
        """Resolve *rel_path* under ``repo_root`` and verify it is inside.

        Raises:
            ValueError: If the resolved path escapes ``repo_root``.
        """
        return _resolve_within(self.repo_root, rel_path)

    # --- write safety -----------------------------------------------------
    def resolve_write(self, slug: str) -> str:
        """Return the writable path for *slug* (always ``<docs_dir>/<slug>.md``).

        Raises:
            ValueError: If *slug* is not a plain file name (no separators,
                no ``..``), so it cannot escape ``docs_dir``.
        """
        if not slug or "/" in slug or "\\" in slug or ".." in slug or slug.startswith("."):
            raise ValueError(f"invalid doc slug: {slug!r}")
        if not slug.endswith(".md"):
            slug = f"{slug}.md"
        target = _resolve_within(self.docs_dir, slug)
        return target


def _resolve_within(root: str, rel_path: str) -> str:
    """Resolve *rel_path* against *root*; raise if it escapes *root*."""
    import os

    root_abs = os.path.abspath(root)
    # Normalise separators and reject absolute or parent-escaping paths.
    candidate = os.path.abspath(os.path.join(root_abs, rel_path or ""))
    if candidate != root_abs and not candidate.startswith(root_abs + os.sep):
        raise ValueError(f"path escapes allowed root: {rel_path!r}")
    return candidate


@dataclass
class ToolResult:
    """The outcome of executing one tool.

    Attributes:
        name: The tool name.
        ok: Whether the tool succeeded (policy errors set this to False).
        data: The JSON-safe payload (None on error).
        error: A human-readable error message (None on success).
    """

    name: str
    ok: bool
    data: Any = None
    error: Optional[str] = None

    def to_content(self) -> str:
        """Serialize the result for the ``tool``-role message (JSON)."""
        import json

        if not self.ok:
            return json.dumps({"ok": False, "error": self.error})
        return json.dumps({"ok": True, "data": self.data})


class ToolRegistry:
    """Interface the author uses to talk to the tool runtime.

    Concrete implementation: :class:`repoquill.agents.tools.RepoQuillTools`.
    Tests use a fake registry. Keep this interface stable — the author and
    the scheduler depend on it.
    """

    def schemas(self) -> List[Dict[str, Any]]:
        """OpenAI function-calling schemas for the enabled tools."""
        raise NotImplementedError

    def names(self) -> List[str]:
        """Names of the enabled tools."""
        raise NotImplementedError

    def execute(self, name: str, arguments: Dict[str, Any]) -> ToolResult:
        """Execute *name* with *arguments*; never raises (errors in result)."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Page task + evidence
# ---------------------------------------------------------------------------

@dataclass
class PageTask:
    """Everything the author needs to write one documentation page.

    Attributes:
        slug: The page slug (kebab-case, no extension).
        title: Human-readable page title.
        description: One-line description of what the page covers.
        source_hints: Deterministic starting list of likely source files
            (relative paths). The agent may (and should) expand this with
            its own tool calls rather than trusting it blindly.
        coverage_checklist: The public symbols this page is expected to
            document. Used by independent verification to compute semantic
            coverage (not by the author's success criterion).
        out_path: Absolute path the page is written to.
    """

    slug: str
    title: str
    description: str = ""
    source_hints: List[str] = field(default_factory=list)
    coverage_checklist: List[str] = field(default_factory=list)
    out_path: str = ""


@dataclass
class EvidencePack:
    """Deterministic, seed evidence for one page (produced by evidence.py).

    This is a *starting point*, not the whole truth: the agent is expected
    to confirm and extend it with live tool calls.
    """

    file_tree: str = ""
    candidate_files: List[str] = field(default_factory=list)
    candidate_tests: List[str] = field(default_factory=list)
    api_surface: str = ""
    coverage_checklist: List[str] = field(default_factory=list)
    readme_excerpt: str = ""


# ---------------------------------------------------------------------------
# Author budget + result
# ---------------------------------------------------------------------------

@dataclass
class AgentBudget:
    """Hard caps for one page's authoring loop (bounded, never unbounded).

    Attributes:
        max_steps: Maximum number of tool-execution steps (one step = one
            model turn that requests >= 1 tool call).
        max_llm_calls: Maximum total LLM calls for the page.
        max_page_chars: A candidate page larger than this is rejected.
    """

    max_steps: int = 12
    max_llm_calls: int = 16
    max_page_chars: int = 60000

    steps_used: int = 0
    llm_calls_used: int = 0

    @property
    def exhausted(self) -> bool:
        return (
            self.steps_used >= self.max_steps
            or self.llm_calls_used >= self.max_llm_calls
        )

    def can_continue(self) -> bool:
        return not self.exhausted

    def consume_llm_call(self) -> bool:
        if self.llm_calls_used >= self.max_llm_calls:
            return False
        self.llm_calls_used += 1
        return True

    def consume_step(self) -> bool:
        if self.steps_used >= self.max_steps:
            return False
        self.steps_used += 1
        return True


@dataclass
class AuthorResult:
    """The outcome of authoring one page with the tool-calling loop.

    Attributes:
        slug: The page slug.
        ok: True when a page was produced and persisted.
        content: The final markdown content ("" if not ok).
        steps: Number of tool-execution steps taken.
        llm_calls: Number of LLM calls made.
        transcript: Ordered list of ``{"role", "name", "ok", "summary"}``
            entries describing every model turn and tool call (for the run
            report / debugging).
        error: Failure reason (None when ok).
        wrote_doc: Whether the terminal ``write_doc`` tool was called.
    """

    slug: str
    ok: bool
    content: str = ""
    steps: int = 0
    llm_calls: int = 0
    transcript: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    wrote_doc: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "slug": self.slug,
            "ok": self.ok,
            "steps": self.steps,
            "llm_calls": self.llm_calls,
            "wrote_doc": self.wrote_doc,
            "error": self.error,
            "transcript_len": len(self.transcript),
        }


# ---------------------------------------------------------------------------
# Independent verification
# ---------------------------------------------------------------------------

@dataclass
class CoverageReport:
    """Semantic coverage of a page against its expected symbol checklist.

    Attributes:
        expected: Symbols the page is expected to document.
        covered: The subset actually documented (mentioned) on the page.
        missing: The subset not mentioned.
        ratio: ``len(covered) / len(expected)`` (1.0 when expected is empty).
    """

    expected: List[str] = field(default_factory=list)
    covered: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    ratio: float = 1.0


# Verification statuses
STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_BUDGET_EXHAUSTED = "budget-exhausted"
STATUS_ERROR = "error"
STATUS_CLEAN = "clean"


@dataclass
class VerificationResult:
    """Independent verification of one generated page.

    This is produced by :mod:`repoquill.agents.verify` — **not** by the
    author — and is the authoritative pass/fail used to decide publication.

    Attributes:
        slug: The page slug.
        passed: Overall pass (see :meth:`compute_passed`).
        coverage: The :class:`CoverageReport` (semantic coverage).
        example_findings: One dict per executed code block (from the
            examples checker) — status passed/failed/timeout.
        import_findings: Findings from the import resolver (unresolved
            imports).
        symbol_findings: Findings from the symbol checker (symbols that do
            not exist in the package).
        coverage_ok: Whether coverage ratio met the threshold.
        examples_ok: Whether all executed examples passed (or none were
            executed / execution disabled).
        summary: A short human-readable line.
    """

    slug: str
    passed: bool
    coverage: Optional[CoverageReport] = None
    example_findings: List[Dict[str, Any]] = field(default_factory=list)
    import_findings: List[Dict[str, Any]] = field(default_factory=list)
    symbol_findings: List[Dict[str, Any]] = field(default_factory=list)
    coverage_ok: bool = True
    examples_ok: bool = True
    summary: str = ""

    @staticmethod
    def compute_passed(
        coverage_ok: bool,
        examples_ok: bool,
        import_findings: List[Dict[str, Any]],
        symbol_findings: List[Dict[str, Any]],
    ) -> bool:
        """A page passes when coverage is met, examples pass, and there are
        no unresolved imports or invented symbols."""
        return (
            coverage_ok
            and examples_ok
            and not import_findings
            and not symbol_findings
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "slug": self.slug,
            "passed": self.passed,
            "coverage_ok": self.coverage_ok,
            "examples_ok": self.examples_ok,
            "coverage_ratio": self.coverage.ratio if self.coverage else 1.0,
            "missing_symbols": self.coverage.missing if self.coverage else [],
            "import_findings": len(self.import_findings),
            "symbol_findings": len(self.symbol_findings),
            "example_failures": sum(
                1 for f in self.example_findings if f.get("status") != "passed"
            ),
            "summary": self.summary,
        }
