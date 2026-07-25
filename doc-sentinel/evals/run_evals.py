#!/usr/bin/env python3
"""Run the labeled eval cases and report precision/recall/F1.

Offline (default): measures the retrieval stage — which doc sections the
link graph + change filter implicate as suspects. No API keys needed.

Live (--live): additionally runs LLM staleness verification, so predicted
stale sections are the verifier's output, and grades generated corrections
against evals/RUBRIC.md with a second LLM pass.

Usage:
    python evals/run_evals.py [--live] [--write-results]
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from git import Repo

from doc_sentinel.detection.diff_parser import diff_chunks
from doc_sentinel.detection.suspects import find_suspects
from doc_sentinel.detection.verifier import verify_all
from doc_sentinel.indexing.indexer import build_index
from doc_sentinel.indexing.store import save_index
from doc_sentinel.llm.base import LLMClient, UsageTracker
from doc_sentinel.models import IndexConfig
from evals.cases import CASES, EvalCase

FIXTURE = Path(__file__).parent / "fixture_project"
RESULTS_PATH = Path(__file__).parent / "RESULTS.md"
RUBRIC_PATH = Path(__file__).parent / "RUBRIC.md"


@dataclass
class CaseResult:
    case: EvalCase
    predicted: set[str]

    @property
    def tp(self) -> set[str]:
        return self.predicted & self.case.expected_stale

    @property
    def fp(self) -> set[str]:
        return self.predicted - self.case.expected_stale

    @property
    def fn(self) -> set[str]:
        return self.case.expected_stale - self.predicted


def run_case(case: EvalCase, llm: LLMClient | None) -> CaseResult:
    workdir = Path(tempfile.mkdtemp(prefix=f"eval-{case.name}-"))
    try:
        target = workdir / "repo"
        shutil.copytree(FIXTURE, target)
        repo = Repo.init(target)
        with repo.config_writer() as cw:
            cw.set_value("user", "name", "eval")
            cw.set_value("user", "email", "eval@example.com")
        repo.git.add(A=True)
        repo.index.commit("base")
        for mutation in case.mutations:
            mutation.apply(target)
        repo.git.add(A=True)
        repo.index.commit(case.name)

        index = build_index(target, IndexConfig(embedding_provider="none"), embedder=None)
        save_index(index, target)
        changes = diff_chunks(target, "HEAD~1", "HEAD")
        suspects = find_suspects(index, changes)
        if llm is None:
            predicted = {s.section.heading_display for s in suspects}
        else:
            verified = verify_all(llm, suspects)
            predicted = {
                v.suspect.section.heading_display
                for v in verified
                if v.verdict is None or v.verdict.is_stale
            }
        return CaseResult(case=case, predicted=predicted)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def micro_metrics(results: list[CaseResult]) -> tuple[float, float, float, int, int, int]:
    tp = sum(len(r.tp) for r in results)
    fp = sum(len(r.fp) for r in results)
    fn = sum(len(r.fn) for r in results)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1, tp, fp, fn


def render_report(results: list[CaseResult], stage: str) -> str:
    precision, recall, f1, tp, fp, fn = micro_metrics(results)
    lines = [
        f"### {stage}",
        "",
        "| Case | Expected stale | Predicted | TP | FP | FN |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        expected = ", ".join(sorted(r.case.expected_stale)) or "—"
        predicted = ", ".join(sorted(r.predicted)) or "—"
        lines.append(
            f"| {r.case.name} | {expected} | {predicted} | "
            f"{len(r.tp)} | {len(r.fp)} | {len(r.fn)} |"
        )
    lines += [
        "",
        f"**Micro-averaged over {len(results)} cases:** "
        f"precision **{precision:.2f}**, recall **{recall:.2f}**, F1 **{f1:.2f}** "
        f"(TP={tp}, FP={fp}, FN={fn})",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Use a real LLM for verification")
    parser.add_argument("--llm", choices=["anthropic", "openai"], default="anthropic")
    parser.add_argument("--write-results", action="store_true")
    args = parser.parse_args()

    llm: LLMClient | None = None
    usage = UsageTracker()
    if args.live:
        from doc_sentinel.llm.providers import get_llm

        llm = get_llm(args.llm, usage)

    results = [run_case(case, llm) for case in CASES]
    stage = (
        "Detection after LLM verification (live)"
        if args.live
        else "Retrieval stage (offline, no LLM verification)"
    )
    report = render_report(results, stage)
    print(report)
    if usage.calls:
        print(f"\nUsage: {usage.summary()}")
    if args.write_results:
        RESULTS_PATH.write_text(
            "# Evaluation Results\n\n"
            "Generated by `python evals/run_evals.py`. See `evals/cases.py` for the\n"
            "labeled test cases and `evals/RUBRIC.md` for the correction rubric.\n\n"
            + report
            + "\n"
        )
        print(f"\nWrote {RESULTS_PATH}")
    failed = sum(1 for r in results if r.fn)
    return 1 if failed and args.live else 0


if __name__ == "__main__":
    raise SystemExit(main())
