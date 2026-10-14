"""Flagship agentic E2E: the REAL pinned Pi binary authors a real page.

This test exercises the complete Pi-first documentation pipeline with a
real ``pi --mode rpc`` process (v1.2.0) and NO live LLM: a scripted
OpenAI-compatible mock model server on 127.0.0.1 (threaded http.server,
SSE streaming, per the verified pi-ai 1.2.0 wire format) drives a
discover → read → inspect → write_doc → done conversation.

The real pieces under test:
* ``repoquill.pi.models.build_ephemeral_agent_dir`` + ``model_pattern``
  (ephemeral Pi agent dir; API key only as a ``$ENV`` reference);
* ``repoquill.pi.extension.ts`` (vetted doc tools, no local file access);
* ``repoquill.pi.bridge.PiBridgeServer`` (per-task Unix-socket bridge to
  the existing ``RepoQuillTools`` — path-scoped reads, staging-only
  writes);
* ``repoquill.pi.rpc.PiRpcBackend`` (spawn, JSONL supervision, trace,
  usage, version, fail-closed errors).

After the run, the staged page is verified by the INDEPENDENT verifier
(``repoquill.agents.verify.verify_page_file``) — the writing agent never
sees it. The full sanitized tool trace is dumped to
``<tmp>/pi_e2e_trace.json`` and printed so CI logs show the actual
authoring evidence.
"""

from __future__ import annotations

import json
import os
import shutil
import types
from pathlib import Path

import pytest

from repoquill.pi import contracts

REPO_ROOT = Path(__file__).resolve().parent.parent
MINIUTIL = REPO_ROOT / "fixtures" / "miniutil"

REAL_PI = os.path.join(
    contracts.DEFAULT_PI_CACHE_DIR, "node_modules", ".bin", "pi")
HAS_REAL_PI = os.path.isfile(REAL_PI)
HAS_NODE = bool(shutil.which("node"))

pytestmark = pytest.mark.skipif(
    not (HAS_REAL_PI and HAS_NODE),
    reason="pinned pi binary (%s) or node not available" % REAL_PI,
)

SLUG = "textkit-guide"

# The page the scripted model writes with write_doc. It must satisfy the
# independent verifier against the real miniutil symbol index: real
# imports, real symbols (slugify, Counter, moving_average, TextStats),
# full semantic coverage.
PAGE = """## TextKit Guide

`miniutil.textkit` provides word statistics and URL-safe slug helpers.

```python
from miniutil import slugify, TextStats

s = TextStats("The quick brown fox")
print(s.word_count(), s.longest_word())
print(slugify("Hello, World!"))
```

### TextStats

`TextStats` computes word-level statistics over whitespace-separated
words: `word_count()` returns the number of words and `longest_word()`
returns the longest one.

### slugify

`slugify` lowercases arbitrary text and collapses runs of
non-alphanumeric characters into single hyphens, for example
`slugify("Hello, World!")` produces `hello-world`.

### Numeric helpers

Alongside TextKit, `miniutil.calc` offers `Counter`, a running numeric
counter (`add` then `total`), and `moving_average`, a sliding-window
average such as `moving_average([1, 2, 3, 4], 2)`.
"""

CHECKLIST = ["TextStats", "slugify", "Counter", "moving_average"]


def _scripted_model(messages):
    """Drive the conversation purely from accumulated tool results."""
    n = sum(1 for m in messages if m.get("role") == "tool")
    if n == 0:
        msg = {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function",
             "function": {"name": "list_files", "arguments": "{}"}}]}
        return msg, "tool_calls"
    if n == 1:
        msg = {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_2", "type": "function",
             "function": {"name": "read_file",
                          "arguments": json.dumps(
                              {"path": "miniutil/textkit.py"})}}]}
        return msg, "tool_calls"
    if n == 2:
        msg = {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_3", "type": "function",
             "function": {"name": "inspect_api",
                          "arguments": json.dumps({})}}]}
        return msg, "tool_calls"
    if n == 3:
        msg = {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_4", "type": "function",
             "function": {"name": "write_doc",
                          "arguments": json.dumps(
                              {"slug": SLUG, "content": PAGE})}}]}
        return msg, "tool_calls"
    return ({"role": "assistant",
             "content": "Page written via write_doc."}, "stop")


def test_pi_agentic_e2e_real_binary(tmp_path, monkeypatch):
    """Real Pi + real bridge + scripted model: author, then verify."""
    # The modules below land in parallel workstreams; skip cleanly with a
    # specific reason when any of them is absent.
    pytest.importorskip("repoquill.pi.rpc")
    pytest.importorskip("repoquill.pi.bridge")
    pytest.importorskip("repoquill.pi.models")
    extension_path = Path(contracts.__file__).parent / "extension.ts"
    if not extension_path.is_file():
        pytest.skip("repoquill/pi/extension.ts not landed yet")
    from tests.pi_fakes.mock_model_server import MockModelServer
    from repoquill.agents.contracts import PageTask, ToolContext
    from repoquill.agents.verify import verify_page_file
    from repoquill.agents.scheduler import build_pi_system_prompt
    from repoquill.pi.bridge import PiBridgeServer
    from repoquill.pi.models import build_ephemeral_agent_dir, model_pattern
    from repoquill.pi.rpc import PiRpcBackend

    assert MINIUTIL.is_dir(), "miniutil fixture is required for this test"

    staged = tmp_path / "staging"
    staged.mkdir()
    agent_dir = tmp_path / "agent"

    with MockModelServer(_scripted_model,
                         log_path=str(tmp_path / "model_requests.log")) as srv:
        # --- Ephemeral Pi model config (API key only as $ENV reference) --
        llm_cfg = types.SimpleNamespace(
            provider="fake", model="fake-model", base_url=srv.base_url,
            api_key_env="REPOQUILL_FAKE_KEY")
        monkeypatch.setenv("REPOQUILL_FAKE_KEY", "dummy-fake-key")
        build_ephemeral_agent_dir(llm_cfg, dest=str(agent_dir))
        model = model_pattern(llm_cfg)
        provider = model.rsplit("/", 1)[0]
        models_json = json.loads(
            (agent_dir / "models.json").read_text(encoding="utf-8"))
        api_key = models_json["providers"][provider]["apiKey"]
        assert api_key == "$REPOQUILL_FAKE_KEY", (
            "models.json must reference the key by env name, not literal")

        # --- Real bridge over fixtures/miniutil, staging-only writes ----
        bridge = PiBridgeServer(
            source_root=str(MINIUTIL),
            pkg_path=str(MINIUTIL / "miniutil"),
            staging_docs_dir=str(staged),
            slug=SLUG,
            allow_example_exec=False,
        )
        bridge.start()
        monkeypatch.setenv(contracts.BRIDGE_SOCKET_ENV, bridge.socket_path)
        try:
            # --- The task -------------------------------------------------
            staged_path = staged / (SLUG + ".md")
            task = contracts.PiTask(
                slug=SLUG,
                title="TextKit Guide",
                description="Guide to miniutil.textkit (TextStats, slugify) "
                            "and the miniutil.calc helpers (Counter, "
                            "moving_average).",
                evidence=(
                    "API surface: TextStats, slugify, Counter, "
                    "moving_average\n"
                    "source files: miniutil/textkit.py, miniutil/calc.py"),
                source_root=str(MINIUTIL),
                staged_docs_dir=str(staged),
                provider=provider,
                model=model,
                allow_example_exec=False,
                timeout_s=180.0,
                system_prompt=build_pi_system_prompt(
                    title="TextKit Guide",
                    description="miniutil.textkit guide",
                    staged_path=str(staged_path),
                    allow_example_exec=False),
            )

            # --- The real run ---------------------------------------------
            backend = PiRpcBackend(
                pi_bin=REAL_PI,
                extension_path=str(extension_path),
                agent_dir=str(agent_dir),
                startup_deadline_s=60.0,
            )
            result = backend.run(task)
        finally:
            bridge.stop()

    # --- Evidence: dump + print the sanitized tool trace ------------------
    trace = result.to_dict()
    (tmp_path / "pi_e2e_trace.json").write_text(
        json.dumps(trace, indent=2), encoding="utf-8")
    print("\n=== Pi E2E tool trace (%s) ===\n%s" % (
        result.pi_version, json.dumps(trace, indent=2)))

    # --- Result assertions --------------------------------------------------
    assert result.ok is True, (
        "Pi run failed: %s" % json.dumps(trace, indent=2))
    assert result.completed is True
    assert result.aborted is False
    assert result.pi_version == "1.2.0"
    assert result.elapsed_s > 0
    assert result.output_path == task.expected_output_path
    assert os.path.isfile(str(staged_path))
    assert result.usage.total_tokens > 0, (
        "mock server reports usage; the backend must surface it")

    names = [tc.name for tc in result.tool_calls]
    assert len(result.tool_calls) >= 2, names
    assert set(names) <= set(contracts.DOC_TOOL_ALLOWLIST), names
    assert "write_doc" in names, names
    assert ("read_file" in names) or ("inspect_api" in names) or (
        "list_files" in names or "search_code" in names), names
    assert all(tc.is_error is False for tc in result.tool_calls), (
        [tc.to_dict() for tc in result.tool_calls])
    # The model server saw a real multi-turn tool-calling conversation.
    assert len(srv.requests) >= 3, "expected a multi-turn model conversation"

    # --- Independent verification (NOT the writing agent) ------------------
    ctx = ToolContext(
        repo_root=str(MINIUTIL),
        pkg_path=str(MINIUTIL / "miniutil"),
        docs_dir=str(staged),
        execute_examples=False,
    )
    page_task = PageTask(
        slug=SLUG,
        title="TextKit Guide",
        description="miniutil.textkit guide",
        source_hints=["miniutil/textkit.py"],
        coverage_checklist=list(CHECKLIST),
        out_path=str(staged_path),
    )
    vres = verify_page_file(
        SLUG, str(staged_path), page_task, ctx,
        run_examples=False, coverage_threshold=0.6)
    assert vres.passed is True, vres.as_dict()
    assert vres.coverage.ratio == 1.0
    assert vres.import_findings == []
    assert vres.symbol_findings == []
