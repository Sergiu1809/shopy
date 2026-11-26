"""Outbox rows from the admin routes (GH-13; PATTERN-010, PATTERN-017; brief test 20).

One `product` row in the request's own transaction exactly when `products.version`
moves; none otherwise. HTTP tests with PATTERN-015 (httpx + ASGITransport, the
rolled-back `session`); starting rows are inserted and committed through `session`
(a savepoint release), as in test_admin_products. Only rows newer than the test's
starting point are compared, by plain SQL.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, Product, ProductVariant, Store

Json = dict[str, Any]


@dataclass(frozen=True)
class Catalog:
    store_id: int
    category_id: int
    other_category_id: int


@pytest.fixture
async def catalog(session: AsyncSession) -> Catalog:
    store_id = await _insert_id(session, Store, name="Shopy", currency="RON")
    category_id = await _insert_id(
        session, Category, store_id=store_id, name="Îmbrăcăminte", slug="clothing"
    )
    other_category_id = await _insert_id(
        session, Category, store_id=store_id, name="Încălțăminte", slug="shoes"
    )
    await session.commit()
    return Catalog(store_id, category_id, other_category_id)


@pytest.fixture
async def admin(
    make_user: Callable[..., Any], auth_header: Callable[..., dict[str, str]]
) -> dict[str, str]:
    user = await make_user(email="admin@example.ro", role="admin")
    return auth_header(user)


async def _insert_id(session: AsyncSession, model: Any, **values: Any) -> int:
    result = await session.execute(insert(model).values(**values).returning(model.id))
    return int(result.scalar_one())


async def add_product(session: AsyncSession, catalog: Catalog, **values: Any) -> int:
    row = {
        "store_id": catalog.store_id,
        "category_id": catalog.category_id,
        "brand": "Nike",
        "name": "Hanorac",
        "description": "Hanorac cu glugă.",
        "attributes": {"material": "bumbac"},
        **values,
    }
    product_id = await _insert_id(session, Product, **row)
    await session.commit()
    return product_id


async def add_variant(
    session: AsyncSession, product_id: int, sku: str, **values: Any
) -> int:
    row = {
        "product_id": product_id,
        "sku": sku,
        "attributes": {"size": "M"},
        "price_minor": 24999,
        "stock": 5,
        **values,
    }
    variant_id = await _insert_id(session, ProductVariant, **row)
    await session.commit()
    return variant_id


async def last_outbox_id(session: AsyncSession) -> int:
    sql = text("SELECT coalesce(max(id), 0) FROM reindex_outbox")
    return int((await session.execute(sql)).scalar_one())


async def outbox_since(session: AsyncSession, after: int) -> list[tuple[Any, ...]]:
    """(source_type, source_id, reason) of every row newer than `after`, by id."""
    result = await session.execute(
        text(
            "SELECT source_type, source_id, reason FROM reindex_outbox"
            " WHERE id > :after ORDER BY id"
        ),
        {"after": after},
    )
    return [tuple(row) for row in result.all()]


def ok(response: Response, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json() if status != 204 else None


def product_body(catalog: Catalog, **values: Any) -> Json:
    return {
        "category_id": catalog.category_id,
        "brand": "Nike",
        "name": "Hanorac Nike Club",
        "description": "Hanorac cu glugă reglabilă.",
        "attributes": {"material": "bumbac"},
        **values,
    }


def variant_body(**values: Any) -> Json:
    return {
        "sku": "CLO-900-NEGRU-M",
        "attributes": {"size": "M", "color": "negru"},
        "price_minor": 24999,
        "stock": 17,
        **values,
    }


# --- a row exactly when products.version moves --------------------------------------


async def test_create_enqueues_the_new_product(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    before = await last_outbox_id(session)

    body = ok(
        await client.post("/admin/products", headers=admin, json=product_body(catalog)),
        201,
    )

    assert await outbox_since(session, before) == [("product", body["id"], "create")]


@pytest.mark.parametrize(
    "field", ["category_id", "brand", "name", "description", "attributes"]
)
async def test_update_enqueues_exactly_that_product(
    client: AsyncClient,
    session: AsyncSession,
    catalog: Catalog,
    admin: dict[str, str],
    field: str,
) -> None:
    """Brief test 20, API half: only the updated product, once."""
    other = await add_product(session, catalog, name="Altul")
    product = await add_product(session, catalog)
    new_value = {
        "category_id": catalog.other_category_id,
        "brand": "Adidas",
        "name": "Hanorac nou",
        "description": "Altă descriere.",
        "attributes": {"material": "lână"},
    }[field]
    before = await last_outbox_id(session)

    ok(
        await client.patch(
            f"/admin/products/{product}", headers=admin, json={field: new_value}
        )
    )

    rows = await outbox_since(session, before)
    assert rows == [("product", product, "update")]
    assert all(source_id != other for _, source_id, _ in rows)


async def test_each_change_enqueues_its_own_row(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    # N4: duplicates are allowed; one row per version bump.
    product = await add_product(session, catalog)
    before = await last_outbox_id(session)

    for name in ["Unu", "Doi"]:
        ok(
            await client.patch(
                f"/admin/products/{product}", headers=admin, json={"name": name}
            )
        )

    assert await outbox_since(session, before) == [
        ("product", product, "update"),
        ("product", product, "update"),
    ]


async def test_delete_enqueues_one_row(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    product = await add_product(session, catalog)
    await add_variant(session, product, "CLO-1-M")
    before = await last_outbox_id(session)

    ok(await client.delete(f"/admin/products/{product}", headers=admin), 204)

    assert await outbox_since(session, before) == [("product", product, "delete")]


async def test_variant_create_enqueues_its_product(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    product = await add_product(session, catalog)
    before = await last_outbox_id(session)

    ok(
        await client.post(
            f"/admin/products/{product}/variants", headers=admin, json=variant_body()
        ),
        201,
    )

    assert await outbox_since(session, before) == [("product", product, "update")]


async def test_variant_delete_enqueues_its_product(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    product = await add_product(session, catalog)
    variant = await add_variant(session, product, "CLO-1-M")
    before = await last_outbox_id(session)

    ok(
        await client.delete(
            f"/admin/products/{product}/variants/{variant}", headers=admin
        ),
        204,
    )

    assert await outbox_since(session, before) == [("product", product, "update")]


@pytest.mark.parametrize(
    "change",
    [
        {"sku": "CLO-1-L"},
        {"attributes": {"size": "L"}},
        {"sku": "CLO-1-XL", "price_minor": 100, "stock": 1},
    ],
    ids=["sku", "attributes", "sku with price and stock"],
)
async def test_variant_descriptive_change_enqueues_its_product(
    client: AsyncClient,
    session: AsyncSession,
    catalog: Catalog,
    admin: dict[str, str],
    change: Json,
) -> None:
    product = await add_product(session, catalog)
    variant = await add_variant(session, product, "CLO-1-M")
    before = await last_outbox_id(session)

    ok(
        await client.patch(
            f"/admin/products/{product}/variants/{variant}", headers=admin, json=change
        )
    )

    assert await outbox_since(session, before) == [("product", product, "update")]


async def test_new_row_is_pending(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    product = await add_product(session, catalog)
    before = await last_outbox_id(session)

    ok(
        await client.patch(
            f"/admin/products/{product}", headers=admin, json={"name": "X"}
        )
    )

    row = (
        await session.execute(
            text(
                "SELECT enqueued_at, locked_at, attempts, last_error, done_at"
                " FROM reindex_outbox WHERE id > :after"
            ),
            {"after": before},
        )
    ).one()
    assert row.enqueued_at is not None
    assert (row.locked_at, row.attempts, row.last_error, row.done_at) == (
        None,
        0,
        None,
        None,
    )


# --- no row without a version bump ---------------------------------------------------


@pytest.mark.parametrize(
    "change",
    [{"price_minor": 19999}, {"stock": 0}, {"price_minor": 1, "stock": 2}, {}],
    ids=["price", "stock", "price and stock", "empty"],
)
async def test_variant_change_without_a_version_bump_enqueues_nothing(
    client: AsyncClient,
    session: AsyncSession,
    catalog: Catalog,
    admin: dict[str, str],
    change: Json,
) -> None:
    product = await add_product(session, catalog)
    variant = await add_variant(session, product, "CLO-1-M")
    before = await last_outbox_id(session)

    ok(
        await client.patch(
            f"/admin/products/{product}/variants/{variant}", headers=admin, json=change
        )
    )

    assert await outbox_since(session, before) == []


@pytest.mark.parametrize("same", [False, True], ids=["empty", "same values"])
async def test_unchanged_product_patch_enqueues_nothing(
    client: AsyncClient,
    session: AsyncSession,
    catalog: Catalog,
    admin: dict[str, str],
    same: bool,
) -> None:
    product = await add_product(session, catalog)
    change: Json = {}
    if same:
        change = {
            "name": "Hanorac",
            "category_id": catalog.category_id,
            "attributes": {"material": "bumbac"},
        }
    before = await last_outbox_id(session)

    ok(await client.patch(f"/admin/products/{product}", headers=admin, json=change))

    assert await outbox_since(session, before) == []


async def test_same_variant_values_enqueue_nothing(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    product = await add_product(session, catalog)
    variant = await add_variant(session, product, "CLO-2-M", attributes={"size": "M"})
    before = await last_outbox_id(session)

    ok(
        await client.patch(
            f"/admin/products/{product}/variants/{variant}",
            headers=admin,
            json={"sku": "CLO-2-M", "attributes": {"size": "M"}, "price_minor": 24999},
        )
    )

    assert await outbox_since(session, before) == []


async def test_duplicate_sku_on_create_enqueues_nothing(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    owner = await add_product(session, catalog)
    await add_variant(session, owner, "CLO-7-M")
    product = await add_product(session, catalog, name="Altul")
    before = await last_outbox_id(session)

    response = await client.post(
        f"/admin/products/{product}/variants",
        headers=admin,
        json=variant_body(sku="CLO-7-M"),
    )

    assert response.status_code == 409, response.text
    assert await outbox_since(session, before) == []


async def test_patch_to_a_taken_sku_enqueues_nothing(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    product = await add_product(session, catalog)
    await add_variant(session, product, "CLO-8-M")
    variant = await add_variant(session, product, "CLO-8-L")
    before = await last_outbox_id(session)

    response = await client.patch(
        f"/admin/products/{product}/variants/{variant}",
        headers=admin,
        json={"sku": "CLO-8-M"},
    )

    assert response.status_code == 409, response.text
    assert await outbox_since(session, before) == []


async def test_unknown_product_enqueues_nothing(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    before = await last_outbox_id(session)

    response = await client.delete("/admin/products/9000000000", headers=admin)
    patched = await client.patch(
        "/admin/products/9000000000", headers=admin, json={"name": "X"}
    )

    assert (response.status_code, patched.status_code) == (404, 404)
    assert await outbox_since(session, before) == []
