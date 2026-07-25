"""Parse markdown documentation into heading-delimited sections."""

from __future__ import annotations

import re
from pathlib import Path

from markdown_it import MarkdownIt

from doc_sentinel.models import DocSection, content_hash

_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_FENCE_RE = re.compile(r"^```.*?$(.*?)^```\s*$", re.MULTILINE | re.DOTALL)


def _extract_code_refs(content: str) -> list[str]:
    """Candidate code identifiers mentioned in a section.

    Pulls identifiers out of fenced code blocks and inline code spans. The
    link graph later filters these against the actual chunk inventory.
    """
    refs: set[str] = set()
    fenced = "\n".join(m.group(1) for m in _FENCE_RE.finditer(content))
    without_fences = _FENCE_RE.sub("", content)
    inline = "\n".join(m.group(1) for m in _INLINE_CODE_RE.finditer(without_fences))
    for blob in (fenced, inline):
        for match in _IDENTIFIER_RE.finditer(blob):
            token = match.group(0)
            if len(token) >= 2:
                refs.add(token)
    return sorted(refs)


def parse_markdown(text: str, rel_path: str) -> list[DocSection]:
    """Split a markdown document into sections by heading.

    Each section spans from its heading line to the line before the next
    heading (any level). Heading paths carry the ancestor chain, e.g.
    ["Configuration", "Environment Variables"].
    """
    md = MarkdownIt()
    tokens = md.parse(text)
    lines = text.splitlines()
    headings: list[tuple[int, int, str]] = []  # (level, start_line_0based, text)
    for i, tok in enumerate(tokens):
        if tok.type == "heading_open" and tok.map:
            level = int(tok.tag[1])
            title = tokens[i + 1].content if i + 1 < len(tokens) else ""
            headings.append((level, tok.map[0], title))

    sections: list[DocSection] = []
    if not headings:
        if text.strip():
            sections.append(
                DocSection(
                    id=f"{rel_path}::{rel_path}",
                    file=rel_path,
                    heading_path=[rel_path],
                    start_line=1,
                    end_line=len(lines),
                    content=text,
                    content_hash=content_hash(text),
                    code_refs=_extract_code_refs(text),
                )
            )
        return sections

    stack: list[tuple[int, str]] = []
    for idx, (level, start0, title) in enumerate(headings):
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        end0 = headings[idx + 1][1] if idx + 1 < len(headings) else len(lines)
        content = "\n".join(lines[start0:end0])
        heading_path = [t for _, t in stack]
        sections.append(
            DocSection(
                id=f"{rel_path}::{' > '.join(heading_path)}",
                file=rel_path,
                heading_path=heading_path,
                start_line=start0 + 1,
                end_line=end0,
                content=content,
                content_hash=content_hash(content),
                code_refs=_extract_code_refs(content),
            )
        )
    return sections


def parse_docs(
    repo_path: Path, doc_roots: list[str], exclude_dirs: list[str]
) -> tuple[list[DocSection], dict[str, str]]:
    """Parse all markdown files under the given roots."""
    sections: list[DocSection] = []
    file_hashes: dict[str, str] = {}
    excluded = set(exclude_dirs)
    seen: set[str] = set()
    for root in doc_roots:
        base = (repo_path / root).resolve()
        if not base.exists():
            continue
        for pattern in ("*.md", "*.mdx"):
            for path in sorted(base.rglob(pattern)):
                rel = path.relative_to(repo_path).as_posix()
                if rel in seen or set(rel.split("/")[:-1]) & excluded:
                    continue
                seen.add(rel)
                text = path.read_text(encoding="utf-8", errors="replace")
                file_hashes[rel] = content_hash(text)
                sections.extend(parse_markdown(text, rel))
    return sections, file_hashes
