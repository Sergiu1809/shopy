"""POST /auth/register (Q6, Q7, Q8, A7): customer only, logs in, strict input."""

from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import (
    assert_error,
    assert_token_body,
    issued_refresh_token,
    sha256_hex,
)

EMAIL = "ana@example.ro"
PASSWORD = "Parola123"
INVALID_EMAIL = "Invalid email address."  # A6, fixed at gate B


async def register(client: AsyncClient, **body: Any) -> Any:
    return await client.post(
        "/auth/register", json={"email": EMAIL, "password": PASSWORD, **body}
    )


async def users_with_email(session: AsyncSession, email: str) -> list[Any]:
    sql = "SELECT * FROM users WHERE lower(email) = lower(:email)"
    return list((await session.execute(text(sql), {"email": email})).all())


async def test_register_creates_a_customer_and_logs_in(
    client: AsyncClient, session: AsyncSession
) -> None:
    response = await register(client)

    assert response.status_code == 201, response.text
    access = assert_token_body(response.json())
    raw = issued_refresh_token(response)

    [user] = await users_with_email(session, EMAIL)
    assert user.role == "customer"
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash

    rows = (
        await session.execute(
            text("SELECT user_id FROM refresh_tokens WHERE token_hash = :h"),
            {"h": sha256_hex(raw)},
        )
    ).all()
    assert [r.user_id for r in rows] == [user.id]

    me = await client.get("/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200
    assert me.json()["email"] == EMAIL


async def test_register_trims_and_lowercases_the_email(
    client: AsyncClient, session: AsyncSession
) -> None:
    response = await register(client, email="  Ana.Pop@Example.RO  ")

    assert response.status_code == 201, response.text
    [user] = await users_with_email(session, "ana.pop@example.ro")
    assert user.email == "ana.pop@example.ro"


@pytest.mark.parametrize("role", ["admin", "customer"])
async def test_register_rejects_a_role_field(
    client: AsyncClient, session: AsyncSession, role: str
) -> None:
    response = await register(client, role=role)

    error = assert_error(response, 422, "validation_error", fields=True)
    assert "role" in [f["field"] for f in error["fields"]]
    assert await users_with_email(session, EMAIL) == []


async def test_register_rejects_any_unknown_field(
    client: AsyncClient, session: AsyncSession
) -> None:
    response = await register(client, stripe_customer_id="cus_x")

    error = assert_error(response, 422, "validation_error", fields=True)
    assert "stripe_customer_id" in [f["field"] for f in error["fields"]]
    assert await users_with_email(session, EMAIL) == []


@pytest.mark.parametrize(
    "second", ["ana@example.ro", "ANA@Example.ro", " ana@example.ro"]
)
async def test_register_duplicate_email_is_409(
    client: AsyncClient, session: AsyncSession, second: str
) -> None:
    first = await register(client)
    assert first.status_code == 201, first.text

    response = await register(client, email=second)

    assert_error(response, 409, "email_taken")
    assert len(await users_with_email(session, EMAIL)) == 1


async def test_register_duplicate_of_a_seeded_admin_is_409(
    client: AsyncClient, make_user: Callable[..., Any]
) -> None:
    await make_user(email="admin@example.ro", role="admin")

    response = await register(client, email="Admin@example.ro")

    assert_error(response, 409, "email_taken")


@pytest.mark.parametrize(
    "password",
    [
        "Abcdefg1",  # 8 characters, the minimum
        "A1" + "b" * 126,  # 128 characters, the maximum
        "Ăbcdefg1",  # A7: a Romanian uppercase letter counts
        "parolA 1 cu spații",  # no other composition rules
    ],
)
async def test_register_accepts_valid_passwords(
    client: AsyncClient, password: str
) -> None:
    response = await register(client, password=password)

    assert response.status_code == 201, response.text


@pytest.mark.parametrize(
    "password",
    [
        "Abcdef1",  # 7 characters
        "A1" + "b" * 127,  # 129 characters
        "parola123",  # no uppercase letter
        "Parolaaaa",  # no digit
        "Parola١٢٣",  # A7: only ASCII 0-9 count as digits
        "",
    ],
)
async def test_register_rejects_invalid_passwords(
    client: AsyncClient, session: AsyncSession, password: str
) -> None:
    response = await register(client, password=password)

    error = assert_error(response, 422, "validation_error", fields=True)
    assert [f["field"] for f in error["fields"]] == ["password"]
    if password:
        assert password not in response.text
    assert await users_with_email(session, EMAIL) == []


def long_email(length: int) -> str:
    local = "a" * 64
    labels = ["b" * 63, "c" * 63]
    tail = ".ro"
    middle = length - len(local) - 1 - sum(len(x) + 1 for x in labels) - len(tail)
    email = f"{local}@{labels[0]}.{labels[1]}.{'d' * middle}{tail}"
    assert len(email) == length
    return email


async def test_register_accepts_a_254_character_email(client: AsyncClient) -> None:
    response = await register(client, email=long_email(254))

    assert response.status_code == 201, response.text


@pytest.mark.parametrize(
    "email",
    ["not-an-email", "ana@", "@example.ro", "ana@@example.ro", "x" * 300, "LONG"],
)
async def test_register_rejects_invalid_emails_with_one_fixed_message(
    client: AsyncClient, email: str
) -> None:
    if email == "LONG":
        email = long_email(255)

    response = await register(client, email=email)

    error = assert_error(response, 422, "validation_error", fields=True)
    assert error["fields"] == [{"field": "email", "message": INVALID_EMAIL}]
    assert email not in response.text


async def test_register_needs_email_and_password(client: AsyncClient) -> None:
    response = await client.post("/auth/register", json={})

    error = assert_error(response, 422, "validation_error", fields=True)
    assert sorted(f["field"] for f in error["fields"]) == ["email", "password"]


async def test_register_takes_json_only(client: AsyncClient) -> None:
    response = await client.post(
        "/auth/register", data={"email": EMAIL, "password": PASSWORD}
    )

    assert_error(response, 422, "validation_error", fields=True)


async def test_register_is_limited_to_5_per_ip_per_hour(
    client_factory: Callable[..., AsyncClient],
) -> None:
    client = client_factory("198.51.100.7")
    for i in range(5):
        ok = await register(client, email=f"user{i}@example.ro")
        assert ok.status_code == 201, ok.text

    response = await register(client, email="user5@example.ro")

    assert_error(response, 429, "rate_limited")
    assert int(response.headers["Retry-After"]) >= 1
    other_ip = await register(client_factory("198.51.100.8"), email="u6@example.ro")
    assert other_ip.status_code == 201, other_ip.text


async def test_register_limit_counts_invalid_requests(
    client_factory: Callable[..., AsyncClient],
) -> None:
    """A5: the IP limit runs before validation, so bad bodies count too."""
    client = client_factory("198.51.100.9")
    for _ in range(5):
        bad = await client.post("/auth/register", json={"email": "nope"})
        assert bad.status_code == 422

    response = await register(client)

    assert_error(response, 429, "rate_limited")
