"""Build or incrementally refresh the code-to-docs index."""

from __future__ import annotations

from pathlib import Path

from doc_sentinel.indexing.code_parser import parse_repo
from doc_sentinel.indexing.doc_parser import parse_docs
from doc_sentinel.indexing.link_graph import build_edges
from doc_sentinel.llm.base import Embedder
from doc_sentinel.models import CodeChunk, DocIndex, IndexConfig


def build_index(
    repo_path: Path,
    config: IndexConfig,
    embedder: Embedder | None,
    previous: DocIndex | None = None,
) -> DocIndex:
    """Parse the repo and build the full index.

    Incrementality: files whose content hash matches the previous index reuse
    their parsed chunks/sections. Embeddings are additionally cached by content
    hash inside the embedder, so unchanged text is never re-embedded even when
    a file is re-parsed.
    """
    chunks, code_hashes = parse_repo(repo_path, config.code_roots, config.exclude_dirs)
    sections, doc_hashes = parse_docs(repo_path, config.doc_roots, config.exclude_dirs)

    if previous is not None:
        prev_chunks_by_file = previous.chunks_by_file()
        reusable = {
            f: prev_chunks_by_file.get(f, [])
            for f, h in code_hashes.items()
            if previous.file_hashes.get(f) == h
        }
        fresh_by_file: dict[str, list[CodeChunk]] = {}
        for chunk in chunks:
            fresh_by_file.setdefault(chunk.file, []).append(chunk)
        merged: list[CodeChunk] = []
        for file in sorted(code_hashes):
            merged.extend(reusable.get(file) or fresh_by_file.get(file, []))
        chunks = merged

    edges = build_edges(chunks, sections, embedder, config.similarity_threshold)
    return DocIndex(
        config=config,
        file_hashes={**code_hashes, **doc_hashes},
        chunks=chunks,
        sections=sections,
        edges=edges,
    )
