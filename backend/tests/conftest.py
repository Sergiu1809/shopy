"""Shared database fixtures: one real Postgres + pgvector container per session (Q11).

There is no skip anywhere: without Docker the DB fixtures error loudly.

App, SQLAlchemy and Alembic imports stay inside the fixtures, so tests that need no
database (test_health, the unit tests in test_db_config) still run on their own.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from testcontainers.community.postgres import PostgresContainer

if TYPE_CHECKING:
    from alembic.config import Config
    from sqlalchemy.ext.asyncio import AsyncSession

# Same image as the `db` service in docker-compose.yml (checked by test_db_config).
PG_IMAGE = "pgvector/pgvector:0.8.7-pg16"

BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


def alembic_config() -> Config:
    """The project's Alembic config; the URL comes from DATABASE_URL via env.py."""
    from alembic.config import Config

    assert ALEMBIC_INI.is_file(), f"{ALEMBIC_INI} is missing"
    return Config(str(ALEMBIC_INI))


def with_database(url: str, name: str) -> str:
    """The same server URL, pointing at another database."""
    from sqlalchemy.engine import make_url

    return make_url(url).set(database=name).render_as_string(hide_password=False)


async def _fetch(url: str, sql: str, autocommit: bool = False) -> list[Any]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    options: dict[str, Any] = {"isolation_level": "AUTOCOMMIT"} if autocommit else {}
    engine = create_async_engine(url, **options)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(sql))
            return list(result.all()) if result.returns_rows else []
    finally:
        await engine.dispose()


def fetch(url: str, sql: str, autocommit: bool = False) -> list[Any]:
    """Run one SQL statement from a sync test or fixture and return its rows."""
    return asyncio.run(_fetch(url, sql, autocommit))


@pytest.fixture(scope="session")
def pg() -> Iterator[PostgresContainer]:
    # No init script is mounted: the migration alone must create the extensions.
    with PostgresContainer(PG_IMAGE, driver="asyncpg") as container:
        yield container


@pytest.fixture(scope="session")
def migrated_url(pg: PostgresContainer) -> Iterator[str]:
    """The container's database, migrated to head through the real Alembic path."""
    from alembic import command

    url = pg.get_connection_url()
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(alembic_config(), "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.fixture
async def session(migrated_url: str) -> AsyncIterator[AsyncSession]:
    """An AsyncSession inside one transaction that is rolled back after the test."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db import create_engine

    engine = create_engine(migrated_url)
    try:
        async with engine.connect() as conn:
            transaction = await conn.begin()
            db = AsyncSession(
                bind=conn,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            try:
                yield db
            finally:
                await db.close()
                if transaction.is_active:
                    await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
def fresh_db_url(pg: PostgresContainer) -> Iterator[str]:
    """A new, empty database in the session container (no extensions, no tables)."""
    admin_url = pg.get_connection_url()
    name = f"fresh_{uuid.uuid4().hex[:12]}"
    fetch(admin_url, f'CREATE DATABASE "{name}"', autocommit=True)
    try:
        yield with_database(admin_url, name)
    finally:
        fetch(admin_url, f'DROP DATABASE "{name}" WITH (FORCE)', autocommit=True)
