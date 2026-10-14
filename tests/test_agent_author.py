"""Tests for the agentic author loop (repoquill.agents.author).

Uses a synthetic package ``alpha``, a real :class:`RepoQuillTools` registry,
and scripted fake LLM clients that speak the OpenAI tool-calling protocol.
"""

import json
import os

from repoquill.agents.author import run_page_agent, run_page_agent_specialized
from repoquill.agents.contracts import (
    AgentBudget,
    ChatResult,
    PageTask,
    ToolCall,
    ToolContext,
)
from repoquill.agents.tools import RepoQuillTools

ALPHA_SRC = '''"""alpha package."""


class Widget:
    """A simple named widget."""

    def __init__(self, name):
        self.name = name

    def describe(self):
        return f"Widget({self.name})"


def make_widget(name):
    return Widget(name)
'''

EXAMPLE_CODE = "from alpha import make_widget\nprint(make_widget('x').describe())"

PAGE_CONTENT = (
    "## Alpha\n\n"
    "`Widget` and `make_widget` create named widgets. "
    "`Widget.describe()` returns a summary string.\n"
)


def _make_pkg(tmp_path):
    pkg = tmp_path / "alpha"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(ALPHA_SRC, encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    ctx = ToolContext(
        repo_root=str(tmp_path),
        pkg_path=str(pkg),
        docs_dir=str(docs),
        execute_examples=True,
    )
    task = PageTask(
        slug="alpha",
        title="Alpha",
        description="Core widget API of the alpha package.",
        coverage_checklist=["Widget", "make_widget"],
        out_path=str(docs / "alpha.md"),
    )
    return ctx, task


class FakeToolCallingClient:
    """Scripted client: pops the next ChatResult per chat_with_tools call."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def chat_with_tools(self, messages, tools, tool_choice=None,
                        max_tokens=None, temperature=None, retries=5):
        self.calls += 1
        if not self.script:
            return ChatResult(content="Done.", tool_calls=[])
        return self.script.pop(0)


class AlwaysToolsClient:
    """Never finishes: every call requests a tool."""

    def __init__(self):
        self.calls = 0

    def chat_with_tools(self, messages, tools, tool_choice=None,
                        max_tokens=None, temperature=None, retries=5):
        self.calls += 1
        return ChatResult(
            content=None,
            tool_calls=[ToolCall(id=f"loop{self.calls}",
                                 name="list_files", arguments={})],
        )


class OutageClient:
    def __init__(self):
        self.calls = 0

    def chat_with_tools(self, messages, tools, tool_choice=None,
                        max_tokens=None, temperature=None, retries=5):
        self.calls += 1
        raise RuntimeError("502 Bad Gateway")


def _standard_script():
    return [
        ChatResult(content=None, tool_calls=[
            ToolCall(id="c1", name="list_files", arguments={})]),
        ChatResult(content=None, tool_calls=[
            ToolCall(id="c2", name="inspect_api", arguments={})]),
        ChatResult(content=None, tool_calls=[
            ToolCall(id="c3", name="run_example",
                     arguments={"code": EXAMPLE_CODE})]),
        ChatResult(content=None, tool_calls=[
            ToolCall(id="c4", name="write_doc",
                     arguments={"slug": "alpha", "content": PAGE_CONTENT})]),
        ChatResult(content="Done.", tool_calls=[]),
    ]


def test_full_tool_calling_loop(tmp_path):
    ctx, task = _make_pkg(tmp_path)
    registry = RepoQuillTools(ctx)
    client = FakeToolCallingClient(_standard_script())

    result = run_page_agent(task, ctx, registry, client)

    assert result.ok is True
    assert result.error is None
    assert result.wrote_doc is True
    assert "Widget" in result.content
    assert os.path.isfile(task.out_path)
    with open(task.out_path, encoding="utf-8") as fh:
        assert "Widget" in fh.read()
    # 4 tool-calling turns + 1 final answer turn.
    assert result.llm_calls == 5
    assert client.calls == 5
    assert result.steps == 4
    # Transcript records the tool calls in order.
    tool_names = [e["name"] for e in result.transcript
                  if e["role"] == "tool"]
    assert tool_names == ["list_files", "inspect_api", "run_example",
                          "write_doc"]
    assert all(e["ok"] for e in result.transcript if e["role"] == "tool")
    # The run_example tool actually executed the snippet via subprocess.
    run_entry = next(e for e in result.transcript
                     if e.get("name") == "run_example")
    assert "Widget(x)" in run_entry["summary"]


def test_budget_exhaustion_is_bounded(tmp_path):
    ctx, task = _make_pkg(tmp_path)
    registry = RepoQuillTools(ctx)
    client = AlwaysToolsClient()

    result = run_page_agent(task, ctx, registry, client,
                            budget=AgentBudget(max_steps=2, max_llm_calls=2))

    assert result.ok is False
    assert result.wrote_doc is False
    assert result.error is not None and "budget" in result.error.lower()
    assert result.llm_calls <= 2
    assert result.steps <= 2
    assert not os.path.isfile(task.out_path)


def test_llm_outage_never_raises(tmp_path):
    ctx, task = _make_pkg(tmp_path)
    registry = RepoQuillTools(ctx)
    client = OutageClient()

    result = run_page_agent(task, ctx, registry, client)

    assert result.ok is False
    assert result.error is not None and "502" in result.error
    assert not os.path.isfile(task.out_path)


def test_final_answer_fallback_persists_page(tmp_path):
    ctx, task = _make_pkg(tmp_path)
    registry = RepoQuillTools(ctx)
    client = FakeToolCallingClient([
        ChatResult(content="## Alpha\nWidget", tool_calls=[]),
    ])

    result = run_page_agent(task, ctx, registry, client)

    assert result.ok is True
    assert result.wrote_doc is True  # author persisted via write_doc
    assert "Widget" in result.content
    assert os.path.isfile(task.out_path)
    with open(task.out_path, encoding="utf-8") as fh:
        assert fh.read() == "## Alpha\nWidget"
    assert result.llm_calls == 1
    assert result.steps == 0


def test_specialized_two_phase_shares_budget(tmp_path):
    ctx, task = _make_pkg(tmp_path)
    registry = RepoQuillTools(ctx)
    budget = AgentBudget(max_steps=4, max_llm_calls=6)
    client = FakeToolCallingClient([
        # Phase 1 (investigator): explore, then return the brief as final
        # answer (no write_doc).
        ChatResult(content=None, tool_calls=[
            ToolCall(id="i1", name="inspect_api", arguments={})]),
        ChatResult(content=(
            "EVIDENCE BRIEF\n"
            "- Widget: class, __init__(self, name), describe(self)\n"
            "- make_widget(name): returns Widget\n"
            "- verified: print(make_widget('x').describe()) -> Widget(x)\n"
        ), tool_calls=[]),
        # Phase 2 (writer): persist the page, then finish.
        ChatResult(content=None, tool_calls=[
            ToolCall(id="w1", name="write_doc",
                     arguments={"slug": "alpha", "content": PAGE_CONTENT})]),
        ChatResult(content="Done.", tool_calls=[]),
    ])

    result = run_page_agent_specialized(task, ctx, registry, client,
                                        budget=budget)

    assert result.ok is True
    assert result.wrote_doc is True
    assert "Widget" in result.content
    assert os.path.isfile(task.out_path)
    # Shared budget: 2 calls (investigator) + 2 calls (writer).
    assert result.llm_calls == 4
    assert budget.llm_calls_used == 4
    # 1 investigator step + 1 writer step.
    assert result.steps == 2
    # Investigator transcript is prepended.
    tool_names = [e["name"] for e in result.transcript
                  if e["role"] == "tool"]
    assert tool_names == ["inspect_api", "write_doc"]


def test_user_message_protocol_shape(tmp_path):
    """The client must see assistant tool_calls and tool-role replies."""
    ctx, task = _make_pkg(tmp_path)

    seen = {}

    class CaptureClient(FakeToolCallingClient):
        def chat_with_tools(self, messages, tools, **kw):
            seen["messages"] = [dict(m) for m in messages]
            seen["tools"] = tools
            return super().chat_with_tools(messages, tools, **kw)

    client = CaptureClient(_standard_script())
    registry = RepoQuillTools(ctx)

    run_page_agent(task, ctx, registry, client)

    msgs = seen["messages"]
    # Every assistant tool-calling turn is echoed with tool_calls, and each
    # tool call id is answered by exactly one tool-role message.
    assistant_turns = [m for m in msgs if m.get("tool_calls")]
    assert assistant_turns, "expected assistant turns with tool_calls"
    for turn in assistant_turns:
        assert turn["role"] == "assistant"
        for tc in turn["tool_calls"]:
            assert tc["type"] == "function"
            assert isinstance(tc["id"], str)
            json.loads(tc["function"]["arguments"])  # must be valid JSON
    tool_msgs = [m for m in msgs if m.get("role") == "tool"]
    assert len(tool_msgs) == 4
    for tm in tool_msgs:
        assert tm["tool_call_id"] in ("c1", "c2", "c3", "c4")
        payload = json.loads(tm["content"])
        assert payload["ok"] is True
    # Tool schemas were passed through.
    names = [s["function"]["name"] for s in seen["tools"]]
    assert "write_doc" in names and "run_example" in names
