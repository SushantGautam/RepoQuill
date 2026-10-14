"""JSONL record layer for the Pi RPC protocol (Pi v1.2.0).

Framing rules, per ``docs/rpc.md`` and ``docs/json.md`` of
``@earendil-works/pi-coding-agent``:

* one JSON object per record, terminated with LF (``\\n``);
* split records **only on LF** and strip one optional preceding CR;
* ``U+2028`` / ``U+2029`` are valid inside JSON strings and are NOT record
  boundaries -- never use ``str.splitlines()`` or universal-newline text
  readers on this stream;
* unparseable records produce a parse-error record (the same shape Pi itself
  emits on its own stdin: ``{"type":"response","command":"parse",...}``);
  the stream continues.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, Iterator, List, Optional

from . import contracts

# --------------------------------------------------------------------------- #
# Framing
# --------------------------------------------------------------------------- #

#: ``command`` value used by parse-error records (Pi's own convention).
PARSE_ERROR_COMMAND = "parse"


def encode_command(command: Dict[str, Any]) -> bytes:
    """Encode one command as a single JSON object + LF.

    ``ensure_ascii`` is set so that any Unicode line/paragraph separators in
    the payload are ``\\uXXXX``-escaped on the wire and can never be
    confused with record boundaries.
    """
    return (
        json.dumps(command, ensure_ascii=True, separators=(",", ":"))
        .encode("utf-8")
        + b"\n"
    )


def _decode_line(line: bytes) -> Optional[Dict[str, Any]]:
    if not line.strip():
        return None
    try:
        record = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return {
            "type": "response",
            "command": PARSE_ERROR_COMMAND,
            "success": False,
            "error": "failed to parse record: %s" % exc,
        }
    if not isinstance(record, dict):
        return {
            "type": "response",
            "command": PARSE_ERROR_COMMAND,
            "success": False,
            "error": "record is not a JSON object",
        }
    return record


def _strip_line(line: bytes) -> bytes:
    if line.endswith(b"\n"):
        line = line[:-1]
    if line.endswith(b"\r"):
        line = line[:-1]
    return line


def _read_chunk(reader: Any) -> bytes:
    """One non-over-reading read.

    ``BufferedReader.read(n)`` on a pipe may issue repeated raw reads until
    ``n`` bytes accumulate, which would stall on small records. ``read1(n)``
    (or a raw ``read``) returns after a single underlying read, so records
    are delivered as soon as they are complete.
    """
    read1 = getattr(reader, "read1", None)
    if callable(read1):
        return read1(8192)
    return reader.read(8192)


def decode_stream(reader: Any) -> Iterator[Dict[str, Any]]:
    """Yield one dict per LF-terminated record from a **binary** reader.

    ``reader`` needs a binary ``readline()`` (subprocess stdout pipes,
    ``io.BytesIO``) or, failing that, ``read(n)``/``read1(n)``. Records are
    split strictly on LF (one optional preceding CR stripped); binary
    readline never treats ``U+2028``/``U+2029`` inside JSON strings as
    boundaries. Unparseable records are yielded as parse-error records and
    iteration continues. A trailing unterminated fragment (if any) is
    decoded once the stream ends.
    """
    if hasattr(reader, "readline"):
        while True:
            line = reader.readline()
            if not line:
                break
            record = _decode_line(_strip_line(line))
            if record is not None:
                yield record
        return
    buf = b""
    while True:
        chunk = _read_chunk(reader)
        if not chunk:
            break
        buf += chunk
        while True:
            idx = buf.find(b"\n")
            if idx < 0:
                break
            line, buf = buf[:idx], buf[idx + 1:]
            record = _decode_line(_strip_line(line))
            if record is not None:
                yield record
    if buf:
        record = _decode_line(buf)
        if record is not None:
            yield record


# --------------------------------------------------------------------------- #
# Prompt disposition
# --------------------------------------------------------------------------- #

def prompt_disposition(response: Dict[str, Any]) -> str:
    """Return the prompt response's ``data.disposition`` ("" if absent).

    ``"started"`` / ``"queued"`` mean a run (or queued work) is pending and
    the client must wait for ``agent_settled``; ``"handled"`` means the
    prompt was consumed without starting a run, so no wait is warranted.
    """
    data = response.get("data")
    if isinstance(data, dict) and isinstance(data.get("disposition"), str):
        return data["disposition"]
    return ""


# --------------------------------------------------------------------------- #
# Sanitization (tool trace safety)
# --------------------------------------------------------------------------- #

REDACTED = "***redacted***"
MAX_ARG_STRING_CHARS = 200
MAX_RESULT_SUMMARY_CHARS = 300
STDERR_TAIL_BYTES = 2048

_SECRET_KEY_PARTS = ("api", "key", "token", "secret", "password", "auth")
_TOKEN_LITERAL_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_\-]{8,}|gh[pousr]_[A-Za-z0-9]{8,}|"
    r"AKIA[A-Z0-9]{16}|xox[baprs]-[A-Za-z0-9\-]{8,})\b"
)
#: ``args`` keys whose string values may be treated as source paths.
_PATH_ARG_KEYS = {
    "path", "file", "filename", "dir", "directory",
    "root", "target", "repo", "cwd",
}
_SOURCE_TOOL_RE = re.compile(r"(read|search|list|inspect)", re.I)


def _is_secret_key(key: Any) -> bool:
    lowered = str(key).lower()
    return any(part in lowered for part in _SECRET_KEY_PARTS)


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "\u2026"  # ellipsis keeps total <= limit


def _redact_token_literals(value: str) -> str:
    if _TOKEN_LITERAL_RE.search(value):
        return REDACTED
    return value


def sanitize_args(args: Any) -> Dict[str, Any]:
    """Return a log-safe copy of tool ``args``.

    * string values longer than ``MAX_ARG_STRING_CHARS`` are truncated;
    * values under keys matching (api|key|token|secret|password|auth) are
      replaced with :data:`REDACTED`;
    * string values that look like bearer/API tokens are replaced.
    """
    out: Dict[str, Any] = {}
    if args is None:
        return out
    if not isinstance(args, dict):
        out["value"] = _truncate(_redact_token_literals(str(args)), MAX_ARG_STRING_CHARS)
        return out
    for key, value in args.items():
        if isinstance(value, dict):
            out[key] = sanitize_args(value)
        elif isinstance(value, list):
            out[key] = [
                sanitize_args(item) if isinstance(item, dict)
                else (_truncate(_redact_token_literals(item), MAX_ARG_STRING_CHARS)
                      if isinstance(item, str) else item)
                for item in value
            ]
        elif isinstance(value, str):
            if _is_secret_key(key):
                out[key] = REDACTED
            else:
                out[key] = _truncate(_redact_token_literals(value), MAX_ARG_STRING_CHARS)
        else:
            out[key] = REDACTED if _is_secret_key(key) else value
    return out


def summarize_result(result: Any) -> str:
    """Collapse a tool ``result`` to a single-line summary (<=300 chars)."""
    if result is None:
        return ""
    if isinstance(result, str):
        text = result
    elif isinstance(result, dict):
        parts: List[str] = []
        content = result.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
        if not parts:
            try:
                text = json.dumps(result, ensure_ascii=True, default=str)
            except (TypeError, ValueError):
                text = str(result)
        else:
            text = "\n".join(parts)
    else:
        text = str(result)
    text = " ".join(text.split())  # one line
    text = _redact_token_literals(text)
    return _truncate(text, MAX_RESULT_SUMMARY_CHARS)


def redact_secrets(text: str) -> str:
    """Redact obvious secrets from free-form text (e.g. stderr tails)."""
    if not text:
        return text
    text = re.sub(
        r"(?i)\b(api[-_ ]?key|apikey|token|secret|passwd|password|"
        r"authorization|bearer)\b(\s*[:=]\s*)(\S+)",
        r"\1\2***",
        text,
    )
    text = _TOKEN_LITERAL_RE.sub("***", text)
    return text


# --------------------------------------------------------------------------- #
# Tool trace
# --------------------------------------------------------------------------- #

class ToolTrace:
    """Accumulates sanitized :class:`contracts.PiToolCall` entries from
    ``tool_execution_start`` / ``tool_execution_update`` /
    ``tool_execution_end`` events, plus the source paths the agent read."""

    def __init__(self) -> None:
        self._calls: Dict[str, contracts.PiToolCall] = {}
        self.source_paths: List[str] = []

    @property
    def tool_calls(self) -> List[contracts.PiToolCall]:
        return list(self._calls.values())

    def handle(self, record: Any) -> None:
        if not isinstance(record, dict):
            return
        rtype = record.get("type")
        if rtype not in (
            contracts.EV_TOOL_START,
            contracts.EV_TOOL_UPDATE,
            contracts.EV_TOOL_END,
        ):
            return
        call_id = str(record.get("toolCallId") or "")
        if not call_id:
            return
        call = self._calls.get(call_id)
        if call is None:
            call = contracts.PiToolCall(
                tool_call_id=call_id,
                name=str(record.get("toolName") or "unknown"),
                started_at=time.monotonic(),
            )
            self._calls[call_id] = call
        if rtype == contracts.EV_TOOL_START:
            call.name = str(record.get("toolName") or call.name)
            call.args = sanitize_args(record.get("args"))
            self._collect_source_paths(call.name, record.get("args"))
        elif rtype == contracts.EV_TOOL_END:
            call.is_error = bool(record.get("isError", False))
            if isinstance(record.get("durationMs"), (int, float)):
                call.duration_ms = int(record["durationMs"])
            call.result_summary = summarize_result(record.get("result"))

    def _collect_source_paths(self, name: str, args: Any) -> None:
        if not isinstance(args, dict) or not _SOURCE_TOOL_RE.search(name):
            return
        for key, value in args.items():
            if not isinstance(value, str) or key.lower() not in _PATH_ARG_KEYS:
                continue
            if not value or len(value) > 2048 or value.startswith("-"):
                continue
            if value not in self.source_paths:
                self.source_paths.append(value)


# --------------------------------------------------------------------------- #
# Usage aggregation
# --------------------------------------------------------------------------- #

def _as_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


class UsageAggregator:
    """Aggregates cumulative per-assistant-message usage.

    ``message_update`` records carry the latest *cumulative* provider usage
    for the in-flight message, so the aggregate is the **max** of each field
    observed across the run, never a sum.
    """

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_tokens = 0
        self.cache_write_tokens = 0
        self.cost = 0.0

    @property
    def total(self) -> int:
        """Peak cumulative total tokens observed (max per field)."""
        return (self.input_tokens + self.output_tokens
                + self.cache_read_tokens + self.cache_write_tokens)

    def observe_record(self, record: Any) -> None:
        if isinstance(record, dict) and record.get("type") == contracts.EV_MSG_UPDATE:
            self.observe_usage(record.get("usage"))

    def observe_usage(self, usage: Any) -> None:
        if not isinstance(usage, dict):
            return
        self.input_tokens = max(self.input_tokens, _as_int(usage.get("input")))
        self.output_tokens = max(self.output_tokens, _as_int(usage.get("output")))
        self.cache_read_tokens = max(
            self.cache_read_tokens, _as_int(usage.get("cacheRead")))
        self.cache_write_tokens = max(
            self.cache_write_tokens, _as_int(usage.get("cacheWrite")))
        total = None
        cost = usage.get("cost")
        if isinstance(cost, dict):
            total = cost.get("total")
            if total is None:
                total = sum(
                    _as_float(cost.get(k))
                    for k in ("input", "output", "cacheRead", "cacheWrite")
                )
        self.cost = max(self.cost, _as_float(total))

    def to_pi_usage(self) -> contracts.PiUsage:
        return contracts.PiUsage(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read_tokens=self.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens,
            cost=round(self.cost, 10),
        )


__all__ = [
    "PARSE_ERROR_COMMAND",
    "REDACTED",
    "MAX_ARG_STRING_CHARS",
    "MAX_RESULT_SUMMARY_CHARS",
    "STDERR_TAIL_BYTES",
    "encode_command",
    "decode_stream",
    "prompt_disposition",
    "sanitize_args",
    "summarize_result",
    "redact_secrets",
    "ToolTrace",
    "UsageAggregator",
]
