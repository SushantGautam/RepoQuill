"""Agentic author: the multi-step tool-calling loop for one documentation page.

The author drives a generic, evidence-grounded loop over the OpenAI
function-calling protocol:

1. The model is sent the tool schemas from a
   :class:`~repoquill.agents.contracts.ToolRegistry` plus a page task and
   (optionally) a deterministic seed :class:`EvidencePack`.
2. While the model keeps requesting tools, each requested tool is executed
   through the registry (the ONLY code that can touch the repository), and
   the ``assistant`` turn with its ``tool_calls`` plus one ``tool``-role
   message per call are echoed back verbatim.
3. The loop is hard-bounded by :class:`AgentBudget` (steps + LLM calls) and
   never raises: an LLM outage or unexpected failure yields an
   ``AuthorResult`` with ``ok=False`` and a descriptive ``error``.
4. The page is persisted only through the terminal tool
   :data:`TERMINAL_TOOL` (``write_doc``); the independent verifier decides
   publication, never the author.

This module does NOT import :mod:`repoquill.llm` (the client is passed in,
duck-typed) and does NOT call :func:`build_evidence_pack` (an evidence pack
is passed in or omitted).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .contracts import (
    TERMINAL_TOOL,
    AgentBudget,
    AuthorResult,
    EvidencePack,
    PageTask,
    ToolContext,
    ToolRegistry,
    ToolResult,
)

__all__ = ["run_page_agent", "run_page_agent_specialized"]

# Character cap for any single evidence section embedded in the prompt.
_EVIDENCE_SECTION_CHARS = 8000
# Max characters kept in a transcript summary (the transcript is for
# humans/debugging, not a full replay).
_SUMMARY_CHARS = 240


_AUTHOR_SYSTEM_PROMPT = """You are a documentation authoring agent for a Python library. You have tools to explore the repository, read source and tests, inspect the authoritative API surface, and execute code examples in an isolated sandbox.

METHOD:
1. Use list_files / read_file / search_code to find the real source for this page.
2. Use inspect_api to learn the exact public symbols and signatures - you may ONLY document symbols that appear there.
3. Use inspect_tests to confirm behavior.
4. When you write a code example, use run_example to verify it actually works; if it fails, fix the example and re-run before documenting it.
5. When you are confident, call write_doc with the COMPLETE markdown page for the given slug, then stop.

RULES:
- Never invent a class, function, parameter, method, or behavior that is not confirmed by inspect_api, the source, or a passing run_example.
- Prefer fewer verified claims over more plausible ones.
- Use proper markdown with a '## <Title>' first header (no '# ' title).
- Reference real symbol names and real file paths.
- Length: 800-2000 words.
- You may write ONLY the documentation page via write_doc. You must never modify source code."""

_INVESTIGATOR_SYSTEM_PROMPT = """You are an investigation agent for a Python library. You have tools to explore the repository, read source and tests, inspect the authoritative API surface, and execute code examples in an isolated sandbox.

YOUR TASK: investigate the page's topic and return a structured evidence brief as your final text answer. Do NOT call write_doc.

The brief must list:
1. The confirmed public symbols relevant to this page, with their exact signatures (from inspect_api).
2. Verified behavior (from source, tests, or passing run_example runs).
3. 2-3 working code examples, each verified with run_example (include the actual observed output).

RULES: only include facts confirmed by inspect_api, source, tests, or a passing run_example. Never invent symbols or behavior."""


@dataclass
class _LoopOutcome:
    """Internal state accumulated by :func:`_author_loop`."""

    transcript: List[Dict[str, Any]] = field(default_factory=list)
    wrote_doc: bool = False
    last_write_doc: Optional[str] = None
    final_answer: Optional[str] = None
    ended_clean: bool = False
    error: Optional[str] = None


def _truncate(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... (truncated)"


def _summary(res: ToolResult) -> str:
    if not res.ok:
        return f"error: {res.error}"
    try:
        text = json.dumps(res.data)
    except (TypeError, ValueError):
        text = str(res.data)
    return _truncate(text, _SUMMARY_CHARS)


def _assistant_message(result, messages) -> Dict[str, Any]:
    """Echo an assistant turn with its tool_calls in OpenAI format."""
    msg: Dict[str, Any] = {
        "role": "assistant",
        "content": result.content,
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments or {}),
                },
            }
            for tc in result.tool_calls
        ],
    }
    messages.append(msg)
    return msg


def _author_loop(messages: List[Dict[str, Any]],
                 task: "PageTask",
                 registry: "ToolRegistry",
                 client,
                 budget: "AgentBudget",
                 max_tokens: int,
                 temperature: float,
                 persist_final: bool = True) -> _LoopOutcome:
    """Run the bounded tool-calling loop in place over *messages*.

    ``persist_final``: when the model ends with a plain text answer and no
    ``write_doc`` has happened, persist that answer as the page. The
    specialized investigator phase passes ``False`` (its final answer is a
    brief, not a page).
    """
    out = _LoopOutcome()
    try:
        while True:
            if not budget.can_continue():
                out.error = "budget exhausted before write_doc"
                break
            if not budget.consume_llm_call():
                out.error = "budget exhausted before write_doc"
                break
            result = client.chat_with_tools(
                messages,
                tools=registry.schemas(),
                max_tokens=max_tokens,
                temperature=temperature,
            )
            if result.done:
                # Final answer: no tool calls requested.
                content = (result.content or "").strip()
                out.final_answer = result.content
                out.transcript.append({
                    "role": "assistant",
                    "ok": True,
                    "summary": _truncate(content, _SUMMARY_CHARS),
                })
                if persist_final and not out.wrote_doc and content:
                    res = registry.execute(
                        TERMINAL_TOOL, {"slug": task.slug, "content": content})
                    if res.ok:
                        out.wrote_doc = True
                        out.last_write_doc = content
                messages.append({"role": "assistant", "content": result.content})
                out.ended_clean = True
                break
            # Tool-calling turn: echo the assistant turn back, then
            # execute each requested tool and echo the results.
            _assistant_message(result, messages)
            if not budget.consume_step():
                out.error = "budget exhausted before write_doc"
                break
            for tc in result.tool_calls:
                res = registry.execute(tc.name, tc.arguments or {})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": res.to_content(),
                })
                out.transcript.append({
                    "role": "tool",
                    "name": tc.name,
                    "ok": res.ok,
                    "summary": _summary(res),
                })
                if tc.name == TERMINAL_TOOL and res.ok:
                    out.wrote_doc = True
                    out.last_write_doc = (tc.arguments or {}).get("content") or ""
    except Exception as e:  # noqa: BLE001 - the author must never raise
        out.error = f"{type(e).__name__}: {e}"
    return out


def _evidence_section(evidence: Optional["EvidencePack"]) -> str:
    if evidence is None:
        return ""
    parts = ["STARTING EVIDENCE (verify & extend with your tools)"]
    if evidence.file_tree:
        parts.append("## file tree\n"
                     + _truncate(evidence.file_tree, _EVIDENCE_SECTION_CHARS))
    if evidence.candidate_files:
        parts.append("## candidate source files\n"
                     + "\n".join(f"- {f}" for f in evidence.candidate_files))
    if evidence.api_surface:
        parts.append("## api surface\n"
                     + _truncate(evidence.api_surface, _EVIDENCE_SECTION_CHARS))
    if evidence.candidate_tests:
        parts.append("## candidate tests\n"
                     + "\n".join(f"- {t}" for t in evidence.candidate_tests))
    if evidence.readme_excerpt:
        parts.append("## readme excerpt\n"
                     + _truncate(evidence.readme_excerpt, _EVIDENCE_SECTION_CHARS))
    return "\n\n".join(parts)


def _user_message(task: "PageTask",
                  evidence: Optional["EvidencePack"],
                  brief: Optional[str] = None) -> str:
    parts = [
        f"Page slug: {task.slug}",
        f"Page title: {task.title}",
    ]
    if task.description:
        parts.append(f"Description: {task.description}")
    if task.coverage_checklist:
        parts.append(
            "Expected coverage (each symbol must be verified, not assumed): "
            + ", ".join(task.coverage_checklist))
    ev = _evidence_section(evidence)
    if ev:
        parts.append(ev)
    parts.append(
        "You MUST confirm everything with your tool calls before documenting "
        "it. You may only document symbols that inspect_api confirms exist.")
    if brief:
        parts.append("INVESTIGATOR EVIDENCE BRIEF (already verified - you may "
                     "rely on it, but spot-check anything surprising)\n\n"
                     + _truncate(brief, _EVIDENCE_SECTION_CHARS))
    parts.append(
        f"Write the COMPLETE markdown page for slug '{task.slug}' by calling "
        f"{TERMINAL_TOOL}, then stop.")
    return "\n\n".join(parts)


def _read_page(task: "PageTask", ctx: "ToolContext") -> Optional[str]:
    """Read the persisted page, if any (prefers the task's out_path)."""
    candidates = []
    if task.out_path:
        candidates.append(task.out_path)
    try:
        candidates.append(ctx.resolve_write(task.slug))
    except ValueError:
        pass
    seen = set()
    for path in candidates:
        if not path or path in seen:
            continue
        seen.add(path)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8",
                      errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        if text.strip():
            return text
    return None


def _build_result(task: "PageTask", ctx: "ToolContext",
                  out: _LoopOutcome, budget: "AgentBudget") -> AuthorResult:
    on_disk = _read_page(task, ctx)
    if on_disk is not None:
        content = on_disk
    elif out.last_write_doc:
        content = out.last_write_doc
    elif out.final_answer and out.final_answer.strip():
        content = out.final_answer
    else:
        content = ""
    page_persisted = on_disk is not None
    ok = page_persisted and bool(content.strip())
    if not ok and out.error is None:
        out.error = "page was not produced"
    return AuthorResult(
        slug=task.slug,
        ok=ok,
        content=content if ok else "",
        steps=budget.steps_used,
        llm_calls=budget.llm_calls_used,
        transcript=out.transcript,
        error=None if ok else out.error,
        wrote_doc=out.wrote_doc,
    )


def _run(task: "PageTask",
         ctx: "ToolContext",
         registry: "ToolRegistry",
         client,
         budget: "AgentBudget",
         system_prompt: str,
         evidence: Optional["EvidencePack"],
         brief: Optional[str],
         max_tokens: int,
         temperature: float) -> AuthorResult:
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": _user_message(task, evidence, brief)},
    ]
    out = _run_phase(messages, task, registry, client, budget,
                     max_tokens, temperature)
    return _build_result(task, ctx, out, budget)


def _run_phase(messages: List[Dict[str, Any]],
               task: "PageTask",
               registry: "ToolRegistry",
               client,
               budget: "AgentBudget",
               max_tokens: int,
               temperature: float,
               persist_final: bool = True) -> _LoopOutcome:
    return _author_loop(messages, task, registry, client, budget,
                        max_tokens, temperature,
                        persist_final=persist_final)


def run_page_agent(task: "PageTask",
                   ctx: "ToolContext",
                   registry: "ToolRegistry",
                   client,
                   budget: Optional["AgentBudget"] = None,
                   evidence: Optional["EvidencePack"] = None,
                   role: str = "unified",
                   max_tokens: int = 8192,
                   temperature: float = 0.3) -> "AuthorResult":
    """Author one page with the unified single-agent tool-calling loop.

    Never raises. ``ok`` is True only when a non-empty page was persisted
    (via ``write_doc``); failures carry an ``error`` and ``ok=False``.
    """
    if budget is None:
        budget = AgentBudget()
    system_prompt = (_AUTHOR_SYSTEM_PROMPT
                     if role in ("unified", "") else str(role))
    return _run(task, ctx, registry, client, budget, system_prompt,
                evidence, None, max_tokens, temperature)


def run_page_agent_specialized(task: "PageTask",
                               ctx: "ToolContext",
                               registry: "ToolRegistry",
                               client,
                               budget: Optional["AgentBudget"] = None,
                               evidence: Optional["EvidencePack"] = None,
                               max_tokens: int = 8192) -> "AuthorResult":
    """Two-phase authoring (investigator -> writer) sharing ONE budget.

    Phase 1 investigates and returns a structured evidence brief as its
    final answer (no ``write_doc``). Phase 2 is the normal authoring loop,
    seeded with the brief, and is responsible for writing the page. The
    returned :class:`AuthorResult` is the writer's, with the investigator's
    LLM-call/step counts included (shared budget) and its transcript
    prepended.
    """
    if budget is None:
        budget = AgentBudget()

    # Phase 1: investigator (no terminal tool expected).
    inv_messages: List[Dict[str, Any]] = [
        {"role": "system", "content": _INVESTIGATOR_SYSTEM_PROMPT},
        {"role": "user", "content": _user_message(task, evidence)},
    ]
    inv_out = _run_phase(inv_messages, task, registry, client, budget,
                         max_tokens, 0.2, persist_final=False)
    brief = (inv_out.final_answer or "").strip()

    # Phase 2: writer, seeded with the brief; the shared budget already
    # carries the investigator's consumed steps/LLM calls.
    writer = _run(task, ctx, registry, client, budget,
                  _AUTHOR_SYSTEM_PROMPT, evidence, brief or None,
                  max_tokens, 0.3)
    writer.transcript = list(inv_out.transcript) + list(writer.transcript)
    return writer
