"""Threaded 127.0.0.1 OpenAI-compatible mock model server (SSE-only).

Pi (pi-ai 1.2.0, verified against ``dist/api/openai-completions.js``)
ALWAYS sends ``stream: true`` + ``stream_options: {"include_usage":
true}`` to ``POST <baseUrl>/chat/completions``. This server therefore
only ever answers with SSE (``data: <json>\n\n`` ... ``data: [DONE]\n\n``).

The conversation is scripted by the caller: ``script(messages)`` receives
the accumulated ``messages`` list from a request and returns
``(message, finish_reason)`` where ``message`` is an OpenAI assistant
message dict (``tool_calls`` for tool turns, ``content`` for text turns).

Unknown request params (``prompt_cache_key``, ``store``, ``temperature``,
``max_completion_tokens`` ...) are ignored. Every request body is logged
to ``log_path`` (one JSON object per line) for debugging.

No external network, ever: the server binds 127.0.0.1 on an ephemeral
port.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, List, Optional, Tuple

# (message, finish_reason)
Script = Callable[[List[dict]], Tuple[dict, str]]


def make_handler(script: Script, log_path: Optional[str],
                 requests_out: List[dict]):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # keep test output quiet
            pass

        def _send(self, code, ctype, data):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._send(404, "text/plain", b"not found")

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                req = json.loads(body.decode("utf-8") or "{}")
            except Exception:
                req = {}
            if log_path:
                with open(log_path, "a", encoding="utf-8") as fh:
                    fh.write(body.decode("utf-8", "replace") + "\n")
            requests_out.append(req)

            messages = req.get("messages", [])
            if not isinstance(messages, list):
                messages = []
            try:
                message, finish = script(messages)
            except Exception as e:  # defensive: never hang the client
                message, finish = {"role": "assistant",
                                   "content": "mock error: %s" % e}, "stop"
            model = req.get("model") or "mock-model"
            n = len(requests_out)
            cid = "chatcmpl-mock%d" % n
            head = {"id": cid, "object": "chat.completion.chunk",
                    "created": 1, "model": model}
            usage = {"prompt_tokens": 120 + 10 * n,
                     "completion_tokens": 25 + 5 * n,
                     "total_tokens": 145 + 15 * n}

            def chunk(choices, with_usage=False):
                c = {**head, "choices": choices}
                if with_usage:
                    c["usage"] = usage
                return c

            tool_calls = message.get("tool_calls")
            if tool_calls:
                frames = [
                    chunk([{"index": 0, "finish_reason": None,
                            "delta": {"role": "assistant",
                                      "content": message.get("content"),
                                      "tool_calls": tool_calls}}]),
                    chunk([{"index": 0, "delta": {},
                            "finish_reason": finish}], with_usage=True),
                ]
            else:
                frames = [
                    chunk([{"index": 0, "finish_reason": None,
                            "delta": {"role": "assistant",
                                      "content": message.get("content")
                                      or ""}}]),
                    chunk([{"index": 0, "delta": {},
                            "finish_reason": finish}], with_usage=True),
                ]
            data = b""
            for f in frames:
                data += b"data: " + json.dumps(f).encode() + b"\n\n"
            data += b"data: [DONE]\n\n"
            self._send(200, "text/event-stream", data)

    return Handler


class MockModelServer:
    """Context-managed mock model server on 127.0.0.1:<ephemeral port>."""

    def __init__(self, script: Script, log_path: Optional[str] = None):
        self._script = script
        self._log_path = log_path
        self.requests: List[dict] = []
        handler = make_handler(script, log_path, self.requests)
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    @property
    def base_url(self) -> str:
        return "http://127.0.0.1:%d/v1" % self.port

    def start(self) -> "MockModelServer":
        self._thread.start()
        return self

    def stop(self) -> None:
        try:
            self._server.shutdown()
        finally:
            self._server.server_close()

    def __enter__(self) -> "MockModelServer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
