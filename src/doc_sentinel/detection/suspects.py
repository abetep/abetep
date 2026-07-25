"""Select doc sections that might be stale given a set of code changes."""

from __future__ import annotations

import re

from doc_sentinel.detection.diff_parser import config_changed_fields
from doc_sentinel.detection.models import (
    MEANINGFUL_CHANGES,
    ChangeType,
    ChunkChange,
    Suspect,
)
from doc_sentinel.models import CodeChunk, DocIndex, DocSection


def meaningful_changes(changes: list[ChunkChange]) -> list[ChunkChange]:
    return [c for c in changes if c.change_type in MEANINGFUL_CHANGES]


def _chunk_names(chunk: CodeChunk | None) -> set[str]:
    if chunk is None:
        return set()
    return {chunk.name, chunk.qualified_name, *chunk.aliases}


def _mentions(section: DocSection, name: str) -> bool:
    return name in section.code_refs or bool(re.search(rf"\b{re.escape(name)}\b", section.content))


def _config_relevant(section: DocSection, change: ChunkChange) -> bool:
    """For config changes, only implicate sections that mention a changed
    field or the config class itself — not every section that happens to
    reference some other field of the same settings class."""
    if change.change_type != ChangeType.CONFIG_CHANGE:
        return True
    changed = config_changed_fields(change.old_chunk, change.new_chunk)
    if not changed:
        return True
    class_names = {change.qualified_name}
    if change.new_chunk:
        class_names.add(change.new_chunk.name)
    if change.old_chunk:
        class_names.add(change.old_chunk.name)
    return any(_mentions(section, name) for name in changed | class_names)


def _lost_names(change: ChunkChange) -> set[str]:
    """Names that existed before the change but are gone after it.

    The index is built at head, so a removed function (or a deleted config
    field) has no chunk/alias to link through anymore; these names recover
    those sections by direct mention."""
    return _chunk_names(change.old_chunk) - _chunk_names(change.new_chunk)


def _add(
    by_section: dict[str, Suspect], section: DocSection, change: ChunkChange, score: float
) -> None:
    existing = by_section.get(section.id)
    if existing is None:
        by_section[section.id] = Suspect(section=section, changes=[change], score=score)
        return
    if change.chunk_id not in {c.chunk_id for c in existing.changes}:
        existing.changes.append(change)
    existing.score = max(existing.score, score)


def find_suspects(index: DocIndex, changes: list[ChunkChange]) -> list[Suspect]:
    """Query the link graph for sections connected to changed chunks.

    Sections implicated by several changes are merged; the suspect score is
    the maximum edge score across implicating links.
    """
    by_section: dict[str, Suspect] = {}
    for change in meaningful_changes(changes):
        for section, edge in index.sections_for_chunk(change.chunk_id):
            if not _config_relevant(section, change):
                continue
            _add(by_section, section, change, edge.score)
        for lost in _lost_names(change):
            for section in index.sections:
                if _mentions(section, lost):
                    _add(by_section, section, change, 1.0)
    return sorted(by_section.values(), key=lambda s: (-s.score, s.section.id))
