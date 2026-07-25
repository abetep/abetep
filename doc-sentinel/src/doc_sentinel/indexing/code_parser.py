"""Parse Python source files into semantic code chunks using the ast module."""

from __future__ import annotations

import ast
from pathlib import Path

from doc_sentinel.models import ChunkKind, CodeChunk, content_hash

ROUTE_DECORATOR_ATTRS = {
    "get",
    "post",
    "put",
    "delete",
    "patch",
    "head",
    "options",
    "route",
    "websocket",
}
CLI_DECORATOR_NAMES = {"command", "group", "argument", "option"}
CONFIG_BASE_HINTS = {"BaseSettings", "Settings"}


def _decorator_root_and_attr(dec: ast.expr) -> tuple[str | None, str | None]:
    """Return (attribute_name, root_name) for decorators like @app.get(...) or @click.command()."""
    node = dec
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        attr = node.attr
        root = node.value
        while isinstance(root, ast.Attribute):
            root = root.value
        root_name = root.id if isinstance(root, ast.Name) else None
        return attr, root_name
    if isinstance(node, ast.Name):
        return node.id, None
    return None, None


def _classify_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> ChunkKind:
    for dec in node.decorator_list:
        attr, _root = _decorator_root_and_attr(dec)
        if attr in ROUTE_DECORATOR_ATTRS:
            return ChunkKind.ROUTE
        if attr in CLI_DECORATOR_NAMES:
            return ChunkKind.CLI
    return ChunkKind.FUNCTION


def _classify_class(node: ast.ClassDef) -> ChunkKind:
    for base in node.bases:
        base_name = base.attr if isinstance(base, ast.Attribute) else None
        if isinstance(base, ast.Name):
            base_name = base.id
        if base_name and any(hint in base_name for hint in CONFIG_BASE_HINTS):
            return ChunkKind.CONFIG
    if node.name.endswith(("Settings", "Config")):
        return ChunkKind.CONFIG
    return ChunkKind.CLASS


def _function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = ast.unparse(node.args)
    ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({args}){ret}"


def _class_signature(node: ast.ClassDef) -> str:
    bases = ", ".join(ast.unparse(b) for b in node.bases)
    return f"class {node.name}({bases})" if bases else f"class {node.name}"


def _signature_fp(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> str:
    if isinstance(node, ast.ClassDef):
        return content_hash(_class_signature(node))
    return content_hash(
        ast.dump(node.args, include_attributes=False)
        + (ast.dump(node.returns, include_attributes=False) if node.returns else "")
    )


def _body_fp(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> str:
    """Fingerprint of the body AST (plus decorators) with the docstring stripped.

    Comments and whitespace never reach the AST, so two bodies that differ only
    cosmetically produce the same fingerprint. Decorators are included so a
    changed route path or CLI option counts as a behavior change.
    """
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    dumped = "\n".join(
        [ast.dump(dec, include_attributes=False) for dec in node.decorator_list]
        + [ast.dump(stmt, include_attributes=False) for stmt in body]
    )
    return content_hash(dumped)


def _config_field_names(node: ast.ClassDef) -> list[str]:
    """Field names declared on a settings/config class body."""
    names: list[str] = []
    for stmt in node.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            names.append(stmt.target.id)
        elif isinstance(stmt, ast.Assign):
            names.extend(t.id for t in stmt.targets if isinstance(t, ast.Name))
    return names


def _node_source(node: ast.stmt, lines: list[str]) -> tuple[str, int, int]:
    """Source text and 1-based inclusive line span, including decorators."""
    start = node.lineno
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        for dec in node.decorator_list:
            start = min(start, dec.lineno)
    end = node.end_lineno or node.lineno
    return "\n".join(lines[start - 1 : end]), start, end


def _make_chunk(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    rel_path: str,
    lines: list[str],
    qualified_name: str,
    kind: ChunkKind,
    signature: str,
) -> CodeChunk:
    source, start, end = _node_source(node, lines)
    aliases: list[str] = []
    if kind == ChunkKind.CONFIG and isinstance(node, ast.ClassDef):
        aliases = _config_field_names(node)
    return CodeChunk(
        aliases=aliases,
        id=f"{rel_path}::{qualified_name}",
        kind=kind,
        file=rel_path,
        start_line=start,
        end_line=end,
        name=node.name,
        qualified_name=qualified_name,
        signature=signature,
        docstring=ast.get_docstring(node) or "",
        source=source,
        source_hash=content_hash(source),
        signature_fp=_signature_fp(node),
        body_fp=_body_fp(node),
    )


def parse_source(source: str, rel_path: str) -> list[CodeChunk]:
    """Extract chunks from a single Python source string."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    lines = source.splitlines()
    chunks: list[CodeChunk] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            kind = _classify_function(node)
            chunks.append(
                _make_chunk(node, rel_path, lines, node.name, kind, _function_signature(node))
            )
        elif isinstance(node, ast.ClassDef):
            kind = _classify_class(node)
            chunks.append(
                _make_chunk(node, rel_path, lines, node.name, kind, _class_signature(node))
            )
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and not (
                    item.name.startswith("_")
                ):
                    qname = f"{node.name}.{item.name}"
                    chunks.append(
                        _make_chunk(
                            item,
                            rel_path,
                            lines,
                            qname,
                            _classify_function(item),
                            _function_signature(item),
                        )
                    )
    return chunks


def parse_repo(
    repo_path: Path, code_roots: list[str], exclude_dirs: list[str]
) -> tuple[list[CodeChunk], dict[str, str]]:
    """Parse all Python files under the given roots.

    Returns the chunks and a map of relative path -> file content hash.
    """
    chunks: list[CodeChunk] = []
    file_hashes: dict[str, str] = {}
    excluded = set(exclude_dirs)
    for root in code_roots:
        base = (repo_path / root).resolve()
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(repo_path).as_posix()
            parts = set(rel.split("/")[:-1])
            if parts & excluded or path.name.startswith("test_"):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            file_hashes[rel] = content_hash(text)
            chunks.extend(parse_source(text, rel))
    return chunks, file_hashes
