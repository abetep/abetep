from pathlib import Path

from doc_sentinel.indexing.code_parser import parse_repo
from doc_sentinel.indexing.doc_parser import parse_docs
from doc_sentinel.indexing.link_graph import build_edges
from doc_sentinel.llm.base import CachedEmbedder, InMemoryEmbeddingCache
from doc_sentinel.models import LinkKind


class FakeEmbedder:
    """Deterministic embedder: identical vector iff texts share a marker word."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[1.0, 0.0] if "posts" in t else [0.0, 1.0] for t in texts]


def test_lexical_edges_link_docs_to_code(mini_repo: Path) -> None:
    chunks, _ = parse_repo(mini_repo, ["."], ["tests"])
    sections, _ = parse_docs(mini_repo, ["docs"], [])
    edges = build_edges(chunks, sections, embedder=None, threshold=0.75)
    linked = {(e.section_id.split("::")[1], e.chunk_id.split("::")[1]) for e in edges}
    assert ("User Guide > API > Fetching users", "get_user") in linked
    assert ("User Guide > Configuration > Environment Variables", "AppSettings") in linked
    assert ("User Guide > CLI", "sync") in linked
    assert all(e.kind == LinkKind.LEXICAL and e.score == 1.0 for e in edges)


def test_semantic_edges_added_above_threshold(mini_repo: Path) -> None:
    chunks, _ = parse_repo(mini_repo, ["."], ["tests"])
    sections, _ = parse_docs(mini_repo, ["docs"], [])
    edges = build_edges(chunks, sections, embedder=FakeEmbedder(), threshold=0.99)
    semantic = [e for e in edges if e.kind == LinkKind.SEMANTIC]
    assert semantic, "expected at least one semantic edge"
    # get_user's docstring mentions posts; the 'Fetching users' section mentions posts
    pairs = {(e.section_id.split("::")[1], e.chunk_id.split("::")[1]) for e in semantic}
    assert ("User Guide > API > Fetching users", "get_user") not in pairs, (
        "lexical pair must not be duplicated as semantic"
    )


def test_embedding_cache_prevents_recomputation() -> None:
    inner = FakeEmbedder()
    embedder = CachedEmbedder(inner, InMemoryEmbeddingCache())
    first = embedder.embed(["alpha posts", "beta"])
    second = embedder.embed(["alpha posts", "beta"])
    assert first == second
    assert len(inner.calls) == 1, "second call must be served entirely from cache"


def test_plain_word_names_require_backticks() -> None:
    from doc_sentinel.indexing.code_parser import parse_source
    from doc_sentinel.indexing.doc_parser import parse_markdown

    chunks = parse_source("def helper() -> None:\n    pass\n", "m.py")
    sections = parse_markdown("# Guide\n\nOur helper will assist you.\n", "d.md")
    edges = build_edges(chunks, sections, embedder=None, threshold=0.75)
    assert edges == [], "bare English word must not create a lexical link"
