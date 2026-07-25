"""doc-sentinel command line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from doc_sentinel.indexing.indexer import build_index
from doc_sentinel.indexing.store import IndexError_, load_index, save_index
from doc_sentinel.llm.base import UsageTracker
from doc_sentinel.llm.providers import get_embedder
from doc_sentinel.models import IndexConfig


def _add_index_parser(sub: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = sub.add_parser("index", help="Build or refresh the code-to-docs index")
    p.add_argument("--repo", type=Path, default=Path("."), help="Path to the target repository")
    p.add_argument("--code-root", action="append", dest="code_roots", default=None)
    p.add_argument("--doc-root", action="append", dest="doc_roots", default=None)
    p.add_argument("--similarity-threshold", type=float, default=0.75)
    p.add_argument(
        "--embeddings",
        choices=["openai", "none"],
        default="openai",
        help="'none' skips semantic linking (lexical links only)",
    )


def cmd_index(args: argparse.Namespace) -> int:
    repo: Path = args.repo.resolve()
    config = IndexConfig(
        code_roots=args.code_roots or ["."],
        doc_roots=args.doc_roots or ["."],
        similarity_threshold=args.similarity_threshold,
        embedding_provider=args.embeddings,
    )
    usage = UsageTracker()
    cache_path = repo / ".doc-sentinel" / "chroma" if args.embeddings != "none" else None
    embedder = get_embedder(args.embeddings, cache_path, usage)
    try:
        previous = load_index(repo)
    except IndexError_:
        previous = None
    index = build_index(repo, config, embedder, previous)
    path = save_index(index, repo)
    print(
        f"Indexed {len(index.chunks)} code chunks, {len(index.sections)} doc sections, "
        f"{len(index.edges)} links -> {path}"
    )
    if usage.calls:
        print(f"Usage: {usage.summary()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="doc-sentinel")
    sub = parser.add_subparsers(dest="command", required=True)
    _add_index_parser(sub)
    # Later-phase subcommands register themselves when their package exists.
    for module, register in [
        ("doc_sentinel.detection.cli_ext", "add_check_parser"),
        ("doc_sentinel.repair.cli_ext", "add_repair_parser"),
        ("doc_sentinel.github.cli_ext", "add_run_parser"),
    ]:
        try:
            mod = __import__(module, fromlist=[register])
        except ImportError:
            continue
        getattr(mod, register)(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = {
        "index": cmd_index,
    }.get(args.command)
    if handler is None:
        handler = getattr(args, "handler", None)
    if handler is None:
        parser.error(f"Unknown command {args.command}")
    try:
        return int(handler(args))
    except IndexError_ as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
