"""Concrete embedding and LLM providers. Imports are lazy so tests run offline.

The LLM client speaks the OpenAI chat-completions API, which has become the
de-facto standard: point it at api.openai.com (default) or at any
OpenAI-compatible server (Azure OpenAI, Ollama, vLLM, OpenRouter, ...) via
DOC_SENTINEL_LLM_BASE_URL / DOC_SENTINEL_LLM_MODEL.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from doc_sentinel.llm.base import (
    CachedEmbedder,
    Embedder,
    EmbeddingCache,
    InMemoryEmbeddingCache,
    LLMClient,
    UsageTracker,
    require_env,
)

EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_LLM_MODEL = "gpt-4o"


class OpenAIEmbedder:
    def __init__(self, usage: UsageTracker | None = None) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=require_env("OPENAI_API_KEY"))
        self._usage = usage

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), 100):
            batch = [t[:8000] for t in texts[start : start + 100]]
            resp = self._client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
            out.extend(d.embedding for d in resp.data)
            if self._usage and resp.usage:
                self._usage.add_embeddings(resp.usage.total_tokens)
        return out


class NullEmbedder:
    """Used with --embeddings none: semantic linking is skipped entirely."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]


class ChromaEmbeddingCache:
    """Persistent embedding cache backed by a file-based ChromaDB collection."""

    def __init__(self, path: Path) -> None:
        import chromadb

        self._client = chromadb.PersistentClient(path=str(path))
        self._collection = self._client.get_or_create_collection("doc_sentinel_embeddings")

    def get_many(self, keys: list[str]) -> dict[str, list[float]]:
        if not keys:
            return {}
        result = self._collection.get(ids=keys, include=["embeddings"])
        ids = result.get("ids") or []
        embeddings = result.get("embeddings")
        if embeddings is None:
            return {}
        return {i: list(e) for i, e in zip(ids, embeddings, strict=True)}

    def put_many(self, items: dict[str, list[float]]) -> None:
        if not items:
            return
        # Typed as Any: chromadb's stubs want ndarray-typed embeddings but
        # accept plain float lists, and CI type-checks without chromadb
        # installed, so a targeted type-ignore would flag as unused there.
        embeddings: Any = list(items.values())
        self._collection.upsert(
            ids=list(items.keys()),
            embeddings=embeddings,
            documents=["" for _ in items],
        )


class OpenAICompatibleClient:
    """Structured-output client for any OpenAI-compatible chat endpoint.

    Environment overrides:
    - DOC_SENTINEL_LLM_BASE_URL: alternate endpoint (Azure, Ollama, vLLM, ...)
    - DOC_SENTINEL_LLM_MODEL: model name (default gpt-4o)
    - DOC_SENTINEL_LLM_API_KEY: key for the alternate endpoint; falls back to
      OPENAI_API_KEY, or "unused" for local servers that need none.
    """

    def __init__(self, usage: UsageTracker | None = None, model: str | None = None) -> None:
        from openai import OpenAI

        base_url = os.environ.get("DOC_SENTINEL_LLM_BASE_URL") or None
        api_key = os.environ.get("DOC_SENTINEL_LLM_API_KEY", "").strip()
        if not api_key:
            # Local OpenAI-compatible servers usually accept any key.
            api_key = "unused" if base_url else require_env("OPENAI_API_KEY")
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._usage = usage
        self._model = model or os.environ.get("DOC_SENTINEL_LLM_MODEL", DEFAULT_LLM_MODEL)

    def complete_structured(
        self, system: str, user: str, schema: dict[str, Any], max_tokens: int = 2048
    ) -> dict[str, Any]:
        resp = self._client.chat.completions.create(
            model=self._model,
            temperature=0,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": schema, "strict": False},
            },
        )
        if self._usage and resp.usage:
            self._usage.add_llm(resp.usage.prompt_tokens, resp.usage.completion_tokens)
        content = resp.choices[0].message.content or "{}"
        return dict(json.loads(content))


def get_embedder(
    provider: str, cache_path: Path | None, usage: UsageTracker | None = None
) -> Embedder | None:
    """Build the embedder for a provider name; None means skip semantic linking."""
    if provider == "none":
        return None
    if provider == "openai":
        cache: EmbeddingCache
        if cache_path is not None:
            cache = ChromaEmbeddingCache(cache_path)
        else:
            cache = InMemoryEmbeddingCache()
        return CachedEmbedder(OpenAIEmbedder(usage), cache)
    raise ValueError(f"Unknown embedding provider: {provider!r}")


def get_llm(provider: str, usage: UsageTracker | None = None) -> LLMClient:
    if provider == "openai":
        return OpenAICompatibleClient(usage)
    raise ValueError(f"Unknown LLM provider: {provider!r}")
