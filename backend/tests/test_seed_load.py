"""The seed loader `python -m seed.seed` (GH-5, points 13-25).

The DB tests call the synchronous `main()` against a fresh database migrated through
Alembic, as in test_migrations: Alembic's and the seed's `asyncio.run` never nest
inside pytest-asyncio's loop. They load the real `backend/seed/catalog.json` and
`users.json` and compare the rows with the files. Passwords are generated at run time.
"""

import json
import secrets
import string
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from httpx import AsyncClient
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import verify_password
from seed.schema import load_catalog, load_users
from seed.seed import SeedError, SeedReport, load, rating_summary, seed_passwords
from seed.seed import main as seed_main
from tests.conftest import alembic_config, assert_token_body, fetch

SEED_DIR = Path(__file__).resolve().parents[1] / "seed"
CATALOG_PATH = SEED_DIR / "catalog.json"
USERS_PATH = SEED_DIR / "users.json"

ADMIN_VAR = "SEED_ADMIN_PASSWORD"
CUSTOMER_VAR = "SEED_CUSTOMER_PASSWORD"
VAR_ROLE = {ADMIN_VAR: "admin", CUSTOMER_VAR: "customer"}

TABLES = [
    "stores",
    "categories",
    "products",
    "product_variants",
    "product_images",
    "reviews",
    "store_policies",
    "users",
    "addresses",
    "user_preferences",
    "refresh_tokens",
]
TABLES_WITH_ID = [t for t in TABLES if t != "user_preferences"]

Data = dict[str, Any]


# --- passwords -----------------------------------------------------------------


def lowercase(n: int) -> str:
    return "".join(secrets.choice(string.ascii_lowercase) for _ in range(n))


def strong_password() -> str:
    """Meets the register rule: 8-128 characters, one uppercase letter, one digit."""
    return f"{lowercase(12)}Q{secrets.randbelow(10)}"


def bad_password(kind: str) -> str:
    return {
        "change-me": "change-me",
        "7 characters": f"Q7{lowercase(5)}",
        "no digit": f"Q{lowercase(11)}",
        "no uppercase": f"{lowercase(11)}7",
        "129 characters": f"Q7{lowercase(127)}",
    }[kind]


@pytest.fixture
def passwords(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Valid passwords in both SEED_* variables; returned by role."""
    by_role = {"admin": strong_password(), "customer": strong_password()}
    monkeypatch.setenv(ADMIN_VAR, by_role["admin"])
    monkeypatch.setenv(CUSTOMER_VAR, by_role["customer"])
    return by_role


# --- the files and the database ------------------------------------------------


@cache
def catalog_json() -> Data:
    data: Data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return data


@cache
def users_json() -> Data:
    data: Data = json.loads(USERS_PATH.read_text(encoding="utf-8"))
    return data


def file_products() -> list[Data]:
    return [p for c in catalog_json()["categories"] for p in c["products"]]


def file_variants() -> list[tuple[int, Data]]:
    """(product ID, variant) in file order; product n in file order has ID n."""
    return [(n, v) for n, p in enumerate(file_products(), 1) for v in p["variants"]]


def file_reviews() -> list[tuple[int, Data]]:
    return [(n, r) for n, p in enumerate(file_products(), 1) for r in p["reviews"]]


def file_users() -> list[Data]:
    users: list[Data] = users_json()["users"]
    return users


def file_review(kind: str) -> tuple[int, Data]:
    """(review ID, review) of a fixture review; review n in file order has ID n."""
    return next(
        (n, r) for n, (_, r) in enumerate(file_reviews(), 1) if r.get("fixture") == kind
    )


def counts(url: str) -> dict[str, int]:
    return {t: fetch(url, f"SELECT count(*) FROM {t}")[0][0] for t in TABLES}


def max_ids(url: str) -> dict[str, int]:
    return {
        t: fetch(url, f"SELECT coalesce(max(id), 0) FROM {t}")[0][0]
        for t in TABLES_WITH_ID
    }


def expected_counts() -> dict[str, int]:
    users = file_users()
    return {
        "stores": 1,
        "categories": len(catalog_json()["categories"]),
        "products": len(file_products()),
        "product_variants": len(file_variants()),
        "product_images": 0,
        "reviews": len(file_reviews()),
        "store_policies": len(catalog_json()["policies"]),
        "users": len(users),
        "addresses": sum(len(u["addresses"]) for u in users),
        "user_preferences": sum(1 for u in users if u["preferences"] is not None),
        "refresh_tokens": 0,
    }


@pytest.fixture
def db_url(
    fresh_db_url: str, monkeypatch: pytest.MonkeyPatch, passwords: dict[str, str]
) -> Iterator[str]:
    """A fresh database migrated to head; DATABASE_URL points at it."""
    monkeypatch.setenv("DATABASE_URL", fresh_db_url)
    command.upgrade(alembic_config(), "head")
    yield fresh_db_url


@pytest.fixture
def seeded_url(db_url: str, capsys: pytest.CaptureFixture[str]) -> str:
    """The database after one successful `main()`."""
    assert seed_main() == 0
    capsys.readouterr()
    return db_url


# --- 13: rating summary --------------------------------------------------------


def test_rating_summary_rounds_to_two_decimals() -> None:
    avg, count = rating_summary([5, 4, 4])
    assert (avg, count) == (Decimal("4.33"), 3)
    assert isinstance(avg, Decimal)


def test_rating_summary_rounds_half_up_not_to_even() -> None:
    ratings = [5, 5, 5, 5, 5, 4, 4, 4]  # 37 / 8 = 4.625
    assert sum(ratings) == 37

    avg, count = rating_summary(ratings)

    assert (avg, count) == (Decimal("4.63"), 8)
    assert str(avg) == "4.63"


# --- 14: password refusal, before any connection -------------------------------

BAD_KINDS = [
    "unset",
    "change-me",
    "7 characters",
    "no digit",
    "no uppercase",
    "129 characters",
]


@pytest.mark.parametrize("variable", [ADMIN_VAR, CUSTOMER_VAR])
@pytest.mark.parametrize("kind", BAD_KINDS)
def test_seed_passwords_refuses_a_bad_variable(variable: str, kind: str) -> None:
    env = {ADMIN_VAR: strong_password(), CUSTOMER_VAR: strong_password()}
    value = None if kind == "unset" else bad_password(kind)
    if value is None:
        del env[variable]
    else:
        env[variable] = value

    with pytest.raises(SeedError) as info:
        seed_passwords(env)

    message = str(info.value)
    assert variable in message
    assert "128" in message
    assert "uppercase" in message.lower()
    assert "digit" in message.lower()
    if value is not None:
        assert value not in message


def test_seed_passwords_returns_the_password_per_role() -> None:
    env = {ADMIN_VAR: strong_password(), CUSTOMER_VAR: strong_password()}

    assert seed_passwords(env) == {
        "admin": env[ADMIN_VAR],
        "customer": env[CUSTOMER_VAR],
    }


@pytest.mark.parametrize("variable", [ADMIN_VAR, CUSTOMER_VAR])
@pytest.mark.parametrize("kind", BAD_KINDS)
def test_main_refuses_a_bad_password_before_connecting(
    variable: str,
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(ADMIN_VAR, strong_password())
    monkeypatch.setenv(CUSTOMER_VAR, strong_password())
    value = None if kind == "unset" else bad_password(kind)
    if value is None:
        monkeypatch.delenv(variable)
    else:
        monkeypatch.setenv(variable, value)

    assert seed_main() == 1

    captured = capsys.readouterr()
    assert variable in captured.err
    if value is not None:
        assert value not in captured.err
        assert value not in captured.out


# --- 15: first run -------------------------------------------------------------


def test_first_run_loads_the_files(
    db_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert seed_main() == 0

    assert counts(db_url) == expected_counts()
    out = capsys.readouterr().out
    assert f"{len(file_products())} products" in out
    assert f"{len(file_reviews())} reviews" in out
    for user in file_users():
        assert user["email"] in out


# --- 16: fixed IDs in file order -----------------------------------------------


def test_store_categories_and_policies_follow_the_file(seeded_url: str) -> None:
    catalog = catalog_json()

    stores = fetch(seeded_url, "SELECT id, name, currency FROM stores")
    assert [tuple(r) for r in stores] == [(1, "Shopy", "RON")]
    categories = fetch(seeded_url, "SELECT id, slug, name FROM categories ORDER BY id")
    assert [tuple(r) for r in categories] == [
        (n, c["slug"], c["name"]) for n, c in enumerate(catalog["categories"], 1)
    ]
    policies = fetch(
        seeded_url, "SELECT kind, title, body FROM store_policies ORDER BY id"
    )
    assert [tuple(r) for r in policies] == [
        (p["kind"], p["title"], p["body"]) for p in catalog["policies"]
    ]


def test_product_ids_follow_the_file_order(seeded_url: str) -> None:
    in_order = [
        (category_id, p)
        for category_id, c in enumerate(catalog_json()["categories"], 1)
        for p in c["products"]
    ]
    expected = [
        (n, category_id, p["brand"], p["name"], p["description"], p["attributes"])
        for n, (category_id, p) in enumerate(in_order, 1)
    ]

    rows = fetch(
        seeded_url,
        "SELECT id, category_id, brand, name, description, attributes"
        " FROM products ORDER BY id",
    )

    assert [tuple(r) for r in rows] == expected


def test_variant_ids_follow_the_file_order(seeded_url: str) -> None:
    rows = fetch(
        seeded_url,
        "SELECT product_id, sku, attributes, price_minor, stock"
        " FROM product_variants ORDER BY id",
    )

    assert [tuple(r) for r in rows] == [
        (n, v["sku"], v["attributes"], v["price_minor"], v["stock"])
        for n, v in file_variants()
    ]


def test_review_ids_follow_the_file_order(seeded_url: str) -> None:
    rows = fetch(
        seeded_url,
        "SELECT product_id, author_display_name, rating, title, created_at"
        " FROM reviews ORDER BY id",
    )

    assert [tuple(r) for r in rows] == [
        (
            n,
            r["author_display_name"],
            r["rating"],
            r["title"],
            datetime.fromisoformat(r["created_at"]),
        )
        for n, r in file_reviews()
    ]


# --- 17: rating summary per product --------------------------------------------


def test_rating_avg_and_count_are_computed_from_the_file(seeded_url: str) -> None:
    rows = fetch(
        seeded_url, "SELECT id, rating_avg, rating_count FROM products ORDER BY id"
    )

    assert [tuple(r) for r in rows] == [
        (n, *rating_summary([r["rating"] for r in p["reviews"]]))
        for n, p in enumerate(file_products(), 1)
    ]


# --- 18: fixtures stored verbatim ----------------------------------------------


def test_review_bodies_are_stored_verbatim(seeded_url: str) -> None:
    rows = fetch(seeded_url, "SELECT body FROM reviews ORDER BY id")
    assert [r.body for r in rows] == [r["body"] for _, r in file_reviews()]


@pytest.mark.parametrize("kind", ["xss", "prompt_injection"])
def test_fixture_reviews_are_byte_for_byte_the_file(seeded_url: str, kind: str) -> None:
    review_id, review = file_review(kind)

    rows = fetch(seeded_url, f"SELECT body, rating FROM reviews WHERE id = {review_id}")

    assert len(rows) == 1
    assert rows[0].body.encode("utf-8") == review["body"].encode("utf-8")
    assert rows[0].rating == review["rating"]
    if kind == "xss":
        assert "<script" in rows[0].body
        assert "onerror=" in rows[0].body


def test_the_out_of_stock_product_has_no_stock(seeded_url: str) -> None:
    product_id = next(
        n
        for n, p in enumerate(file_products(), 1)
        if p.get("fixture") == "out_of_stock"
    )

    rows = fetch(
        seeded_url,
        f"SELECT stock FROM product_variants WHERE product_id = {product_id}",
    )

    assert rows
    assert all(r.stock == 0 for r in rows)


# --- 19: users -----------------------------------------------------------------


def test_users_are_stored_with_hashed_passwords(
    seeded_url: str, passwords: dict[str, str]
) -> None:
    rows = fetch(
        seeded_url,
        "SELECT email, role, stripe_customer_id, password_hash FROM users ORDER BY id",
    )

    assert [(r.email, r.role) for r in rows] == [
        (u["email"].lower(), u["role"]) for u in file_users()
    ]
    for row in rows:
        assert row.stripe_customer_id is None
        assert row.password_hash != passwords[row.role]
        assert passwords[row.role] not in row.password_hash
        assert verify_password(passwords[row.role], row.password_hash)


def test_addresses_and_preferences_follow_the_file(seeded_url: str) -> None:
    rows = fetch(
        seeded_url,
        "SELECT u.email, a.label, a.full_name, a.phone, a.street, a.city, a.county,"
        " a.postal_code, a.is_default"
        " FROM addresses a JOIN users u ON u.id = a.user_id ORDER BY a.id",
    )
    assert [tuple(r) for r in rows] == [
        (
            u["email"].lower(),
            a["label"],
            a["full_name"],
            a["phone"],
            a["street"],
            a["city"],
            a["county"],
            a["postal_code"],
            a["is_default"],
        )
        for u in file_users()
        for a in u["addresses"]
    ]

    preferences = fetch(
        seeded_url,
        "SELECT u.email, p.sizes, p.preferred_brands"
        " FROM user_preferences p JOIN users u ON u.id = p.user_id ORDER BY u.id",
    )
    assert [tuple(r) for r in preferences] == [
        (
            u["email"].lower(),
            u["preferences"]["sizes"],
            u["preferences"]["preferred_brands"],
        )
        for u in file_users()
        if u["preferences"] is not None
    ]


# --- 20-23: reruns insert only what is missing ---------------------------------


def test_a_rerun_changes_nothing(
    seeded_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    before = (counts(seeded_url), max_ids(seeded_url))

    assert seed_main() == 0

    assert "already seeded" in capsys.readouterr().out
    assert (counts(seeded_url), max_ids(seeded_url)) == before


def test_an_admin_edit_survives_a_rerun(seeded_url: str) -> None:
    fetch(seeded_url, "UPDATE products SET name = 'Editat de admin' WHERE id = 1")
    fetch(seeded_url, "UPDATE product_variants SET price_minor = 12345 WHERE id = 1")

    assert seed_main() == 0

    assert fetch(seeded_url, "SELECT name FROM products WHERE id = 1")[0][0] == (
        "Editat de admin"
    )
    price = fetch(seeded_url, "SELECT price_minor FROM product_variants WHERE id = 1")
    assert price[0][0] == 12345


def test_a_deleted_user_is_inserted_again(
    seeded_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    others = "SELECT id, email FROM users WHERE email <> 'customer2@example.com'"
    before_others = [tuple(r) for r in fetch(seeded_url, others)]
    products_before = counts(seeded_url)["products"]
    fetch(seeded_url, "DELETE FROM users WHERE email = 'customer2@example.com'")

    assert seed_main() == 0

    assert "already seeded" in capsys.readouterr().out
    assert [tuple(r) for r in fetch(seeded_url, others)] == before_others
    customer2 = next(u for u in file_users() if u["email"] == "customer2@example.com")
    rows = fetch(
        seeded_url,
        "SELECT a.street, a.is_default FROM addresses a JOIN users u"
        " ON u.id = a.user_id WHERE u.email = 'customer2@example.com' ORDER BY a.id",
    )
    assert [tuple(r) for r in rows] == [
        (a["street"], a["is_default"]) for a in customer2["addresses"]
    ]
    assert counts(seeded_url)["products"] == products_before


def test_an_existing_email_matches_case_insensitively(
    db_url: str, passwords: dict[str, str]
) -> None:
    fetch(
        db_url,
        "INSERT INTO users (email, password_hash, role)"
        " VALUES ('Admin@Example.com', 'not-a-real-hash', 'admin')",
    )

    assert seed_main() == 0

    admins = fetch(
        db_url,
        "SELECT email, password_hash FROM users"
        " WHERE lower(email) = 'admin@example.com'",
    )
    assert [tuple(r) for r in admins] == [("Admin@Example.com", "not-a-real-hash")]
    customers = fetch(
        db_url, "SELECT email FROM users WHERE role = 'customer' ORDER BY id"
    )
    assert [r.email for r in customers] == [
        u["email"].lower() for u in file_users() if u["role"] == "customer"
    ]
    assert counts(db_url)["products"] == len(file_products())


# --- 24: one transaction -------------------------------------------------------


def test_a_failure_on_the_second_user_rolls_everything_back(db_url: str) -> None:
    # The DB refuses the second user row, whatever the loader's code looks like.
    fetch(
        db_url,
        "CREATE FUNCTION fail_second_user() RETURNS trigger LANGUAGE plpgsql AS $$"
        " BEGIN"
        "   IF (SELECT count(*) FROM users) >= 1 THEN"
        "     RAISE EXCEPTION 'test: the second user insert fails';"
        "   END IF;"
        "   RETURN NEW;"
        " END $$",
    )
    fetch(
        db_url,
        "CREATE TRIGGER fail_second_user BEFORE INSERT ON users"
        " FOR EACH ROW EXECUTE FUNCTION fail_second_user()",
    )

    with pytest.raises(DBAPIError, match="the second user insert fails"):
        seed_main()

    after = counts(db_url)
    assert (after["stores"], after["products"], after["users"]) == (0, 0, 0)
    assert sum(after.values()) == 0


# --- 25: seeded accounts log in (PATTERN-015) ----------------------------------


async def test_seeded_accounts_log_in(
    session: AsyncSession, client: AsyncClient, passwords: dict[str, str]
) -> None:
    report = await load(
        session, load_catalog(CATALOG_PATH), load_users(USERS_PATH), passwords
    )
    assert isinstance(report, SeedReport)

    for user in file_users():
        response = await client.post(
            "/auth/login",
            json={"email": user["email"], "password": passwords[user["role"]]},
        )
        assert response.status_code == 200, (user["email"], response.text)
        access = assert_token_body(response.json())

        me = await client.get("/me", headers={"Authorization": f"Bearer {access}"})
        assert me.status_code == 200, me.text
        assert me.json()["email"] == user["email"].lower()
        assert me.json()["role"] == user["role"]
