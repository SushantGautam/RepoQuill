---
name: RepoQuill Runtime
description: Implement the Pi-backed in-product authoring runtime rather than a new custom Python LLM agent
user-invocable: false
---
The original bounded repair runtime already exists at `repoquill/agents/repair.py`, and a homegrown multi-step LLM author exists at `repoquill/agents/author.py`. **Do not rebuild either.** This profile now belongs to the Pi-first milestone.

For actual work take the `RepoQuill Pi RPC` or `RepoQuill Pi Bridge` assignment from `engineering/PI_FIRST_CLASS_PLAN.md`; own only its explicitly allocated paths. Build around real `pi --mode rpc --no-session`. RepoQuill must be able to send a page task, observe tool calls, get staged output, enforce deadlines, and distinguish success, failure, abort and incomplete session.

No source changes from runtime agents; don't expose unrestricted `bash`/`edit`/`write`. Custom vetted Pi tools bridge to RepoQuill's Python source read/search/API/evidence and docs-only write semantics. Failure must preserve previously verified documentation. Unit tests and a real Pi smoke trace are acceptance evidence.

Coordinate interfaces early with Pi Integration, which alone edits `cli.py`, `config.py` and the current agents scheduler.
