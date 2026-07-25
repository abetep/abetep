"""Provider-agnostic interfaces for embeddings and LLM completions."""

from __future__ import annotations

import hashlib
import os
from typing import Any, Protocol


class MissingCredentialsError(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise MissingCredentialsError(
            f"Environment variable {name} is required but not set. "
            f"Set it (e.g. via the Action input or repository secret) and re-run."
        )
    return value


class UsageTracker:
    """Accumulates token usage across LLM/embedding calls for cost reporting."""

    # USD per 1M tokens; rough public list prices, only used for the summary estimate.
    PRICES = {
        "embedding": (0.02, 0.0),
        "llm": (3.0, 15.0),
    }

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.embedding_tokens = 0
        self.calls = 0

    def add_llm(self, input_tokens: int, output_tokens: int) -> None:
        self.calls += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens

    def add_embeddings(self, tokens: int) -> None:
        self.calls += 1
        self.embedding_tokens += tokens

    def cost_estimate_usd(self) -> float:
        emb_in, _ = self.PRICES["embedding"]
        llm_in, llm_out = self.PRICES["llm"]
        return (
            self.embedding_tokens / 1e6 * emb_in
            + self.input_tokens / 1e6 * llm_in
            + self.output_tokens / 1e6 * llm_out
        )

    def summary(self) -> str:
        return (
            f"{self.calls} API calls, {self.input_tokens} in / {self.output_tokens} out "
            f"LLM tokens, {self.embedding_tokens} embedding tokens "
            f"(~${self.cost_estimate_usd():.4f})"
        )


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class LLMClient(Protocol):
    def complete_structured(
        self, system: str, user: str, schema: dict[str, Any], max_tokens: int = 2048
    ) -> dict[str, Any]:
        """Return a JSON object conforming to the given JSON schema."""
        ...


def text_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class EmbeddingCache(Protocol):
    def get_many(self, keys: list[str]) -> dict[str, list[float]]: ...

    def put_many(self, items: dict[str, list[float]]) -> None: ...


class InMemoryEmbeddingCache:
    def __init__(self) -> None:
        self._store: dict[str, list[float]] = {}

    def get_many(self, keys: list[str]) -> dict[str, list[float]]:
        return {k: self._store[k] for k in keys if k in self._store}

    def put_many(self, items: dict[str, list[float]]) -> None:
        self._store.update(items)


class CachedEmbedder:
    """Wraps an Embedder with a content-hash cache so unchanged text is never re-embedded."""

    def __init__(self, inner: Embedder, cache: EmbeddingCache) -> None:
        self._inner = inner
        self._cache = cache

    def embed(self, texts: list[str]) -> list[list[float]]:
        keys = [text_key(t) for t in texts]
        cached = self._cache.get_many(list(dict.fromkeys(keys)))
        missing: dict[str, str] = {}
        for key, text in zip(keys, texts, strict=True):
            if key not in cached and key not in missing:
                missing[key] = text
        if missing:
            fresh = self._inner.embed(list(missing.values()))
            new_items = dict(zip(missing.keys(), fresh, strict=True))
            self._cache.put_many(new_items)
            cached.update(new_items)
        return [cached[k] for k in keys]
