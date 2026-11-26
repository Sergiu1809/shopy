"""The reindex worker on a committed database (GH-13 N1-N9, B6; brief tests 20, 22).

`process_next(sessionmaker, provider, config)` handles one outbox row per call and
opens its own transactions, so every test gets its own migrated database
(`indexing_db`) and a sessionmaker on it. The provider is always the stub; the
config is built with `IndexingConfig.from_env(<dict>)`, which never raises: an
invalid value blocks the row inside `process_next` (A6, A7).

The loop is `worker.__main__.run(sessionmaker, provider, stop)`: it reads the
environment per row and returns once `stop` is set.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import pytest
from alembic import command
from app.indexing.chunking import content_hash
from app.indexing.embeddings import EmbeddingError
from app.indexing.outbox import enqueue_full_reindex
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from worker.process import (
    BACKOFF_BASE_SECONDS,
    IDLE_SECONDS,
    MAX_ATTEMPTS,
    IndexingConfig,
    Outcome,
    process_next,
)

from app.db import create_engine, create_sessionmaker
from tests.conftest import alembic_config
from tests.indexing_data import (
    ENV,
    MODEL,
    Shop,
    add_ledger,
    chunk_count,
    chunks,
    enqueue_row,
    execute,
    ledger_rows,
    make_policy,
    make_product,
    make_review,
    make_shop,
    make_variant,
    outbox_row,
    outbox_rows,
    rows,
    scalar,
)
from tests.stubs import StubEmbeddingProvider, stub_vector
from worker.__main__ import run

Sessionmaker = async_sessionmaker[AsyncSession]
MISSING_ID = 9_000_000_000  # a source id no row has
LONG_BODY = "r" * 1500  # one review of this size fills most of a chunk
NEW_LONG_BODY = "s" * 1500  # still too long to share a chunk with LONG_BODY

# The golden text of the default product of `indexed_product` (B1).
PRODUCT_TEXT = (
    "Nume: Hanorac\n"
    "Marcă: Nike\n"
    "Categorie: Îmbrăcăminte\n"
    "material: bumbac\n"
    "Descriere: Hanorac cu glugă.\n"
    "Variante: color: negru; size: M"
)


def config(**overrides: str | None) -> IndexingConfig:
    """The valid ENV with some variables replaced (a value) or removed (None)."""
    env = dict(ENV)
    for name, value in overrides.items():
        if value is None:
            env.pop(name, None)
        else:
            env[name] = value
    return IndexingConfig.from_env(env)


def floats(embedding: str) -> list[float]:
    return [float(x) for x in embedding.strip("[]").split(",")]


async def drain(
    sm: Sessionmaker, provider: StubEmbeddingProvider, cfg: IndexingConfig
) -> list[Outcome]:
    """process_next until IDLE; every other outcome must be DONE."""
    outcomes = []
    for _ in range(100):
        outcome = await process_next(sm, provider, cfg)
        outcomes.append(outcome)
        if outcome is Outcome.IDLE:
            assert set(outcomes[:-1]) <= {Outcome.DONE}, outcomes
            return outcomes
    raise AssertionError(f"the outbox never drained: {outcomes[-5:]}")


async def product_with_variant(sm: Sessionmaker, shop: Shop, **values: Any) -> int:
    product = await make_product(sm, shop, **values)
    await make_variant(
        sm,
        product,
        f"CLO-{product}-NEGRU-M",
        attributes={"size": "M", "color": "negru"},
    )
    return product


async def indexed_product(
    sm: Sessionmaker, shop: Shop, stub: StubEmbeddingProvider, **values: Any
) -> int:
    """A product with one variant, enqueued and processed."""
    product = await product_with_variant(sm, shop, **values)
    await enqueue_row(sm, "product", product, "create")
    await drain(sm, stub, config())
    return product


async def set_locked_back(sm: Sessionmaker, row_id: int, seconds: float) -> None:
    await execute(
        sm,
        "UPDATE reindex_outbox SET locked_at = now() - make_interval(secs => :s)"
        " WHERE id = :id",
        s=seconds,
        id=row_id,
    )


@pytest.fixture
async def sm(indexing_sessionmaker: Sessionmaker) -> Sessionmaker:
    return indexing_sessionmaker


@pytest.fixture
async def shop(sm: Sessionmaker) -> Shop:
    return await make_shop(sm)


# --- constants (N5, N7) ---------------------------------------------------------------


def test_constants() -> None:
    assert MAX_ATTEMPTS == 5
    assert BACKOFF_BASE_SECONDS == 30
    assert IDLE_SECONDS == 2
    assert {o.name for o in Outcome} == {"IDLE", "DONE", "BLOCKED", "FAILED"}


async def test_idle_when_nothing_is_due(sm: Sessionmaker) -> None:
    stub = StubEmbeddingProvider()

    assert await process_next(sm, stub, config()) is Outcome.IDLE
    assert stub.calls == []


# --- the chunks a row produces (B1, B2, N1, N2, B5) -----------------------------------


async def test_product_chunk_is_stored(sm: Sessionmaker, shop: Shop) -> None:
    product = await product_with_variant(sm, shop, version=4)
    row_id = await enqueue_row(sm, "product", product, "create")
    stub = StubEmbeddingProvider()

    assert await process_next(sm, stub, config()) is Outcome.DONE

    assert stub.calls == [[PRODUCT_TEXT]]
    [chunk] = await chunks(sm, "product", product)
    assert chunk.chunk_index == 0
    assert chunk.text == PRODUCT_TEXT
    assert chunk.store_id == shop.store_id
    assert chunk.source_version == 4
    assert chunk.content_hash == content_hash(MODEL, PRODUCT_TEXT)
    assert chunk.tsv_null is True
    assert chunk.dims == 1536
    assert floats(chunk.embedding) == pytest.approx(stub_vector(PRODUCT_TEXT))
    row = await outbox_row(sm, row_id)
    assert row.done_at is not None
    assert row.attempts == 0


async def test_reviews_chunks_are_stored(sm: Sessionmaker, shop: Shop) -> None:
    product = await make_product(sm, shop, version=3)
    first = await make_review(sm, product, rating=4, title="Bun", body="Îmi place.")
    second = await make_review(sm, product, rating=2, title="Slab", body="S-a rupt.")
    await enqueue_row(sm, "reviews", product, "full")

    assert await process_next(sm, StubEmbeddingProvider(), config()) is Outcome.DONE

    expected = f"[#{first}] 4/5 — Bun: Îmi place.\n[#{second}] 2/5 — Slab: S-a rupt."
    [chunk] = await chunks(sm, "reviews", product)
    assert chunk.text == expected
    assert chunk.store_id == shop.store_id
    assert chunk.source_version is None
    assert chunk.content_hash == content_hash(MODEL, expected)
    assert "Maria" not in chunk.text


async def test_policy_chunk_is_stored(sm: Sessionmaker, shop: Shop) -> None:
    policy = await make_policy(sm, shop, title="Livrare", body="În 2 zile.", version=3)
    await enqueue_row(sm, "policy", policy, "full")

    assert await process_next(sm, StubEmbeddingProvider(), config()) is Outcome.DONE

    [chunk] = await chunks(sm, "policy", policy)
    assert chunk.text == "Livrare\n\nÎn 2 zile."
    assert chunk.store_id == shop.store_id
    assert chunk.source_version == 3
    assert chunk.content_hash == content_hash(MODEL, "Livrare\n\nÎn 2 zile.")


async def test_product_hash_set_without_touching_version(
    sm: Sessionmaker, shop: Shop
) -> None:
    product = await product_with_variant(sm, shop, version=4)
    await execute(
        sm,
        "UPDATE products SET updated_at = '2026-01-01T00:00:00Z' WHERE id = :id",
        id=product,
    )
    before = await scalar(
        sm, "SELECT updated_at FROM products WHERE id = :id", id=product
    )
    await enqueue_row(sm, "product", product, "update")

    assert await process_next(sm, StubEmbeddingProvider(), config()) is Outcome.DONE

    [chunk] = await chunks(sm, "product", product)
    [found] = await rows(
        sm,
        "SELECT content_hash, version, updated_at FROM products WHERE id = :id",
        id=product,
    )
    assert found.content_hash == chunk.content_hash
    assert found.version == 4
    assert found.updated_at == before


# --- brief test 20: only the changed source; unchanged content makes no call ----------


async def test_only_the_changed_product_is_reindexed(
    sm: Sessionmaker, shop: Shop
) -> None:
    first = StubEmbeddingProvider()
    changed = await indexed_product(sm, shop, first)
    other = await indexed_product(sm, shop, first, name="Geacă")
    other_before = await chunks(sm, "product", other)
    await execute(
        sm,
        "UPDATE products SET name = 'Hanorac nou', version = version + 1"
        " WHERE id = :id",
        id=changed,
    )
    await enqueue_row(sm, "product", changed, "update")
    second = StubEmbeddingProvider()

    assert await drain(sm, second, config()) == [Outcome.DONE, Outcome.IDLE]

    new_text = PRODUCT_TEXT.replace("Nume: Hanorac\n", "Nume: Hanorac nou\n")
    assert second.calls == [[new_text]]
    [chunk] = await chunks(sm, "product", changed)
    assert chunk.text == new_text
    assert chunk.source_version == 2
    assert await chunks(sm, "product", other) == other_before


async def test_unchanged_content_makes_no_call(sm: Sessionmaker, shop: Shop) -> None:
    product = await indexed_product(sm, shop, StubEmbeddingProvider())
    [before] = await chunks(sm, "product", product)
    ledger_before = await ledger_rows(sm)
    row_id = await enqueue_row(sm, "product", product, "update")
    second = StubEmbeddingProvider()

    assert await process_next(sm, second, config()) is Outcome.DONE

    assert second.calls == []
    [after] = await chunks(sm, "product", product)
    assert (after.text, after.content_hash, after.embedding) == (
        before.text,
        before.content_hash,
        before.embedding,
    )
    assert await ledger_rows(sm) == ledger_before
    assert (await outbox_row(sm, row_id)).done_at is not None


async def test_only_new_chunks_are_embedded(sm: Sessionmaker, shop: Shop) -> None:
    product = await make_product(sm, shop)
    await make_review(sm, product, body=LONG_BODY)
    second_review = await make_review(sm, product, body=LONG_BODY)
    await enqueue_row(sm, "reviews", product, "full")
    await drain(sm, StubEmbeddingProvider(), config())
    kept, replaced = await chunks(sm, "reviews", product)
    await execute(
        sm,
        "UPDATE reviews SET body = :body WHERE id = :id",
        body=NEW_LONG_BODY,
        id=second_review,
    )
    await enqueue_row(sm, "reviews", product, "full")
    stub = StubEmbeddingProvider()

    assert await process_next(sm, stub, config()) is Outcome.DONE

    new_first, new_second = await chunks(sm, "reviews", product)
    assert stub.calls == [[new_second.text]]
    assert new_second.text == f"[#{second_review}] 5/5 — Foarte bun: {NEW_LONG_BODY}"
    assert (new_first.text, new_first.embedding) == (kept.text, kept.embedding)
    assert new_second.content_hash != replaced.content_hash


async def test_one_call_per_source(sm: Sessionmaker, shop: Shop) -> None:
    product = await make_product(sm, shop)
    for _ in range(3):
        await make_review(sm, product, body=LONG_BODY)
    await enqueue_row(sm, "reviews", product, "full")
    stub = StubEmbeddingProvider()

    assert await process_next(sm, stub, config()) is Outcome.DONE

    found = await chunks(sm, "reviews", product)
    assert [c.chunk_index for c in found] == [0, 1, 2]
    assert stub.calls == [[c.text for c in found]]


async def test_shrinking_source_drops_extra_chunks(
    sm: Sessionmaker, shop: Shop
) -> None:
    product = await make_product(sm, shop)
    await make_review(sm, product, body=LONG_BODY)
    last = await make_review(sm, product, body=LONG_BODY)
    await enqueue_row(sm, "reviews", product, "full")
    await drain(sm, StubEmbeddingProvider(), config())
    await execute(sm, "DELETE FROM reviews WHERE id = :id", id=last)
    await enqueue_row(sm, "reviews", product, "full")

    assert await process_next(sm, StubEmbeddingProvider(), config()) is Outcome.DONE

    assert [c.chunk_index for c in await chunks(sm, "reviews", product)] == [0]


# --- B6: a source that no longer exists -----------------------------------------------


@pytest.mark.parametrize("source", ["product", "reviews", "policy"])
async def test_missing_source_removes_its_chunks(
    sm: Sessionmaker, shop: Shop, source: str
) -> None:
    gone = await product_with_variant(sm, shop)
    kept = await product_with_variant(sm, shop, name="Geacă")
    for product in (gone, kept):
        await make_review(sm, product)
        await enqueue_row(sm, "product", product, "create")
        await enqueue_row(sm, "reviews", product, "full")
    gone_policy = await make_policy(sm, shop, kind="shipping")
    kept_policy = await make_policy(sm, shop, kind="returns", title="Retur")
    for policy in (gone_policy, kept_policy):
        await enqueue_row(sm, "policy", policy, "full")
    await drain(sm, StubEmbeddingProvider(), config())
    kept_chunks = {
        "product": await chunks(sm, "product", kept),
        "reviews": await chunks(sm, "reviews", kept),
        "policy": await chunks(sm, "policy", kept_policy),
    }
    if source == "policy":
        await execute(sm, "DELETE FROM store_policies WHERE id = :id", id=gone_policy)
        row_id = await enqueue_row(sm, "policy", gone_policy, "delete")
    else:
        await execute(sm, "DELETE FROM products WHERE id = :id", id=gone)
        reason = "delete" if source == "product" else "full"
        row_id = await enqueue_row(sm, source, gone, reason)
    stub = StubEmbeddingProvider()

    assert await process_next(sm, stub, config()) is Outcome.DONE

    assert stub.calls == []
    assert (await outbox_row(sm, row_id)).done_at is not None
    if source == "policy":
        assert await chunks(sm, "policy", gone_policy) == []
    else:
        assert await chunks(sm, "reviews", gone) == []
    if source == "product":
        assert await chunks(sm, "product", gone) == []
    assert kept_chunks == {
        "product": await chunks(sm, "product", kept),
        "reviews": await chunks(sm, "reviews", kept),
        "policy": await chunks(sm, "policy", kept_policy),
    }


async def test_reviews_source_without_reviews_has_no_chunks(
    sm: Sessionmaker, shop: Shop
) -> None:
    product = await make_product(sm, shop)
    review = await make_review(sm, product)
    await enqueue_row(sm, "reviews", product, "full")
    await drain(sm, StubEmbeddingProvider(), config())
    await execute(sm, "DELETE FROM reviews WHERE id = :id", id=review)
    await enqueue_row(sm, "reviews", product, "full")
    stub = StubEmbeddingProvider()

    assert await process_next(sm, stub, config()) is Outcome.DONE

    assert stub.calls == []
    assert await chunks(sm, "reviews", product) == []


# --- N6: the claim --------------------------------------------------------------------


async def test_claims_oldest_due_row(sm: Sessionmaker) -> None:
    newer = await enqueue_row(sm, "policy", MISSING_ID, "update")
    older = await enqueue_row(sm, "policy", MISSING_ID + 1, "update")
    backing_off = await enqueue_row(sm, "policy", MISSING_ID + 2, "update")
    await execute(
        sm,
        "UPDATE reindex_outbox SET enqueued_at = now() - interval '1 minute'"
        " WHERE id = :id",
        id=newer,
    )
    await execute(
        sm,
        "UPDATE reindex_outbox SET enqueued_at = now() - interval '10 minutes'"
        " WHERE id = :id",
        id=older,
    )
    await execute(
        sm,
        "UPDATE reindex_outbox SET enqueued_at = now() - interval '1 hour',"
        " attempts = 1, locked_at = now() WHERE id = :id",
        id=backing_off,
    )
    stub = StubEmbeddingProvider()

    assert await process_next(sm, stub, config()) is Outcome.DONE
    assert (await outbox_row(sm, older)).done_at is not None
    assert (await outbox_row(sm, newer)).done_at is None

    assert await process_next(sm, stub, config()) is Outcome.DONE
    assert (await outbox_row(sm, newer)).done_at is not None

    assert await process_next(sm, stub, config()) is Outcome.IDLE
    assert (await outbox_row(sm, backing_off)).done_at is None


async def wait_for(
    condition: Callable[[], Awaitable[bool]] | Callable[[], bool],
    timeout: float,
    what: str,
    task: asyncio.Task[Any] | None = None,
) -> None:
    """Poll `condition` until true; a finished `task` re-raises its error at once."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        if task is not None and task.done():
            task.result()  # raises the task's exception, if any
            raise AssertionError(f"the task ended before: {what}")
        result = condition()
        if not isinstance(result, bool):
            result = await result
        if result:
            return
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"timed out waiting for: {what}")
        await asyncio.sleep(0.02)


async def test_lock_is_held_during_the_call(sm: Sessionmaker, shop: Shop) -> None:
    product = await product_with_variant(sm, shop)
    row_id = await enqueue_row(sm, "product", product, "create")
    gate = asyncio.Event()
    held = StubEmbeddingProvider(gate=gate)
    task = asyncio.create_task(process_next(sm, held, config()))
    try:
        await wait_for(lambda: bool(held.calls), 5, "the embedding call", task)

        with pytest.raises(DBAPIError, match="lock"):
            async with sm() as session, session.begin():
                await session.execute(
                    text(
                        "SELECT id FROM reindex_outbox WHERE id = :id FOR UPDATE NOWAIT"
                    ),
                    {"id": row_id},
                )
        other = StubEmbeddingProvider()
        assert await process_next(sm, other, config()) is Outcome.IDLE
        assert other.calls == []
        assert (await outbox_row(sm, row_id)).done_at is None
    finally:
        gate.set()
    assert await asyncio.wait_for(task, 10) is Outcome.DONE
    assert (await outbox_row(sm, row_id)).done_at is not None


# --- N7: failures, separate error transaction -----------------------------------------


async def test_failure_keeps_old_chunks(sm: Sessionmaker, shop: Shop) -> None:
    product = await indexed_product(sm, shop, StubEmbeddingProvider())
    before = await chunks(sm, "product", product)
    hash_before = await scalar(
        sm, "SELECT content_hash FROM products WHERE id = :id", id=product
    )
    await execute(
        sm,
        "UPDATE products SET name = 'Altceva', version = version + 1 WHERE id = :id",
        id=product,
    )
    row_id = await enqueue_row(sm, "product", product, "update")

    outcome = await process_next(sm, StubEmbeddingProvider(dim=1535), config())

    assert outcome is Outcome.FAILED
    assert await chunks(sm, "product", product) == before
    assert (
        await scalar(sm, "SELECT content_hash FROM products WHERE id = :id", id=product)
        == hash_before
    )
    row = await outbox_row(sm, row_id)
    assert (row.attempts, row.done_at) == (1, None)
    assert row.locked_at is not None
    assert row.last_error


async def test_wrong_dimension_is_retried(sm: Sessionmaker, shop: Shop) -> None:
    product = await product_with_variant(sm, shop)
    row_id = await enqueue_row(sm, "product", product, "create")

    assert await process_next(sm, StubEmbeddingProvider(dim=1535), config()) is (
        Outcome.FAILED
    )
    good = StubEmbeddingProvider()
    assert await process_next(sm, good, config()) is Outcome.IDLE  # backing off
    await set_locked_back(sm, row_id, BACKOFF_BASE_SECONDS + 1)

    assert await process_next(sm, good, config()) is Outcome.DONE

    row = await outbox_row(sm, row_id)
    assert row.done_at is not None
    assert row.attempts == 1
    assert len(await chunks(sm, "product", product)) == 1


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (
            EmbeddingError("openai AuthenticationError (401)"),
            "openai AuthenticationError (401)",
        ),
        (RuntimeError("boom"), "RuntimeError: boom"),
    ],
    ids=["provider error", "other error"],
)
async def test_provider_error_counts_an_attempt(
    sm: Sessionmaker, shop: Shop, error: BaseException, message: str
) -> None:
    product = await product_with_variant(sm, shop)
    row_id = await enqueue_row(sm, "product", product, "create")
    stub = StubEmbeddingProvider(fail_with=error)

    assert await process_next(sm, stub, config()) is Outcome.FAILED

    assert len(stub.calls) == 1
    row = await outbox_row(sm, row_id)
    assert (row.attempts, row.last_error, row.done_at) == (1, message, None)
    assert row.locked_at is not None
    assert await chunks(sm, "product", product) == []
    assert await ledger_rows(sm) == []  # no result, nothing paid to record


async def test_last_error_is_cut_to_500(sm: Sessionmaker, shop: Shop) -> None:
    product = await product_with_variant(sm, shop)
    row_id = await enqueue_row(sm, "product", product, "create")
    stub = StubEmbeddingProvider(fail_with=RuntimeError("x" * 1000))

    assert await process_next(sm, stub, config()) is Outcome.FAILED

    last_error = (await outbox_row(sm, row_id)).last_error
    assert len(last_error) == 500
    assert last_error.startswith("RuntimeError: xxx")


# --- N5: backoff and giving up --------------------------------------------------------


@pytest.mark.parametrize("attempts", [1, 2, 3, 4])
async def test_backoff_due_times(sm: Sessionmaker, attempts: int) -> None:
    row_id = await enqueue_row(sm, "policy", MISSING_ID, "update")
    delay = BACKOFF_BASE_SECONDS * 2 ** (attempts - 1)
    await execute(
        sm,
        "UPDATE reindex_outbox SET attempts = :a WHERE id = :id",
        a=attempts,
        id=row_id,
    )
    stub = StubEmbeddingProvider()

    await set_locked_back(sm, row_id, delay - 5)
    assert await process_next(sm, stub, config()) is Outcome.IDLE

    await set_locked_back(sm, row_id, delay + 5)
    assert await process_next(sm, stub, config()) is Outcome.DONE
    assert (await outbox_row(sm, row_id)).done_at is not None


async def test_gives_up_after_five(sm: Sessionmaker, shop: Shop) -> None:
    product = await product_with_variant(sm, shop)
    row_id = await enqueue_row(sm, "product", product, "create")
    stub = StubEmbeddingProvider(fail_with=RuntimeError("boom"))

    for attempt in range(1, 6):
        assert await process_next(sm, stub, config()) is Outcome.FAILED
        assert (await outbox_row(sm, row_id)).attempts == attempt
        await set_locked_back(sm, row_id, 86_400)

    assert await process_next(sm, stub, config()) is Outcome.IDLE
    assert len(stub.calls) == 5
    row = await outbox_row(sm, row_id)
    assert (row.attempts, row.done_at, row.last_error) == (
        5,
        None,
        "RuntimeError: boom",
    )


async def test_new_row_after_give_up(sm: Sessionmaker, shop: Shop) -> None:
    product = await product_with_variant(sm, shop)
    given_up = await enqueue_row(sm, "product", product, "create")
    await execute(
        sm,
        "UPDATE reindex_outbox SET attempts = 5, last_error = 'RuntimeError: boom',"
        " locked_at = now() - interval '1 day' WHERE id = :id",
        id=given_up,
    )
    fresh = await enqueue_row(sm, "product", product, "update")

    assert await drain(sm, StubEmbeddingProvider(), config()) == [
        Outcome.DONE,
        Outcome.IDLE,
    ]

    assert (await outbox_row(sm, fresh)).done_at is not None
    old = await outbox_row(sm, given_up)
    assert (old.attempts, old.done_at, old.last_error) == (
        5,
        None,
        "RuntimeError: boom",
    )
    assert len(await chunks(sm, "product", product)) == 1


# --- brief test 22 (worker half): the daily cap; N8, N9, B3 ---------------------------


async def assert_blocked(
    sm: Sessionmaker, row_id: int, stub: StubEmbeddingProvider, message: str
) -> None:
    row = await outbox_row(sm, row_id)
    assert stub.calls == []
    assert (row.attempts, row.done_at, row.last_error) == (0, None, message)
    assert await chunk_count(sm) == 0


async def test_cap_reached_makes_no_call(sm: Sessionmaker, shop: Shop) -> None:
    await add_ledger(sm, "0.60000000")
    await add_ledger(sm, "0.40000000", provider="anthropic")  # every provider counts
    product = await product_with_variant(sm, shop)
    row_id = await enqueue_row(sm, "product", product, "create")
    stub = StubEmbeddingProvider()

    assert await process_next(sm, stub, config()) is Outcome.BLOCKED
    await assert_blocked(sm, row_id, stub, "daily cost cap reached")
    assert await process_next(sm, stub, config()) is Outcome.BLOCKED  # re-checked
    await assert_blocked(sm, row_id, stub, "daily cost cap reached")
    assert len(await ledger_rows(sm)) == 2

    assert await process_next(sm, stub, config(DAILY_COST_CAP_EUR="2")) is Outcome.DONE

    assert len(stub.calls) == 1
    row = await outbox_row(sm, row_id)
    assert (row.attempts, row.done_at is not None) == (0, True)


async def test_yesterday_does_not_count_toward_the_cap(
    sm: Sessionmaker, shop: Shop
) -> None:
    await add_ledger(
        sm,
        "5.00000000",
        created_at_sql="date_trunc('day', now(), 'UTC') - interval '1 second'",
    )
    await add_ledger(sm, "0.50000000")
    product = await product_with_variant(sm, shop)
    await enqueue_row(sm, "product", product, "create")
    stub = StubEmbeddingProvider()

    assert await process_next(sm, stub, config()) is Outcome.DONE
    assert len(stub.calls) == 1


async def test_no_call_needed_ignores_the_cap(sm: Sessionmaker, shop: Shop) -> None:
    product = await indexed_product(sm, shop, StubEmbeddingProvider())
    await add_ledger(sm, "1.00000000")
    unchanged = await enqueue_row(sm, "product", product, "update")
    missing = await enqueue_row(sm, "policy", MISSING_ID, "delete")
    stub = StubEmbeddingProvider()

    assert await drain(sm, stub, config()) == [Outcome.DONE, Outcome.DONE, Outcome.IDLE]

    assert stub.calls == []
    for row_id in (unchanged, missing):
        assert (await outbox_row(sm, row_id)).done_at is not None


async def test_ledger_row_after_call(sm: Sessionmaker, shop: Shop) -> None:
    product = await product_with_variant(sm, shop)
    await enqueue_row(sm, "product", product, "create")

    assert (
        await process_next(sm, StubEmbeddingProvider(total_tokens=1234), config())
        is Outcome.DONE
    )

    [row] = await ledger_rows(sm)
    assert row.user_id is None
    assert (row.provider, row.operation, row.units) == ("openai", "embedding", 1234)
    assert row.estimated_cost_eur == Decimal("0.00002468")
    assert row.created_at is not None


async def test_ledger_row_survives_a_later_failure(
    sm: Sessionmaker, shop: Shop
) -> None:
    product = await product_with_variant(sm, shop)
    row_id = await enqueue_row(sm, "product", product, "create")
    stub = StubEmbeddingProvider(total_tokens=500, dim=1535)

    assert await process_next(sm, stub, config()) is Outcome.FAILED

    [row] = await ledger_rows(sm)
    assert (row.units, row.estimated_cost_eur) == (500, Decimal("0.00001000"))
    assert (await outbox_row(sm, row_id)).attempts == 1


PRICE = "PRICE_OPENAI_EMBEDDING_EUR_PER_1M_TOKENS"
CAP = "DAILY_COST_CAP_EUR"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"EMBEDDING_MODEL": None}, "EMBEDDING_MODEL is not set"),
        ({"EMBEDDING_MODEL": ""}, "EMBEDDING_MODEL is not set"),
        ({"OPENAI_API_KEY": None}, "OPENAI_API_KEY is not set"),
        ({"OPENAI_API_KEY": ""}, "OPENAI_API_KEY is not set"),
        ({PRICE: None}, f"{PRICE} is not set"),
        ({PRICE: ""}, f"{PRICE} is not set"),
        ({PRICE: "not-a-number"}, f"{PRICE} is invalid"),
        ({PRICE: "0"}, f"{PRICE} is invalid"),
        ({PRICE: "-0.02"}, f"{PRICE} is invalid"),
        ({CAP: "not-a-number"}, f"{CAP} is invalid"),
        ({CAP: "-1"}, f"{CAP} is invalid"),
    ],
    ids=[
        "model unset",
        "model empty",
        "key unset",
        "key empty",
        "price unset",
        "price empty",
        "price not a number",
        "price zero",
        "price negative",
        "cap not a number",
        "cap negative",
    ],
)
async def test_missing_config_blocks_without_an_attempt(
    sm: Sessionmaker, shop: Shop, overrides: dict[str, str | None], message: str
) -> None:
    product = await product_with_variant(sm, shop)
    row_id = await enqueue_row(sm, "product", product, "create")
    stub = StubEmbeddingProvider()

    assert await process_next(sm, stub, config(**overrides)) is Outcome.BLOCKED

    await assert_blocked(sm, row_id, stub, message)
    assert await ledger_rows(sm) == []


# --- B4 + MT-002 in small: a second full reindex makes no paid call -------------------


async def test_second_full_reindex_makes_no_call(sm: Sessionmaker, shop: Shop) -> None:
    with_reviews = await product_with_variant(sm, shop)
    await make_review(sm, with_reviews)
    await make_review(sm, with_reviews, rating=3)
    await product_with_variant(sm, shop, name="Geacă")  # no reviews: no reviews chunk
    await make_policy(sm, shop, kind="shipping")
    await make_policy(sm, shop, kind="returns", title="Retur")
    async with sm() as session, session.begin():
        assert await enqueue_full_reindex(session) == 6
    first = StubEmbeddingProvider()

    await drain(sm, first, config())

    assert len(first.calls) == 5  # 2 products, 1 reviews source, 2 policies
    assert len(await ledger_rows(sm)) == 5
    assert await chunk_count(sm) == 5
    async with sm() as session, session.begin():
        assert await enqueue_full_reindex(session) == 6
    second = StubEmbeddingProvider()

    await drain(sm, second, config())

    assert second.calls == []
    assert len(await ledger_rows(sm)) == 5
    assert await chunk_count(sm) == 5
    assert all(row.done_at is not None for row in await outbox_rows(sm))


# --- the loop (N7, A9) ----------------------------------------------------------------


@pytest.fixture
def worker_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)


async def all_done(sm: Sessionmaker) -> bool:
    found = await outbox_rows(sm)
    return bool(found) and all(row.done_at is not None for row in found)


@pytest.mark.usefixtures("worker_env")
async def test_loop_drains_then_idles(sm: Sessionmaker, shop: Shop) -> None:
    product = await product_with_variant(sm, shop)
    await enqueue_row(sm, "product", product, "create")
    for offset in range(3):
        await enqueue_row(sm, "policy", MISSING_ID + offset, "delete")
    stop = asyncio.Event()
    stub = StubEmbeddingProvider()

    task = asyncio.create_task(run(sm, stub, stop))
    try:
        # Four rows well inside one idle wait (2 s): no wait between DONE rows.
        await wait_for(lambda: all_done(sm), 1.5, "all rows done back to back", task)
    finally:
        stop.set()
    # The stop event ends the idle wait at once.
    await asyncio.wait_for(task, 1.0)
    assert len(stub.calls) == 1


@pytest.mark.usefixtures("worker_env")
async def test_loop_polls_again_when_idle(sm: Sessionmaker) -> None:
    stop = asyncio.Event()
    task = asyncio.create_task(run(sm, StubEmbeddingProvider(), stop))
    try:
        await asyncio.sleep(0.3)
        assert not task.done()
        await enqueue_row(sm, "policy", MISSING_ID, "delete")
        await wait_for(lambda: all_done(sm), IDLE_SECONDS + 2, "the next poll", task)
    finally:
        stop.set()
    await asyncio.wait_for(task, 1.0)


@pytest.mark.usefixtures("worker_env")
async def test_missing_tables_are_retried(
    fresh_db_url: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Alembic's fileConfig (earlier tests) disables loggers that existed then.
    for name, logger in list(logging.root.manager.loggerDict.items()):
        if (name == "worker" or name.startswith("worker.")) and isinstance(
            logger, logging.Logger
        ):
            monkeypatch.setattr(logger, "disabled", False)
    caplog.set_level(logging.INFO)
    engine = create_engine(fresh_db_url)
    sm = create_sessionmaker(engine)
    stop = asyncio.Event()
    task = asyncio.create_task(run(sm, StubEmbeddingProvider(), stop))
    try:
        await wait_for(
            lambda: "reindex_outbox missing; waiting for migrations" in caplog.text,
            3,
            "the missing-table log line",
            task,
        )
        assert not task.done()
        monkeypatch.setenv("DATABASE_URL", fresh_db_url)
        await asyncio.to_thread(command.upgrade, alembic_config(), "head")
        await enqueue_row(sm, "policy", MISSING_ID, "delete")

        await wait_for(lambda: all_done(sm), IDLE_SECONDS + 3, "the retry", task)
    finally:
        stop.set()
        try:
            await asyncio.wait_for(task, 3.0)
        finally:
            await engine.dispose()
