"""One outbox row per call: claim, rebuild one source, record (GH-13 N5-N9, B6).

Transactions:
- T1 claims the oldest due row (`FOR UPDATE SKIP LOCKED`) and stays open, row lock
  included, through the embedding call; it replaces the source's chunks and marks the
  row done in one commit (N6).
- The usage_ledger row of a paid call commits on its own, at once, so a later failure
  never loses the record of a paid call (D-019).
- A failure rolls T1 back (old chunks stay) and records the attempt in its own
  transaction (N7).
"""

import enum
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.indexing.chunking import (
    content_hash,
    policy_chunks,
    product_text,
    review_chunks,
)
from app.indexing.embeddings import EmbeddingError, EmbeddingProvider, check_vectors
from app.models import (
    Category,
    KbChunk,
    Product,
    ProductVariant,
    ReindexOutbox,
    Review,
    StorePolicy,
)
from app.usage.ledger import (
    ConfigError,
    daily_cap_eur,
    estimate_cost_eur,
    record,
    spent_today_eur,
    unit_price_eur,
)

log = logging.getLogger("worker.process")

MAX_ATTEMPTS = 5
# A failed row is due again at locked_at + 30 s × 2^(attempts − 1) (N5).
BACKOFF_BASE_SECONDS = 30
# The loop's wait when nothing is due or the due row is blocked (N7).
IDLE_SECONDS = 2
LAST_ERROR_MAX_CHARS = 500
PRICE_VARIABLE = "PRICE_OPENAI_EMBEDDING_EUR_PER_1M_TOKENS"

Sessionmaker = async_sessionmaker[AsyncSession]


class Outcome(enum.Enum):
    IDLE = "idle"  # nothing due
    DONE = "done"  # the source is current, or its chunks are gone with it
    BLOCKED = "blocked"  # no paid call allowed now; attempts unchanged (N9)
    FAILED = "failed"  # an attempt counted


@dataclass(frozen=True)
class IndexingConfig:
    """The environment of one row. Built without raising: a bad value blocks rows."""

    model: str | None
    price_per_1m: Decimal | None
    daily_cap: Decimal | None
    # Why no paid call may start (key, price, cap; the first problem wins).
    call_blocked: str | None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "IndexingConfig":
        model = env.get("EMBEDDING_MODEL", "").strip() or None
        if not env.get("OPENAI_API_KEY", "").strip():
            return cls(model, None, None, "OPENAI_API_KEY is not set")
        try:
            price = unit_price_eur(env, PRICE_VARIABLE)
            cap = daily_cap_eur(env)
        except ConfigError as exc:
            return cls(model, None, None, str(exc))
        return cls(model, price, cap, None)


@dataclass(frozen=True)
class _Source:
    store_id: int
    version: int | None
    texts: list[str]


class _Blocked(Exception):
    """No paid call now; the row stays pending with this reason."""


async def process_next(
    sessionmaker: Sessionmaker,
    provider: EmbeddingProvider | None,
    config: IndexingConfig,
) -> Outcome:
    """Handle the oldest due outbox row, if any."""
    async with sessionmaker() as session:
        row = await _claim(session)
        if row is None:
            await session.rollback()
            return Outcome.IDLE
        row_id, source_type, source_id = row.id, row.source_type, row.source_id
        try:
            try:
                await _rebuild(session, sessionmaker, provider, config, row)
                row.done_at = func.now()
                outcome = Outcome.DONE
            except _Blocked as blocked:
                row.last_error = str(blocked)
                outcome = Outcome.BLOCKED
            await session.commit()
        except Exception as exc:
            await session.rollback()
            error = _describe(exc)
        else:
            if outcome is Outcome.DONE:
                log.info("reindexed %s %s", source_type, source_id)
            return outcome
    await _record_failure(sessionmaker, row_id, error)
    log.warning("reindex of %s %s failed: %s", source_type, source_id, error)
    return Outcome.FAILED


async def _claim(session: AsyncSession) -> ReindexOutbox | None:
    """The oldest due row, locked until this transaction ends (N6)."""
    backoff = func.make_interval(
        0,
        0,
        0,
        0,
        0,
        0,
        BACKOFF_BASE_SECONDS * func.power(2, ReindexOutbox.attempts - 1),
    )
    row = await session.scalar(
        select(ReindexOutbox)
        .where(
            ReindexOutbox.done_at.is_(None),
            ReindexOutbox.attempts < MAX_ATTEMPTS,
            or_(
                ReindexOutbox.attempts == 0,
                ReindexOutbox.locked_at + backoff <= func.now(),
            ),
        )
        .order_by(ReindexOutbox.enqueued_at, ReindexOutbox.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if row is not None:
        row.locked_at = func.now()
        await session.flush()
    return row


async def _rebuild(
    session: AsyncSession,
    sessionmaker: Sessionmaker,
    provider: EmbeddingProvider | None,
    config: IndexingConfig,
    row: ReindexOutbox,
) -> None:
    """Replace the chunks of the row's source; a missing source loses its chunks."""
    source = await _load(session, row)
    if source is None:
        await _delete_chunks(session, row, missing=True)
        return
    # The model is part of every hash, so nothing is compared without it (A6).
    if config.model is None:
        raise _Blocked("EMBEDDING_MODEL is not set")

    hashes = [content_hash(config.model, text) for text in source.texts]
    existing = await session.execute(
        select(KbChunk.content_hash, KbChunk.embedding).where(
            KbChunk.source_type == row.source_type, KbChunk.source_id == row.source_id
        )
    )
    vectors: dict[str, Sequence[float]] = {h: v for h, v in existing}
    needed = [i for i, h in enumerate(hashes) if h not in vectors]
    if needed:
        embedded = await _embed(
            session, sessionmaker, provider, config, [source.texts[i] for i in needed]
        )
        vectors.update(zip((hashes[i] for i in needed), embedded, strict=True))

    await _delete_chunks(session, row, missing=False)
    session.add_all(
        KbChunk(
            store_id=source.store_id,
            source_type=row.source_type,
            source_id=row.source_id,
            chunk_index=index,
            text=text,
            embedding=vectors[hashes[index]],
            source_version=source.version,
            content_hash=hashes[index],
        )
        for index, text in enumerate(source.texts)
    )
    if row.source_type == "product":
        # The explicit updated_at stops its onupdate; version is not touched.
        await session.execute(
            update(Product)
            .where(Product.id == row.source_id)
            .values(content_hash=hashes[0], updated_at=Product.updated_at)
            .execution_options(synchronize_session=False)
        )
    await session.flush()


async def _load(session: AsyncSession, row: ReindexOutbox) -> _Source | None:
    """The source's chunk texts, or None when the source no longer exists."""
    if row.source_type == "policy":
        policy = await session.get(StorePolicy, row.source_id)
        if policy is None:
            return None
        return _Source(
            policy.store_id, policy.version, policy_chunks(policy.title, policy.body)
        )
    product = await session.get(Product, row.source_id)
    if product is None:
        return None
    if row.source_type == "reviews":
        reviews = await session.scalars(
            select(Review).where(Review.product_id == product.id)
        )
        return _Source(product.store_id, None, review_chunks(reviews))
    category_name = await session.scalar(
        select(Category.name).where(Category.id == product.category_id)
    )
    variants = await session.scalars(
        select(ProductVariant).where(ProductVariant.product_id == product.id)
    )
    text = product_text(product, category_name or "", variants)
    return _Source(product.store_id, product.version, [text])


async def _delete_chunks(
    session: AsyncSession, row: ReindexOutbox, *, missing: bool
) -> None:
    """The source's chunks; a missing product takes its reviews chunks too (B6)."""
    types = [row.source_type]
    if missing and row.source_type == "product":
        types.append("reviews")
    await session.execute(
        delete(KbChunk).where(
            KbChunk.source_type.in_(types), KbChunk.source_id == row.source_id
        )
    )


async def _embed(
    session: AsyncSession,
    sessionmaker: Sessionmaker,
    provider: EmbeddingProvider | None,
    config: IndexingConfig,
    texts: list[str],
) -> list[list[float]]:
    """One paid call for every text, after the cost gate; its ledger row first."""
    if config.call_blocked is not None:
        raise _Blocked(config.call_blocked)
    if provider is None or config.price_per_1m is None or config.daily_cap is None:
        raise _Blocked("OPENAI_API_KEY is not set")
    if await spent_today_eur(session) >= config.daily_cap:
        raise _Blocked("daily cost cap reached")

    result = await provider.embed(texts)
    async with sessionmaker() as ledger, ledger.begin():
        await record(
            ledger,
            provider=provider.provider,
            operation="embedding",
            units=result.total_tokens,
            estimated_cost_eur=estimate_cost_eur(
                result.total_tokens, config.price_per_1m
            ),
        )
    check_vectors(result, len(texts))
    return result.vectors


def _describe(exc: Exception) -> str:
    """last_error: our own message for provider errors, else class and message (A8)."""
    text = (
        str(exc) if isinstance(exc, EmbeddingError) else f"{type(exc).__name__}: {exc}"
    )
    return text[:LAST_ERROR_MAX_CHARS]


async def _record_failure(sessionmaker: Sessionmaker, row_id: int, error: str) -> None:
    """One attempt more, in its own transaction; the 5th leaves the row given up."""
    async with sessionmaker() as session, session.begin():
        await session.execute(
            update(ReindexOutbox)
            .where(ReindexOutbox.id == row_id, ReindexOutbox.done_at.is_(None))
            .values(
                attempts=ReindexOutbox.attempts + 1,
                locked_at=func.now(),
                last_error=error,
            )
        )
