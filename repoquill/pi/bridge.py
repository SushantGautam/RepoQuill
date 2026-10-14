"""Python side of the RepoQuill <-> Pi tool bridge.

:mod:`repoquill.pi.extension.ts` (loaded by the Pi runtime via
``--extension``) speaks a tiny line-oriented JSON envelope over a Unix
domain socket to :class:`PiBridgeServer`. Each request is one
documentation tool call from the Pi model; each response is the existing
:class:`repoquill.agents.contracts.ToolResult` mapped onto the envelope
defined by :data:`repoquill.pi.contracts.BRIDGE_PROTOCOL_VERSION`.

Design
------
* **One server per documentation task.** The server binds a socket in a
  private temp dir, dispatches through the existing
  :class:`repoquill.agents.tools.RepoQuillTools` (reused, never
  reimplemented), and is torn down with the task.
* **Defense in depth.** ``RepoQuillTools`` already confines reads/writes,
  but the bridge re-validates every path argument with
  :func:`os.path.realpath` containment checks (so symlink traversal is
  caught even though ``ToolContext.resolve_read`` only normalizes) and
  restricts ``write_doc`` to the exact task slug.
* **Never leak internals.** Envelope errors carry short, safe messages
  (no stack traces, no secrets). ``run_example`` stays opt-in: when the
  task does not allow execution the bridge refuses the call outright.
* **Bounded.** A single worker thread serializes all tool executions
  (tools never run concurrently), each request has a wall-clock timeout,
  and every response is capped at 256 KB (truncated ``data`` is marked
  with ``"_truncated": true``).

Envelope (LF-terminated JSON, one object per line)::

    request:  {"v": 1, "id": "<str>", "tool": "<name>", "args": {...}}
    response: {"v": 1, "id": "<str>", "ok": true,  "data": ...}
              {"v": 1, "id": "<str>", "ok": false, "error": "<msg>"}
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import socket
import tempfile
import threading
import types
from typing import Any, Dict, Optional, Tuple

from repoquill.agents.contracts import ToolRegistry, ToolResult
from repoquill.agents.tools import RepoQuillTools, build_tool_context

from . import contracts as pi_contracts

BRIDGE_PROTOCOL_VERSION = pi_contracts.BRIDGE_PROTOCOL_VERSION

#: Tools the bridge will dispatch (the docs-only vetted allowlist).
_DISPATCHABLE = tuple(pi_contracts.DOC_TOOL_ALLOWLIST)

# Read-only, deterministic tools for which an identical re-call returns
# an identical payload. The bridge answers exact repeats with a memo so
# proxy-model repeat loops (see PiBridgeServer._run_tool) break instead
# of burning the tool budget and the context window. write_doc is NOT
# deduped (a model refining its draft may legitimately rewrite), nor
# run_example (execution is not assumed idempotent).
_DEDUPABLE_TOOLS = frozenset({
    "list_files", "read_file", "search_code", "inspect_api", "inspect_tests",
})

_DEFAULT_REQUEST_TIMEOUT_S = 120.0
_DEFAULT_RUN_EXAMPLE_TIMEOUT_S = 90.0
_DEFAULT_MAX_RESPONSE_BYTES = 256 * 1024
#: Hard cap on one inbound envelope line (guards the read loop from
#: unbounded buffering; legitimate model tool calls are far smaller).
_MAX_REQUEST_BYTES = 2 * 1024 * 1024

_STOP = object()


def _discover_pkg_path(source_root: str) -> Optional[str]:
    """Best-effort discovery of the single top-level package under
    *source_root* (a subdirectory containing ``__init__.py``).

    Used only when no explicit ``pkg_path`` is provided, so that
    ``run_example`` puts the directory that CONTAINS the package on the
    example's ``sys.path``. Returns ``None`` when there is no package or
    the choice is ambiguous (caller falls back to *source_root*).
    """
    try:
        entries = sorted(os.listdir(source_root))
    except OSError:
        return None
    candidates = [
        name for name in entries
        if not name.startswith(".")
        and os.path.isdir(os.path.join(source_root, name))
        and os.path.isfile(
            os.path.join(source_root, name, "__init__.py"))
    ]
    if len(candidates) == 1:
        return os.path.join(source_root, candidates[0])
    return None


class _BridgePolicyError(ValueError):
    """A defense-in-depth policy violation at the bridge layer."""


class PiBridgeServer:
    """Per-task Unix-socket server bridging Pi tool calls to Python tools.

    Args:
        tools: A :class:`ToolRegistry` (typically
            :class:`repoquill.agents.tools.RepoQuillTools`) to dispatch
            through. If omitted, one is built from *source_root* +
            *staging_docs_dir* via :func:`build_tool_context`.
        source_root: Read-only repository root (required when *tools* is
            omitted; otherwise it must match ``tools.ctx.repo_root``).
        pkg_path: Documented package path (only used when building the
            tools; defaults to *source_root*).
        staging_docs_dir: The ONLY writable tree (``docs_dir`` for the
            built tools; writes are further restricted to the task slug).
        slug: The single page slug this task may write
            (``<staging_docs_dir>/<slug>.md``).
        allow_example_exec: When False (default) ``run_example`` calls are
            refused with ``"example execution disabled"``.
        request_timeout_s: Wall-clock limit for any single tool request.
        run_example_timeout_s: Wall-clock limit for ``run_example``.
        max_response_bytes: Response size cap (default 256 KB).
        socket_dir: Directory for the socket file; a private temp dir is
            created (and removed on :meth:`stop`) when omitted.
    """

    def __init__(
        self,
        tools: Optional[ToolRegistry] = None,
        *,
        source_root: Optional[str] = None,
        staging_docs_dir: Optional[str] = None,
        slug: str,
        allow_example_exec: bool = False,
        request_timeout_s: float = _DEFAULT_REQUEST_TIMEOUT_S,
        run_example_timeout_s: float = _DEFAULT_RUN_EXAMPLE_TIMEOUT_S,
        max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
        socket_dir: Optional[str] = None,
        pkg_path: Optional[str] = None,
    ) -> None:
        if not slug or "/" in slug or "\\" in slug or ".." in slug:
            raise ValueError(f"invalid task slug: {slug!r}")
        if tools is None:
            if not source_root or not staging_docs_dir:
                raise ValueError(
                    "PiBridgeServer requires a tools instance or "
                    "source_root + staging_docs_dir")
            # build_tool_context takes a config-like object; bridge tasks
            # map directly onto its three path attributes. Without an
            # explicit pkg_path, discover the single top-level package so
            # run_example can import it (parent of the package dir goes on
            # the example's sys.path).
            pkg = pkg_path or _discover_pkg_path(source_root) or source_root
            cfg = types.SimpleNamespace(
                root=source_root,
                pkg_path=pkg,
                out_guides=staging_docs_dir,
            )
            tools = RepoQuillTools(build_tool_context(
                cfg, execute_examples=bool(allow_example_exec)))
        self._tools = tools
        self._repo_root = os.path.realpath(
            source_root or tools.ctx.repo_root)  # type: ignore[attr-defined]
        self._staging = os.path.realpath(
            staging_docs_dir or tools.ctx.docs_dir)  # type: ignore[attr-defined]
        self._slug = slug
        self._allow_example_exec = bool(allow_example_exec)
        self._request_timeout = float(request_timeout_s)
        self._run_example_timeout = float(run_example_timeout_s)
        self._max_response_bytes = int(max_response_bytes)

        self._owns_socket_dir = socket_dir is None
        self._socket_dir = socket_dir or tempfile.mkdtemp(
            prefix="repoquill-pi-bridge-")
        self._socket_path = os.path.join(self._socket_dir, "bridge.sock")

        # Exact-repeat detection state (per page run: a new bridge
        # server is built per task).
        self._seen_calls: Dict[str, Tuple[int, str]] = {}
        self._dedup_lock = threading.Lock()

        self._server: Optional[socket.socket] = None
        self._stop_event = threading.Event()
        self._queue: "queue.Queue[Any]" = queue.Queue()
        self._accept_thread: Optional[threading.Thread] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._conns: set = set()
        self._started = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    @property
    def socket_path(self) -> str:
        """Path for :data:`repoquill.pi.contracts.BRIDGE_SOCKET_ENV`."""
        return self._socket_path

    def start(self) -> "PiBridgeServer":
        os.makedirs(self._socket_dir, mode=0o700, exist_ok=True)
        if os.path.exists(self._socket_path):
            os.unlink(self._socket_path)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(self._socket_path)
        except OSError:
            server.close()
            raise
        server.listen(8)
        # Poll-style accept so stop() can wake the thread portably (closing
        # the fd does not reliably unblock a blocked accept()).
        server.settimeout(0.5)
        try:
            os.chmod(self._socket_path, 0o600)
        except OSError:
            pass
        self._server = server
        self._stop_event.clear()
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name="pi-bridge-accept", daemon=True)
        self._worker_thread = threading.Thread(
            target=self._worker_loop, name="pi-bridge-worker", daemon=True)
        self._accept_thread.start()
        self._worker_thread.start()
        self._started = True
        return self

    def stop(self) -> None:
        if not self._started:
            return
        self._stop_event.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
            self._server = None
        self._queue.put(_STOP)
        for conn in list(self._conns):
            try:
                conn.close()
            except OSError:
                pass
        for t in (self._worker_thread, self._accept_thread):
            if t is not None:
                t.join(timeout=5.0)
        self._worker_thread = None
        self._accept_thread = None
        self._conns.clear()
        if os.path.exists(self._socket_path):
            try:
                os.unlink(self._socket_path)
            except OSError:
                pass
        if self._owns_socket_dir:
            shutil.rmtree(self._socket_dir, ignore_errors=True)
        self._started = False

    def __enter__(self) -> "PiBridgeServer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # ------------------------------------------------------------------
    # Threading
    # ------------------------------------------------------------------
    def _accept_loop(self) -> None:
        assert self._server is not None
        while not self._stop_event.is_set():
            try:
                conn, _addr = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break  # server socket closed by stop()
            self._conns.add(conn)
            threading.Thread(
                target=self._read_loop, args=(conn,),
                name="pi-bridge-client", daemon=True).start()

    def _read_loop(self, conn: socket.socket) -> None:
        try:
            fh = conn.makefile("rb")
            while not self._stop_event.is_set():
                line = fh.readline(_MAX_REQUEST_BYTES + 1)
                if not line:
                    break
                if len(line) > _MAX_REQUEST_BYTES or not line.endswith(b"\n"):
                    self._send(conn, self._err(
                        "unknown", "request too large; connection closed"))
                    break
                self._queue.put((conn, line))
        except (OSError, ValueError):
            pass
        finally:
            self._conns.discard(conn)
            try:
                conn.close()
            except OSError:
                pass

    def _worker_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                break
            conn, line = item
            response, straggler = self._handle_line(line)
            # Answer immediately (incl. timeout failures), then wait for
            # any straggling tool so tools never run concurrently.
            self._send(conn, response)
            if straggler is not None:
                straggler.join()

    @staticmethod
    def _send(conn: socket.socket, envelope: Dict[str, Any]) -> None:
        try:
            conn.sendall(json.dumps(envelope).encode("utf-8") + b"\n")
        except OSError:
            pass  # client went away; the worker stays alive for others

    # ------------------------------------------------------------------
    # Envelope handling
    # ------------------------------------------------------------------
    def _handle_line(self, line: bytes) -> Tuple[Dict[str, Any],
                                                 Optional[threading.Thread]]:
        def done(resp: Dict[str, Any],
                 straggler: Optional[threading.Thread] = None
                 ) -> Tuple[Dict[str, Any], Optional[threading.Thread]]:
            return resp, straggler

        try:
            env = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            return done(self._err(
                "unknown", "malformed envelope: not valid JSON"))
        if not isinstance(env, dict):
            return done(self._err("unknown",
                                  "malformed envelope: not an object"))
        rid = env.get("id") if isinstance(env.get("id"), str) else "unknown"
        if env.get("v") != BRIDGE_PROTOCOL_VERSION:
            return done(self._err(rid, "unsupported bridge protocol version"))
        tool = env.get("tool")
        if not isinstance(tool, str):
            return done(self._err(rid,
                                  "malformed envelope: 'tool' must be a string"))
        args = env.get("args")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return done(self._err(rid,
                                  "malformed envelope: 'args' must be an object"))
        if tool not in _DISPATCHABLE:
            return done(self._err(rid, f"unknown tool: {tool}"))

        # Defense in depth: re-validate policy even though the tool
        # runtime validates too.
        try:
            self._validate_request(tool, args)
        except _BridgePolicyError as e:
            return done(self._err(rid, str(e)))

        result_q: "queue.Queue[Any]" = queue.Queue()
        runner = threading.Thread(
            target=self._run_tool, args=(tool, args, rid, result_q),
            name="pi-bridge-tool", daemon=True)
        runner.start()
        limit = (self._run_example_timeout
                 if tool == "run_example" else self._request_timeout)
        try:
            response = result_q.get(timeout=limit)
            # The tool finished in time: join before answering so the next
            # request can safely start.
            runner.join()
            return done(response)
        except queue.Empty:
            # Answer the timeout NOW; the worker joins the straggler after
            # sending so tools never overlap with the next execution.
            return done(self._err(rid, f"request timed out after {limit:g}s"),
                        runner)

    def _run_tool(self, tool: str, args: Dict[str, Any],
                  rid: str, out: "queue.Queue[Any]") -> None:
        # Determinism exploit: re-issuing an identical read-only call
        # returns the identical result, which is already in the model's
        # conversation (with default compaction settings the earlier
        # result is kept). Measured baseline runs show proxy models
        # re-issuing the SAME read/search 10-190 times and burning the
        # whole tool budget (and context) on it. Answer exact repeats
        # with a short memo instead of the payload: no information is
        # lost and the repeated-call loop is broken.
        dedup_key = self._dedup_key(tool, args)
        if dedup_key is not None:
            with self._dedup_lock:
                seen = self._seen_calls.get(dedup_key)
            if seen is not None:
                count, head = seen
                with self._dedup_lock:
                    self._seen_calls[dedup_key] = (count + 1, head)
                if count >= 4:
                    # The memo did not stop the loop: make it an ERROR
                    # so the model cannot treat it as more (duplicate)
                    # data, and tell it explicitly what to do instead.
                    # The supervisor's repeat guard aborts the run if
                    # the loop still continues.
                    out.put(self._err(rid, (
                        "ERROR: you have now called this exact tool "
                        f"{count + 1} times with identical arguments. "
                        "Re-calling is pointless - it is deterministic "
                        "and returns the same result you already have. "
                        "STOP exploring: verify the required symbols "
                        "against what you have read and call write_doc "
                        "now.")))
                    return
                out.put(self._ok(rid, {
                    "deduplicated": True,
                    "note": (
                        "You have already made this exact tool call "
                        f"{count} time(s) earlier in this run. It is "
                        "deterministic: re-calling returns the same "
                        "result, which is already in your conversation "
                        "above. Continue using what you have - verify "
                        "any remaining required symbols and then call "
                        "write_doc. Do not repeat identical calls."),
                    "previous_result_head": head,
                }))
                return
        try:
            result = self._tools.execute(tool, args)
        except Exception:  # noqa: BLE001 - envelope must always answer
            out.put(self._err(rid, "tool execution failed"))
            return
        if isinstance(result, ToolResult):
            if not result.ok:
                out.put(self._err(rid, result.error or "tool failed"))
                return
            self._record_call(dedup_key, result.data)
            out.put(self._ok(rid, result.data))
            return
        # Tolerate any other registry that returns a simple mapping.
        self._record_call(dedup_key, result)
        out.put(self._ok(rid, result))

    @staticmethod
    def _dedup_key(tool: str, args: Dict[str, Any]) -> Optional[str]:
        """Key for exact-repeat detection, or None (never dedupe)."""
        if tool not in _DEDUPABLE_TOOLS:
            return None
        try:
            return json.dumps([tool, args], sort_keys=True, default=str)
        except (TypeError, ValueError):
            return None

    def _record_call(self, key: Optional[str], data: Any) -> None:
        if key is None:
            return
        try:
            head = json.dumps(data, default=str)[:200]
        except (TypeError, ValueError):
            head = ""
        with self._dedup_lock:
            self._seen_calls[key] = (1, head)

    def _validate_request(self, tool: str, args: Dict[str, Any]) -> None:
        if tool in ("list_files", "search_code"):
            path = args.get("path")
            if path:
                self._check_read_path(path)
        elif tool == "read_file":
            self._check_read_path(args.get("path"))
        elif tool == "write_doc":
            slug = args.get("slug")
            if not isinstance(slug, str) or not slug.strip():
                raise _BridgePolicyError("write_doc requires a 'slug'")
            normalized = slug[:-3] if slug.endswith(".md") else slug
            if normalized != self._slug:
                raise _BridgePolicyError(
                    "write_doc may only write the task's own page "
                    f"(slug {self._slug!r})")
            target = os.path.realpath(
                os.path.join(self._staging, f"{self._slug}.md"))
            if not target.startswith(self._staging + os.sep):
                raise _BridgePolicyError("write target escapes staging dir")
        elif tool == "run_example":
            if not self._allow_example_exec:
                raise _BridgePolicyError("example execution disabled")
            code = args.get("code")
            if code is not None and not isinstance(code, str):
                raise _BridgePolicyError(
                    "run_example requires a string 'code'")

    def _check_read_path(self, path: Any) -> None:
        if not isinstance(path, str) or not path.strip():
            raise _BridgePolicyError("path must be a non-empty string")
        if path.startswith("/") or path.startswith("\\"):
            raise _BridgePolicyError(
                "absolute paths are not allowed; use repo-relative paths")
        if path.startswith("~"):
            raise _BridgePolicyError(
                "home-relative paths are not allowed")
        candidate = os.path.join(self._repo_root, path)
        target = os.path.realpath(candidate)  # resolves symlink traversal
        if target != self._repo_root and not target.startswith(
                self._repo_root + os.sep):
            raise _BridgePolicyError("path escapes the repository root")

    # ------------------------------------------------------------------
    # Envelope helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _err(rid: Any, message: str) -> Dict[str, Any]:
        return {"v": BRIDGE_PROTOCOL_VERSION, "id": rid, "ok": False,
                "error": str(message)[:500]}

    def _ok(self, rid: Any, data: Any) -> Dict[str, Any]:
        base = {"v": BRIDGE_PROTOCOL_VERSION, "id": rid, "ok": True,
                "data": data}
        if self._size(base) <= self._max_response_bytes:
            return base
        truncated = self._truncate_data(data, rid)
        capped = {"v": BRIDGE_PROTOCOL_VERSION, "id": rid, "ok": True,
                  "data": truncated}
        if self._size(capped) > self._max_response_bytes:
            # Last resort: keep only the marker (message stays small).
            capped["data"] = {
                "_truncated": True,
                "note": "response exceeded the bridge size cap and could "
                        "not be represented; re-request with narrower "
                        "arguments",
            }
        return capped

    def _size(self, envelope: Dict[str, Any]) -> int:
        try:
            return len(json.dumps(envelope).encode("utf-8"))
        except (TypeError, ValueError):
            return self._max_response_bytes + 1

    def _truncate_data(self, data: Any, rid: Any) -> Any:
        if not isinstance(data, dict):
            return {"_truncated": True,
                    "preview": str(data)[:2000],
                    "note": "response exceeded the bridge size cap"}
        d: Dict[str, Any] = dict(data)
        for _ in range(32):
            d["_truncated"] = True
            envelope = {"v": BRIDGE_PROTOCOL_VERSION, "id": rid, "ok": True,
                        "data": d}
            if self._size(envelope) <= self._max_response_bytes:
                return d
            shrank = False
            for key, value in list(d.items()):
                if isinstance(value, str) and len(value) > 128:
                    d[key] = value[: max(128, len(value) // 2)] + \
                        " ... (truncated by bridge)"
                    shrank = True
                elif isinstance(value, list) and len(value) > 8:
                    d[key] = value[: max(4, len(value) // 2)]
                    shrank = True
                elif isinstance(value, dict):
                    d[key] = {
                        "_truncated": True,
                        "note": "nested payload dropped to respect the "
                                "bridge size cap",
                    }
                    shrank = True
            if not shrank:
                break
        return d


__all__ = ["PiBridgeServer", "BRIDGE_PROTOCOL_VERSION"]
