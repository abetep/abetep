"""Map a git diff between two refs onto code chunks."""

from __future__ import annotations

from pathlib import Path

from git import Repo

from doc_sentinel.detection.models import ChangeType, ChunkChange
from doc_sentinel.indexing.code_parser import parse_source
from doc_sentinel.models import CodeChunk


def _is_test_path(path: str) -> bool:
    parts = path.split("/")
    return any(p in ("tests", "test") for p in parts[:-1]) or parts[-1].startswith("test_")


def _blob_text(repo: Repo, ref: str, path: str) -> str | None:
    try:
        return str(repo.git.show(f"{ref}:{path}"))
    except Exception:
        return None


def changed_python_files(repo_path: Path, base_ref: str, head_ref: str) -> list[str]:
    repo = Repo(repo_path)
    diff = repo.commit(base_ref).diff(repo.commit(head_ref))
    files: set[str] = set()
    for d in diff:
        for p in (d.a_path, d.b_path):
            if p and p.endswith(".py") and not _is_test_path(p):
                files.add(p)
    return sorted(files)


def diff_chunks(repo_path: Path, base_ref: str, head_ref: str) -> list[ChunkChange]:
    """Compute per-chunk changes between two refs.

    Both versions of every changed file are re-parsed so old and new chunk
    fingerprints can be compared on the AST, not on text.
    """
    repo = Repo(repo_path)
    changes: list[ChunkChange] = []
    for path in changed_python_files(repo_path, base_ref, head_ref):
        old_src = _blob_text(repo, base_ref, path)
        new_src = _blob_text(repo, head_ref, path)
        old_chunks = {c.qualified_name: c for c in parse_source(old_src, path)} if old_src else {}
        new_chunks = {c.qualified_name: c for c in parse_source(new_src, path)} if new_src else {}
        for qname in sorted(old_chunks.keys() | new_chunks.keys()):
            old = old_chunks.get(qname)
            new = new_chunks.get(qname)
            change_type = _classify(old, new)
            if change_type is None:
                continue
            current = new or old
            chunk_id = current.id if current is not None else f"{path}::{qname}"
            changes.append(
                ChunkChange(
                    chunk_id=chunk_id,
                    file=path,
                    qualified_name=qname,
                    change_type=change_type,
                    old_chunk=old,
                    new_chunk=new,
                )
            )
    return changes


def _classify(old: CodeChunk | None, new: CodeChunk | None) -> ChangeType | None:
    from doc_sentinel.models import ChunkKind

    if old is None and new is None:
        return None
    if old is None:
        return ChangeType.ADDED
    if new is None:
        return ChangeType.REMOVED
    is_config = ChunkKind.CONFIG in (old.kind, new.kind)
    if old.signature_fp != new.signature_fp:
        return ChangeType.CONFIG_CHANGE if is_config else ChangeType.SIGNATURE_CHANGE
    if old.body_fp != new.body_fp:
        return ChangeType.CONFIG_CHANGE if is_config else ChangeType.BEHAVIOR_CHANGE
    if old.source_hash != new.source_hash:
        return ChangeType.COSMETIC
    return None
