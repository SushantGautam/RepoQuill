"""Shared contracts for the embedded Pi documentation runtime.

This is M0 of the Pi-first milestone. Every workstream (Pi RPC, Pi Bridge,
Pi Models, Pi Bootstrap, Pi Quality, Pi Integration) codes against these
signatures. Keep them small and stable; do not add speculative fields.

Design notes
------------
* Reuse ``PageTask``/``PageOutcome`` from ``repoquill.agents`` where possible
  rather than inventing parallel types. These Pi-specific contracts describe
  only the process/runtime boundary (spawn → prompt → events → staged file).
* A Pi documentation run is **docs-only**: source is read-only, and the only
  writable tree is a per-task staging directory separate from the live docs.
* ``PiRunResult`` is what the scheduler/CLI consume; it carries the sanitized
  tool trace, the staged output path, and structured errors for fail-closed
  behavior. Never silently fall back to another engine on failure.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------------------- #
# Tool allowlist (docs-only, vetted). Ordered = declaration order.
# --------------------------------------------------------------------------- #
#: Tools the Pi model may call. These map 1:1 onto the existing
#: ``repoquill.agents.tools.RepoQuillTools`` registry methods. ``run_example``
#: is only enabled when the task explicitly allows execution.
DOC_TOOL_ALLOWLIST: List[str] = [
    "list_files",
    "read_file",
    "search_code",
    "inspect_api",
    "inspect_tests",
    "run_example",
    "write_doc",
]

#: Hard-denylist of built-in Pi tools that must NEVER be active in unattended
#: documentation runs, regardless of allowlist handling.
DENY_BUILTIN_TOOLS: List[str] = [
    "bash",
    "powershell",
    "write",
    "edit",
    "multiedit",
    "apply_patch",
]

# --------------------------------------------------------------------------- #
# Pinned runtime + canonical launch (security-critical: ONE place)
# --------------------------------------------------------------------------- #
import os as _os

#: Official npm distribution (verify against upstream before bumping).
PI_PACKAGE = "@earendil-works/pi-coding-agent"
#: Pin a tested version; never install @latest at runtime.
PI_PINNED_VERSION = "1.2.0"
#: Default app-cache install location (kept out of the user's global env).
DEFAULT_PI_CACHE_DIR = _os.path.join(
    _os.path.expanduser("~"), ".cache", "repoquill", "pi"
)
#: Override for the pi binary (tests / CI preprovision).
PI_BIN_ENV = "REPOQUILL_PI_BIN"
#: Pi reads this to locate models.json / settings.json (per-run temp dir).
AGENT_DIR_ENV = "PI_CODING_AGENT_DIR"
#: The extension reads this to find the Python bridge socket.
BRIDGE_SOCKET_ENV = "REPOQUILL_BRIDGE_SOCKET"
#: Env applied to every Pi child process.
PI_RUNTIME_ENV = {
    "PI_OFFLINE": "1",           # no startup network activity
    "PI_SKIP_VERSION_CHECK": "1",
    "PI_TELEMETRY": "0",
}

#: Verified against `pi --help` of PI_PINNED_VERSION (1.2.0). No built-in
#: tool enablers; the only model-visible tools are the vetted extension
#: tools loaded via ``--extension``.
SAFE_LAUNCH_FLAGS: List[str] = [
    "--mode", "rpc",
    "--no-session",
    "--no-builtin-tools",     # disable read/write/edit/bash built-ins
    "--no-extensions",        # disable discovery; explicit -e still works
    "--no-mcp",
    "--no-skills",
    "--no-prompt-templates",
    "--no-context-files",     # never load user repo AGENTS.md/CLAUDE.md
    "--no-approve",           # ignore project-local .pi config
]


def build_launch_args(
    pi_bin: str,
    *,
    extension_path: str,
    provider: str,
    model: str,
    system_prompt: str,
    thinking: str = "off",
) -> List[str]:
    """Canonical argument list for a documentation Pi process."""
    return [
        pi_bin,
        *SAFE_LAUNCH_FLAGS,
        "--extension", extension_path,
        "--provider", provider,
        "--model", model,
        "--thinking", thinking,
        "--system-prompt", system_prompt,
    ]


def build_runtime_env(agent_dir: Optional[str] = None) -> Dict[str, str]:
    """Env for a Pi child process. The model API key stays in the process
    environment referenced by name (``$NAME``) inside models.json — it is
    never materialized here."""
    env = dict(_os.environ)
    env.update(PI_RUNTIME_ENV)
    if agent_dir:
        env[AGENT_DIR_ENV] = agent_dir
    return env


# --------------------------------------------------------------------------- #
# Bridge IPC envelope
# --------------------------------------------------------------------------- #
BRIDGE_PROTOCOL_VERSION = 1
#: Request:  {"v": 1, "id": "<str>", "tool": "<name>", "args": {...}}
#: Response: {"v": 1, "id": "<str>", "ok": true,  "data": ...}
#:           {"v": 1, "id": "<str>", "ok": false, "error": "<message>"}

# --------------------------------------------------------------------------- #
# RPC / process constants
# --------------------------------------------------------------------------- #
#: JSONL record family we emit on stdin.
CMD_PROMPT = "prompt"
CMD_GET_STATE = "get_state"
CMD_ABORT = "abort"

#: Event types that matter at the boundary.
EV_AGENT_START = "agent_start"
EV_AGENT_END = "agent_end"
EV_AGENT_SETTLED = "agent_settled"
EV_TURN_START = "turn_start"
EV_TURN_END = "turn_end"
EV_MSG_START = "message_start"
EV_MSG_UPDATE = "message_update"
EV_MSG_END = "message_end"
EV_TOOL_START = "tool_execution_start"
EV_TOOL_UPDATE = "tool_execution_update"
EV_TOOL_END = "tool_execution_end"
EV_AUTO_RETRY_START = "auto_retry_start"
EV_AUTO_RETRY_END = "auto_retry_end"
EV_EXTENSION_ERROR = "extension_error"


# --------------------------------------------------------------------------- #
# Data contracts
# --------------------------------------------------------------------------- #
@dataclass
class PiToolCall:
    """One observed tool invocation (sanitized for logs/artifacts)."""

    tool_call_id: str
    name: str
    args: Dict[str, Any] = field(default_factory=dict)
    started_at: float = 0.0
    duration_ms: Optional[int] = None
    is_error: bool = False
    result_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.tool_call_id,
            "name": self.name,
            "args": self.args,
            "duration_ms": self.duration_ms,
            "is_error": self.is_error,
            "result_summary": self.result_summary,
        }


@dataclass
class PiUsage:
    """Provider-reported token/cost usage, if the endpoint reports it."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class PiTask:
    """Input describing one documentation page to author via Pi.

    ``staged_docs_dir`` is the ONLY writable location for the produced page.
    The final file is expected at ``staged_docs_dir/<slug>.md``.
    """

    slug: str
    title: str
    description: str
    evidence: str                      # precomputed evidence pack (text)
    source_root: str                   # read-only repo root
    staged_docs_dir: str               # writable staging tree for this task
    provider: str                      # Pi provider name
    model: str                         # Pi model pattern/id
    allow_example_exec: bool = False   # gate for the run_example tool
    timeout_s: float = 300.0           # overall deadline for the run
    system_prompt: str = ""            # docs-only system prompt
    #: Symbols the page must mention; independent verification checks
    #: coverage against exactly this list.
    coverage_checklist: List[str] = field(default_factory=list)

    @property
    def expected_output_path(self) -> str:
        return f"{self.staged_docs_dir.rstrip('/')}/{self.slug}.md"


@dataclass
class PiRunResult:
    """Output of one Pi documentation run, consumed by the scheduler/CLI."""

    slug: str
    completed: bool                    # True only if agent_settled + file written
    output_path: Optional[str]         # staged file path (if produced)
    tool_calls: List[PiToolCall] = field(default_factory=list)
    usage: PiUsage = field(default_factory=PiUsage)
    elapsed_s: float = 0.0
    pi_version: str = ""
    model: str = ""
    errors: List[str] = field(default_factory=list)
    aborted: bool = False
    source_paths_read: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.completed and bool(self.output_path) and not self.aborted

    @property
    def tool_trace(self) -> List[str]:
        """Compact, log-safe trace line per tool call."""
        return [
            f"{tc.name}({'err' if tc.is_error else 'ok'}"
            f"{f',{tc.duration_ms}ms' if tc.duration_ms is not None else ''})"
            for tc in self.tool_calls
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "slug": self.slug,
            "completed": self.completed,
            "ok": self.ok,
            "aborted": self.aborted,
            "output_path": self.output_path,
            "tool_trace": self.tool_trace,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "source_paths_read": self.source_paths_read,
            "usage": {
                "input_tokens": self.usage.input_tokens,
                "output_tokens": self.usage.output_tokens,
                "total_tokens": self.usage.total_tokens,
                "cost": self.usage.cost,
            },
            "elapsed_s": round(self.elapsed_s, 3),
            "pi_version": self.pi_version,
            "model": self.model,
            "errors": self.errors,
        }


# --------------------------------------------------------------------------- #
# Backend interface
# --------------------------------------------------------------------------- #
class PiBackend:
    """Interface for the Pi runtime adapter.

    The concrete implementation lives in ``repoquill.pi.rpc`` (PiRpcBackend).
    The scheduler calls ``run(task)`` and treats any raised
    :class:`PiError` or returned non-``ok`` result as a FAILED page — it must
    never fall back to another engine silently.
    """

    def __init__(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def run(self, task: PiTask) -> PiRunResult:  # pragma: no cover - interface
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #
class PiError(RuntimeError):
    """Base class for Pi runtime failures (fail-closed)."""


class PiNotInstalledError(PiError):
    """Pi (or Node) is not available. Message must be actionable."""


class PiStartTimeoutError(PiError):
    """Pi process did not become ready within the startup deadline."""


class PiRunTimeoutError(PiError):
    """Pi did not reach agent_settled before the run deadline."""


class PiProcessError(PiError):
    """Pi exited unexpectedly or the RPC stream went malformed."""


class PiModelAuthError(PiError):
    """The model endpoint rejected authentication / was unreachable."""


class PiSecurityError(PiError):
    """A policy/containment violation was detected (path escape, etc.)."""


def _now() -> float:
    return time.time()


__all__ = [
    "DOC_TOOL_ALLOWLIST",
    "DENY_BUILTIN_TOOLS",
    "PI_PACKAGE",
    "PI_PINNED_VERSION",
    "DEFAULT_PI_CACHE_DIR",
    "PI_BIN_ENV",
    "AGENT_DIR_ENV",
    "BRIDGE_SOCKET_ENV",
    "PI_RUNTIME_ENV",
    "SAFE_LAUNCH_FLAGS",
    "build_launch_args",
    "build_runtime_env",
    "BRIDGE_PROTOCOL_VERSION",
    "CMD_PROMPT",
    "CMD_GET_STATE",
    "CMD_ABORT",
    "EV_AGENT_START",
    "EV_AGENT_END",
    "EV_AGENT_SETTLED",
    "EV_TURN_START",
    "EV_TURN_END",
    "EV_MSG_START",
    "EV_MSG_UPDATE",
    "EV_MSG_END",
    "EV_TOOL_START",
    "EV_TOOL_UPDATE",
    "EV_TOOL_END",
    "EV_AUTO_RETRY_START",
    "EV_AUTO_RETRY_END",
    "EV_EXTENSION_ERROR",
    "PiToolCall",
    "PiUsage",
    "PiTask",
    "PiRunResult",
    "PiBackend",
    "PiError",
    "PiNotInstalledError",
    "PiStartTimeoutError",
    "PiRunTimeoutError",
    "PiProcessError",
    "PiModelAuthError",
    "PiSecurityError",
]
