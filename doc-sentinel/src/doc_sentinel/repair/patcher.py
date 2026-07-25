"""Apply section corrections to markdown files on disk."""

from __future__ import annotations

from pathlib import Path

from doc_sentinel.repair.models import TODO_MARKER, RepairMode, SectionRepair


def apply_repairs(repo_path: Path, repairs: list[SectionRepair]) -> dict[str, str]:
    """Apply auto-fix and draft repairs, returning {relative_path: new_content}.

    Corrections replace exactly the section's line span, so every other
    section in the file stays byte-identical. Multiple sections in one file
    are applied bottom-up so earlier spans stay valid.
    """
    applicable = [
        r
        for r in repairs
        if r.mode in (RepairMode.AUTO_FIX, RepairMode.DRAFT_WITH_TODOS) and r.correction
    ]
    by_file: dict[str, list[SectionRepair]] = {}
    for repair in applicable:
        by_file.setdefault(repair.verified.suspect.section.file, []).append(repair)

    results: dict[str, str] = {}
    for rel_path, file_repairs in sorted(by_file.items()):
        path = repo_path / rel_path
        lines = path.read_text(encoding="utf-8").splitlines()
        for repair in sorted(
            file_repairs, key=lambda r: r.verified.suspect.section.start_line, reverse=True
        ):
            section = repair.verified.suspect.section
            assert repair.correction is not None
            new_content = repair.correction.corrected_markdown.rstrip("\n")
            if repair.mode == RepairMode.DRAFT_WITH_TODOS:
                new_content = _inject_todo(new_content)
            lines[section.start_line - 1 : section.end_line] = new_content.splitlines()
        results[rel_path] = "\n".join(lines) + "\n"
    return results


def write_repairs(repo_path: Path, results: dict[str, str]) -> None:
    for rel_path, content in results.items():
        (repo_path / rel_path).write_text(content, encoding="utf-8")


def _inject_todo(content: str) -> str:
    lines = content.splitlines()
    if lines and lines[0].lstrip().startswith("#"):
        return "\n".join([lines[0], "", TODO_MARKER, *lines[1:]])
    return TODO_MARKER + "\n" + content
