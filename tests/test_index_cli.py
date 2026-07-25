import json
from pathlib import Path

import pytest

from doc_sentinel.cli import main
from doc_sentinel.indexing.store import IndexError_, load_index


def run_index(repo: Path) -> None:
    rc = main(["index", "--repo", str(repo), "--embeddings", "none"])
    assert rc == 0


def test_index_command_builds_valid_index(mini_repo: Path) -> None:
    run_index(mini_repo)
    index = load_index(mini_repo)
    assert index.chunks and index.sections and index.edges
    chunk_ids = {c.id for c in index.chunks}
    assert "app/api.py::get_user" in chunk_ids


def test_index_is_deterministic(mini_repo: Path) -> None:
    run_index(mini_repo)
    first = (mini_repo / ".doc-sentinel" / "index.json").read_text()
    run_index(mini_repo)
    second = (mini_repo / ".doc-sentinel" / "index.json").read_text()
    assert first == second


def test_incremental_rebuild_reuses_unchanged_files(mini_repo: Path) -> None:
    run_index(mini_repo)
    before = load_index(mini_repo)
    (mini_repo / "app" / "cli.py").write_text(
        'import click\n\n\n@click.command()\ndef sync() -> None:\n    """Sync."""\n'
    )
    run_index(mini_repo)
    after = load_index(mini_repo)
    get_user_before = next(c for c in before.chunks if c.name == "get_user")
    get_user_after = next(c for c in after.chunks if c.name == "get_user")
    assert get_user_before == get_user_after
    sync_after = next(c for c in after.chunks if c.name == "sync")
    assert "verbose" not in sync_after.signature


def test_version_mismatch_is_rejected(mini_repo: Path) -> None:
    run_index(mini_repo)
    path = mini_repo / ".doc-sentinel" / "index.json"
    data = json.loads(path.read_text())
    data["version"] = "999"
    path.write_text(json.dumps(data))
    with pytest.raises(IndexError_, match="version mismatch"):
        load_index(mini_repo)
