"""LLM provider adapter (LiteLLM) + optional local-embedding RAG.

This module is the ONLY place RepoQuill talks to an LLM. It hides the
provider details behind a single :func:`chat` function so the rest of the
codebase is provider-agnostic.

Providers:
    Any provider LiteLLM supports — OpenAI, Anthropic, OpenRouter, Groq,
    Together, Ollama, vLLM, LM Studio, Open WebUI, etc. The provider,
    model, base_url, and API-key env var are all configured in
    ``repoquill.yml`` under the ``llm:`` block.

Secrets:
    The API key is NEVER stored in the config file. For standard providers
    the key is resolved by LiteLLM from the provider's standard env var
    (``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``, ``GROQ_API_KEY``, ...) —
    set it in your environment or as a GitHub Actions secret. The
    ``api_key_env`` config is only consulted for custom ``base_url``
    (OpenAI-compatible) endpoints.

RAG (optional):
    When ``llm.rag.enabled`` is true, RepoQuill builds a local vector
    index over the repo's source files using ``sentence-transformers``
    (running fully offline on the GitHub runner, no API key) and injects
    the top-k most relevant chunks into the prompt. When disabled (the
    default), source code is injected directly into the prompt.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

import litellm

# Drop unsupported params (e.g. temperature for o-series models)
litellm.drop_params = True

# Providers that run locally and never need an API key.
_LOCAL_PROVIDERS = {"ollama", "lm_studio", "vllm", "local"}


class LLMClient:
    """Thin wrapper over LiteLLM with retry/backoff and optional RAG.

    Attributes:
        llm_cfg: The :class:`repoquill.config.LLMConfig`.
    """

    def __init__(self, llm_cfg):
        self.llm_cfg = llm_cfg
        self._rag_index = None

    def _litellm_model(self) -> str:
        """Build the LiteLLM model string for the configured provider.

        Rules:
            - If ``base_url`` is set, the endpoint is OpenAI-compatible and
              the model is passed as-is (the server expects the bare model
              name). Routing is handled via ``custom_llm_provider`` in
              :meth:`chat`, not by prefixing the model string.
            - If the provider is "openai", the model is passed as-is.
            - Otherwise, prefix with ``{provider}/`` (e.g.
              ``anthropic/claude-...``, ``openrouter/...``).
        """
        cfg = self.llm_cfg
        if cfg.base_url or cfg.provider == "openai":
            return cfg.model
        return f"{cfg.provider}/{cfg.model}"

    def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        retries: int = 3,
    ) -> str:
        """Send a chat completion request and return the assistant text.

        Args:
            messages: OpenAI-style message list.
            max_tokens: Max tokens for the response.
            temperature: Sampling temperature.
            retries: Number of attempts with exponential backoff.

        Returns:
            The model's text response.

        Raises:
            RuntimeError: If all retries are exhausted.

        Note:
            API-key resolution is delegated to LiteLLM. For standard
            providers LiteLLM reads the key from the provider's standard
            env var (``OPENAI_API_KEY``, ``ANTHROPIC_API_KEY``,
            ``GROQ_API_KEY``, ...) — no explicit key is passed. Local and
            OAuth providers (e.g. github_copilot) need no key. The
            ``api_key_env`` config is only consulted for custom
            ``base_url`` (OpenAI-compatible) endpoints.
        """
        import litellm

        cfg = self.llm_cfg

        # Custom OpenAI-compatible endpoint: use the OpenAI client directly
        # with a custom user-agent. Some servers (e.g. behind Cloudflare)
        # block the default "OpenAI/Python" user-agent that LiteLLM's
        # wrapper sends, so we set our own.
        if cfg.base_url:
            return self._chat_openai_direct(
                messages=messages,
                api_key=self._resolve_api_key(),
                max_tokens=max_tokens,
                temperature=temperature,
                retries=retries,
            )

        # Standard providers: let LiteLLM resolve the API key itself.
        # LiteLLM reads each provider's key from its standard env var
        # (OPENAI_API_KEY, ANTHROPIC_API_KEY, GROQ_API_KEY, ...), so we
        # do NOT pass api_key explicitly — that would force a single
        # env-var name and defeat generic per-provider auth.
        kwargs: Dict[str, Any] = {
            "model": self._litellm_model(),
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        last_error: Optional[Exception] = None
        for attempt in range(retries):
            try:
                response = litellm.completion(**kwargs)
                return response.choices[0].message.content
            except Exception as e:  # noqa: BLE001
                last_error = e
                if attempt < retries - 1:
                    wait = 2 ** attempt
                    print(f"  retry {attempt + 1}/{retries} in {wait}s ({e})")
                    time.sleep(wait)
        raise RuntimeError(
            f"LLM request failed after {retries} attempts: {last_error}"
        ) from last_error

    def _chat_openai_direct(
        self,
        *,
        messages: List[Dict[str, str]],
        api_key: Optional[str],
        max_tokens: Optional[int],
        temperature: Optional[float],
        retries: int,
    ) -> str:
        """Call a custom OpenAI-compatible endpoint directly.

        Uses the ``openai`` Python client with a custom user-agent, because
        some OpenAI-compatible servers (e.g. behind Cloudflare) block the
        default ``OpenAI/Python`` user-agent that LiteLLM's wrapper sends.
        """
        from openai import OpenAI

        cfg = self.llm_cfg
        client = OpenAI(
            api_key=api_key,
            base_url=cfg.base_url,
            default_headers={
                "User-Agent": "repoquill/0.1.0 (+https://github.com/SushantGautam/RepoQuill)"
            },
        )
        last_error: Optional[Exception] = None
        for attempt in range(retries):
            try:
                response = client.chat.completions.create(
                    model=cfg.model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                return response.choices[0].message.content
            except Exception as e:  # noqa: BLE001
                last_error = e
                if attempt < retries - 1:
                    wait = 2 ** attempt
                    print(f"  retry {attempt + 1}/{retries} in {wait}s ({e})")
                    time.sleep(wait)
        raise RuntimeError(
            f"LLM request failed after {retries} attempts: {last_error}"
        ) from last_error

    def _resolve_api_key(self) -> Optional[str]:
        """Read the API key from the env var named in the config.

        Only used for custom ``base_url`` (OpenAI-compatible) endpoints,
        where LiteLLM's per-provider resolution doesn't apply. Standard
        providers resolve their key via LiteLLM directly.
        """
        return os.environ.get(self.llm_cfg.api_key_env)


class LocalRAG:
    """Optional local-embedding retrieval over the repo's source files.

    Builds an in-memory embedding index (sentence-transformers + numpy
    cosine similarity) at construction. No external service, no API key —
    runs entirely on the local machine / GitHub runner.
    """

    def __init__(self, rag_cfg: Dict[str, Any], source_files: Dict[str, str]):
        self.rag_cfg = rag_cfg
        self.source_files = source_files
        self._chunks: List[Dict[str, Any]] = []
        self._embeddings = None
        self._model = None

    def _chunk_text(self, path: str, text: str, chunk_size: int) -> List[str]:
        """Split text into ~chunk_size pieces on paragraph/line boundaries."""
        # Split into paragraphs (blank-line separated), then lines.
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        pieces: List[str] = []
        current = ""
        for para in paragraphs:
            # If a single paragraph is longer than chunk_size, split by lines.
            if len(para) > chunk_size:
                if current:
                    pieces.append(current)
                    current = ""
                for line in para.split("\n"):
                    if current and len(current) + len(line) + 1 > chunk_size:
                        pieces.append(current)
                        current = line
                    else:
                        current = f"{current}\n{line}" if current else line
                continue
            if current and len(current) + len(para) + 2 > chunk_size:
                pieces.append(current)
                current = para
            else:
                current = f"{current}\n\n{para}" if current else para
        if current:
            pieces.append(current)
        return pieces

    def build(self) -> None:
        """Chunk the source files and compute embeddings."""
        try:
            import numpy as np
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError(
                "RAG requires the optional 'rag' extra. Install it with: "
                "pip install repoquill[rag]"
            ) from e

        chunk_size = int(self.rag_cfg.get("chunk_size", 1500))
        model_name = self.rag_cfg.get("model", "all-MiniLM-L6-v2")

        # Chunk every source file, keeping the path with each chunk.
        self._chunks = []
        for path, text in self.source_files.items():
            for piece in self._chunk_text(path, text, chunk_size):
                self._chunks.append({"path": path, "content": piece})

        if not self._chunks:
            self._embeddings = None
            return

        self._model = SentenceTransformer(model_name)
        self._embeddings = self._model.encode(
            [c["content"] for c in self._chunks],
            normalize_embeddings=True,
            show_progress_bar=False,
        )

    def retrieve(self, query: str, top_k: int = 6) -> List[Dict[str, Any]]:
        """Return the top-k most relevant source chunks for a query.

        Args:
            query: The search query (e.g. the page title + description).
            top_k: Number of chunks to return.

        Returns:
            List of {path, content, score} dicts, most relevant first.
        """
        if self._embeddings is None:
            self.build()
        if self._embeddings is None or not self._chunks:
            return []

        import numpy as np

        query_vec = self._model.encode(
            [query], normalize_embeddings=True, show_progress_bar=False
        )[0]
        # Normalized vectors -> dot product == cosine similarity.
        scores = self._embeddings @ query_vec
        top_idx = np.argsort(scores)[::-1][:top_k]
        return [
            {
                "path": self._chunks[i]["path"],
                "content": self._chunks[i]["content"],
                "score": float(scores[i]),
            }
            for i in top_idx
        ]


def strip_code_fences(text: str) -> str:
    """Remove markdown code fences if the LLM wrapped its output in them.

    Args:
        text: Raw LLM output.

    Returns:
        The text with surrounding code fences removed.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()
