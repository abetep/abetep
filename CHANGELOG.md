# Changelog

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
