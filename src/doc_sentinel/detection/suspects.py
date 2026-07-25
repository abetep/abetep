"""Select doc sections that might be stale given a set of code changes."""

from __future__ import annotations

from doc_sentinel.detection.models import MEANINGFUL_CHANGES, ChunkChange, Suspect
from doc_sentinel.models import DocIndex


def meaningful_changes(changes: list[ChunkChange]) -> list[ChunkChange]:
    return [c for c in changes if c.change_type in MEANINGFUL_CHANGES]


def find_suspects(index: DocIndex, changes: list[ChunkChange]) -> list[Suspect]:
    """Query the link graph for sections connected to changed chunks.

    Sections implicated by several changes are merged; the suspect score is
    the maximum edge score across implicating links.
    """
    by_section: dict[str, Suspect] = {}
    for change in meaningful_changes(changes):
        for section, edge in index.sections_for_chunk(change.chunk_id):
            existing = by_section.get(section.id)
            if existing is None:
                by_section[section.id] = Suspect(
                    section=section, changes=[change], score=edge.score
                )
            else:
                if change.chunk_id not in {c.chunk_id for c in existing.changes}:
                    existing.changes.append(change)
                existing.score = max(existing.score, edge.score)
    return sorted(by_section.values(), key=lambda s: (-s.score, s.section.id))
