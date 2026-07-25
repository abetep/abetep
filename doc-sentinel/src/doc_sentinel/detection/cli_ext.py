"""`doc-sentinel check` subcommand."""

from __future__ import annotations

import argparse
from pathlib import Path

from doc_sentinel.detection.diff_parser import diff_chunks
from doc_sentinel.detection.models import CheckReport, VerifiedSuspect
from doc_sentinel.detection.suspects import find_suspects, meaningful_changes
from doc_sentinel.detection.verifier import verify_all
from doc_sentinel.indexing.store import load_index
from doc_sentinel.llm.base import LLMClient, UsageTracker
from doc_sentinel.llm.providers import get_llm


def run_check(
    repo: Path,
    base_ref: str,
    head_ref: str,
    llm: LLMClient | None,
) -> CheckReport:
    index = load_index(repo)
    changes = diff_chunks(repo, base_ref, head_ref)
    suspects = find_suspects(index, changes)
    if llm is None:
        verified = [VerifiedSuspect(suspect=s, verdict=None) for s in suspects]
    else:
        verified = verify_all(llm, suspects)
    return CheckReport(
        base_ref=base_ref,
        head_ref=head_ref,
        changes=meaningful_changes(changes),
        verified=verified,
    )


def add_check_parser(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser("check", help="Detect doc sections made stale by a code change")
    p.add_argument("--repo", type=Path, default=Path("."))
    p.add_argument("--base-ref", required=True)
    p.add_argument("--head-ref", default="HEAD")
    p.add_argument("--llm", choices=["anthropic", "openai", "none"], default="anthropic")
    p.add_argument("--output", type=Path, default=None, help="Write the JSON report here")
    p.set_defaults(handler=cmd_check)


def cmd_check(args: argparse.Namespace) -> int:
    usage = UsageTracker()
    llm = None if args.llm == "none" else get_llm(args.llm, usage)
    report = run_check(args.repo.resolve(), args.base_ref, args.head_ref, llm)
    payload = report.model_dump_json(indent=2)
    if args.output:
        args.output.write_text(payload + "\n")
    else:
        print(payload)
    print(
        f"\n{len(report.changes)} meaningful changes, {len(report.verified)} suspects: "
        f"{len(report.stale)} stale, {len(report.accurate)} accurate, "
        f"{len(report.unverified)} unverified"
    )
    if usage.calls:
        print(f"Usage: {usage.summary()}")
    return 0
