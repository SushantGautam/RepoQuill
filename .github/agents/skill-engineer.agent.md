---
name: RepoQuill Skill
description: Fix hardcoded domain-specific SKILL.md generation and test generic project-derived agent instructions
user-invocable: false
---
Implement the **P0 generic SKILL.md** workstream.

Own: `repoquill/site.py` function `build_skill_md` and `tests/test_skill_generic.py`. Avoid unrelated edits to site layout and do not change orchestration modules.

Current `build_skill_md` contains hard-coded LLM auditing and scenario/judge language regardless of project. Replace with source/config-derived project descriptions, documented entry points, supported API sections and verified examples. Never assert workflows, installs or commands not proved by package metadata/source/example context. Generalize to arbitrary Python repositories, not only SimpleAudit.

Test with fixtures representing a CLI library, a plain utility library and a documentation repo without package-specific workflows. Ensure no ungrounded SimpleAudit phrases remain; preserve emitted `SKILL.md` expected shape/location as much as possible. Report changes and evidence.
