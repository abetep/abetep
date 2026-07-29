"""Provider wiring: no Anthropic dependency, OpenAI-compatible overrides."""

import pytest

from doc_sentinel.llm.base import MissingCredentialsError
from doc_sentinel.llm.providers import DEFAULT_LLM_MODEL, OpenAICompatibleClient, get_llm

# Client-construction tests need the optional runtime extra.
openai = pytest.importorskip("openai")


def test_anthropic_provider_is_gone() -> None:
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        get_llm("anthropic")


def test_openai_client_requires_key_without_base_url(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DOC_SENTINEL_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("DOC_SENTINEL_LLM_API_KEY", raising=False)
    with pytest.raises(MissingCredentialsError, match="OPENAI_API_KEY"):
        OpenAICompatibleClient()


def test_alternate_endpoint_needs_no_openai_key(monkeypatch) -> None:
    """A self-hosted OpenAI-compatible server must work without any OpenAI key."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DOC_SENTINEL_LLM_API_KEY", raising=False)
    monkeypatch.setenv("DOC_SENTINEL_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("DOC_SENTINEL_LLM_MODEL", "qwen2.5-coder:32b")
    client = OpenAICompatibleClient()
    assert client._model == "qwen2.5-coder:32b"
    assert str(client._client.base_url).startswith("http://localhost:11434/v1")


def test_model_defaults_to_gpt4o(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("DOC_SENTINEL_LLM_MODEL", raising=False)
    monkeypatch.delenv("DOC_SENTINEL_LLM_BASE_URL", raising=False)
    client = OpenAICompatibleClient()
    assert client._model == DEFAULT_LLM_MODEL
