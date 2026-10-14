---
name: RepoQuill Runtime
description: Build a lightweight optional mini-agent task runtime for evidence-grounded documentation repair
user-invocable: false
---
Implement the **optional production mini-agent runtime**. This is not the VS Code coding-agent orchestration; it is RepoQuill's opt-in repair subsystem.

Own: new `repoquill/agents/`, `tests/test_agent_runtime.py`. Do not edit `repoquill/llm.py`, `repoquill/cli.py`, `repoquill/narrative.py` or other workers' files.

Implement bounded task execution using an injected existing LLM client. Define immutable task/findings/evidence records, max retries, concurrency limit, token/call budget, task-specific instructions and output patch validation. Allow only documentation paths, stage proposed changes in memory or isolated temp area, and require independent validation before promotion. No shell-running privileges for the agent by default; no source edits, network or arbitrary tool calls. Subtasks should be independent and safely parallelizable when useful.

Start with minimal 'explain/repair page based on diagnostic' operations, not a sprawling general-purpose framework. Unit-test invalid patch paths, repeated failed repairs, budget exhaustion, no-LLM fallback, deterministic reporting and successful repair. Return an integration API and budget semantics.
