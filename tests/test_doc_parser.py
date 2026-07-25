from pathlib import Path

from doc_sentinel.indexing.doc_parser import parse_docs, parse_markdown


def test_sections_split_by_heading_with_paths(mini_repo: Path) -> None:
    sections, hashes = parse_docs(mini_repo, ["docs"], [])
    paths = [s.heading_path for s in sections]
    assert ["User Guide"] in paths
    assert ["User Guide", "API", "Fetching users"] in paths
    assert ["User Guide", "Configuration", "Environment Variables"] in paths
    assert "docs/usage.md" in hashes


def test_section_line_spans_cover_content(mini_repo: Path) -> None:
    text = (mini_repo / "docs" / "usage.md").read_text()
    sections = parse_markdown(text, "docs/usage.md")
    lines = text.splitlines()
    fetching = next(s for s in sections if s.heading_path[-1] == "Fetching users")
    assert lines[fetching.start_line - 1].startswith("### Fetching users")
    assert "include_posts=True" in fetching.content


def test_code_refs_extracted_from_inline_code(mini_repo: Path) -> None:
    text = (mini_repo / "docs" / "usage.md").read_text()
    sections = parse_markdown(text, "docs/usage.md")
    fetching = next(s for s in sections if s.heading_path[-1] == "Fetching users")
    assert "get_user" in fetching.code_refs
    assert "include_posts" in fetching.code_refs
    env = next(s for s in sections if s.heading_path[-1] == "Environment Variables")
    assert "AppSettings" in env.code_refs
    assert "timeout_seconds" in env.code_refs


def test_code_refs_from_fenced_blocks() -> None:
    md = "# Setup\n\n```python\nfrom app import get_user\nget_user(1)\n```\n"
    (section,) = parse_markdown(md, "d.md")
    assert "get_user" in section.code_refs


def test_file_without_headings_is_one_section() -> None:
    sections = parse_markdown("just some prose\n", "notes.md")
    assert len(sections) == 1
    assert sections[0].heading_path == ["notes.md"]


def test_sibling_headings_do_not_nest() -> None:
    md = "# A\n\n## B\n\ntext\n\n## C\n\nmore\n"
    sections = parse_markdown(md, "d.md")
    paths = [s.heading_path for s in sections]
    assert ["A", "B"] in paths
    assert ["A", "C"] in paths
