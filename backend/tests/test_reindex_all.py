"""Full and single-source enqueue (GH-13 B4), and `python -m worker.reindex_all`.

`enqueue_full_reindex(session) -> int` and `enqueue(session, source_type, source_id,
reason)` join the caller's transaction (PATTERN-010). `worker.reindex_all.main()` is
what `make reindex` runs; it uses `asyncio.run`, so its test is synchronous.
"""

from __future__ import annotations

from collections import Counter

import pytest
from app.indexing.outbox import enqueue, enqueue_full_reindex

from tests.conftest import fetch
from tests.indexing_data import (
    Sessionmaker,
    make_policy,
    make_product,
    make_review,
    make_shop,
    outbox_rows,
)
from worker import reindex_all


class Abort(Exception):
    """Raised inside the caller's transaction to roll it back."""


async def test_full_reindex_enqueues_every_source(
    indexing_sessionmaker: Sessionmaker,
) -> None:
    sm = indexing_sessionmaker
    shop = await make_shop(sm)
    first = await make_product(sm, shop)
    second = await make_product(sm, shop, name="Fără recenzii")
    await make_review(sm, first)
    shipping = await make_policy(sm, shop, kind="shipping")
    returns = await make_policy(sm, shop, kind="returns", title="Retur")

    async with sm() as session, session.begin():
        count = await enqueue_full_reindex(session)

    rows = await outbox_rows(sm)
    assert count == 6 == len(rows)
    assert sorted((r.source_type, r.source_id) for r in rows) == sorted(
        [
            ("product", first),
            ("product", second),
            ("reviews", first),
            ("reviews", second),
            ("policy", shipping),
            ("policy", returns),
        ]
    )
    assert {r.reason for r in rows} == {"full"}
    assert all((r.attempts, r.done_at) == (0, None) for r in rows)


async def test_full_reindex_of_an_empty_store_enqueues_nothing(
    indexing_sessionmaker: Sessionmaker,
) -> None:
    async with indexing_sessionmaker() as session, session.begin():
        assert await enqueue_full_reindex(session) == 0

    assert await outbox_rows(indexing_sessionmaker) == []


async def test_full_reindex_joins_the_callers_transaction(
    indexing_sessionmaker: Sessionmaker,
) -> None:
    sm = indexing_sessionmaker
    shop = await make_shop(sm)
    await make_product(sm, shop)

    with pytest.raises(Abort):
        async with sm() as session, session.begin():
            assert await enqueue_full_reindex(session) == 2
            raise Abort

    assert await outbox_rows(sm) == []


@pytest.mark.parametrize(
    ("source_type", "reason"),
    [("product", "update"), ("reviews", "full"), ("policy", "delete")],
)
async def test_single_source_enqueue(
    indexing_sessionmaker: Sessionmaker, source_type: str, reason: str
) -> None:
    sm = indexing_sessionmaker

    async with sm() as session, session.begin():
        await enqueue(session, source_type, 42, reason)

    [row] = await outbox_rows(sm)
    assert (row.source_type, row.source_id, row.reason) == (source_type, 42, reason)
    assert (row.attempts, row.done_at) == (0, None)


async def test_single_source_enqueue_joins_the_callers_transaction(
    indexing_sessionmaker: Sessionmaker,
) -> None:
    sm = indexing_sessionmaker

    with pytest.raises(Abort):
        async with sm() as session, session.begin():
            await enqueue(session, "product", 42, "update")
            raise Abort

    assert await outbox_rows(sm) == []


def test_main_enqueues(
    indexing_db: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`make reindex`: a full reindex of a database seeded before P2a."""
    fetch(indexing_db, "INSERT INTO stores (name) VALUES ('Shopy')")
    fetch(
        indexing_db,
        "INSERT INTO categories (store_id, name, slug) VALUES (1, 'Rochii', 'rochii')",
    )
    for name in ["Unu", "Doi", "Trei"]:
        fetch(
            indexing_db,
            "INSERT INTO products (store_id, category_id, brand, name, description)"
            f" VALUES (1, 1, 'B', '{name}', 'D')",
        )
    fetch(
        indexing_db,
        "INSERT INTO store_policies (store_id, kind, title, body)"
        " VALUES (1, 'shipping', 'Livrare', 'În 2 zile.')",
    )
    monkeypatch.setenv("DATABASE_URL", indexing_db)

    reindex_all.main()

    assert "Reindex: enqueued 7 sources." in capsys.readouterr().out
    rows = fetch(indexing_db, "SELECT source_type, reason FROM reindex_outbox")
    assert Counter(r.source_type for r in rows) == {
        "product": 3,
        "reviews": 3,
        "policy": 1,
    }
    assert {r.reason for r in rows} == {"full"}
