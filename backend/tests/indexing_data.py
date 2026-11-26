"""Rows for the GH-13 worker tests, committed through a sessionmaker on `indexing_db`.

Catalog rows go through the existing models (SQLAlchemy Core, bound parameters); the
new tables are read and written with plain SQL, so the tests name their columns
exactly as the migration does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Category, Product, ProductVariant, Review, Store, StorePolicy

Sessionmaker = async_sessionmaker[AsyncSession]

MODEL = "text-embedding-3-small"
# A complete, valid configuration (the key is a placeholder; the stub never sends it).
ENV: dict[str, str] = {
    "EMBEDDING_MODEL": MODEL,
    "OPENAI_API_KEY": "test-key-not-real",
    "PRICE_OPENAI_EMBEDDING_EUR_PER_1M_TOKENS": "0.02",
    "DAILY_COST_CAP_EUR": "1",
}


@dataclass(frozen=True)
class Shop:
    store_id: int
    category_id: int
    category_name: str


async def _insert_id(sm: Sessionmaker, model: Any, **values: Any) -> int:
    async with sm() as session, session.begin():
        result = await session.execute(
            insert(model).values(**values).returning(model.id)
        )
        return int(result.scalar_one())


async def execute(sm: Sessionmaker, sql: str, **params: Any) -> None:
    async with sm() as session, session.begin():
        await session.execute(text(sql), params)


async def rows(sm: Sessionmaker, sql: str, **params: Any) -> list[Any]:
    async with sm() as session:
        return list((await session.execute(text(sql), params)).all())


async def scalar(sm: Sessionmaker, sql: str, **params: Any) -> Any:
    async with sm() as session:
        return (await session.execute(text(sql), params)).scalar_one()


async def make_shop(sm: Sessionmaker, category_name: str = "Îmbrăcăminte") -> Shop:
    store_id = await _insert_id(sm, Store, name="Shopy", currency="RON")
    category_id = await _insert_id(
        sm, Category, store_id=store_id, name=category_name, slug="clothing"
    )
    return Shop(store_id, category_id, category_name)


async def make_product(sm: Sessionmaker, shop: Shop, **values: Any) -> int:
    row = {
        "store_id": shop.store_id,
        "category_id": shop.category_id,
        "brand": "Nike",
        "name": "Hanorac",
        "description": "Hanorac cu glugă.",
        "attributes": {"material": "bumbac"},
        **values,
    }
    return await _insert_id(sm, Product, **row)


async def make_variant(
    sm: Sessionmaker, product_id: int, sku: str, **values: Any
) -> int:
    row = {
        "product_id": product_id,
        "sku": sku,
        "attributes": {"size": "M"},
        "price_minor": 24999,
        "stock": 5,
        **values,
    }
    return await _insert_id(sm, ProductVariant, **row)


async def make_review(
    sm: Sessionmaker,
    product_id: int,
    *,
    rating: int = 5,
    title: str = "Foarte bun",
    body: str = "Îmi place mult.",
    author: str = "Maria Popescu",
    created_at: datetime | None = None,
) -> int:
    values: dict[str, Any] = {
        "product_id": product_id,
        "author_display_name": author,
        "rating": rating,
        "title": title,
        "body": body,
    }
    if created_at is not None:
        values["created_at"] = created_at
    return await _insert_id(sm, Review, **values)


async def make_policy(
    sm: Sessionmaker,
    shop: Shop,
    *,
    kind: str = "shipping",
    title: str = "Livrare",
    body: str = "Livrăm în 2-3 zile lucrătoare.",
    version: int = 1,
) -> int:
    return await _insert_id(
        sm,
        StorePolicy,
        store_id=shop.store_id,
        kind=kind,
        title=title,
        body=body,
        version=version,
    )


async def enqueue_row(
    sm: Sessionmaker, source_type: str, source_id: int, reason: str = "update"
) -> int:
    async with sm() as session, session.begin():
        result = await session.execute(
            text(
                "INSERT INTO reindex_outbox (source_type, source_id, reason)"
                " VALUES (:source_type, :source_id, :reason) RETURNING id"
            ),
            {"source_type": source_type, "source_id": source_id, "reason": reason},
        )
        return int(result.scalar_one())


async def outbox_row(sm: Sessionmaker, row_id: int) -> Any:
    found = await rows(
        sm,
        "SELECT id, source_type, source_id, reason, enqueued_at, locked_at,"
        " attempts, last_error, done_at FROM reindex_outbox WHERE id = :id",
        id=row_id,
    )
    assert len(found) == 1, f"outbox row {row_id} not found"
    return found[0]


async def outbox_rows(sm: Sessionmaker) -> list[Any]:
    return await rows(
        sm,
        "SELECT id, source_type, source_id, reason, attempts, done_at"
        " FROM reindex_outbox ORDER BY id",
    )


async def chunks(sm: Sessionmaker, source_type: str, source_id: int) -> list[Any]:
    """The chunks of one source by chunk_index; the embedding as pgvector text."""
    return await rows(
        sm,
        "SELECT id, store_id, chunk_index, text, embedding::text AS embedding,"
        " vector_dims(embedding) AS dims, tsv IS NULL AS tsv_null,"
        " source_version, content_hash"
        " FROM kb_chunks WHERE source_type = :source_type AND source_id = :source_id"
        " ORDER BY chunk_index",
        source_type=source_type,
        source_id=source_id,
    )


async def chunk_count(sm: Sessionmaker) -> int:
    return int(await scalar(sm, "SELECT count(*) FROM kb_chunks"))


async def add_ledger(
    sm: Sessionmaker,
    cost_eur: Decimal | str,
    *,
    provider: str = "openai",
    created_at_sql: str = "now()",
) -> None:
    """One usage_ledger row; `created_at_sql` is a fixed SQL expression of the test."""
    await execute(
        sm,
        "INSERT INTO usage_ledger (provider, operation, units, estimated_cost_eur,"
        f" created_at) VALUES (:provider, 'embedding', 1, :cost, {created_at_sql})",
        provider=provider,
        cost=Decimal(cost_eur),
    )


async def ledger_rows(sm: Sessionmaker) -> list[Any]:
    return await rows(
        sm,
        "SELECT user_id, provider, operation, units, estimated_cost_eur, created_at"
        " FROM usage_ledger ORDER BY id",
    )
