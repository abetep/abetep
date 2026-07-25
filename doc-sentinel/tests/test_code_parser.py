from pathlib import Path

from doc_sentinel.indexing.code_parser import parse_repo, parse_source
from doc_sentinel.models import ChunkKind


def chunk_map(chunks):
    return {c.qualified_name: c for c in chunks}


def test_parses_all_chunk_kinds(mini_repo: Path) -> None:
    chunks, hashes = parse_repo(mini_repo, ["."], ["tests", ".git"])
    by_name = chunk_map(chunks)

    assert by_name["get_user"].kind == ChunkKind.ROUTE
    assert by_name["format_username"].kind == ChunkKind.FUNCTION
    assert by_name["AppSettings"].kind == ChunkKind.CONFIG
    assert by_name["sync"].kind == ChunkKind.CLI
    # Private helper is still chunked at module level (needed for diff mapping)
    assert "_load" in by_name
    # Test files are excluded
    assert not any(c.file.startswith("tests/") for c in chunks)
    assert "app/api.py" in hashes and "tests/test_api.py" not in hashes


def test_chunk_ids_and_spans_are_stable(mini_repo: Path) -> None:
    chunks, _ = parse_repo(mini_repo, ["."], ["tests"])
    get_user = chunk_map(chunks)["get_user"]
    assert get_user.id == "app/api.py::get_user"
    # span includes the decorator line
    assert get_user.source.startswith('@app.get("/users/{user_id}")')
    assert get_user.docstring.startswith("Fetch a user by id.")
    assert get_user.signature == "def get_user(user_id: int, include_posts: bool=False) -> dict"


def test_fingerprints_ignore_cosmetic_changes() -> None:
    v1 = "def f(a: int) -> int:\n    return a + 1\n"
    v2 = "def f(a: int) -> int:\n    # add one\n    return a + 1\n"
    v3 = 'def f(a: int) -> int:\n    """Docs."""\n    return a + 1\n'
    v4 = "def f(a: int) -> int:\n    return a + 2\n"
    c1, c2, c3, c4 = (parse_source(v, "m.py")[0] for v in (v1, v2, v3, v4))
    assert c1.body_fp == c2.body_fp == c3.body_fp
    assert c1.body_fp != c4.body_fp
    assert c1.signature_fp == c4.signature_fp


def test_signature_fingerprint_changes_on_rename_and_default() -> None:
    base = parse_source("def f(a: int, b: int = 1) -> int:\n    return a\n", "m.py")[0]
    renamed = parse_source("def f(a: int, c: int = 1) -> int:\n    return a\n", "m.py")[0]
    new_default = parse_source("def f(a: int, b: int = 2) -> int:\n    return a\n", "m.py")[0]
    assert base.signature_fp != renamed.signature_fp
    assert base.signature_fp != new_default.signature_fp


def test_methods_get_qualified_ids() -> None:
    src = "class Store:\n    def save(self, item: str) -> None:\n        pass\n"
    chunks = parse_source(src, "m.py")
    names = {c.qualified_name for c in chunks}
    assert names == {"Store", "Store.save"}


def test_syntax_errors_are_skipped() -> None:
    assert parse_source("def broken(:\n", "m.py") == []
