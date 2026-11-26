"""Enqueue sources for the reindex worker (PATTERN-010, D-006).

Every function joins the caller's transaction: the row commits with the change that
caused it, or rolls back with it. Nothing here calls the embedding API.
"""

from sqlalchemy import insert, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Product, ReindexOutbox, StorePolicy

# The values the CHECK constraints of migration 0002 allow.
SOURCE_TYPES = ("product", "reviews", "policy")
REASONS = ("create", "update", "delete", "full")


async def enqueue(
    session: AsyncSession, source_type: str, source_id: int, reason: str
) -> None:
    """One source (admin routes; GH-15's single-source reindex).

    Added, not flushed: the caller's next flush or commit writes it, so an error of
    that flush (a taken SKU) stays where the caller handles it.
    """
    session.add(
        ReindexOutbox(source_type=source_type, source_id=source_id, reason=reason)
    )


async def enqueue_full_reindex(session: AsyncSession) -> int:
    """Every product, every product's reviews and every policy; returns the count."""
    sources = [
        ("product", select(Product.id)),
        ("reviews", select(Product.id)),
        ("policy", select(StorePolicy.id)),
    ]
    count = 0
    for source_type, ids in sources:
        query = ids.add_columns(
            literal(source_type).label("source_type"), literal("full").label("reason")
        )
        result = await session.execute(
            insert(ReindexOutbox)
            .from_select(["source_id", "source_type", "reason"], query)
            .returning(ReindexOutbox.id)
        )
        count += len(result.all())
    return count
