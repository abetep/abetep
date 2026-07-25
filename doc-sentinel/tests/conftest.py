"""Shared fixtures: a mini fixture repo exercising every chunk kind."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

API_PY = '''\
from fastapi import FastAPI

app = FastAPI()


@app.get("/users/{user_id}")
def get_user(user_id: int, include_posts: bool = False) -> dict:
    """Fetch a user by id.

    When include_posts is true, the response embeds the user's posts.
    """
    return _load(user_id, include_posts)


def _load(user_id: int, include_posts: bool) -> dict:
    return {"id": user_id, "posts": [] if include_posts else None}


def format_username(name: str, upper: bool = False) -> str:
    """Normalize a username for display."""
    result = name.strip()
    return result.upper() if upper else result
'''

CONFIG_PY = '''\
from pydantic_settings import BaseSettings


class AppSettings(BaseSettings):
    """Application configuration loaded from environment variables."""

    database_url: str = "sqlite:///app.db"
    timeout_seconds: int = 30
    debug: bool = False
'''

CLI_PY = '''\
import click


@click.command()
@click.option("--verbose", is_flag=True)
def sync(verbose: bool) -> None:
    """Synchronize local state with the server."""
    click.echo("syncing")
'''

USAGE_MD = """\
# User Guide

Welcome to the demo app.

## API

### Fetching users

Call `get_user(user_id)` to fetch a user. Pass `include_posts=True`
to embed the user's posts in the response.

### Formatting

Use `format_username` to normalize names; by default it only strips
whitespace and does not change case.

## Configuration

### Environment Variables

`AppSettings` reads config from the environment. The default
`timeout_seconds` is 30 and `database_url` points to a local SQLite file.

## CLI

Run the `sync` command to synchronize local state.
"""


def write_fixture_repo(root: Path) -> Path:
    (root / "app").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "tests").mkdir()
    (root / "app" / "api.py").write_text(API_PY)
    (root / "app" / "config.py").write_text(CONFIG_PY)
    (root / "app" / "cli.py").write_text(CLI_PY)
    (root / "docs" / "usage.md").write_text(USAGE_MD)
    (root / "tests" / "test_api.py").write_text(
        textwrap.dedent(
            """\
            def test_get_user():
                assert True
            """
        )
    )
    return root


@pytest.fixture
def mini_repo(tmp_path: Path) -> Path:
    return write_fixture_repo(tmp_path / "mini")
