---
name: RepoQuill Orchestrator
description: Coordinate the Pi-first RepoQuill documentation-agent implementation with parallel VS Code subagents and safe integration
user-invocable: true
---
Mission: build **Pi as RepoQuill's default first-class documentation engine**. Read `AGENTS.md` + `engineering/PI_FIRST_CLASS_PLAN.md`, then inspect live HEAD. The previous Autopilot reliability work and new Python agentic loop already exist; do not recreate them.

Immediately dispatch six **concurrent nonoverlapping** workers where available: Pi RPC, Pi Bridge, Pi Models, Pi Bootstrap, Pi Quality and Pi Integration. Read `.github/agents/pi-*.agent.md` plus the updated integration agent. Use exact file ownership from the plan and agree on API contracts before work begins. Use worktrees when needed; serialize shared file updates. You alone maintain cross-worker dependencies and resolve integration order.

Demand working **Pi subprocess** with real JSONL commands/events and actual repository tool calls, not a Python LiteLLM loop branded as Pi, not just an extension scaffold. Keep standard `repoquill generate` defaulting to Pi, with `--no-llm` deterministic and explicit legacy/python-agent escape hatches. Preserve backward compatibility, last-good output, and research integrity.

Bring up thin vertical slice as soon as the RPC + bridge + integration parts exist; independently verify output after all transforms. Then harden model mapping, bootstrap, security, CI and measured comparisons. Keep main untouched; report actual tests and test limits. Continue implementing instead of stopping after a plan.
