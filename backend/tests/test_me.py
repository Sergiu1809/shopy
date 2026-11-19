"""GET /me (Q14, A13) and the access-token dependency: the role comes from the DB."""

from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import assert_error


async def test_me_returns_exactly_id_email_role_created_at(
    client: AsyncClient,
    make_user: Callable[..., Any],
    auth_header: Callable[..., dict[str, str]],
) -> None:
    user = await make_user(stripe_customer_id="cus_test_123")

    response = await client.get("/me", headers=auth_header(user))

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"id", "email", "role", "created_at"}
    assert body["id"] == user.id
    assert isinstance(body["id"], int)
    assert body["email"] == "ana@example.ro"
    assert body["role"] == "customer"
    assert datetime.fromisoformat(body["created_at"]) == user.created_at
    assert "cus_test_123" not in response.text
    assert "argon2" not in response.text


async def test_me_reads_the_role_from_the_database(
    client: AsyncClient,
    session: AsyncSession,
    make_user: Callable[..., Any],
    auth_header: Callable[..., dict[str, str]],
) -> None:
    """No role in the token: a role change applies to a token issued before it."""
    user = await make_user()
    header = auth_header(user)
    await session.execute(
        text("UPDATE users SET role = 'admin' WHERE id = :id"), {"id": user.id}
    )

    response = await client.get("/me", headers=header)

    assert response.status_code == 200, response.text
    assert response.json()["role"] == "admin"


async def test_me_for_a_deleted_user_is_401(
    client: AsyncClient,
    session: AsyncSession,
    make_user: Callable[..., Any],
    auth_header: Callable[..., dict[str, str]],
) -> None:
    user = await make_user()
    header = auth_header(user)
    await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user.id})

    response = await client.get("/me", headers=header)

    assert_error(response, 401, "unauthorized")
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer not-a-jwt"},
        {"Authorization": "Basic YW5hOnBhcm9sYQ=="},
    ],
    ids=["none", "empty-bearer", "garbage", "basic"],
)
async def test_me_without_a_valid_token_is_401_with_www_authenticate(
    client: AsyncClient, headers: dict[str, str]
) -> None:
    response = await client.get("/me", headers=headers)

    assert_error(response, 401, "unauthorized")
    assert response.headers["WWW-Authenticate"] == "Bearer"
