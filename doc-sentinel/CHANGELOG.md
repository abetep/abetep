# Changelog

## Unreleased

- **Provider-independent LLM client.** Removed the Anthropic API dependency;
  the single LLM client now speaks the OpenAI chat-completions standard and
  works against api.openai.com (default) or any OpenAI-compatible endpoint
  (Azure OpenAI, Ollama, vLLM, OpenRouter, …) via the new `llm-base-url`,
  `llm-model` and `llm-api-key` Action inputs
  (`DOC_SENTINEL_LLM_BASE_URL/_MODEL/_API_KEY` on the CLI). With
  `embeddings: none` plus a self-hosted endpoint the pipeline runs with no
  external API at all.

## v0.1.0 — 2026-07-25

Initial release.

- AST-based code→docs link graph (lexical + embedding similarity, ChromaDB
  content-hash cache)
- PR diff mapped to semantic chunks; cosmetic changes provably filtered on
  the AST
- LLM staleness verification with verbatim-quote validation and fail-closed
  semantics
- Surgical correction generator + LLM/difflib quality gate + confidence
  router (auto-fix / draft-with-TODOs / flag-only)
- Docker GitHub Action: docs-fix PRs, idempotent summary comment, typed
  outputs
- Offline evaluation harness: 13 labeled cases, precision 0.83 / recall 1.00
  at the retrieval stage
