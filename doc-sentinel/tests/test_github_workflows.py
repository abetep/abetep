"""Phase 4 tests: summary comment idempotency, fix PR flow, pipeline integration."""

from pathlib import Path

from git import Repo

from doc_sentinel.detection.models import (
    ChangeType,
    CheckReport,
    StalenessVerdict,
    VerifiedSuspect,
)
from doc_sentinel.github.workflows import (
    SUMMARY_MARKER,
    build_fix_pr_body,
    build_summary_body,
    open_fix_pr,
    push_fix_branch,
    upsert_summary_comment,
)
from doc_sentinel.llm.base import UsageTracker
from doc_sentinel.repair.models import (
    Correction,
    DocEdit,
    RepairMode,
    RepairReport,
    SectionRepair,
    ValidationResult,
)
from doc_sentinel.repair.router import RouterConfig

from .test_repair import make_suspect, stale_verdict


class FakeComment:
    def __init__(self, body: str) -> None:
        self.body = body

    def edit(self, body: str) -> None:
        self.body = body


class FakePR:
    def __init__(self) -> None:
        self.comments: list[FakeComment] = []

    def get_issue_comments(self):
        return list(self.comments)

    def create_issue_comment(self, body: str) -> FakeComment:
        comment = FakeComment(body)
        self.comments.append(comment)
        return comment


class FakeRepo:
    def __init__(self) -> None:
        self.pulls: list[dict] = []

    def create_pull(self, *, title: str, body: str, head: str, base: str):
        record = {"title": title, "body": body, "head": head, "base": base}
        self.pulls.append(record)

        class _PR:
            html_url = "https://example.com/pull/42"

        return _PR()


def sample_reports(mini_repo: Path):
    suspect = make_suspect(mini_repo, "Fetching users", "get_user", ChangeType.SIGNATURE_CHANGE)
    verified = VerifiedSuspect(suspect=suspect, verdict=stale_verdict("include_posts=True"))
    ok_suspect = make_suspect(mini_repo, "CLI", "sync", ChangeType.BEHAVIOR_CHANGE)
    ok = VerifiedSuspect(
        suspect=ok_suspect,
        verdict=StalenessVerdict(is_stale=False, confidence=0.9, issues=[]),
    )
    check = CheckReport(
        base_ref="a", head_ref="b", changes=suspect.changes, verified=[verified, ok]
    )
    repair = RepairReport(
        repairs=[
            SectionRepair(
                verified=verified,
                mode=RepairMode.AUTO_FIX,
                correction=Correction(
                    corrected_markdown=suspect.section.content.replace(
                        "include_posts=True", "embed_posts=True"
                    ),
                    edits=[
                        DocEdit(
                            old_text="include_posts=True",
                            new_text="embed_posts=True",
                            reason="rename",
                        )
                    ],
                ),
                validation=ValidationResult(
                    accurate=True, style_consistent=True, score=0.95, preserved_ratio=0.95
                ),
            )
        ]
    )
    return check, repair


def test_summary_body_contents(mini_repo: Path) -> None:
    check, repair = sample_reports(mini_repo)
    body = build_summary_body(
        check, repair, "https://github.com/o/r", "abc123", "https://github.com/o/r/pull/9", None
    )
    assert SUMMARY_MARKER in body
    assert "1 section(s) verified accurate" in body
    assert "1 auto-fixed" in body
    assert "https://github.com/o/r/blob/abc123/docs/usage.md#L" in body


def test_summary_comment_is_idempotent(mini_repo: Path) -> None:
    check, repair = sample_reports(mini_repo)
    pr = FakePR()
    pr.create_issue_comment("unrelated human comment")
    body1 = build_summary_body(check, repair, "https://x", "s1", None, None)
    upsert_summary_comment(pr, body1)
    assert len(pr.comments) == 2
    body2 = build_summary_body(check, repair, "https://x", "s2", None, None)
    upsert_summary_comment(pr, body2)
    assert len(pr.comments) == 2, "second run must edit, not duplicate"
    assert pr.comments[1].body == body2
    assert pr.comments[0].body == "unrelated human comment"


def test_fix_pr_body_lists_edits(mini_repo: Path) -> None:
    _check, repair = sample_reports(mini_repo)
    body = build_fix_pr_body(repair, 7)
    assert "#7" in body
    assert "include_posts=True" in body and "embed_posts=True" in body
    assert "| Section | Change in code | Correction |" in body


def test_open_fix_pr_targets_head_branch(mini_repo: Path) -> None:
    _check, repair = sample_reports(mini_repo)
    gh_repo = FakeRepo()
    pr = open_fix_pr(gh_repo, "doc-sentinel/fix-7", "feature-branch", 7, repair)
    assert pr.html_url == "https://example.com/pull/42"
    assert gh_repo.pulls[0]["head"] == "doc-sentinel/fix-7"
    assert gh_repo.pulls[0]["base"] == "feature-branch"


def test_push_fix_branch_to_local_remote(mini_repo: Path, tmp_path: Path) -> None:
    from .test_detection import git_repo

    repo = git_repo(mini_repo)
    remote_path = tmp_path / "origin.git"
    Repo.init(remote_path, bare=True)
    repo.create_remote("origin", str(remote_path))

    push_fix_branch(
        mini_repo,
        "doc-sentinel/fix-1",
        {"docs/usage.md": "# Patched\n"},
        "docs: fix stale documentation for #1",
    )
    remote = Repo(remote_path)
    assert "doc-sentinel/fix-1" in [h.name for h in remote.heads]
    tree = remote.heads["doc-sentinel/fix-1"].commit.tree
    assert (tree / "docs/usage.md").data_stream.read().decode() == "# Patched\n"


def test_run_pipeline_offline_end_to_end(mini_repo: Path) -> None:
    """Full pipeline with llm=None: everything becomes flag-only, nothing patched."""
    from doc_sentinel.github.runner import run_pipeline

    from .test_detection import commit_all, git_repo

    repo = git_repo(mini_repo)
    api = mini_repo / "app" / "api.py"
    api.write_text(api.read_text().replace("include_posts: bool = False", "embed: bool = False"))
    commit_all(repo, "rename param")

    result = run_pipeline(
        mini_repo,
        "HEAD~1",
        "HEAD",
        llm=None,
        embeddings_provider="none",
        router_config=RouterConfig(),
        usage=UsageTracker(),
    )
    assert result.check.changes
    assert result.repair.repairs
    assert all(r.mode == RepairMode.FLAG_ONLY for r in result.repair.repairs)
    assert result.patched_files == {}
    outputs = result.outputs()
    assert outputs["flagged-count"] != "0"
    assert outputs["fix-pr-url"] == ""


def test_pipeline_with_scripted_llm_produces_patch(mini_repo: Path) -> None:
    """Full pipeline with a scripted LLM: verify -> generate -> validate -> patch."""
    from doc_sentinel.github.runner import run_pipeline

    from .test_detection import commit_all, git_repo
    from .test_repair import ScriptedLLM

    repo = git_repo(mini_repo)
    api = mini_repo / "app" / "api.py"
    api.write_text(
        api.read_text().replace("include_posts: bool = False", "embed_posts: bool = False")
    )
    commit_all(repo, "rename param")

    # Suspects: "Fetching users" (get_user). ScriptedLLM answers in call order:
    # one verify per suspect, then generate+validate for the stale one.
    from doc_sentinel.indexing.doc_parser import parse_docs

    sections, _ = parse_docs(mini_repo, ["docs"], [])
    fetching = next(s for s in sections if s.heading_path[-1] == "Fetching users")
    corrected = fetching.content.replace("include_posts=True", "embed_posts=True")
    llm = ScriptedLLM(
        [
            {
                "is_stale": True,
                "confidence": 0.95,
                "issues": [
                    {
                        "quote_from_docs": "include_posts=True",
                        "what_is_wrong": "renamed",
                        "what_code_says_now": "embed_posts",
                    }
                ],
            },
            {
                "corrected_markdown": corrected,
                "edits": [
                    {
                        "old_text": "include_posts=True",
                        "new_text": "embed_posts=True",
                        "reason": "renamed parameter",
                    }
                ],
            },
            {
                "accurate": True,
                "style_consistent": True,
                "score": 0.95,
                "reasons": ["minimal"],
            },
        ]
    )
    result = run_pipeline(
        mini_repo,
        "HEAD~1",
        "HEAD",
        llm=llm,
        embeddings_provider="none",
        router_config=RouterConfig(),
        usage=UsageTracker(),
    )
    assert result.outputs()["stale-count"] == "1"
    assert "docs/usage.md" in result.patched_files
    assert "embed_posts=True" in result.patched_files["docs/usage.md"]
