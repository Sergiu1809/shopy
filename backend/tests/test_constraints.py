"""The database itself enforces the GH-3 gate A rules (Q1-Q8).

Each test runs in a transaction that the `session` fixture rolls back. A statement
that is expected to fail comes last in its test, because it aborts the transaction.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, Product, Store

LATER = datetime.now(UTC) + timedelta(days=30)


async def insert(session: AsyncSession, table: str, **values: Any) -> Any:
    """INSERT one row with bound parameters and return it."""
    cols = ", ".join(values)
    params = ", ".join(f":{name}" for name in values)
    sql = f"INSERT INTO {table} ({cols}) VALUES ({params}) RETURNING *"
    return (await session.execute(text(sql), values)).one()


async def scalar(session: AsyncSession, sql: str, **params: Any) -> Any:
    return (await session.execute(text(sql), params)).scalar_one()


async def make_store(session: AsyncSession, name: str = "Shopy Demo") -> int:
    row = await insert(session, "stores", name=name)
    return int(row.id)


async def make_user(session: AsyncSession, email: str = "ana@example.ro") -> int:
    row = await insert(session, "users", email=email, password_hash="hash")
    return int(row.id)


async def make_category(
    session: AsyncSession, store_id: int, slug: str = "rochii"
) -> int:
    row = await insert(
        session, "categories", store_id=store_id, name="Rochii", slug=slug
    )
    return int(row.id)


async def make_product(
    session: AsyncSession, store_id: int, category_id: int, **values: Any
) -> int:
    row = await insert(
        session,
        "products",
        store_id=store_id,
        category_id=category_id,
        brand="Brand",
        name="Rochie",
        description="O rochie.",
        **values,
    )
    return int(row.id)


async def make_catalog(session: AsyncSession) -> tuple[int, int, int]:
    """A store, a category and a product; returns their ids."""
    store_id = await make_store(session)
    category_id = await make_category(session, store_id)
    return store_id, category_id, await make_product(session, store_id, category_id)


async def make_variant(
    session: AsyncSession, product_id: int, sku: str = "SKU-1", **values: Any
) -> int:
    defaults: dict[str, Any] = {"price_minor": 19999, "stock": 3}
    row = await insert(
        session,
        "product_variants",
        product_id=product_id,
        sku=sku,
        **(defaults | values),
    )
    return int(row.id)


async def make_review(session: AsyncSession, product_id: int, rating: int) -> int:
    row = await insert(
        session,
        "reviews",
        product_id=product_id,
        author_display_name="Ana",
        rating=rating,
        title="Bun",
        body="Foarte bun.",
    )
    return int(row.id)


async def make_policy(session: AsyncSession, store_id: int, kind: str) -> int:
    row = await insert(
        session, "store_policies", store_id=store_id, kind=kind, title="T", body="B"
    )
    return int(row.id)


async def make_address(session: AsyncSession, user_id: int, is_default: bool) -> int:
    row = await insert(
        session,
        "addresses",
        user_id=user_id,
        full_name="Ana Pop",
        phone="0700000000",
        street="Str. Lunga 1",
        city="Cluj-Napoca",
        county="Cluj",
        postal_code="400000",
        is_default=is_default,
    )
    return int(row.id)


async def make_image(session: AsyncSession, product_id: int, position: int) -> int:
    row = await insert(
        session,
        "product_images",
        product_id=product_id,
        storage_key=f"products/{product_id}/{position}.jpg",
        position=position,
    )
    return int(row.id)


async def make_token(session: AsyncSession, user_id: int, token_hash: str) -> int:
    row = await insert(
        session,
        "refresh_tokens",
        user_id=user_id,
        token_hash=token_hash,
        expires_at=LATER,
    )
    return int(row.id)


# --- Q1 / D-024: identity ids -------------------------------------------------


async def test_explicit_id_insert_rejected(session: AsyncSession) -> None:
    with pytest.raises(DBAPIError, match="non-DEFAULT value"):
        await insert(session, "stores", id=999, name="Explicit")


# --- Q2: ON DELETE ------------------------------------------------------------


async def test_delete_user_cascades(session: AsyncSession) -> None:
    user_id = await make_user(session)
    await make_token(session, user_id, "hash-1")
    await make_address(session, user_id, is_default=True)
    await insert(session, "user_preferences", user_id=user_id)

    await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})

    for table in ("refresh_tokens", "addresses", "user_preferences"):
        count = await scalar(
            session, f"SELECT count(*) FROM {table} WHERE user_id = :id", id=user_id
        )
        assert count == 0, table


async def test_delete_product_cascades(session: AsyncSession) -> None:
    _, _, product_id = await make_catalog(session)
    await make_variant(session, product_id)
    await make_image(session, product_id, position=0)
    await make_review(session, product_id, rating=5)

    await session.execute(
        text("DELETE FROM products WHERE id = :id"), {"id": product_id}
    )

    for table in ("product_variants", "product_images", "reviews"):
        count = await scalar(
            session,
            f"SELECT count(*) FROM {table} WHERE product_id = :id",
            id=product_id,
        )
        assert count == 0, table


async def test_delete_category_with_products_restricted(session: AsyncSession) -> None:
    _, category_id, _ = await make_catalog(session)

    with pytest.raises(IntegrityError, match="fk_products_category_id_categories"):
        await session.execute(
            text("DELETE FROM categories WHERE id = :id"), {"id": category_id}
        )


@pytest.mark.parametrize("child", ["categories", "products", "store_policies"])
async def test_delete_store_with_children_restricted(
    session: AsyncSession, child: str
) -> None:
    store_id = await make_store(session, "Store under test")
    if child == "categories":
        await make_category(session, store_id)
    elif child == "products":
        # The product's category lives in another store, so only products.store_id
        # references the store under test.
        other_store = await make_store(session, "Other store")
        category_id = await make_category(session, other_store)
        await make_product(session, store_id, category_id)
    else:
        await make_policy(session, store_id, "shipping")

    with pytest.raises(IntegrityError, match=f"fk_{child}_store_id_stores"):
        await session.execute(
            text("DELETE FROM stores WHERE id = :id"), {"id": store_id}
        )


# --- Q3: uniqueness -----------------------------------------------------------


async def test_email_unique_case_insensitive(session: AsyncSession) -> None:
    await make_user(session, "a@x.ro")

    with pytest.raises(IntegrityError, match="uq_users_email_lower"):
        await make_user(session, "A@X.ro")


async def test_sku_unique_across_products(session: AsyncSession) -> None:
    store_id, category_id, first = await make_catalog(session)
    second = await make_product(session, store_id, category_id)
    await make_variant(session, first, sku="SKU-DUP")

    with pytest.raises(IntegrityError, match="uq_product_variants_sku"):
        await make_variant(session, second, sku="SKU-DUP")


async def test_category_slug_unique_per_store(session: AsyncSession) -> None:
    store_a = await make_store(session, "A")
    store_b = await make_store(session, "B")
    await make_category(session, store_a, "incaltaminte")
    await make_category(session, store_b, "incaltaminte")

    with pytest.raises(IntegrityError, match="uq_categories_store_id_slug"):
        await make_category(session, store_a, "incaltaminte")


async def test_refresh_token_hash_unique(session: AsyncSession) -> None:
    first = await make_user(session, "one@example.ro")
    second = await make_user(session, "two@example.ro")
    await make_token(session, first, "same-hash")

    with pytest.raises(IntegrityError, match="uq_refresh_tokens_token_hash"):
        await make_token(session, second, "same-hash")


async def test_policy_kind_unique_per_store(session: AsyncSession) -> None:
    store_a = await make_store(session, "A")
    store_b = await make_store(session, "B")
    await make_policy(session, store_a, "returns")
    await make_policy(session, store_b, "returns")

    with pytest.raises(IntegrityError, match="uq_store_policies_store_id_kind"):
        await make_policy(session, store_a, "returns")


async def test_stripe_customer_id_not_unique(session: AsyncSession) -> None:
    for email in ("one@example.ro", "two@example.ro"):
        await insert(
            session,
            "users",
            email=email,
            password_hash="hash",
            stripe_customer_id="cus_same",
        )

    count = await scalar(
        session, "SELECT count(*) FROM users WHERE stripe_customer_id = 'cus_same'"
    )
    assert count == 2


async def test_image_position_not_unique(session: AsyncSession) -> None:
    _, _, product_id = await make_catalog(session)
    await make_image(session, product_id, position=1)
    await make_image(session, product_id, position=1)

    count = await scalar(
        session,
        "SELECT count(*) FROM product_images WHERE product_id = :id AND position = 1",
        id=product_id,
    )
    assert count == 2


# --- addresses: at most one default per user ---------------------------------


async def test_second_default_address_rejected(session: AsyncSession) -> None:
    user_id = await make_user(session)
    await make_address(session, user_id, is_default=True)

    with pytest.raises(IntegrityError, match="uq_addresses_user_id_default"):
        await make_address(session, user_id, is_default=True)


async def test_many_non_default_addresses_allowed(session: AsyncSession) -> None:
    user_id = await make_user(session)
    for _ in range(3):
        await make_address(session, user_id, is_default=False)
    await make_address(session, user_id, is_default=True)

    count = await scalar(
        session, "SELECT count(*) FROM addresses WHERE user_id = :id", id=user_id
    )
    assert count == 4


async def test_default_per_user_independent(session: AsyncSession) -> None:
    for email in ("one@example.ro", "two@example.ro"):
        user_id = await make_user(session, email)
        await make_address(session, user_id, is_default=True)

    count = await scalar(session, "SELECT count(*) FROM addresses WHERE is_default")
    assert count == 2


# --- Q4 / Q5: CHECK constraints -----------------------------------------------


async def insert_with(session: AsyncSession, column: str, value: Any) -> None:
    """Insert one otherwise valid row whose `column` is set to `value`."""
    if column in ("price_minor", "stock"):
        _, _, product_id = await make_catalog(session)
        await make_variant(session, product_id, **{column: value})
    elif column == "rating":
        _, _, product_id = await make_catalog(session)
        await make_review(session, product_id, rating=value)
    elif column in ("rating_count", "rating_avg"):
        store_id = await make_store(session)
        category_id = await make_category(session, store_id)
        await make_product(session, store_id, category_id, **{column: value})
    elif column == "role":
        await insert(session, "users", email="r@x.ro", password_hash="h", role=value)
    elif column == "kind":
        await make_policy(session, await make_store(session), value)
    else:
        raise AssertionError(f"no row builder for {column}")


@pytest.mark.parametrize(
    ("column", "value", "constraint"),
    [
        pytest.param(
            "price_minor",
            -1,
            "ck_product_variants_price_minor_non_negative",
            id="price_minor=-1",
        ),
        pytest.param(
            "stock", -1, "ck_product_variants_stock_non_negative", id="stock=-1"
        ),
        pytest.param("rating", 0, "ck_reviews_rating_range", id="rating=0"),
        pytest.param("rating", 6, "ck_reviews_rating_range", id="rating=6"),
        pytest.param(
            "rating_count",
            -1,
            "ck_products_rating_count_non_negative",
            id="rating_count=-1",
        ),
        pytest.param(
            "rating_avg",
            Decimal("5.01"),
            "ck_products_rating_avg_range",
            id="rating_avg=5.01",
        ),
        pytest.param(
            "rating_avg",
            Decimal("-0.01"),
            "ck_products_rating_avg_range",
            id="rating_avg=-0.01",
        ),
        pytest.param("role", "owner", "ck_users_role", id="role=owner"),
        pytest.param("kind", "other", "ck_store_policies_kind", id="kind=other"),
    ],
)
async def test_check_rejects(
    session: AsyncSession, column: str, value: Any, constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        await insert_with(session, column, value)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("price_minor", 0),
        ("stock", 0),
        ("rating", 1),
        ("rating", 5),
        ("rating_count", 0),
        ("rating_avg", None),
        ("rating_avg", Decimal("0")),
        ("rating_avg", Decimal("5.00")),
        ("role", "customer"),
        ("role", "admin"),
        ("kind", "shipping"),
        ("kind", "returns"),
        ("kind", "warranty"),
        ("kind", "payment"),
        ("kind", "size_guide"),
    ],
)
async def test_check_accepts(session: AsyncSession, column: str, value: Any) -> None:
    await insert_with(session, column, value)


async def test_rating_avg_keeps_two_decimals(session: AsyncSession) -> None:
    store_id = await make_store(session)
    category_id = await make_category(session, store_id)
    product_id = await make_product(
        session, store_id, category_id, rating_avg=Decimal("4.567")
    )

    stored = await scalar(
        session, "SELECT rating_avg FROM products WHERE id = :id", id=product_id
    )
    assert stored == Decimal("4.57")


# --- Q5-Q8: server defaults ---------------------------------------------------


async def make_address_without_default_flag(session: AsyncSession, user_id: int) -> int:
    row = await insert(
        session,
        "addresses",
        user_id=user_id,
        full_name="Ana Pop",
        phone="0700000000",
        street="Str. Lunga 1",
        city="Cluj-Napoca",
        county="Cluj",
        postal_code="400000",
    )
    return int(row.id)


async def test_user_role_defaults_to_customer(session: AsyncSession) -> None:
    user_id = await make_user(session)

    role = await scalar(session, "SELECT role FROM users WHERE id = :id", id=user_id)
    assert role == "customer"


async def test_server_defaults(session: AsyncSession) -> None:
    store_id, _, product_id = await make_catalog(session)
    variant_id = await make_variant(session, product_id)
    user_id = await make_user(session)
    await insert(session, "user_preferences", user_id=user_id)
    address_id = await make_address_without_default_flag(session, user_id)
    policy_id = await make_policy(session, store_id, "warranty")

    store = (
        await session.execute(
            text("SELECT currency FROM stores WHERE id = :id"), {"id": store_id}
        )
    ).one()
    user = (
        await session.execute(
            text("SELECT role, created_at FROM users WHERE id = :id"), {"id": user_id}
        )
    ).one()
    product = (
        await session.execute(
            text(
                "SELECT attributes = '{}'::jsonb AS empty_attributes, version,"
                " rating_count, rating_avg, content_hash, updated_at"
                " FROM products WHERE id = :id"
            ),
            {"id": product_id},
        )
    ).one()
    variant = (
        await session.execute(
            text(
                "SELECT attributes = '{}'::jsonb AS empty_attributes, version"
                " FROM product_variants WHERE id = :id"
            ),
            {"id": variant_id},
        )
    ).one()
    preferences = (
        await session.execute(
            text(
                "SELECT sizes = '{}'::jsonb AS empty_sizes,"
                " preferred_brands = '{}'::text[] AS empty_brands"
                " FROM user_preferences WHERE user_id = :id"
            ),
            {"id": user_id},
        )
    ).one()

    assert store.currency == "RON"
    assert user.role == "customer"
    assert user.created_at is not None and user.created_at.tzinfo is not None
    assert product.empty_attributes is True
    assert product.version == 1
    assert product.rating_count == 0
    assert product.rating_avg is None
    assert product.content_hash is None
    assert product.updated_at is not None and product.updated_at.tzinfo is not None
    assert variant.empty_attributes is True
    assert variant.version == 1
    assert preferences.empty_sizes is True
    assert preferences.empty_brands is True
    assert (
        await scalar(
            session, "SELECT is_default FROM addresses WHERE id = :id", id=address_id
        )
        is False
    )
    assert (
        await scalar(
            session, "SELECT version FROM store_policies WHERE id = :id", id=policy_id
        )
        == 1
    )
    review_id = await make_review(session, product_id, rating=4)
    created_at = await scalar(
        session, "SELECT created_at FROM reviews WHERE id = :id", id=review_id
    )
    assert created_at is not None and created_at.tzinfo is not None


# --- Q7: updated_at on ORM update, version left to app code -------------------


async def orm_product(session: AsyncSession) -> Product:
    store = Store(name="Shopy Demo")
    session.add(store)
    await session.flush()
    category = Category(store_id=store.id, name="Rochii", slug="rochii")
    session.add(category)
    await session.flush()
    product = Product(
        store_id=store.id,
        category_id=category.id,
        brand="Brand",
        name="Rochie",
        description="O rochie.",
    )
    session.add(product)
    await session.flush()
    return product


async def test_product_updated_at_changes_on_orm_update(
    session: AsyncSession,
) -> None:
    # now() is fixed inside one transaction, so start from a clearly older value.
    product = await orm_product(session)
    old = datetime(2000, 1, 1, tzinfo=UTC)
    await session.execute(
        text("UPDATE products SET updated_at = :old WHERE id = :id"),
        {"old": old, "id": product.id},
    )
    await session.refresh(product)
    assert product.updated_at == old

    product.name = "Rochie de vara"
    await session.flush()
    await session.refresh(product)

    assert product.updated_at > old


async def test_version_not_auto_incremented(session: AsyncSession) -> None:
    product = await orm_product(session)
    await session.refresh(product)
    assert product.version == 1

    product.name = "Rochie de vara"
    await session.flush()
    await session.refresh(product)

    assert product.version == 1
