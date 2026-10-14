"""PiRpcBackend -- JSONL RPC process supervisor for one Pi docs run.

Implements the :class:`repoquill.pi.contracts.PiBackend` interface against a
pinned Pi binary (v1.2.0) launched with :func:`contracts.build_launch_args`
in ``--mode rpc``. The backend:

* fetches ``pi --version`` before every run (fail closed if missing);
* spawns Pi and reads stdout **continuously** into a queue (never lets the
  pipe fill), decodes strict-LF JSONL framing via :mod:`protocol`;
* correlates commands by ``id`` (``get_state`` readiness probe, then
  ``prompt``);
* consumes the event stream until ``agent_settled`` (or the run deadline),
  building a sanitized tool trace and max-cumulative usage;
* keeps the last ~2 KB of stderr (never parsed as protocol), redacted;
* closes stdin on success for an orderly shutdown, escalating to
  terminate/kill on expiry, abort, or unexpected exit.

Failure mapping (fail-closed; the scheduler must never fall back silently):

=========================  =================================================
condition                  result
=========================  =================================================
binary missing/unrunnable  ``PiNotInstalledError`` (actionable message)
no ready/prompt response   ``PiStartTimeoutError`` / ``PiRunTimeoutError``
hard model/auth error      ``PiModelAuthError``
early exit / rejected cmd  ``PiProcessError`` (stderr tail redacted)
soft mid-run model error   result with ``completed=False`` + ``errors``
=========================  =================================================

``PiRunResult.stderr_tail`` is set as a runtime attribute (proposal: promote
to a contract field -- see the worker report).
"""

from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from . import contracts
from .protocol import (
    STDERR_TAIL_BYTES,
    ToolTrace,
    UsageAggregator,
    decode_stream,
    encode_command,
    prompt_disposition,
    redact_secrets,
)

__all__ = [
    "PiProbe",
    "PiRpcBackend",
    "build_task_prompt",
]


def build_task_prompt(task: contracts.PiTask) -> str:
    """Compose the single ``prompt`` message for a documentation task."""
    lines: List[str] = [
        "You are RepoQuill's documentation author, running in docs-only mode.",
        "Write exactly one documentation page.",
        "",
        "Page title: %s" % task.title,
        "Page slug (the page must be saved as %s.md): %s" % (task.slug, task.slug),
        "",
        "## Task",
        (task.description or "").strip(),
        "",
        "## Evidence (precomputed from the source)",
        (task.evidence or "(none)").strip(),
        "",
    ]
    if task.coverage_checklist:
        lines += [
            "## Required coverage",
            "This page MUST mention every one of the following symbols, "
            "each grounded in the source (verify before writing):",
            ", ".join(task.coverage_checklist),
            "Independent verification will check that all of them are "
            "present; the page is rejected if any are missing.",
            "",
        ]
    lines += [
        "## Instructions",
        "1. Ground the page in the code: use the provided tools (list_files,",
        "   read_file, search_code, inspect_api, inspect_tests) as needed.",
        "2. When the page is complete you MUST call the write_doc tool to save",
        "   it to %s." % task.expected_output_path,
        "3. Do not modify source code and do not run commands. Every factual",
        "   claim must come from the evidence above or from files you read.",
    ]
    if not task.allow_example_exec:
        lines.append("4. Do not attempt to execute example code.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Error classification
# --------------------------------------------------------------------------- #

#: Hard failures that must raise ``PiModelAuthError`` (never retry/repair).
_AUTH_ERROR_RE = re.compile(
    r"(?i)(model not found|unknown provider|provider not found|"
    r"\b401\b|\b403\b|unauthorized|not authenticated|"
    r"authentication (failed|error|required)|invalid (api[-_ ]?key|token)|"
    r"api[-_ ]?key (is )?(invalid|missing|expired|refused)|"
    r"access denied|no (api )?key|permission denied)"
)


def _looks_like_auth_error(text: str) -> bool:
    return bool(text) and bool(_AUTH_ERROR_RE.search(text))


# --------------------------------------------------------------------------- #
# Small plumbing
# --------------------------------------------------------------------------- #

class _CappedBuffer:
    """Thread-safe byte buffer that keeps only the last ``limit`` bytes."""

    def __init__(self, limit: int) -> None:
        self._limit = int(limit)
        self._buf = bytearray()
        self._lock = threading.Lock()

    def append(self, data: bytes) -> None:
        if not data:
            return
        with self._lock:
            self._buf += data
            overflow = len(self._buf) - self._limit
            if overflow > 0:
                del self._buf[:overflow]

    def get(self) -> str:
        with self._lock:
            return bytes(self._buf).decode("utf-8", "replace")


class _PipePumps:
    """Continuously drains stdout/stderr of a child process.

    stdout is decoded (strict-LF JSONL) into a queue; ``None`` marks EOF.
    stderr is never parsed -- only retained (capped) for diagnostics.
    """

    def __init__(self, proc: "subprocess.Popen") -> None:
        self.proc = proc
        self.out_q: "queue.Queue[Any]" = queue.Queue()
        self.err_buf = _CappedBuffer(STDERR_TAIL_BYTES)
        self._t_out = threading.Thread(target=self._pump_stdout, daemon=True)
        self._t_err = threading.Thread(target=self._pump_stderr, daemon=True)
        self._t_out.start()
        self._t_err.start()

    def _pump_stdout(self) -> None:
        try:
            assert self.proc.stdout is not None
            for record in decode_stream(self.proc.stdout):
                self.out_q.put(record)
        except Exception:
            pass
        finally:
            self.out_q.put(None)

    def _pump_stderr(self) -> None:
        try:
            assert self.proc.stderr is not None
            # read1(): one raw read per call, so small stderr bursts are
            # observed promptly instead of waiting for 4096 bytes/EOF.
            read = getattr(self.proc.stderr, "read1", None)
            if not callable(read):
                read = self.proc.stderr.read
            while True:
                chunk = read(4096)
                if not chunk:
                    break
                self.err_buf.append(chunk)
        except Exception:
            pass

    def join(self, timeout: float = 2.0) -> None:
        """Wait for both pumps to drain (they finish on stream EOF)."""
        for t in (self._t_out, self._t_err):
            t.join(timeout=timeout)


class _RunState:
    """Per-run event sink: tool trace, usage, errors, settled flag."""

    def __init__(self, result: contracts.PiRunResult) -> None:
        self.result = result
        self.trace = ToolTrace()
        self.usage = UsageAggregator()
        self.settled = False
        self.model_auth_error: Optional[str] = None

    def handle(self, record: Any) -> None:
        if not isinstance(record, dict):
            return
        rtype = record.get("type")
        if rtype == contracts.EV_AGENT_SETTLED:
            self.settled = True
            self.result.aborted = bool(record.get("aborted", False))
            return
        self.trace.handle(record)
        self.usage.observe_record(record)
        self._record_errors(record)

    def _record_errors(self, rec: Dict[str, Any]) -> None:
        errors = self.result.errors
        rtype = rec.get("type")
        if rtype == contracts.EV_MSG_UPDATE:
            event = rec.get("assistantMessageEvent")
            if isinstance(event, dict) and event.get("type") == "error":
                text = str(event.get("error") or event.get("reason")
                           or "provider stream error")
                errors.append("message_update error: %s" % text)
                if (self.model_auth_error is None
                        and _looks_like_auth_error(text)):
                    self.model_auth_error = text
        elif rtype == contracts.EV_MSG_END:
            message = rec.get("message")
            if isinstance(message, dict) and message.get("stopReason") == "error":
                errors.append("message_end stopReason=error")
        elif rtype == contracts.EV_AUTO_RETRY_END:
            if rec.get("success") is False:
                text = str(rec.get("finalError") or "auto retry exhausted")
                errors.append("auto_retry_end: %s" % text)
                if (self.model_auth_error is None
                        and _looks_like_auth_error(text)):
                    self.model_auth_error = text
        elif rtype == contracts.EV_EXTENSION_ERROR:
            errors.append(
                "extension_error: %s"
                % (rec.get("error") or rec.get("extensionPath") or "unknown"))


def _is_response(rec: Any, req_id: str, command: str) -> bool:
    return (
        isinstance(rec, dict)
        and rec.get("type") == "response"
        and rec.get("id") == req_id
        and rec.get("command") == command
    )


# --------------------------------------------------------------------------- #
# Public types
# --------------------------------------------------------------------------- #

@dataclass
class PiProbe:
    """Result of :meth:`PiRpcBackend.probe` (binary + protocol handshake)."""

    pi_version: str
    state: Dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Backend
# --------------------------------------------------------------------------- #

class PiRpcBackend(contracts.PiBackend):
    """One backend instance supervises one Pi process per :meth:`run` call.

    The scheduler constructs a backend per run with the resolved runtime:
    ``PiRpcBackend(pi_bin, extension_path, agent_dir=None)``.
    """

    def __init__(
        self,
        pi_bin: str,
        extension_path: Optional[str] = None,
        agent_dir: Optional[str] = None,
        startup_deadline_s: float = 30.0,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> None:
        # Absolute path: Popen() changes to the child cwd before exec,
        # which would break relative program paths.
        self.pi_bin = os.path.abspath(str(pi_bin))
        self.extension_path = extension_path
        self.agent_dir = agent_dir
        self.startup_deadline_s = float(startup_deadline_s)
        # Per-instance child env (e.g. the per-task bridge socket path).
        # Per-instance (not os.environ) so parallel page tasks each reach
        # their own bridge.
        self.extra_env = dict(extra_env or {})
        self._process: Optional["subprocess.Popen"] = None

    def _child_env(self) -> Dict[str, str]:
        env = contracts.build_runtime_env(agent_dir=self.agent_dir)
        env.update(self.extra_env)
        return env

    # -- version / probe ---------------------------------------------------

    def _install_hint(self) -> str:
        return (
            "Install the pinned Pi runtime: npm install --prefix %s %s@%s "
            "(needs Node >= 18), or point %s at an existing pi executable."
            % (
                contracts.DEFAULT_PI_CACHE_DIR,
                contracts.PI_PACKAGE,
                contracts.PI_PINNED_VERSION,
                contracts.PI_BIN_ENV,
            )
        )

    def _fetch_version(self) -> str:
        try:
            proc = subprocess.run(
                [self.pi_bin, "--version"],
                capture_output=True, text=True, timeout=15,
            )
        except FileNotFoundError:
            raise contracts.PiNotInstalledError(
                "Pi binary not found at %r. %s"
                % (self.pi_bin, self._install_hint())
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise contracts.PiNotInstalledError(
                "Pi binary at %r is not runnable (%s: %s). %s"
                % (self.pi_bin, type(exc).__name__, exc, self._install_hint())
            )
        if proc.returncode != 0:
            raise contracts.PiNotInstalledError(
                "Pi binary at %r failed `--version` (exit %d). %s"
                % (self.pi_bin, proc.returncode, self._install_hint())
            )
        version = (proc.stdout or "").strip()
        return version.splitlines()[-1].strip() if version else ""

    def _probe_args(self) -> List[str]:
        """Launch args for a readiness probe: canonical safe flags only
        (no provider/model/extension, so the probe needs no credentials)."""
        return [self.pi_bin, *contracts.SAFE_LAUNCH_FLAGS]

    def _launch_args(
        self,
        provider: str,
        model: str,
        system_prompt: str,
    ) -> List[str]:
        args = contracts.build_launch_args(
            self.pi_bin,
            extension_path=self.extension_path or "",
            provider=provider,
            model=model,
            system_prompt=system_prompt or "",
        )
        if self.extension_path:
            return args
        # Empty extension path: drop the ``--extension`` pair.
        pruned: List[str] = []
        i = 0
        while i < len(args):
            if args[i] == "--extension" and i + 1 < len(args) and args[i + 1] == "":
                i += 2
                continue
            pruned.append(args[i])
            i += 1
        return pruned

    def probe(self, startup_deadline_s: Optional[float] = None) -> PiProbe:
        """Spawn Pi with the safe flag set, confirm readiness via a
        correlated ``get_state``, and shut down. Returns version + state."""
        pi_version = self._fetch_version()
        proc = subprocess.Popen(
            self._probe_args(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._child_env(),
        )
        self._process = proc
        pumps = _PipePumps(proc)
        state = _RunState(
            contracts.PiRunResult(
                slug="probe", completed=False, output_path=None,
                pi_version=pi_version,
            )
        )
        try:
            probe_id = "probe-%s" % uuid.uuid4().hex[:12]
            self._send(proc, {"id": probe_id, "type": contracts.CMD_GET_STATE})
            deadline = time.monotonic() + (
                float(startup_deadline_s)
                if startup_deadline_s is not None
                else self.startup_deadline_s
            )
            resp = self._wait_for(
                proc, pumps, state,
                lambda r: _is_response(r, probe_id, contracts.CMD_GET_STATE),
                deadline,
                lambda msg: contracts.PiStartTimeoutError(msg),
            )
            if resp.get("success") is not True:
                raise contracts.PiProcessError(
                    "get_state failed: %s"
                    % (resp.get("error") or "unknown error"))
            data = resp.get("data")
            state_data = data if isinstance(data, dict) else {}
        except BaseException:
            self._shutdown(proc)
            raise
        self._shutdown(proc)
        self._process = None
        return PiProbe(pi_version=pi_version, state=state_data)

    # -- run ---------------------------------------------------------------

    def run(self, task: contracts.PiTask) -> contracts.PiRunResult:
        started = time.monotonic()
        pi_version = self._fetch_version()
        result = contracts.PiRunResult(
            slug=task.slug,
            completed=False,
            output_path=None,
            pi_version=pi_version,
            model=task.model,
        )
        state = _RunState(result)
        cwd = (
            task.source_root
            if task.source_root and os.path.isdir(task.source_root)
            else None
        )
        proc = subprocess.Popen(
            self._launch_args(task.provider, task.model, task.system_prompt),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._child_env(),
            cwd=cwd,
        )
        self._process = proc
        pumps = _PipePumps(proc)
        try:
            ready_id = "ready-%s" % uuid.uuid4().hex[:12]
            self._send(proc, {"id": ready_id, "type": contracts.CMD_GET_STATE})
            startup_deadline = started + self.startup_deadline_s
            resp = self._wait_for(
                proc, pumps, state,
                lambda r: _is_response(r, ready_id, contracts.CMD_GET_STATE),
                startup_deadline,
                lambda msg: contracts.PiStartTimeoutError(msg),
            )
            if resp.get("success") is not True:
                raise contracts.PiProcessError(
                    "get_state failed: %s"
                    % (resp.get("error") or "unknown error"))

            prompt_id = "prompt-%s" % uuid.uuid4().hex[:12]
            self._send(proc, {
                "id": prompt_id,
                "type": contracts.CMD_PROMPT,
                "message": build_task_prompt(task),
            })
            run_deadline = started + max(1.0, float(task.timeout_s))
            resp = self._wait_for(
                proc, pumps, state,
                lambda r: _is_response(r, prompt_id, contracts.CMD_PROMPT),
                run_deadline,
                lambda msg: contracts.PiRunTimeoutError(msg),
            )
            if resp.get("success") is not True:
                error = str(resp.get("error") or "unknown error")
                if _looks_like_auth_error(error):
                    raise contracts.PiModelAuthError("prompt rejected: %s" % error)
                raise contracts.PiProcessError("prompt rejected: %s" % error)
            disposition = prompt_disposition(resp)
            # "handled" (or any non-run disposition): no run will occur,
            # so do not wait for agent_settled.
            if disposition not in ("", "started", "queued"):
                pass
            else:
                self._wait_for(
                    proc, pumps, state,
                    lambda r: (
                        isinstance(r, dict)
                        and r.get("type") == contracts.EV_AGENT_SETTLED
                    ),
                    run_deadline,
                    lambda msg: contracts.PiRunTimeoutError(
                        "pi did not reach agent_settled within %.1fs"
                        % float(task.timeout_s)),
                )
        except BaseException:
            self._shutdown(proc)
            self._process = None
            raise

        # Final bookkeeping (also runs on the clean path).
        self._shutdown(proc)
        pumps.join(timeout=2.0)
        self._process = None
        result.stderr_tail = redact_secrets(pumps.err_buf.get())  # type: ignore[attr-defined]
        result.tool_calls = state.trace.tool_calls
        result.usage = state.usage.to_pi_usage()
        result.source_paths_read = state.trace.source_paths
        output_path = task.expected_output_path
        if os.path.isfile(output_path):
            result.output_path = output_path
        result.completed = bool(
            state.settled and not result.aborted and result.output_path
        )
        result.elapsed_s = time.monotonic() - started
        if state.model_auth_error is not None:
            raise contracts.PiModelAuthError(state.model_auth_error)
        return result

    def cancel(self) -> None:
        """Send ``abort`` and then proceed to shutdown (best effort)."""
        proc = self._process
        if proc is None or proc.poll() is not None:
            return
        try:
            self._send(proc, {
                "id": "abort-%s" % uuid.uuid4().hex[:12],
                "type": contracts.CMD_ABORT,
            })
        except Exception:
            pass
        self._shutdown(proc)
        self._process = None

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _send(proc: "subprocess.Popen", command: Dict[str, Any]) -> None:
        assert proc.stdin is not None
        data = encode_command(command)
        proc.stdin.write(data)
        proc.stdin.flush()

    def _wait_for(
        self,
        proc: "subprocess.Popen",
        pumps: _PipePumps,
        state: _RunState,
        predicate: Callable[[Any], bool],
        deadline: float,
        timeout_error: Callable[[str], contracts.PiError],
    ) -> Dict[str, Any]:
        """Pump records until ``predicate`` matches, deadline, or EOF."""
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise timeout_error("timed out waiting for the Pi RPC stream")
            try:
                record = pumps.out_q.get(timeout=min(0.2, remaining))
            except queue.Empty:
                continue  # no record yet; the pump emits None on true EOF
            if record is None:
                raise self._early_exit(proc, pumps, state)
            state.handle(record)
            if predicate(record):
                return record

    @staticmethod
    def _early_exit(
        proc: "subprocess.Popen",
        pumps: _PipePumps,
        state: _RunState,
    ) -> contracts.PiProcessError:
        code = proc.poll()
        # The process is gone, so the streams hit EOF; join the pumps so
        # any trailing stderr is fully captured before we read it.
        pumps.join(timeout=2.0)
        tail = redact_secrets(pumps.err_buf.get())
        tail_clean = tail.strip()
        state.result.stderr_tail = tail  # type: ignore[attr-defined]
        if tail_clean:
            state.result.errors.append(
                "process exited early (code %s); stderr tail: %s"
                % (code, tail_clean[-500:]))
        message = "pi process exited early with code %s" % code
        if tail_clean:
            message += "; stderr tail: %s" % tail_clean[-500:]
        return contracts.PiProcessError(message)

    @staticmethod
    def _shutdown(proc: "subprocess.Popen", wait_s: float = 5.0) -> None:
        try:
            if proc.poll() is None:
                try:
                    if proc.stdin:
                        proc.stdin.close()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=wait_s)
                    return
                except subprocess.TimeoutExpired:
                    pass
                try:
                    proc.terminate()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=3.0)
                    return
                except subprocess.TimeoutExpired:
                    pass
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=3.0)
                except Exception:
                    pass
        finally:
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                try:
                    if stream:
                        stream.close()
                except Exception:
                    pass
