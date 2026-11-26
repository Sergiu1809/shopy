"""Admin product and variant CRUD under /admin (GH-6, PLAN.md points 1-18).

HTTP tests with PATTERN-015: the app through httpx + ASGITransport, the rolled-back
`session`. Rows the tests start from are inserted with SQLAlchemy Core through
`session` and committed (a savepoint release, as `make_user` does), so an app-side
rollback (the 409 path) never takes them away. Every write is checked through the
API and, for versions, through plain SQL.

The 403 / 401 matrix for these routes is `test_admin_access.py` (unchanged); it
enumerates `app.routes`, so the new routes join it on their own.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, Product, ProductVariant, Store
from tests.conftest import assert_error

INT4_MAX = 2_147_483_647
UNKNOWN_ID = 9_000_000_000  # a valid bigint that no row has

PRODUCT_NOT_FOUND = "Product not found."  # A8
VARIANT_NOT_FOUND = "Variant not found."  # A8

PRODUCT_OUT_KEYS = {
    "id",
    "store_id",
    "category_id",
    "brand",
    "name",
    "description",
    "attributes",
    "rating_avg",
    "rating_count",
    "version",
    "updated_at",
}
PRODUCT_DETAIL_KEYS = PRODUCT_OUT_KEYS | {"variants"}
VARIANT_OUT_KEYS = {
    "id",
    "product_id",
    "sku",
    "attributes",
    "price_minor",
    "stock",
    "version",
}

Json = dict[str, Any]


# --- fixtures and helpers -------------------------------------------------------


@dataclass(frozen=True)
class Catalog:
    store_id: int  # the first (lowest-id) store: the one the server uses
    category_id: int
    other_category_id: int
    foreign_store_id: int
    foreign_category_id: int  # belongs to the second store


@pytest.fixture
async def catalog(session: AsyncSession) -> Catalog:
    """A store with two categories, then a second store with a category of its own."""
    store_id = await _insert_id(session, Store, name="Shopy", currency="RON")
    category_id = await _insert_id(
        session, Category, store_id=store_id, name="Îmbrăcăminte", slug="clothing"
    )
    other_category_id = await _insert_id(
        session, Category, store_id=store_id, name="Încălțăminte", slug="shoes"
    )
    foreign_store_id = await _insert_id(session, Store, name="Alt magazin")
    foreign_category_id = await _insert_id(
        session, Category, store_id=foreign_store_id, name="Altele", slug="other"
    )
    await session.commit()
    return Catalog(
        store_id, category_id, other_category_id, foreign_store_id, foreign_category_id
    )


@pytest.fixture
async def admin(
    make_user: Callable[..., Any], auth_header: Callable[..., dict[str, str]]
) -> dict[str, str]:
    """The Authorization header of an admin."""
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
    session: AsyncSession, product_id: int, sku: str | None = None, **values: Any
) -> int:
    row = {
        "product_id": product_id,
        "sku": sku or f"SKU-{secrets.token_hex(4).upper()}",
        "attributes": {"size": "M"},
        "price_minor": 24999,
        "stock": 5,
        **values,
    }
    variant_id = await _insert_id(session, ProductVariant, **row)
    await session.commit()
    return variant_id


async def product_version(session: AsyncSession, product_id: int) -> int:
    sql = text("SELECT version FROM products WHERE id = :id")
    return int((await session.execute(sql, {"id": product_id})).scalar_one())


async def variant_version(session: AsyncSession, variant_id: int) -> int:
    sql = text("SELECT version FROM product_variants WHERE id = :id")
    return int((await session.execute(sql, {"id": variant_id})).scalar_one())


async def count(session: AsyncSession, table: str, product_id: int) -> int:
    # `table` is one of a fixed set named in the tests, never input.
    sql = text(f"SELECT count(*) FROM {table} WHERE product_id = :id")
    return int((await session.execute(sql, {"id": product_id})).scalar_one())


def product_body(catalog: Catalog, **values: Any) -> Json:
    return {
        "category_id": catalog.category_id,
        "brand": "Nike",
        "name": "Hanorac Nike Club",
        "description": "Hanorac cu glugă reglabilă.",
        "attributes": {"material": "bumbac", "fit": "regular"},
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


def ok(response: Response, status: int = 200) -> Any:
    assert response.status_code == status, response.text
    return response.json() if status != 204 else None


def field_names(error: Json) -> list[str]:
    return [item["field"] for item in error["fields"]]


def assert_product_out(body: Json, *, detail: bool) -> None:
    assert set(body) == (PRODUCT_DETAIL_KEYS if detail else PRODUCT_OUT_KEYS)
    assert isinstance(body["version"], int)
    if detail:
        for variant in body["variants"]:
            assert_variant_out(variant)


def assert_variant_out(body: Json) -> None:
    assert set(body) == VARIANT_OUT_KEYS
    assert isinstance(body["version"], int)


# --- 1, 18: the routes exist; a variant under another product is 404 -------------

ROUTES = {
    ("get", "/admin/products"),
    ("post", "/admin/products"),
    ("get", "/admin/products/{product_id}"),
    ("patch", "/admin/products/{product_id}"),
    ("delete", "/admin/products/{product_id}"),
    ("get", "/admin/products/{product_id}/variants"),
    ("post", "/admin/products/{product_id}/variants"),
    ("patch", "/admin/products/{product_id}/variants/{variant_id}"),
    ("delete", "/admin/products/{product_id}/variants/{variant_id}"),
}


def _normalize(path: str) -> str:
    """Path parameter names are the builder's choice: compare the shape only."""
    parts = path.split("/")
    names = iter(["{product_id}", "{variant_id}"])
    return "/".join(next(names) if p.startswith("{") else p for p in parts)


async def test_openapi_lists_every_admin_product_route(client: AsyncClient) -> None:
    spec = ok(await client.get("/openapi.json"))

    found = {
        (method, _normalize(path))
        for path, operations in spec["paths"].items()
        if path.startswith("/admin/products")
        for method in operations
    }
    assert found == ROUTES


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
async def test_variant_of_another_product_is_404(
    client: AsyncClient,
    session: AsyncSession,
    catalog: Catalog,
    admin: dict[str, str],
    method: str,
) -> None:
    owner = await add_product(session, catalog)
    other = await add_product(session, catalog, name="Altul")
    variant = await add_variant(session, owner)
    body = {"stock": 3} if method == "PATCH" else None

    response = await client.request(
        method, f"/admin/products/{other}/variants/{variant}", headers=admin, json=body
    )

    error = assert_error(response, 404, "not_found")
    assert error["message"] == VARIANT_NOT_FOUND
    assert await variant_version(session, variant) == 1
    # The same request on the right product succeeds.
    right = await client.request(
        method, f"/admin/products/{owner}/variants/{variant}", headers=admin, json=body
    )
    assert right.status_code == (200 if method == "PATCH" else 204), right.text


# --- 2: 403 before body validation -------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/admin/products", {"bogus": 1}),
        ("PATCH", "/admin/products/1/variants/1", {"price_minor": -1}),
    ],
)
async def test_customer_with_an_invalid_body_gets_403(
    client: AsyncClient,
    make_user: Callable[..., Any],
    auth_header: Callable[..., dict[str, str]],
    method: str,
    path: str,
    body: Json,
) -> None:
    customer = await make_user()

    response = await client.request(
        method, path, headers=auth_header(customer), json=body
    )

    assert_error(response, 403, "forbidden")


# --- 3: writable fields only; store_id set by the server -------------------------


async def test_create_product_sets_the_store(
    client: AsyncClient, catalog: Catalog, admin: dict[str, str]
) -> None:
    body = ok(
        await client.post("/admin/products", headers=admin, json=product_body(catalog)),
        201,
    )

    assert body["store_id"] == catalog.store_id


READ_ONLY_PRODUCT = {
    "store_id": 1,
    "rating_avg": "4.50",
    "rating_count": 3,
    "version": 9,
    "content_hash": "abc",
    "id": 1,
}


@pytest.mark.parametrize("field", sorted(READ_ONLY_PRODUCT))
@pytest.mark.parametrize("method", ["POST", "PATCH"])
async def test_read_only_product_field_is_rejected(
    client: AsyncClient,
    session: AsyncSession,
    catalog: Catalog,
    admin: dict[str, str],
    method: str,
    field: str,
) -> None:
    product = await add_product(session, catalog)
    extra = {field: READ_ONLY_PRODUCT[field]}
    if method == "POST":
        response = await client.post(
            "/admin/products", headers=admin, json=product_body(catalog, **extra)
        )
    else:
        response = await client.patch(
            f"/admin/products/{product}", headers=admin, json=extra
        )

    error = assert_error(response, 422, "validation_error", fields=True)
    assert field_names(error) == ["body"]
    assert await product_version(session, product) == 1


READ_ONLY_VARIANT = {"version": 9, "product_id": 1, "id": 1}


@pytest.mark.parametrize("field", sorted(READ_ONLY_VARIANT))
@pytest.mark.parametrize("method", ["POST", "PATCH"])
async def test_read_only_variant_field_is_rejected(
    client: AsyncClient,
    session: AsyncSession,
    catalog: Catalog,
    admin: dict[str, str],
    method: str,
    field: str,
) -> None:
    product = await add_product(session, catalog)
    variant = await add_variant(session, product)
    extra = {field: READ_ONLY_VARIANT[field]}
    if method == "POST":
        response = await client.post(
            f"/admin/products/{product}/variants",
            headers=admin,
            json=variant_body(**extra),
        )
    else:
        response = await client.patch(
            f"/admin/products/{product}/variants/{variant}", headers=admin, json=extra
        )

    error = assert_error(response, 422, "validation_error", fields=True)
    assert field_names(error) == ["body"]
    assert await variant_version(session, variant) == 1


# --- 4: products.version ------------------------------------------------------------


@pytest.mark.parametrize(
    "field", ["category_id", "brand", "name", "description", "attributes"]
)
async def test_product_patch_bumps_product_version(
    client: AsyncClient,
    session: AsyncSession,
    catalog: Catalog,
    admin: dict[str, str],
    field: str,
) -> None:
    product = await add_product(session, catalog)
    new_value = {
        "category_id": catalog.other_category_id,
        "brand": "Adidas",
        "name": "Hanorac nou",
        "description": "Altă descriere.",
        "attributes": {"material": "lână"},
    }[field]

    body = ok(
        await client.patch(
            f"/admin/products/{product}", headers=admin, json={field: new_value}
        )
    )

    assert_product_out(body, detail=True)
    assert body[field] == new_value
    assert body["version"] == 2
    assert await product_version(session, product) == 2


async def test_variant_create_bumps_product_version(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    product = await add_product(session, catalog)

    body = ok(
        await client.post(
            f"/admin/products/{product}/variants", headers=admin, json=variant_body()
        ),
        201,
    )

    assert_variant_out(body)
    assert body["product_id"] == product
    assert body["version"] == 1
    assert body["sku"] == "CLO-900-NEGRU-M"
    assert body["price_minor"] == 24999
    assert await product_version(session, product) == 2


async def test_variant_delete_bumps_product_version(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    product = await add_product(session, catalog)
    await add_variant(session, product)
    variant = await add_variant(session, product)

    response = await client.delete(
        f"/admin/products/{product}/variants/{variant}", headers=admin
    )

    assert response.status_code == 204, response.text
    assert response.content == b""
    assert await count(session, "product_variants", product) == 1
    assert await product_version(session, product) == 2


async def test_variant_sku_change_bumps_product_not_variant(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    product = await add_product(session, catalog)
    variant = await add_variant(session, product, sku="CLO-1-M")

    body = ok(
        await client.patch(
            f"/admin/products/{product}/variants/{variant}",
            headers=admin,
            json={"sku": "CLO-1-L"},
        )
    )

    assert_variant_out(body)
    assert body["sku"] == "CLO-1-L"
    assert body["version"] == 1
    assert await variant_version(session, variant) == 1
    assert await product_version(session, product) == 2


async def test_variant_attributes_change_bumps_product_not_variant(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    product = await add_product(session, catalog)
    variant = await add_variant(session, product)

    body = ok(
        await client.patch(
            f"/admin/products/{product}/variants/{variant}",
            headers=admin,
            json={"attributes": {"size": "L"}},
        )
    )

    assert body["attributes"] == {"size": "L"}
    assert body["version"] == 1
    assert await variant_version(session, variant) == 1
    assert await product_version(session, product) == 2


@pytest.mark.parametrize(
    "change", [{"price_minor": 19999}, {"stock": 0}, {"price_minor": 1, "stock": 2}]
)
async def test_price_or_stock_change_leaves_product_version(
    client: AsyncClient,
    session: AsyncSession,
    catalog: Catalog,
    admin: dict[str, str],
    change: Json,
) -> None:
    product = await add_product(session, catalog)
    variant = await add_variant(session, product)

    body = ok(
        await client.patch(
            f"/admin/products/{product}/variants/{variant}", headers=admin, json=change
        )
    )

    assert body["version"] == 2
    assert await product_version(session, product) == 1


# --- 5: product_variants.version ---------------------------------------------------


async def test_price_change_bumps_variant_version(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    product = await add_product(session, catalog)
    variant = await add_variant(session, product, price_minor=24999)

    body = ok(
        await client.patch(
            f"/admin/products/{product}/variants/{variant}",
            headers=admin,
            json={"price_minor": 19999},
        )
    )

    assert_variant_out(body)
    assert body["price_minor"] == 19999
    assert body["version"] == 2
    assert await variant_version(session, variant) == 2


async def test_stock_change_bumps_variant_version(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    product = await add_product(session, catalog)
    variant = await add_variant(session, product, stock=5)

    body = ok(
        await client.patch(
            f"/admin/products/{product}/variants/{variant}",
            headers=admin,
            json={"stock": 4},
        )
    )

    assert body["stock"] == 4
    assert body["version"] == 2
    assert await variant_version(session, variant) == 2


# --- 6: only on a real change; empty PATCH; atomic increment ------------------------


async def test_empty_patch_changes_nothing(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    product = await add_product(session, catalog)
    variant = await add_variant(session, product)
    before = ok(await client.get(f"/admin/products/{product}", headers=admin))

    after = ok(await client.patch(f"/admin/products/{product}", headers=admin, json={}))
    variant_after = ok(
        await client.patch(
            f"/admin/products/{product}/variants/{variant}", headers=admin, json={}
        )
    )

    assert after == before
    assert after["version"] == 1
    assert after["updated_at"] == before["updated_at"]
    assert variant_after == before["variants"][0]
    assert variant_after["version"] == 1
    assert await product_version(session, product) == 1
    assert await variant_version(session, variant) == 1


async def test_same_values_change_nothing(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    product = await add_product(
        session, catalog, name="Hanorac", attributes={"a": "x", "b": 2, "c": ["p"]}
    )
    variant = await add_variant(
        session, product, sku="CLO-2-M", price_minor=500, attributes={"size": "M"}
    )

    product_body_ = ok(
        await client.patch(
            f"/admin/products/{product}",
            headers=admin,
            json={
                "name": "Hanorac",
                "category_id": catalog.category_id,
                "attributes": {"c": ["p"], "b": 2, "a": "x"},
            },
        )
    )
    variant_body_ = ok(
        await client.patch(
            f"/admin/products/{product}/variants/{variant}",
            headers=admin,
            json={"price_minor": 500, "sku": "CLO-2-M", "attributes": {"size": "M"}},
        )
    )

    assert product_body_["version"] == 1
    assert variant_body_["version"] == 1
    assert await product_version(session, product) == 1
    assert await variant_version(session, variant) == 1


async def test_one_becoming_true_is_a_change(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    """Python says `1 == True`; JSONB does not, so this is a real change."""
    product = await add_product(session, catalog, attributes={"k": 1})

    body = ok(
        await client.patch(
            f"/admin/products/{product}",
            headers=admin,
            json={"attributes": {"k": True}},
        )
    )

    assert body["attributes"] == {"k": True}
    assert body["version"] == 2


async def test_version_is_incremented_in_sql(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    """The new version is the row's version + 1, whatever the app read before."""
    product = await add_product(session, catalog)
    variant = await add_variant(session, product)
    ok(await client.get(f"/admin/products/{product}", headers=admin))
    await session.execute(
        text("UPDATE products SET version = 7 WHERE id = :id"), {"id": product}
    )
    await session.execute(
        text("UPDATE product_variants SET version = 4 WHERE id = :id"), {"id": variant}
    )

    product_out = ok(
        await client.patch(
            f"/admin/products/{product}", headers=admin, json={"name": "Nou"}
        )
    )
    variant_out = ok(
        await client.patch(
            f"/admin/products/{product}/variants/{variant}",
            headers=admin,
            json={"stock": 1},
        )
    )

    assert product_out["version"] == 8
    assert variant_out["version"] == 5
    assert await product_version(session, product) == 8
    assert await variant_version(session, variant) == 5


# --- 7: attributes -------------------------------------------------------------------


async def test_attributes_are_replaced_not_merged(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    product = await add_product(session, catalog, attributes={"a": "x", "b": "y"})
    variant = await add_variant(
        session, product, attributes={"size": "M", "color": "negru"}
    )

    product_out = ok(
        await client.patch(
            f"/admin/products/{product}",
            headers=admin,
            json={"attributes": {"c": "z"}},
        )
    )
    variant_out = ok(
        await client.patch(
            f"/admin/products/{product}/variants/{variant}",
            headers=admin,
            json={"attributes": {"size": "L"}},
        )
    )

    assert product_out["attributes"] == {"c": "z"}
    assert variant_out["attributes"] == {"size": "L"}
    detail = ok(await client.get(f"/admin/products/{product}", headers=admin))
    assert detail["attributes"] == {"c": "z"}
    assert detail["variants"][0]["attributes"] == {"size": "L"}


async def test_every_seed_attribute_value_shape_is_accepted(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    product = await add_product(session, catalog)
    attributes = {"s": "text", "n": 3, "b": False, "l": ["a", "b"], "e": []}

    body = ok(
        await client.patch(
            f"/admin/products/{product}",
            headers=admin,
            json={"attributes": attributes},
        )
    )

    assert body["attributes"] == attributes


BAD_KEY = "Xbadkeymarker"  # fails ^[a-z][a-z0-9_]*$; must never be echoed

BAD_PRODUCT_ATTRIBUTES: dict[str, Json] = {
    "bad key": {BAD_KEY: "x"},
    "float": {"weight": 1.5},
    "nested object": {"size": {"eu": "42"}},
    "list of ints": {"sizes": [40, 41]},
    "null value": {"color": None},
}


@pytest.mark.parametrize("kind", sorted(BAD_PRODUCT_ATTRIBUTES))
@pytest.mark.parametrize("method", ["POST", "PATCH"])
async def test_bad_product_attributes_are_422(
    client: AsyncClient,
    session: AsyncSession,
    catalog: Catalog,
    admin: dict[str, str],
    method: str,
    kind: str,
) -> None:
    attributes = BAD_PRODUCT_ATTRIBUTES[kind]
    product = await add_product(session, catalog)
    if method == "POST":
        response = await client.post(
            "/admin/products",
            headers=admin,
            json=product_body(catalog, attributes=attributes),
        )
    else:
        response = await client.patch(
            f"/admin/products/{product}",
            headers=admin,
            json={"attributes": attributes},
        )

    error = assert_error(response, 422, "validation_error", fields=True)
    assert field_names(error) == ["attributes"]
    assert BAD_KEY not in response.text
    for key in attributes:
        assert key not in response.text


BAD_VARIANT_ATTRIBUTES: dict[str, Json] = {
    "int": {"size": 42},
    "bool": {"size": True},
    "list": {"size": ["M"]},
    "empty string": {"size": ""},
    "blank string": {"size": "   "},
    "bad key": {BAD_KEY: "M"},
}


@pytest.mark.parametrize("kind", sorted(BAD_VARIANT_ATTRIBUTES))
@pytest.mark.parametrize("method", ["POST", "PATCH"])
async def test_bad_variant_attributes_are_422(
    client: AsyncClient,
    session: AsyncSession,
    catalog: Catalog,
    admin: dict[str, str],
    method: str,
    kind: str,
) -> None:
    attributes = BAD_VARIANT_ATTRIBUTES[kind]
    product = await add_product(session, catalog)
    variant = await add_variant(session, product)
    if method == "POST":
        response = await client.post(
            f"/admin/products/{product}/variants",
            headers=admin,
            json=variant_body(attributes=attributes),
        )
    else:
        response = await client.patch(
            f"/admin/products/{product}/variants/{variant}",
            headers=admin,
            json={"attributes": attributes},
        )

    error = assert_error(response, 422, "validation_error", fields=True)
    assert field_names(error) == ["attributes"]
    assert BAD_KEY not in response.text


# --- 8: price and stock ---------------------------------------------------------------

BAD_NUMBERS: dict[str, Any] = {
    "negative": -1,
    "above int4": INT4_MAX + 1,
    "float": 1.5,
    "whole float": 100.0,
    "string": "100",
    "bool": True,
    "null": None,
}


@pytest.mark.parametrize("kind", sorted(BAD_NUMBERS))
@pytest.mark.parametrize("field", ["price_minor", "stock"])
@pytest.mark.parametrize("method", ["POST", "PATCH"])
async def test_bad_price_or_stock_is_422(
    client: AsyncClient,
    session: AsyncSession,
    catalog: Catalog,
    admin: dict[str, str],
    method: str,
    field: str,
    kind: str,
) -> None:
    value = BAD_NUMBERS[kind]
    product = await add_product(session, catalog)
    variant = await add_variant(session, product)
    if method == "POST":
        response = await client.post(
            f"/admin/products/{product}/variants",
            headers=admin,
            json=variant_body(**{field: value}),
        )
    else:
        response = await client.patch(
            f"/admin/products/{product}/variants/{variant}",
            headers=admin,
            json={field: value},
        )

    error = assert_error(response, 422, "validation_error", fields=True)
    assert field in field_names(error)
    assert set(field_names(error)) == {field}
    assert await variant_version(session, variant) == 1


@pytest.mark.parametrize("value", [0, INT4_MAX])
async def test_price_and_stock_bounds_are_accepted(
    client: AsyncClient,
    session: AsyncSession,
    catalog: Catalog,
    admin: dict[str, str],
    value: int,
) -> None:
    product = await add_product(session, catalog)

    created = ok(
        await client.post(
            f"/admin/products/{product}/variants",
            headers=admin,
            json=variant_body(price_minor=value, stock=value),
        ),
        201,
    )
    patched = ok(
        await client.patch(
            f"/admin/products/{product}/variants/{created['id']}",
            headers=admin,
            json={"price_minor": INT4_MAX - value, "stock": INT4_MAX - value},
        )
    )

    assert (created["price_minor"], created["stock"]) == (value, value)
    assert (patched["price_minor"], patched["stock"]) == (INT4_MAX - value,) * 2


# --- 9: SKU ---------------------------------------------------------------------------


@pytest.mark.parametrize("sku", ["clo-1-m", "CLO_1_M", "CLO--1", "-CLO", "CLO 1", ""])
@pytest.mark.parametrize("method", ["POST", "PATCH"])
async def test_badly_formed_sku_is_422(
    client: AsyncClient,
    session: AsyncSession,
    catalog: Catalog,
    admin: dict[str, str],
    method: str,
    sku: str,
) -> None:
    product = await add_product(session, catalog)
    variant = await add_variant(session, product)
    if method == "POST":
        response = await client.post(
            f"/admin/products/{product}/variants",
            headers=admin,
            json=variant_body(sku=sku),
        )
    else:
        response = await client.patch(
            f"/admin/products/{product}/variants/{variant}",
            headers=admin,
            json={"sku": sku},
        )

    error = assert_error(response, 422, "validation_error", fields=True)
    assert field_names(error) == ["sku"]


async def test_duplicate_sku_on_create_is_409(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    owner = await add_product(session, catalog)
    await add_variant(session, owner, sku="CLO-7-M")
    product = await add_product(session, catalog, name="Altul")

    response = await client.post(
        f"/admin/products/{product}/variants",
        headers=admin,
        json=variant_body(sku="CLO-7-M"),
    )

    error = assert_error(response, 409, "sku_taken")
    assert error["message"] == "This SKU is already in use."
    assert await count(session, "product_variants", product) == 0
    assert await product_version(session, product) == 1


async def test_patch_to_another_variants_sku_is_409(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    product = await add_product(session, catalog)
    await add_variant(session, product, sku="CLO-8-M")
    variant = await add_variant(session, product, sku="CLO-8-L")

    response = await client.patch(
        f"/admin/products/{product}/variants/{variant}",
        headers=admin,
        json={"sku": "CLO-8-M"},
    )

    assert_error(response, 409, "sku_taken")
    detail = ok(await client.get(f"/admin/products/{product}", headers=admin))
    assert [v["sku"] for v in detail["variants"]] == ["CLO-8-M", "CLO-8-L"]
    assert detail["version"] == 1


async def test_patch_to_its_own_sku_is_a_no_op(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    product = await add_product(session, catalog)
    variant = await add_variant(session, product, sku="CLO-9-M")

    body = ok(
        await client.patch(
            f"/admin/products/{product}/variants/{variant}",
            headers=admin,
            json={"sku": "CLO-9-M"},
        )
    )

    assert body["sku"] == "CLO-9-M"
    assert body["version"] == 1
    assert await product_version(session, product) == 1


# --- 10: unknown category, unknown path IDs ---------------------------------------


@pytest.mark.parametrize("which", ["missing", "other store"])
@pytest.mark.parametrize("method", ["POST", "PATCH"])
async def test_unknown_or_foreign_category_is_422(
    client: AsyncClient,
    session: AsyncSession,
    catalog: Catalog,
    admin: dict[str, str],
    method: str,
    which: str,
) -> None:
    category_id = UNKNOWN_ID if which == "missing" else catalog.foreign_category_id
    product = await add_product(session, catalog)
    if method == "POST":
        response = await client.post(
            "/admin/products",
            headers=admin,
            json=product_body(catalog, category_id=category_id),
        )
    else:
        response = await client.patch(
            f"/admin/products/{product}",
            headers=admin,
            json={"category_id": category_id},
        )

    error = assert_error(response, 422, "validation_error", fields=True)
    assert field_names(error) == ["category_id"]
    assert str(UNKNOWN_ID) not in response.text
    assert await product_version(session, product) == 1
    total = await session.execute(text("SELECT count(*) FROM products"))
    assert total.scalar_one() == 1


UNKNOWN_PRODUCT: list[tuple[str, str, Json | None]] = [
    ("GET", "/admin/products/{u}", None),
    ("PATCH", "/admin/products/{u}", {}),
    ("DELETE", "/admin/products/{u}", None),
    ("GET", "/admin/products/{u}/variants", None),
    ("POST", "/admin/products/{u}/variants", variant_body()),
    ("PATCH", "/admin/products/{u}/variants/{v}", {}),
    ("DELETE", "/admin/products/{u}/variants/{v}", None),
]
UNKNOWN_VARIANT: list[tuple[str, str, Json | None]] = [
    ("PATCH", "/admin/products/{p}/variants/{u}", {}),
    ("DELETE", "/admin/products/{p}/variants/{u}", None),
]


@pytest.mark.parametrize(
    ("method", "template", "body", "message"),
    [(*route, PRODUCT_NOT_FOUND) for route in UNKNOWN_PRODUCT]
    + [(*route, VARIANT_NOT_FOUND) for route in UNKNOWN_VARIANT],
)
async def test_unknown_id_is_404(
    client: AsyncClient,
    session: AsyncSession,
    catalog: Catalog,
    admin: dict[str, str],
    method: str,
    template: str,
    body: Json | None,
    message: str,
) -> None:
    product = await add_product(session, catalog)
    variant = await add_variant(session, product)
    path = template.format(u=UNKNOWN_ID, p=product, v=variant)

    response = await client.request(method, path, headers=admin, json=body)

    error = assert_error(response, 404, "not_found")
    assert error["message"] == message
    assert str(UNKNOWN_ID) not in response.text


@pytest.mark.parametrize("bad_id", ["0", "-1", str(2**63), "abc"])
async def test_malformed_path_id_is_422(
    client: AsyncClient, catalog: Catalog, admin: dict[str, str], bad_id: str
) -> None:
    """A4: outside 1…2^63−1 is a malformed ID (422), never a DB overflow (500)."""
    response = await client.get(f"/admin/products/{bad_id}", headers=admin)

    assert_error(response, 422, "validation_error", fields=True)


# --- 11: text fields --------------------------------------------------------------


@pytest.mark.parametrize("field", ["brand", "name", "description"])
@pytest.mark.parametrize("value", ["", "   "])
@pytest.mark.parametrize("method", ["POST", "PATCH"])
async def test_blank_text_is_422(
    client: AsyncClient,
    session: AsyncSession,
    catalog: Catalog,
    admin: dict[str, str],
    method: str,
    value: str,
    field: str,
) -> None:
    product = await add_product(session, catalog)
    if method == "POST":
        response = await client.post(
            "/admin/products",
            headers=admin,
            json=product_body(catalog, **{field: value}),
        )
    else:
        response = await client.patch(
            f"/admin/products/{product}", headers=admin, json={field: value}
        )

    error = assert_error(response, 422, "validation_error", fields=True)
    assert field_names(error) == [field]
    assert await product_version(session, product) == 1


@pytest.mark.parametrize(
    "field", ["brand", "name", "description", "category_id", "attributes"]
)
async def test_null_on_product_patch_is_422(
    client: AsyncClient,
    session: AsyncSession,
    catalog: Catalog,
    admin: dict[str, str],
    field: str,
) -> None:
    """The columns are NOT NULL: an explicit null is rejected under the field."""
    product = await add_product(session, catalog)

    response = await client.patch(
        f"/admin/products/{product}", headers=admin, json={field: None}
    )

    error = assert_error(response, 422, "validation_error", fields=True)
    assert field_names(error) == [field]


async def test_text_is_stored_trimmed(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    created = ok(
        await client.post(
            "/admin/products",
            headers=admin,
            json=product_body(catalog, brand="  Nike  ", name="\tHanorac \n"),
        ),
        201,
    )
    patched = ok(
        await client.patch(
            f"/admin/products/{created['id']}",
            headers=admin,
            json={"description": "  Descriere.  "},
        )
    )

    assert (created["brand"], created["name"]) == ("Nike", "Hanorac")
    assert patched["description"] == "Descriere."
    row = (
        await session.execute(
            text("SELECT brand, name, description FROM products WHERE id = :id"),
            {"id": created["id"]},
        )
    ).one()
    assert tuple(row) == ("Nike", "Hanorac", "Descriere.")


async def test_long_description_is_accepted(
    client: AsyncClient, catalog: Catalog, admin: dict[str, str]
) -> None:
    description = "Descriere lungă. " * 1200  # about 20 000 characters

    body = ok(
        await client.post(
            "/admin/products",
            headers=admin,
            json=product_body(catalog, description=description),
        ),
        201,
    )

    assert body["description"] == description.strip()


# --- 12: the product list -----------------------------------------------------------


async def test_list_pages_by_id(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    ids = [await add_product(session, catalog, name=f"P{n}") for n in range(3)]
    await add_variant(session, ids[1])

    body = ok(await client.get("/admin/products?limit=2&offset=1", headers=admin))

    assert set(body) == {"items", "total"}
    assert body["total"] == 3
    assert [item["id"] for item in body["items"]] == ids[1:]
    for item in body["items"]:
        assert_product_out(item, detail=False)
        assert "variants" not in item
        assert "content_hash" not in item


async def test_list_default_limit_is_50(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    rows = [
        {
            "store_id": catalog.store_id,
            "category_id": catalog.category_id,
            "brand": "B",
            "name": f"P{n}",
            "description": "D",
            "attributes": {},
        }
        for n in range(51)
    ]
    await session.execute(insert(Product), rows)
    await session.commit()
    first_ids = list(
        (await session.execute(select(Product.id).order_by(Product.id).limit(50)))
        .scalars()
        .all()
    )

    body = ok(await client.get("/admin/products", headers=admin))
    hundred = ok(await client.get("/admin/products?limit=100", headers=admin))

    assert body["total"] == 51
    assert [item["id"] for item in body["items"]] == first_ids
    assert len(hundred["items"]) == 51


@pytest.mark.parametrize(
    "query", ["limit=0", "limit=101", "offset=-1", "limit=abc", f"offset={2**63}"]
)
async def test_bad_paging_is_422(
    client: AsyncClient, catalog: Catalog, admin: dict[str, str], query: str
) -> None:
    response = await client.get(f"/admin/products?{query}", headers=admin)

    error = assert_error(response, 422, "validation_error", fields=True)
    assert field_names(error) == [f"query.{query.split('=')[0]}"]


# --- 13: detail ---------------------------------------------------------------------


async def test_detail_includes_variants_in_id_order(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    product = await add_product(session, catalog, attributes={"material": "bumbac"})
    variants = [
        await add_variant(
            session, product, sku=f"CLO-3-{size}", attributes={"size": size}
        )
        for size in ("S", "M", "L")
    ]
    other = await add_product(session, catalog, name="Altul")
    await add_variant(session, other)

    body = ok(await client.get(f"/admin/products/{product}", headers=admin))
    listed = ok(await client.get(f"/admin/products/{product}/variants", headers=admin))

    assert_product_out(body, detail=True)
    assert "content_hash" not in body
    assert body["id"] == product
    assert body["store_id"] == catalog.store_id
    assert body["category_id"] == catalog.category_id
    assert body["attributes"] == {"material": "bumbac"}
    assert [v["id"] for v in body["variants"]] == variants
    assert [v["sku"] for v in body["variants"]] == ["CLO-3-S", "CLO-3-M", "CLO-3-L"]
    assert body["variants"][0] == {
        "id": variants[0],
        "product_id": product,
        "sku": "CLO-3-S",
        "attributes": {"size": "S"},
        "price_minor": 24999,
        "stock": 5,
        "version": 1,
    }
    assert listed == body["variants"]  # A2: a plain array, ordered by id


async def test_rating_avg_is_a_string_or_null(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    rated = await add_product(session, catalog)
    await session.execute(
        text("UPDATE products SET rating_avg = 4.3, rating_count = 7 WHERE id = :id"),
        {"id": rated},
    )
    unrated = await add_product(session, catalog, name="Nou")

    rated_out = ok(await client.get(f"/admin/products/{rated}", headers=admin))
    unrated_out = ok(await client.get(f"/admin/products/{unrated}", headers=admin))
    listed = ok(await client.get("/admin/products", headers=admin))

    assert (rated_out["rating_avg"], rated_out["rating_count"]) == ("4.30", 7)
    assert (unrated_out["rating_avg"], unrated_out["rating_count"]) == (None, 0)
    assert [item["rating_avg"] for item in listed["items"]] == ["4.30", None]


# --- 14: create a product -----------------------------------------------------------


async def test_create_product_returns_201_without_variants(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    sent = product_body(catalog)

    body = ok(await client.post("/admin/products", headers=admin, json=sent), 201)

    assert_product_out(body, detail=True)
    assert body["variants"] == []
    assert body["version"] == 1
    assert body["rating_count"] == 0
    assert body["rating_avg"] is None
    for field in ("category_id", "brand", "name", "description", "attributes"):
        assert body[field] == sent[field]
    fetched = ok(await client.get(f"/admin/products/{body['id']}", headers=admin))
    assert fetched == body
    assert await count(session, "product_variants", body["id"]) == 0


@pytest.mark.parametrize(
    "missing", ["category_id", "brand", "name", "description", "attributes"]
)
async def test_create_product_needs_every_field(
    client: AsyncClient, catalog: Catalog, admin: dict[str, str], missing: str
) -> None:
    body = product_body(catalog)
    del body[missing]

    response = await client.post("/admin/products", headers=admin, json=body)

    error = assert_error(response, 422, "validation_error", fields=True)
    assert field_names(error) == [missing]


@pytest.mark.parametrize("missing", ["sku", "attributes", "price_minor", "stock"])
async def test_create_variant_needs_every_field(
    client: AsyncClient,
    session: AsyncSession,
    catalog: Catalog,
    admin: dict[str, str],
    missing: str,
) -> None:
    """A3: attributes is required too; `{}` is a valid value."""
    product = await add_product(session, catalog)
    body = variant_body()
    del body[missing]

    response = await client.post(
        f"/admin/products/{product}/variants", headers=admin, json=body
    )

    error = assert_error(response, 422, "validation_error", fields=True)
    assert field_names(error) == [missing]


async def test_empty_attributes_are_valid(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    product = ok(
        await client.post(
            "/admin/products", headers=admin, json=product_body(catalog, attributes={})
        ),
        201,
    )
    variant = ok(
        await client.post(
            f"/admin/products/{product['id']}/variants",
            headers=admin,
            json=variant_body(attributes={}),
        ),
        201,
    )

    assert product["attributes"] == {}
    assert variant["attributes"] == {}


# --- 15: delete ---------------------------------------------------------------------


async def test_delete_product_cascades(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    product = await add_product(session, catalog)
    kept = await add_product(session, catalog, name="Rămâne")
    await add_variant(session, product)
    await add_variant(session, kept)
    for target in (product, kept):
        await session.execute(
            text(
                "INSERT INTO product_images (product_id, storage_key, position) "
                "VALUES (:id, 'img/1.jpg', 0)"
            ),
            {"id": target},
        )
        await session.execute(
            text(
                "INSERT INTO reviews"
                " (product_id, author_display_name, rating, title, body)"
                " VALUES (:id, 'Ana', 5, 'Bun', 'Foarte bun.')"
            ),
            {"id": target},
        )
    await session.commit()

    response = await client.delete(f"/admin/products/{product}", headers=admin)

    assert response.status_code == 204, response.text
    assert response.content == b""
    for table in ("product_variants", "product_images", "reviews"):
        assert await count(session, table, product) == 0, table
        assert await count(session, table, kept) == 1, table
    error = assert_error(
        await client.get(f"/admin/products/{product}", headers=admin), 404, "not_found"
    )
    assert error["message"] == PRODUCT_NOT_FOUND
    ok(await client.get(f"/admin/products/{kept}", headers=admin))


async def test_last_variant_can_be_deleted(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    product = await add_product(session, catalog)
    variant = await add_variant(session, product)

    response = await client.delete(
        f"/admin/products/{product}/variants/{variant}", headers=admin
    )

    assert response.status_code == 204, response.text
    listed = ok(await client.get(f"/admin/products/{product}/variants", headers=admin))
    assert listed == []
    detail = ok(await client.get(f"/admin/products/{product}", headers=admin))
    assert detail["variants"] == []
    assert detail["version"] == 2


# --- 16: the input is never echoed -----------------------------------------------


async def test_errors_never_echo_input(
    client: AsyncClient, session: AsyncSession, catalog: Catalog, admin: dict[str, str]
) -> None:
    product = await add_product(session, catalog)
    unknown_field = "zzunknownfieldmarker"
    bad_sku = "lowercase-sku-marker"

    responses = [
        await client.post(
            f"/admin/products/{product}/variants",
            headers=admin,
            json=variant_body(sku=bad_sku),
        ),
        await client.patch(
            f"/admin/products/{product}",
            headers=admin,
            json={"attributes": {BAD_KEY: "x"}},
        ),
        await client.patch(
            f"/admin/products/{product}", headers=admin, json={unknown_field: 1}
        ),
    ]

    for response in responses:
        assert_error(response, 422, "validation_error", fields=True)
        for marker in (bad_sku, BAD_KEY, unknown_field):
            assert marker not in response.text


# --- 17: the seeded admin edits a seeded product ------------------------------------


async def test_seeded_admin_edits_a_seeded_product(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Seed loaded as in test 25 of test_seed_load.py; passwords made at run time."""
    from seed.schema import load_catalog, load_users
    from seed.seed import load
    from tests.test_seed_load import CATALOG_PATH, USERS_PATH, strong_password

    passwords = {"admin": strong_password(), "customer": strong_password()}
    users = load_users(USERS_PATH)
    await load(session, load_catalog(CATALOG_PATH), users, passwords)
    [admin_email] = [u.email for u in users.users if u.role == "admin"]
    product = (
        await session.execute(select(Product.id).order_by(Product.id).limit(1))
    ).scalar_one()
    variant, price = (
        await session.execute(
            select(ProductVariant.id, ProductVariant.price_minor)
            .where(ProductVariant.product_id == product)
            .order_by(ProductVariant.id)
            .limit(1)
        )
    ).one()
    await session.commit()

    login = await client.post(
        "/auth/login", json={"email": admin_email, "password": passwords["admin"]}
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    before = ok(await client.get(f"/admin/products/{product}", headers=headers))

    ok(
        await client.patch(
            f"/admin/products/{product}",
            headers=headers,
            json={"name": "Hanorac editat de admin"},
        )
    )
    ok(
        await client.patch(
            f"/admin/products/{product}/variants/{variant}",
            headers=headers,
            json={"price_minor": price + 100},
        )
    )
    after = ok(await client.get(f"/admin/products/{product}", headers=headers))

    assert after["name"] == "Hanorac editat de admin"
    assert after["version"] == before["version"] + 1
    [edited] = [v for v in after["variants"] if v["id"] == variant]
    [original] = [v for v in before["variants"] if v["id"] == variant]
    assert edited["price_minor"] == price + 100
    assert edited["version"] == original["version"] + 1
