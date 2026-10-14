---
name: RepoQuill Pi Models
description: Map RepoQuill LLM config into ephemeral Pi custom-model provider configuration, including Qwen
user-invocable: false
---
Read `engineering/PI_FIRST_CLASS_PLAN.md` and https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md.

**Exclusive ownership:** new `repoquill/pi/models.py` and `tests/test_pi_models.py`. Don't touch `repoquill/config.py` or `repoquill/llm.py`; the integration agent owns config translation call sites.

Implement an ephemeral Pi provider/model settings generator using RepoQuill's `llm.provider`, `llm.model`, `llm.base_url`, `llm.api_key_env`. Support OpenAI-compatible Qwen with `api: openai-completions` and tested compatibility behavior. Validate endpoint URL, context window/max tokens and reasoning/sampling options; don't invent support for nonstandard tool calls. Never log or serialize raw API secrets into tracked config, session transcript or artifact. Prefer environment-reference keys, per-task isolated Pi settings, clean process env. Handle model override / provider list / missing key / wrong endpoint / failed tool-call format with informative errors.

Test with fake endpoint/model metadata, self-hosted Qwen-like path, context limits, token limits, auth handling and config roundtrip; provide a runnable real endpoint smoke when credentials are available.
