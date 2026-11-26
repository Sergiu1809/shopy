"""Alembic: revision 0001 on a fresh database, the round trip and the drift check.

Alembic's async env.py calls asyncio.run, so every Alembic command runs from a sync
test. Each test gets its own empty database (`fresh_db_url`), created in the session
container without any init script.
"""

from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.models import Base
from tests.conftest import alembic_config, fetch

TABLES = {
    "stores",
    "users",
    "refresh_tokens",
    "addresses",
    "user_preferences",
    "categories",
    "products",
    "product_variants",
    "product_images",
    "reviews",
    "store_policies",
    "kb_chunks",
    "reindex_outbox",
    "usage_ledger",
}
EXTENSIONS = {"vector", "unaccent"}


def public_tables(url: str) -> set[str]:
    rows = fetch(
        url,
        "SELECT table_name FROM information_schema.tables"
        " WHERE table_schema = 'public' AND table_type = 'BASE TABLE'",
    )
    return {row.table_name for row in rows}


def extensions(url: str) -> set[str]:
    return {row.extname for row in fetch(url, "SELECT extname FROM pg_extension")}


def upgrade(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(alembic_config(), "head")


def test_upgrade_head_creates_all_tables(
    fresh_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    upgrade(fresh_db_url, monkeypatch)

    assert public_tables(fresh_db_url) == TABLES | {"alembic_version"}
    versions = fetch(fresh_db_url, "SELECT version_num FROM alembic_version")
    assert [row.version_num for row in versions] == ["0002"]


def test_upgrade_creates_extensions(
    fresh_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No init script in the test container: the migration alone creates them.
    assert extensions(fresh_db_url).isdisjoint(EXTENSIONS)

    upgrade(fresh_db_url, monkeypatch)

    assert EXTENSIONS <= extensions(fresh_db_url)


def test_upgrade_is_safe_when_extensions_exist(
    fresh_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Like the Compose db, whose init script already created both.
    fetch(fresh_db_url, "CREATE EXTENSION vector", autocommit=True)
    fetch(fresh_db_url, "CREATE EXTENSION unaccent", autocommit=True)

    upgrade(fresh_db_url, monkeypatch)

    assert public_tables(fresh_db_url) == TABLES | {"alembic_version"}


def test_round_trip(fresh_db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    upgrade(fresh_db_url, monkeypatch)

    command.downgrade(alembic_config(), "base")

    # Q10: the tables go, the extensions stay.
    assert public_tables(fresh_db_url) == {"alembic_version"}
    assert EXTENSIONS <= extensions(fresh_db_url)

    command.upgrade(alembic_config(), "head")

    assert public_tables(fresh_db_url) == TABLES | {"alembic_version"}


def diff_models(connection: Connection) -> list[Any]:
    context = MigrationContext.configure(
        connection,
        opts={"compare_type": True, "compare_server_default": True},
    )
    return list(compare_metadata(context, Base.metadata))


async def test_models_match_migration(migrated_url: str) -> None:
    # A4: CHECK constraints are not compared by Alembic; test_constraints covers
    # them. Any narrowly scoped exclusion added here must be named and justified.
    engine = create_async_engine(migrated_url)
    try:
        async with engine.connect() as conn:
            diff = await conn.run_sync(diff_models)
    finally:
        await engine.dispose()

    assert diff == []
