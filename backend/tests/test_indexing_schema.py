"""Migration 0002 details the column lists in test_schema don't cover (GH-13).

CHECKs, the vector size, numeric(12,8), indexes and the A1 unique key. Each test runs
in the rolled-back `session`; a statement expected to fail comes last in its test.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

SOURCE_TYPES = ["product", "reviews", "policy"]
REASONS = ["create", "update", "delete", "full"]


async def scalar(session: AsyncSession, sql: str, **params: Any) -> Any:
    return (await session.execute(text(sql), params)).scalar_one()


async def make_store(session: AsyncSession) -> int:
    return int(
        await scalar(session, "INSERT INTO stores (name) VALUES ('S') RETURNING id")
    )


def vector(dim: int) -> str:
    return "[" + ",".join(["0.5"] * dim) + "]"


async def insert_chunk(
    session: AsyncSession,
    store_id: int,
    *,
    source_type: str = "product",
    source_id: int = 1,
    chunk_index: int = 0,
    dim: int = 1536,
) -> int:
    return int(
        await scalar(
            session,
            "INSERT INTO kb_chunks (store_id, source_type, source_id, chunk_index,"
            " text, embedding, content_hash) VALUES (:store_id, :source_type,"
            " :source_id, :chunk_index, 'Nume: X', CAST(:embedding AS vector),"
            " 'hash') RETURNING id",
            store_id=store_id,
            source_type=source_type,
            source_id=source_id,
            chunk_index=chunk_index,
            embedding=vector(dim),
        )
    )


async def insert_outbox(
    session: AsyncSession, source_type: str = "product", reason: str = "update"
) -> int:
    return int(
        await scalar(
            session,
            "INSERT INTO reindex_outbox (source_type, source_id, reason)"
            " VALUES (:source_type, 1, :reason) RETURNING id",
            source_type=source_type,
            reason=reason,
        )
    )


async def insert_ledger(
    session: AsyncSession, operation: str = "embedding", user_id: int | None = None
) -> int:
    return int(
        await scalar(
            session,
            "INSERT INTO usage_ledger (user_id, provider, operation, units,"
            " estimated_cost_eur) VALUES (:user_id, 'openai', :operation, 10,"
            " 0.00000020) RETURNING id",
            user_id=user_id,
            operation=operation,
        )
    )


async def column_type(session: AsyncSession, table: str, column: str) -> str:
    return str(
        await scalar(
            session,
            "SELECT format_type(a.atttypid, a.atttypmod) FROM pg_attribute a"
            " WHERE a.attrelid = CAST(:table AS regclass) AND a.attname = :column",
            table=f"public.{table}",
            column=column,
        )
    )


async def indexes(session: AsyncSession, table: str) -> list[Any]:
    result = await session.execute(
        text(
            "SELECT ix.relname AS name, i.indisunique, i.indisprimary,"
            " pg_get_indexdef(i.indexrelid) AS definition,"
            " (SELECT a.attname FROM pg_attribute a WHERE a.attrelid = i.indrelid"
            "  AND a.attnum = i.indkey[0]) AS first_column"
            " FROM pg_index i JOIN pg_class ix ON ix.oid = i.indexrelid"
            " WHERE i.indrelid = CAST(:table AS regclass)"
        ),
        {"table": f"public.{table}"},
    )
    return list(result.all())


# --- types --------------------------------------------------------------------------


async def test_embedding_is_vector_1536(session: AsyncSession) -> None:
    assert await column_type(session, "kb_chunks", "embedding") == "vector(1536)"


async def test_tsv_is_tsvector(session: AsyncSession) -> None:
    assert await column_type(session, "kb_chunks", "tsv") == "tsvector"


async def test_cost_is_numeric_12_8_and_units_bigint(session: AsyncSession) -> None:
    cost = await column_type(session, "usage_ledger", "estimated_cost_eur")
    units = await column_type(session, "usage_ledger", "units")

    assert cost == "numeric(12,8)"
    assert units == "bigint"


async def test_a_chunk_without_tsv_is_valid(session: AsyncSession) -> None:
    chunk = await insert_chunk(session, await make_store(session))

    tsv_null = await scalar(
        session, "SELECT tsv IS NULL FROM kb_chunks WHERE id = :id", id=chunk
    )
    assert tsv_null is True


async def test_a_1535_dimension_embedding_is_refused(session: AsyncSession) -> None:
    store_id = await make_store(session)

    with pytest.raises(DBAPIError, match="1536"):
        await insert_chunk(session, store_id, dim=1535)


# --- CHECKs (text + CHECK, PATTERN-014) ---------------------------------------------


@pytest.mark.parametrize("source_type", SOURCE_TYPES)
async def test_valid_source_types_are_accepted(
    session: AsyncSession, source_type: str
) -> None:
    store_id = await make_store(session)

    await insert_chunk(session, store_id, source_type=source_type)
    await insert_outbox(session, source_type=source_type)


@pytest.mark.parametrize("table", ["kb_chunks", "reindex_outbox"])
async def test_unknown_source_type_is_refused(
    session: AsyncSession, table: str
) -> None:
    store_id = await make_store(session)

    with pytest.raises(IntegrityError, match=f"ck_{table}_source_type"):
        if table == "kb_chunks":
            await insert_chunk(session, store_id, source_type="products")
        else:
            await insert_outbox(session, source_type="products")


@pytest.mark.parametrize("reason", REASONS)
async def test_valid_reasons_are_accepted(session: AsyncSession, reason: str) -> None:
    await insert_outbox(session, reason=reason)


async def test_unknown_reason_is_refused(session: AsyncSession) -> None:
    with pytest.raises(IntegrityError, match="ck_reindex_outbox_reason"):
        await insert_outbox(session, reason="rename")


async def test_embedding_operation_is_accepted(session: AsyncSession) -> None:
    await insert_ledger(session, operation="embedding")


@pytest.mark.parametrize("operation", ["llm", "stt", "tts", "Embedding"])
async def test_other_operations_are_refused_until_p3(
    session: AsyncSession, operation: str
) -> None:
    with pytest.raises(IntegrityError, match="ck_usage_ledger_operation"):
        await insert_ledger(session, operation=operation)


async def test_provider_has_no_check(session: AsyncSession) -> None:
    # A2: P3 adds providers without a migration of this column.
    await session.execute(
        text(
            "INSERT INTO usage_ledger (provider, operation, units, estimated_cost_eur)"
            " VALUES ('anthropic', 'embedding', 1, 0)"
        )
    )


# --- defaults, duplicates, unique key, indexes ----------------------------------------


async def test_outbox_defaults(session: AsyncSession) -> None:
    row_id = await insert_outbox(session)

    row = (
        await session.execute(
            text(
                "SELECT enqueued_at IS NOT NULL AS stamped, locked_at, attempts,"
                " last_error, done_at FROM reindex_outbox WHERE id = :id"
            ),
            {"id": row_id},
        )
    ).one()
    assert row.stamped
    assert (row.locked_at, row.attempts, row.last_error, row.done_at) == (
        None,
        0,
        None,
        None,
    )


async def test_pending_duplicates_are_allowed(session: AsyncSession) -> None:
    # N4: no unique index on pending rows.
    first = await insert_outbox(session)
    second = await insert_outbox(session)

    assert first != second
    unique = [
        ix.name for ix in await indexes(session, "reindex_outbox") if ix.indisunique
    ]
    assert unique == ["pk_reindex_outbox"]


async def test_one_chunk_per_source_and_index(session: AsyncSession) -> None:
    # A1: unique (source_type, source_id, chunk_index).
    store_id = await make_store(session)
    await insert_chunk(session, store_id, chunk_index=0)
    await insert_chunk(session, store_id, chunk_index=1)
    await insert_chunk(session, store_id, source_type="reviews", chunk_index=0)

    with pytest.raises(IntegrityError, match="uq_kb_chunks_"):
        await insert_chunk(session, store_id, chunk_index=1)


async def test_chunk_unique_key_columns(session: AsyncSession) -> None:
    unique = [
        ix.definition
        for ix in await indexes(session, "kb_chunks")
        if ix.indisunique and not ix.indisprimary
    ]

    assert len(unique) == 1
    assert "(source_type, source_id, chunk_index)" in unique[0]


async def test_ledger_created_at_and_user_id_are_indexed(session: AsyncSession) -> None:
    leading = {ix.first_column for ix in await indexes(session, "usage_ledger")}

    assert {"created_at", "user_id"} <= leading


async def test_deleting_a_user_keeps_their_ledger_rows(session: AsyncSession) -> None:
    user_id = int(
        await scalar(
            session,
            "INSERT INTO users (email, password_hash)"
            " VALUES ('a@b.ro', 'h') RETURNING id",
        )
    )
    row_id = await insert_ledger(session, user_id=user_id)

    await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})

    assert (
        await scalar(
            session, "SELECT user_id FROM usage_ledger WHERE id = :id", id=row_id
        )
        is None
    )


async def test_chunks_keep_their_store(session: AsyncSession) -> None:
    store_id = await make_store(session)
    await insert_chunk(session, store_id)

    with pytest.raises(IntegrityError, match="fk_kb_chunks_store_id_stores"):
        await session.execute(
            text("DELETE FROM stores WHERE id = :id"), {"id": store_id}
        )
