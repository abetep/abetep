"""Orchestrate the full pipeline inside a GitHub Actions run."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from doc_sentinel.detection.cli_ext import run_check
from doc_sentinel.detection.models import CheckReport
from doc_sentinel.github.workflows import (
    FIX_BRANCH_PREFIX,
    build_summary_body,
    open_fix_pr,
    push_fix_branch,
    upsert_summary_comment,
)
from doc_sentinel.indexing.indexer import build_index
from doc_sentinel.indexing.store import save_index
from doc_sentinel.llm.base import LLMClient, UsageTracker
from doc_sentinel.llm.providers import get_embedder, get_llm
from doc_sentinel.models import IndexConfig
from doc_sentinel.repair.engine import repair_sections
from doc_sentinel.repair.models import RepairMode, RepairReport
from doc_sentinel.repair.patcher import apply_repairs
from doc_sentinel.repair.router import RouterConfig


@dataclass
class ActionContext:
    repo_path: Path
    repo_full_name: str
    repo_html_url: str
    pr_number: int
    base_sha: str
    head_sha: str
    head_branch: str

    @classmethod
    def from_env(cls) -> ActionContext:
        event_path = os.environ.get("GITHUB_EVENT_PATH", "")
        if not event_path or not Path(event_path).exists():
            raise RuntimeError(
                "GITHUB_EVENT_PATH is not set; `doc-sentinel run` must run inside "
                "a GitHub Actions pull_request workflow."
            )
        event = json.loads(Path(event_path).read_text())
        pr = event.get("pull_request")
        if not pr:
            raise RuntimeError("The triggering event is not a pull_request event.")
        return cls(
            repo_path=Path(os.environ.get("GITHUB_WORKSPACE", ".")),
            repo_full_name=os.environ.get("GITHUB_REPOSITORY", ""),
            repo_html_url=event["repository"]["html_url"],
            pr_number=int(pr["number"]),
            base_sha=pr["base"]["sha"],
            head_sha=pr["head"]["sha"],
            head_branch=pr["head"]["ref"],
        )


@dataclass
class RunResult:
    check: CheckReport
    repair: RepairReport
    patched_files: dict[str, str] = field(default_factory=dict)
    fix_pr_url: str | None = None

    def outputs(self) -> dict[str, str]:
        return {
            "stale-count": str(len(self.check.stale)),
            "fixed-count": str(
                len(self.repair.by_mode(RepairMode.AUTO_FIX))
                + len(self.repair.by_mode(RepairMode.DRAFT_WITH_TODOS))
            ),
            "flagged-count": str(len(self.repair.by_mode(RepairMode.FLAG_ONLY))),
            "fix-pr-url": self.fix_pr_url or "",
        }


def run_pipeline(
    repo_path: Path,
    base_ref: str,
    head_ref: str,
    llm: LLMClient | None,
    embeddings_provider: str,
    router_config: RouterConfig,
    usage: UsageTracker,
) -> RunResult:
    """index -> check -> repair, with no GitHub side effects (unit-testable)."""
    cache_path = repo_path / ".doc-sentinel" / "chroma" if embeddings_provider != "none" else None
    embedder = get_embedder(embeddings_provider, cache_path, usage)
    config = IndexConfig(similarity_threshold=0.75, embedding_provider=embeddings_provider)
    index = build_index(repo_path, config, embedder)
    save_index(index, repo_path)
    check = run_check(repo_path, base_ref, head_ref, llm)
    if llm is not None:
        repair = repair_sections(llm, check, router_config)
    else:
        from doc_sentinel.repair.models import SectionRepair

        repair = RepairReport(
            repairs=[SectionRepair(verified=v, mode=RepairMode.FLAG_ONLY) for v in check.verified]
        )
    patched = apply_repairs(repo_path, repair.repairs)
    return RunResult(check=check, repair=repair, patched_files=patched)


def publish_results(
    result: RunResult,
    context: ActionContext,
    gh_repo: Any,
    pr: Any,
    mode: str,
    usage: UsageTracker,
) -> None:
    """Push the fix branch / open the PR / upsert the summary comment."""
    if mode == "fix" and result.patched_files:
        branch = f"{FIX_BRANCH_PREFIX}{context.pr_number}"
        push_fix_branch(
            context.repo_path,
            branch,
            result.patched_files,
            f"docs: fix stale documentation for #{context.pr_number}",
        )
        fix_pr = open_fix_pr(gh_repo, branch, context.head_branch, context.pr_number, result.repair)
        result.fix_pr_url = getattr(fix_pr, "html_url", None)
    body = build_summary_body(
        result.check,
        result.repair,
        context.repo_html_url,
        context.head_sha,
        result.fix_pr_url,
        usage.summary() if usage.calls else None,
    )
    upsert_summary_comment(pr, body)


def write_outputs(outputs: dict[str, str]) -> None:
    out_path = os.environ.get("GITHUB_OUTPUT")
    if not out_path:
        return
    with open(out_path, "a", encoding="utf-8") as fh:
        for key, value in outputs.items():
            fh.write(f"{key}={value}\n")


def run_action(
    llm_provider: str,
    embeddings_provider: str,
    confidence_threshold: float,
    mode: str,
) -> dict[str, str]:
    context = ActionContext.from_env()
    usage = UsageTracker()
    llm = None if llm_provider == "none" else get_llm(llm_provider, usage)
    router_config = RouterConfig(
        auto_fix_confidence=confidence_threshold,
        auto_fix_validation_score=confidence_threshold,
    )
    result = run_pipeline(
        context.repo_path,
        context.base_sha,
        context.head_sha,
        llm,
        embeddings_provider,
        router_config,
        usage,
    )
    from github import Github

    from doc_sentinel.llm.base import require_env

    gh = Github(require_env("GITHUB_TOKEN"))
    gh_repo = gh.get_repo(context.repo_full_name)
    pr = gh_repo.get_pull(context.pr_number)
    publish_results(result, context, gh_repo, pr, mode, usage)
    outputs = result.outputs()
    write_outputs(outputs)
    print(f"doc-sentinel: {outputs}")
    if usage.calls:
        print(f"Usage: {usage.summary()}")
    return outputs
