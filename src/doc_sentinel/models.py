"""Core data models for the doc-sentinel index."""

from __future__ import annotations

import hashlib
from enum import StrEnum

from pydantic import BaseModel, Field

INDEX_VERSION = "1"


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ChunkKind(StrEnum):
    FUNCTION = "function"
    CLASS = "class"
    ROUTE = "route"
    CONFIG = "config"
    CLI = "cli"


class CodeChunk(BaseModel):
    id: str
    kind: ChunkKind
    file: str
    start_line: int
    end_line: int
    name: str
    qualified_name: str
    signature: str
    docstring: str = ""
    source: str
    source_hash: str
    # AST fingerprints used by change classification (Phase 2).
    signature_fp: str
    body_fp: str
    # Extra linkable names, e.g. config field names on a settings class.
    aliases: list[str] = Field(default_factory=list)

    def embedding_text(self) -> str:
        parts = [f"{self.kind.value} {self.qualified_name}", f"signature: {self.signature}"]
        if self.docstring:
            parts.append(f"docstring: {self.docstring}")
        return "\n".join(parts)


class DocSection(BaseModel):
    id: str
    file: str
    heading_path: list[str]
    start_line: int
    end_line: int
    content: str
    content_hash: str
    code_refs: list[str] = Field(default_factory=list)

    @property
    def heading_display(self) -> str:
        return " > ".join(self.heading_path)


class LinkKind(StrEnum):
    LEXICAL = "lexical"
    SEMANTIC = "semantic"


class Edge(BaseModel):
    section_id: str
    chunk_id: str
    kind: LinkKind
    score: float


class IndexConfig(BaseModel):
    code_roots: list[str] = Field(default_factory=lambda: ["."])
    doc_roots: list[str] = Field(default_factory=lambda: ["."])
    exclude_dirs: list[str] = Field(
        default_factory=lambda: [
            ".git",
            ".doc-sentinel",
            "tests",
            "test",
            "node_modules",
            ".venv",
            "venv",
            "__pycache__",
        ]
    )
    similarity_threshold: float = 0.75
    embedding_provider: str = "openai"


class DocIndex(BaseModel):
    version: str = INDEX_VERSION
    tool_version: str = "0.1.0"
    config: IndexConfig
    file_hashes: dict[str, str] = Field(default_factory=dict)
    chunks: list[CodeChunk] = Field(default_factory=list)
    sections: list[DocSection] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)

    def chunks_by_file(self) -> dict[str, list[CodeChunk]]:
        out: dict[str, list[CodeChunk]] = {}
        for chunk in self.chunks:
            out.setdefault(chunk.file, []).append(chunk)
        return out

    def sections_for_chunk(self, chunk_id: str) -> list[tuple[DocSection, Edge]]:
        sections = {s.id: s for s in self.sections}
        out = []
        for edge in self.edges:
            if edge.chunk_id == chunk_id and edge.section_id in sections:
                out.append((sections[edge.section_id], edge))
        return out
