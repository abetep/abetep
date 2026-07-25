"""`doc-sentinel repair` subcommand."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from doc_sentinel.detection.models import CheckReport
from doc_sentinel.llm.base import UsageTracker
from doc_sentinel.llm.providers import get_llm
from doc_sentinel.repair.engine import repair_sections
from doc_sentinel.repair.models import RepairMode
from doc_sentinel.repair.patcher import apply_repairs, write_repairs
from doc_sentinel.repair.router import RouterConfig


def add_repair_parser(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser("repair", help="Generate and apply doc corrections from a check report")
    p.add_argument("--repo", type=Path, default=Path("."))
    p.add_argument("--report", type=Path, required=True, help="JSON report from `check`")
    p.add_argument("--llm", choices=["anthropic", "openai"], default="anthropic")
    p.add_argument("--confidence-threshold", type=float, default=0.8)
    p.add_argument("--apply", action="store_true", help="Write corrections to disk")
    p.add_argument("--output", type=Path, default=None, help="Write the repair report here")
    p.set_defaults(handler=cmd_repair)


def cmd_repair(args: argparse.Namespace) -> int:
    usage = UsageTracker()
    check = CheckReport.model_validate(json.loads(args.report.read_text()))
    llm = get_llm(args.llm, usage)
    config = RouterConfig(
        auto_fix_confidence=args.confidence_threshold,
        auto_fix_validation_score=args.confidence_threshold,
    )
    report = repair_sections(llm, check, config)
    if args.apply:
        results = apply_repairs(args.repo.resolve(), report.repairs)
        write_repairs(args.repo.resolve(), results)
        print(f"Patched {len(results)} file(s): {', '.join(sorted(results))}")
    payload = report.model_dump_json(indent=2)
    if args.output:
        args.output.write_text(payload + "\n")
    else:
        print(payload)
    print(
        f"\n{len(report.by_mode(RepairMode.AUTO_FIX))} auto-fixed, "
        f"{len(report.by_mode(RepairMode.DRAFT_WITH_TODOS))} drafted with TODOs, "
        f"{len(report.by_mode(RepairMode.FLAG_ONLY))} flagged for review"
    )
    if usage.calls:
        print(f"Usage: {usage.summary()}")
    return 0
