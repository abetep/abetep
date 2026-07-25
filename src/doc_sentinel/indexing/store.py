"""Persistence for the code-to-docs index (.doc-sentinel/index.json)."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from doc_sentinel.models import INDEX_VERSION, DocIndex

INDEX_DIR = ".doc-sentinel"
INDEX_FILE = "index.json"


class IndexError_(RuntimeError):
    pass


def index_path(repo_path: Path) -> Path:
    return repo_path / INDEX_DIR / INDEX_FILE


def save_index(index: DocIndex, repo_path: Path) -> Path:
    path = index_path(repo_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(index.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def load_index(repo_path: Path) -> DocIndex:
    path = index_path(repo_path)
    if not path.exists():
        raise IndexError_(f"No index found at {path}. Run `doc-sentinel index` first.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IndexError_(f"Index at {path} is not valid JSON: {exc}") from exc
    version = data.get("version")
    if version != INDEX_VERSION:
        raise IndexError_(
            f"Index version mismatch: file has {version!r}, tool expects {INDEX_VERSION!r}. "
            f"Re-run `doc-sentinel index`."
        )
    try:
        return DocIndex.model_validate(data)
    except ValidationError as exc:
        raise IndexError_(f"Index at {path} failed schema validation: {exc}") from exc
