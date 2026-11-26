"""The migrated schema matches brief §7 and the GH-3 gate A answers, per column."""

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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

BIGINT = "bigint"
TEXT = "text"
INT = "integer"
TSTZ = "timestamp with time zone"
JSONB = "jsonb"
NO_DEFAULT = None

# column -> (data_type, nullable, default). The default is compared exactly for
# integers and by substring otherwise; NO_DEFAULT means column_default IS NULL.
Column = tuple[str, bool, str | None]
ID: Column = (BIGINT, False, NO_DEFAULT)  # identity: no column_default
FK: Column = (BIGINT, False, NO_DEFAULT)
REQUIRED_TEXT: Column = (TEXT, False, NO_DEFAULT)
NULL_TEXT: Column = (TEXT, True, NO_DEFAULT)
EMPTY_JSONB: Column = (JSONB, False, "'{}'")
VERSION: Column = (INT, False, "1")
NOW: Column = (TSTZ, False, "now()")

EXPECTED: dict[str, dict[str, Column]] = {
    "stores": {
        "id": ID,
        "name": REQUIRED_TEXT,
        "currency": ("character", False, "'RON'"),
    },
    "users": {
        "id": ID,
        "email": REQUIRED_TEXT,
        "password_hash": REQUIRED_TEXT,
        "role": (TEXT, False, "'customer'"),
        "stripe_customer_id": NULL_TEXT,
        "created_at": NOW,
    },
    "refresh_tokens": {
        "id": ID,
        "user_id": FK,
        "token_hash": REQUIRED_TEXT,
        "expires_at": (TSTZ, False, NO_DEFAULT),
        "revoked_at": (TSTZ, True, NO_DEFAULT),
    },
    "addresses": {
        "id": ID,
        "user_id": FK,
        "label": NULL_TEXT,
        "full_name": REQUIRED_TEXT,
        "phone": REQUIRED_TEXT,
        "street": REQUIRED_TEXT,
        "city": REQUIRED_TEXT,
        "county": REQUIRED_TEXT,
        "postal_code": REQUIRED_TEXT,
        "is_default": ("boolean", False, "false"),
    },
    "user_preferences": {
        "user_id": FK,
        "sizes": EMPTY_JSONB,
        "preferred_brands": ("ARRAY", False, "'{}'"),
    },
    "categories": {
        "id": ID,
        "store_id": FK,
        "name": REQUIRED_TEXT,
        "slug": REQUIRED_TEXT,
    },
    "products": {
        "id": ID,
        "store_id": FK,
        "category_id": FK,
        "brand": REQUIRED_TEXT,
        "name": REQUIRED_TEXT,
        "description": REQUIRED_TEXT,
        "attributes": EMPTY_JSONB,
        "rating_avg": ("numeric", True, NO_DEFAULT),
        "rating_count": (INT, False, "0"),
        "version": VERSION,
        "content_hash": NULL_TEXT,
        "updated_at": NOW,
    },
    "product_variants": {
        "id": ID,
        "product_id": FK,
        "sku": REQUIRED_TEXT,
        "attributes": EMPTY_JSONB,
        "price_minor": (INT, False, NO_DEFAULT),
        "stock": (INT, False, NO_DEFAULT),
        "version": VERSION,
    },
    "product_images": {
        "id": ID,
        "product_id": FK,
        "storage_key": REQUIRED_TEXT,
        "alt_text": NULL_TEXT,
        "position": (INT, False, NO_DEFAULT),
    },
    "reviews": {
        "id": ID,
        "product_id": FK,
        "author_display_name": REQUIRED_TEXT,
        "rating": (INT, False, NO_DEFAULT),
        "title": REQUIRED_TEXT,
        "body": REQUIRED_TEXT,
        "created_at": NOW,
    },
    "store_policies": {
        "id": ID,
        "store_id": FK,
        "kind": REQUIRED_TEXT,
        "title": REQUIRED_TEXT,
        "body": REQUIRED_TEXT,
        "version": VERSION,
    },
    # GH-13 (P2a): the index, its outbox and the usage ledger.
    "kb_chunks": {
        "id": ID,
        "store_id": FK,
        "source_type": REQUIRED_TEXT,
        "source_id": (BIGINT, False, NO_DEFAULT),
        "chunk_index": (INT, False, NO_DEFAULT),
        "text": REQUIRED_TEXT,
        "embedding": ("USER-DEFINED", False, NO_DEFAULT),
        "tsv": ("tsvector", True, NO_DEFAULT),
        "source_version": (INT, True, NO_DEFAULT),
        "content_hash": REQUIRED_TEXT,
    },
    "reindex_outbox": {
        "id": ID,
        "source_type": REQUIRED_TEXT,
        "source_id": (BIGINT, False, NO_DEFAULT),
        "reason": REQUIRED_TEXT,
        "enqueued_at": NOW,
        "locked_at": (TSTZ, True, NO_DEFAULT),
        "attempts": (INT, False, "0"),
        "last_error": NULL_TEXT,
        "done_at": (TSTZ, True, NO_DEFAULT),
    },
    "usage_ledger": {
        "id": ID,
        "user_id": (BIGINT, True, NO_DEFAULT),
        "provider": REQUIRED_TEXT,
        "operation": REQUIRED_TEXT,
        "units": (BIGINT, False, NO_DEFAULT),
        "estimated_cost_eur": ("numeric", False, NO_DEFAULT),
        "created_at": NOW,
    },
}

# The only nullable columns (Q6).
NULLABLE = {
    ("addresses", "label"),
    ("users", "stripe_customer_id"),
    ("refresh_tokens", "revoked_at"),
    ("products", "rating_avg"),
    ("products", "content_hash"),
    ("product_images", "alt_text"),
    # GH-13: tsv is filled by GH-14 (B5); reviews have no source version (N2).
    ("kb_chunks", "tsv"),
    ("kb_chunks", "source_version"),
    ("reindex_outbox", "locked_at"),
    ("reindex_outbox", "last_error"),
    ("reindex_outbox", "done_at"),
    ("usage_ledger", "user_id"),
}

# (table, column, referenced table) -> pg_constraint.confdeltype (Q2).
CASCADE, RESTRICT, SET_NULL = "c", "r", "n"
FK_DELETE_RULES = {
    ("refresh_tokens", "user_id", "users"): CASCADE,
    ("addresses", "user_id", "users"): CASCADE,
    ("user_preferences", "user_id", "users"): CASCADE,
    ("product_variants", "product_id", "products"): CASCADE,
    ("product_images", "product_id", "products"): CASCADE,
    ("reviews", "product_id", "products"): CASCADE,
    ("categories", "store_id", "stores"): RESTRICT,
    ("products", "store_id", "stores"): RESTRICT,
    ("store_policies", "store_id", "stores"): RESTRICT,
    ("products", "category_id", "categories"): RESTRICT,
    # GH-13: chunks belong to a store; ledger rows outlive a deleted user (N13).
    ("kb_chunks", "store_id", "stores"): RESTRICT,
    ("usage_ledger", "user_id", "users"): SET_NULL,
}


async def rows(session: AsyncSession, sql: str, **params: Any) -> list[Any]:
    return list((await session.execute(text(sql), params)).all())


async def columns(session: AsyncSession, table: str) -> dict[str, Any]:
    result = await rows(
        session,
        """
        SELECT column_name, data_type, is_nullable, column_default,
               character_maximum_length, numeric_precision, numeric_scale,
               is_identity, identity_generation, udt_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = :table
        """,
        table=table,
    )
    return {row.column_name: row for row in result}


async def test_tables_exist(session: AsyncSession) -> None:
    result = await rows(
        session,
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        """,
    )

    assert {row.table_name for row in result} == TABLES | {"alembic_version"}


@pytest.mark.parametrize("table", sorted(EXPECTED))
async def test_columns_match_brief(session: AsyncSession, table: str) -> None:
    actual = await columns(session, table)

    assert set(actual) == set(EXPECTED[table])
    for name, (data_type, nullable, default) in EXPECTED[table].items():
        col = actual[name]
        where = f"{table}.{name}"
        assert col.data_type == data_type, where
        assert (col.is_nullable == "YES") is nullable, where
        if default is None:
            assert col.column_default is None, where
        elif data_type == INT:
            assert col.column_default == default, where
        else:
            assert col.column_default is not None, where
            assert default in col.column_default, where


async def test_typed_details(session: AsyncSession) -> None:
    stores = await columns(session, "stores")
    products = await columns(session, "products")
    preferences = await columns(session, "user_preferences")

    assert stores["currency"].character_maximum_length == 3
    assert products["rating_avg"].numeric_precision == 3
    assert products["rating_avg"].numeric_scale == 2
    assert preferences["preferred_brands"].udt_name == "_text"


async def test_only_listed_columns_are_nullable(session: AsyncSession) -> None:
    result = await rows(
        session,
        """
        SELECT table_name, column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND is_nullable = 'YES'
          AND table_name <> 'alembic_version'
        """,
    )

    assert {(r.table_name, r.column_name) for r in result} == NULLABLE


async def test_money_columns_are_integer_minor(session: AsyncSession) -> None:
    result = await rows(
        session,
        """
        SELECT table_name, column_name, data_type FROM information_schema.columns
        WHERE table_schema = 'public'
          AND (column_name LIKE '%price%' OR column_name LIKE '%\\_minor')
        """,
    )

    assert result, "no money column found"
    for row in result:
        where = f"{row.table_name}.{row.column_name}"
        assert row.column_name.endswith("_minor"), where
        assert row.data_type == INT, where


async def test_timestamps_are_timestamptz(session: AsyncSession) -> None:
    result = await rows(
        session,
        """
        SELECT table_name, column_name, data_type FROM information_schema.columns
        WHERE table_schema = 'public'
          AND (column_name LIKE '%\\_at' OR data_type LIKE 'timestamp%')
        """,
    )

    assert result, "no timestamp column found"
    for row in result:
        where = f"{row.table_name}.{row.column_name}"
        assert row.column_name.endswith("_at"), where
        assert row.data_type == TSTZ, where


async def test_store_id_only_on_catalog_parents(session: AsyncSession) -> None:
    result = await rows(
        session,
        """
        SELECT table_name FROM information_schema.columns
        WHERE table_schema = 'public' AND column_name = 'store_id'
        """,
    )

    assert {r.table_name for r in result} == {
        "categories",
        "products",
        "store_policies",
        "kb_chunks",
    }


async def primary_key(session: AsyncSession, table: str) -> list[str]:
    result = await rows(
        session,
        """
        SELECT a.attname
        FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = CAST(:table AS regclass) AND i.indisprimary
        """,
        table=f"public.{table}",
    )
    return sorted(r.attname for r in result)


@pytest.mark.parametrize("table", sorted(TABLES - {"user_preferences"}))
async def test_ids_are_bigint_identity_always(
    session: AsyncSession, table: str
) -> None:
    col = (await columns(session, table))["id"]

    assert col.data_type == BIGINT
    assert col.is_identity == "YES"
    assert col.identity_generation == "ALWAYS"
    assert await primary_key(session, table) == ["id"]


async def test_user_preferences_pk_is_user_id(session: AsyncSession) -> None:
    col = (await columns(session, "user_preferences"))["user_id"]

    assert await primary_key(session, "user_preferences") == ["user_id"]
    assert col.is_identity == "NO"


async def test_fk_delete_rules(session: AsyncSession) -> None:
    result = await rows(
        session,
        """
        SELECT src.relname AS table_name, a.attname AS column_name,
               ref.relname AS ref_table, c.confdeltype::text AS confdeltype,
               cardinality(c.conkey) AS n
        FROM pg_constraint c
        JOIN pg_class src ON src.oid = c.conrelid
        JOIN pg_class ref ON ref.oid = c.confrelid
        JOIN pg_namespace ns ON ns.oid = src.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
        WHERE c.contype = 'f' AND ns.nspname = 'public'
        """,
    )

    assert all(r.n == 1 for r in result), "only single-column foreign keys"
    actual = {(r.table_name, r.column_name, r.ref_table): r.confdeltype for r in result}
    assert actual == FK_DELETE_RULES


async def test_every_fk_column_leads_an_index(session: AsyncSession) -> None:
    result = await rows(
        session,
        """
        SELECT src.relname AS table_name, a.attname AS column_name,
               EXISTS (
                   SELECT 1 FROM pg_index i
                   WHERE i.indrelid = c.conrelid AND i.indkey[0] = c.conkey[1]
               ) AS indexed
        FROM pg_constraint c
        JOIN pg_class src ON src.oid = c.conrelid
        JOIN pg_namespace ns ON ns.oid = src.relnamespace
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
        WHERE c.contype = 'f' AND ns.nspname = 'public'
        """,
    )

    assert len(result) == len(FK_DELETE_RULES)
    unindexed = [f"{r.table_name}.{r.column_name}" for r in result if not r.indexed]
    assert unindexed == []


async def index(session: AsyncSession, name: str) -> Any:
    result = await rows(
        session,
        """
        SELECT t.relname AS table_name, i.indisunique,
               pg_get_indexdef(i.indexrelid) AS definition,
               pg_get_expr(i.indpred, i.indrelid) AS predicate
        FROM pg_index i
        JOIN pg_class ix ON ix.oid = i.indexrelid
        JOIN pg_class t ON t.oid = i.indrelid
        JOIN pg_namespace ns ON ns.oid = ix.relnamespace
        WHERE ns.nspname = 'public' AND ix.relname = :name
        """,
        name=name,
    )
    assert len(result) == 1, f"index {name} not found"
    return result[0]


async def test_email_index_is_lower_expression(session: AsyncSession) -> None:
    ix = await index(session, "uq_users_email_lower")

    assert ix.table_name == "users"
    assert ix.indisunique
    assert "lower(email)" in ix.definition
    assert ix.predicate is None


async def test_default_address_index_is_partial(session: AsyncSession) -> None:
    ix = await index(session, "uq_addresses_user_id_default")

    assert ix.table_name == "addresses"
    assert ix.indisunique
    assert "(user_id)" in ix.definition
    assert ix.predicate is not None
    assert "is_default" in ix.predicate


async def test_no_native_enum_types(session: AsyncSession) -> None:
    result = await rows(
        session,
        """
        SELECT t.typname FROM pg_type t
        JOIN pg_namespace ns ON ns.oid = t.typnamespace
        WHERE ns.nspname = 'public' AND t.typtype = 'e'
        """,
    )

    assert result == []


async def test_no_triggers(session: AsyncSession) -> None:
    result = await rows(
        session,
        """
        SELECT tg.tgname FROM pg_trigger tg
        JOIN pg_class c ON c.oid = tg.tgrelid
        JOIN pg_namespace ns ON ns.oid = c.relnamespace
        WHERE ns.nspname = 'public' AND NOT tg.tgisinternal
        """,
    )

    assert result == []


async def test_constraint_names_follow_convention(session: AsyncSession) -> None:
    constraints = await rows(
        session,
        """
        SELECT c.conname AS name, c.contype::text AS contype FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace ns ON ns.oid = t.relnamespace
        WHERE ns.nspname = 'public' AND t.relname <> 'alembic_version'
        """,
    )
    indexes = await rows(
        session,
        """
        SELECT indexname AS name FROM pg_indexes
        WHERE schemaname = 'public' AND tablename <> 'alembic_version'
        """,
    )
    prefix = {"p": "pk_", "f": "fk_", "u": "uq_", "c": "ck_"}

    assert constraints and indexes
    wrong = [
        r.name for r in constraints if not r.name.startswith(prefix.get(r.contype, "?"))
    ]
    assert wrong == []
    wrong = [r.name for r in indexes if not r.name.startswith(("pk_", "uq_", "ix_"))]
    assert wrong == []
