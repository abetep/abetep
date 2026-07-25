"""`doc-sentinel run` subcommand: the GitHub Action entrypoint."""

from __future__ import annotations

import argparse

from doc_sentinel.github.runner import run_action


def add_run_parser(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser("run", help="Run the full pipeline inside GitHub Actions")
    p.add_argument("--llm", choices=["openai", "none"], default="openai")
    p.add_argument("--embeddings", choices=["openai", "none"], default="openai")
    p.add_argument("--confidence-threshold", type=float, default=0.8)
    p.add_argument("--mode", choices=["fix", "flag-only"], default="fix")
    p.set_defaults(handler=cmd_run)


def cmd_run(args: argparse.Namespace) -> int:
    run_action(
        llm_provider=args.llm,
        embeddings_provider=args.embeddings,
        confidence_threshold=args.confidence_threshold,
        mode=args.mode,
    )
    return 0
