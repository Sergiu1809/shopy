"""DATABASE_URL comes from the environment only (PATTERN-013); no Docker needed."""

import re

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db import create_engine, create_sessionmaker, database_url
from tests.conftest import BACKEND_DIR, PG_IMAGE

ENV_URL = "postgresql+asyncpg://shopy:secret@db.invalid:5432/shopy"


def test_database_url_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", ENV_URL)

    assert database_url() == ENV_URL


def test_database_url_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        database_url()


def test_create_engine_defaults_to_env_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # db.invalid never resolves: building the engine must not connect.
    monkeypatch.setenv("DATABASE_URL", ENV_URL)

    engine = create_engine()

    assert isinstance(engine, AsyncEngine)
    assert engine.url.render_as_string(hide_password=False) == ENV_URL


def test_create_engine_uses_given_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    other = "postgresql+asyncpg://other:pw@elsewhere.invalid:5432/other"

    engine = create_engine(other)

    assert engine.url.render_as_string(hide_password=False) == other


def test_sessionmaker_does_not_expire_on_commit() -> None:
    engine = create_engine(ENV_URL)

    maker = create_sessionmaker(engine)

    assert maker.kw["bind"] is engine
    assert maker.kw["expire_on_commit"] is False


def test_test_image_matches_compose() -> None:
    compose = (BACKEND_DIR.parent / "docker-compose.yml").read_text()

    match = re.search(r"^  db:\n(?:    .*\n)*?    image:\s*(\S+)", compose, re.M)

    assert match is not None, "no image line under the db service"
    assert match.group(1) == PG_IMAGE
