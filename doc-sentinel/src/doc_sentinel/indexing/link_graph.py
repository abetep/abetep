"""Build the code-to-docs link graph with lexical and semantic strategies."""

from __future__ import annotations

import math
import re

from doc_sentinel.llm.base import Embedder
from doc_sentinel.models import CodeChunk, DocSection, Edge, LinkKind

_BARE_NAME_MIN_LEN = 4


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _is_linkable_bare_name(name: str) -> bool:
    """Names safe to match outside backticks: snake_case, dotted, or CamelCase.

    Plain lowercase words ("helper", "run") are too likely to appear as
    English prose, so they only link when backtick-quoted.
    """
    return "_" in name or "." in name or (name[:1].isupper() and not name.isupper())


def build_lexical_edges(chunks: list[CodeChunk], sections: list[DocSection]) -> list[Edge]:
    by_name: dict[str, list[str]] = {}
    for chunk in chunks:
        by_name.setdefault(chunk.name, []).append(chunk.id)
        by_name.setdefault(chunk.qualified_name, []).append(chunk.id)

    edges: list[Edge] = []
    seen: set[tuple[str, str]] = set()
    for section in sections:
        mentioned: set[str] = set()
        for ref in section.code_refs:
            if ref in by_name:
                mentioned.add(ref)
            # `get_user()` style refs arrive without parens already; also try last dotted part
            tail = ref.rsplit(".", 1)[-1]
            if tail != ref and tail in by_name:
                mentioned.add(tail)
        for name in by_name:
            if name in mentioned:
                continue
            if len(name) >= _BARE_NAME_MIN_LEN and _is_linkable_bare_name(name):
                if re.search(rf"\b{re.escape(name)}\b", section.content):
                    mentioned.add(name)
        for name in mentioned:
            for chunk_id in by_name.get(name, []):
                pair = (section.id, chunk_id)
                if pair not in seen:
                    seen.add(pair)
                    edges.append(
                        Edge(
                            section_id=section.id,
                            chunk_id=chunk_id,
                            kind=LinkKind.LEXICAL,
                            score=1.0,
                        )
                    )
    return edges


def build_semantic_edges(
    chunks: list[CodeChunk],
    sections: list[DocSection],
    embedder: Embedder,
    threshold: float,
    skip_pairs: set[tuple[str, str]],
) -> list[Edge]:
    if not chunks or not sections:
        return []
    chunk_vecs = embedder.embed([c.embedding_text() for c in chunks])
    section_vecs = embedder.embed([s.content[:8000] for s in sections])
    edges: list[Edge] = []
    for section, svec in zip(sections, section_vecs, strict=True):
        for chunk, cvec in zip(chunks, chunk_vecs, strict=True):
            if (section.id, chunk.id) in skip_pairs:
                continue
            score = _cosine(svec, cvec)
            if score >= threshold:
                edges.append(
                    Edge(
                        section_id=section.id,
                        chunk_id=chunk.id,
                        kind=LinkKind.SEMANTIC,
                        score=round(score, 6),
                    )
                )
    return edges


def build_edges(
    chunks: list[CodeChunk],
    sections: list[DocSection],
    embedder: Embedder | None,
    threshold: float,
) -> list[Edge]:
    lexical = build_lexical_edges(chunks, sections)
    edges = list(lexical)
    if embedder is not None:
        skip = {(e.section_id, e.chunk_id) for e in lexical}
        edges.extend(build_semantic_edges(chunks, sections, embedder, threshold, skip))
    edges.sort(key=lambda e: (e.section_id, e.chunk_id, e.kind.value))
    return edges
