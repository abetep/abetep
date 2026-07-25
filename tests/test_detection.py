from pathlib import Path

from git import Repo

from doc_sentinel.cli import main
from doc_sentinel.detection.diff_parser import diff_chunks
from doc_sentinel.detection.models import ChangeType
from doc_sentinel.detection.suspects import find_suspects, meaningful_changes
from doc_sentinel.indexing.store import load_index


def git_repo(path: Path) -> Repo:
    repo = Repo.init(path)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "test")
        cw.set_value("user", "email", "test@example.com")
    repo.git.add(A=True)
    repo.index.commit("initial")
    return repo


def commit_all(repo: Repo, message: str) -> None:
    repo.git.add(A=True)
    repo.index.commit(message)


def test_diff_maps_changes_to_chunks(mini_repo: Path) -> None:
    repo = git_repo(mini_repo)
    api = mini_repo / "app" / "api.py"
    # rename a parameter, change a default, delete a function
    text = api.read_text()
    text = text.replace("include_posts: bool = False", "embed_posts: bool = False")
    text = text.replace("include_posts", "embed_posts")
    text = text[: text.index("def format_username")].rstrip() + "\n"
    api.write_text(text)
    config = mini_repo / "app" / "config.py"
    config.write_text(
        config.read_text().replace("timeout_seconds: int = 30", "timeout_seconds: int = 60")
    )
    commit_all(repo, "breaking changes")

    changes = {c.qualified_name: c for c in diff_chunks(mini_repo, "HEAD~1", "HEAD")}
    assert changes["get_user"].change_type == ChangeType.SIGNATURE_CHANGE
    assert changes["format_username"].change_type == ChangeType.REMOVED
    assert changes["AppSettings"].change_type == ChangeType.CONFIG_CHANGE
    # _load's signature and body both reference the renamed parameter
    assert changes["_load"].change_type in (
        ChangeType.SIGNATURE_CHANGE,
        ChangeType.BEHAVIOR_CHANGE,
    )


def test_cosmetic_only_diff_yields_no_meaningful_changes(mini_repo: Path) -> None:
    repo = git_repo(mini_repo)
    api = mini_repo / "app" / "api.py"
    text = api.read_text()
    text = text.replace('"""Normalize a username for display."""', '"""Normalize a username."""')
    text = text.replace(
        "    return result.upper() if upper else result",
        "    # choose casing\n    return result.upper() if upper else result",
    )
    api.write_text(text)
    commit_all(repo, "cosmetic only")

    changes = diff_chunks(mini_repo, "HEAD~1", "HEAD")
    assert meaningful_changes(changes) == []
    assert all(c.change_type == ChangeType.COSMETIC for c in changes)


def test_test_file_changes_are_ignored(mini_repo: Path) -> None:
    repo = git_repo(mini_repo)
    (mini_repo / "tests" / "test_api.py").write_text("def test_x():\n    assert 1 + 1 == 2\n")
    commit_all(repo, "touch tests")
    assert diff_chunks(mini_repo, "HEAD~1", "HEAD") == []


def test_suspects_come_from_link_graph(mini_repo: Path) -> None:
    repo = git_repo(mini_repo)
    assert main(["index", "--repo", str(mini_repo), "--embeddings", "none"]) == 0
    api = mini_repo / "app" / "api.py"
    api.write_text(api.read_text().replace("include_posts: bool = False", "embed: bool = False"))
    commit_all(repo, "rename param")

    index = load_index(mini_repo)
    changes = diff_chunks(mini_repo, "HEAD~1", "HEAD")
    suspects = find_suspects(index, changes)
    headings = {s.section.heading_display for s in suspects}
    assert "User Guide > API > Fetching users" in headings
    assert "User Guide > CLI" not in headings
    top = suspects[0]
    assert top.score == 1.0
    assert any(c.qualified_name == "get_user" for c in top.changes)


class ScriptedLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete_structured(self, system, user, schema, max_tokens=2048):
        self.calls.append(user)
        return self.responses.pop(0)


def _suspect(mini_repo: Path):
    from doc_sentinel.detection.models import ChunkChange, Suspect
    from doc_sentinel.indexing.code_parser import parse_repo
    from doc_sentinel.indexing.doc_parser import parse_docs

    chunks, _ = parse_repo(mini_repo, ["."], ["tests"])
    sections, _ = parse_docs(mini_repo, ["docs"], [])
    section = next(s for s in sections if s.heading_path[-1] == "Fetching users")
    get_user = next(c for c in chunks if c.name == "get_user")
    change = ChunkChange(
        chunk_id=get_user.id,
        file=get_user.file,
        qualified_name="get_user",
        change_type=ChangeType.SIGNATURE_CHANGE,
        old_chunk=get_user,
        new_chunk=get_user,
    )
    return Suspect(section=section, changes=[change], score=1.0)


def test_verifier_accepts_valid_verdict(mini_repo: Path) -> None:
    from doc_sentinel.detection.verifier import verify_suspect

    suspect = _suspect(mini_repo)
    llm = ScriptedLLM(
        [
            {
                "is_stale": True,
                "confidence": 0.9,
                "issues": [
                    {
                        "quote_from_docs": "include_posts=True",
                        "what_is_wrong": "parameter was renamed",
                        "what_code_says_now": "the parameter is now embed_posts",
                    }
                ],
            }
        ]
    )
    result = verify_suspect(llm, suspect)
    assert result.verdict is not None and result.verdict.is_stale
    assert len(llm.calls) == 1


def test_verifier_retries_on_fabricated_quote_then_fails_closed(mini_repo: Path) -> None:
    from doc_sentinel.detection.verifier import verify_suspect

    suspect = _suspect(mini_repo)
    bad = {
        "is_stale": True,
        "confidence": 0.9,
        "issues": [
            {
                "quote_from_docs": "THIS TEXT IS NOT IN THE DOCS",
                "what_is_wrong": "x",
                "what_code_says_now": "y",
            }
        ],
    }
    llm = ScriptedLLM([bad, dict(bad)])
    result = verify_suspect(llm, suspect)
    assert result.verdict is None, "invalid responses must fail closed (flag for review)"
    assert len(llm.calls) == 2
    assert "not verbatim substrings" in llm.calls[1]


def test_verifier_retries_on_schema_violation(mini_repo: Path) -> None:
    from doc_sentinel.detection.verifier import verify_suspect

    suspect = _suspect(mini_repo)
    good = {"is_stale": False, "confidence": 0.8, "issues": []}
    llm = ScriptedLLM([{"is_stale": "definitely"}, good])
    result = verify_suspect(llm, suspect)
    assert result.verdict is not None and not result.verdict.is_stale
    assert len(llm.calls) == 2


def test_check_report_via_cli_offline(mini_repo: Path, capsys) -> None:
    repo = git_repo(mini_repo)
    assert main(["index", "--repo", str(mini_repo), "--embeddings", "none"]) == 0
    api = mini_repo / "app" / "api.py"
    api.write_text(api.read_text().replace("include_posts: bool = False", "embed: bool = False"))
    commit_all(repo, "rename param")

    out = mini_repo / "report.json"
    rc = main(
        [
            "check",
            "--repo",
            str(mini_repo),
            "--base-ref",
            "HEAD~1",
            "--llm",
            "none",
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    import json

    from doc_sentinel.detection.models import CheckReport

    report = CheckReport.model_validate(json.loads(out.read_text()))
    assert report.changes and report.unverified
