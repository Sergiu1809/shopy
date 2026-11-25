"""POST /auth/refresh and /auth/logout (Q3, Q5, Q6, Q7, Q12, A3, A8, A9).

Rotation on every use, reuse of a revoked token logs out every device, logout needs
only the cookie and always answers 204. DB state is read with plain SQL, so the
session's identity map can never hide what the app wrote.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import (
    REFRESH_MAX_AGE,
    assert_error,
    assert_refresh_cookie_cleared,
    assert_token_body,
    cookie_header,
    issued_refresh_token,
    sha256_hex,
)

EMAIL = "ana@example.ro"
PASSWORD = "Parola123"


async def login(client: AsyncClient, email: str = EMAIL) -> str:
    response = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return issued_refresh_token(response)


async def post_with_cookie(client: AsyncClient, path: str, raw: str | None) -> Any:
    """POST with exactly this refresh cookie (or none); the jar never interferes."""
    client.cookies.clear()
    return await client.post(path, headers=cookie_header(raw) if raw else {})


async def token_row(session: AsyncSession, raw: str) -> Any:
    sql = (
        "SELECT user_id, token_hash, expires_at, revoked_at FROM refresh_tokens"
        " WHERE token_hash = :h"
    )
    return (await session.execute(text(sql), {"h": sha256_hex(raw)})).one_or_none()


async def active_tokens(session: AsyncSession, user_id: int) -> int:
    sql = (
        "SELECT count(*) FROM refresh_tokens WHERE user_id = :id AND revoked_at IS NULL"
    )
    return int((await session.execute(text(sql), {"id": user_id})).scalar_one())


async def expire(session: AsyncSession, raw: str, at: datetime) -> None:
    await session.execute(
        text("UPDATE refresh_tokens SET expires_at = :at WHERE token_hash = :h"),
        {"at": at, "h": sha256_hex(raw)},
    )


# --- refresh -------------------------------------------------------------------


async def test_refresh_rotates_the_token(
    client: AsyncClient, session: AsyncSession, make_user: Callable[..., Any]
) -> None:
    user = await make_user()
    old = await login(client)

    response = await post_with_cookie(client, "/auth/refresh", old)

    assert response.status_code == 200, response.text
    access = assert_token_body(response.json())
    new = issued_refresh_token(response)
    assert new != old
    old_row, new_row = await token_row(session, old), await token_row(session, new)
    assert old_row.revoked_at is not None
    assert new_row.revoked_at is None
    assert new_row.user_id == user.id
    assert (
        await client.get("/me", headers={"Authorization": f"Bearer {access}"})
    ).status_code == 200


async def test_refresh_stores_only_the_sha256_of_the_token(
    client: AsyncClient, session: AsyncSession, make_user: Callable[..., Any]
) -> None:
    await make_user()
    raw = await login(client)

    row = await token_row(session, raw)
    plain = (
        await session.execute(
            text("SELECT count(*) FROM refresh_tokens WHERE token_hash = :raw"),
            {"raw": raw},
        )
    ).scalar_one()

    assert row is not None
    assert row.token_hash == sha256_hex(raw)
    assert len(row.token_hash) == 64
    assert plain == 0
    assert len(raw) >= 43  # secrets.token_urlsafe(32)


async def test_refresh_gives_a_fresh_30_day_expiry(
    client: AsyncClient, session: AsyncSession, make_user: Callable[..., Any]
) -> None:
    """Sliding: the new token gets 30 days from now, not the old token's end."""
    await make_user()
    old = await login(client)
    await expire(session, old, datetime.now(UTC) + timedelta(days=1))

    response = await post_with_cookie(client, "/auth/refresh", old)

    assert response.status_code == 200, response.text
    new_row = await token_row(session, issued_refresh_token(response))
    expected = datetime.now(UTC) + timedelta(seconds=REFRESH_MAX_AGE)
    assert abs((new_row.expires_at - expected).total_seconds()) < 60


async def test_refresh_chain_with_the_client_cookie_jar(
    client: AsyncClient, make_user: Callable[..., Any]
) -> None:
    """The Secure, Path=/auth cookie comes back on its own to https://test/auth/…"""
    await make_user()
    await login(client)

    first = await client.post("/auth/refresh")
    second = await client.post("/auth/refresh")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert issued_refresh_token(first) != issued_refresh_token(second)


async def test_reuse_of_a_rotated_token_revokes_every_token_of_the_user(
    client_factory: Callable[..., AsyncClient],
    session: AsyncSession,
    make_user: Callable[..., Any],
) -> None:
    user = await make_user()
    other = await make_user(email="ion@example.ro")
    phone, laptop, ion = client_factory(), client_factory(), client_factory()
    old = await login(phone)
    rotated = issued_refresh_token(await post_with_cookie(phone, "/auth/refresh", old))
    laptop_token = await login(laptop)
    ion_token = await login(ion, email="ion@example.ro")

    response = await post_with_cookie(phone, "/auth/refresh", old)

    assert_error(response, 401, "unauthorized")
    assert_refresh_cookie_cleared(response)
    assert await active_tokens(session, user.id) == 0
    for raw in (rotated, laptop_token):
        retry = await post_with_cookie(laptop, "/auth/refresh", raw)
        assert_error(retry, 401, "unauthorized")
    assert await active_tokens(session, other.id) == 1
    ion_refresh = await post_with_cookie(ion, "/auth/refresh", ion_token)
    assert ion_refresh.status_code == 200, ion_refresh.text


async def test_reuse_of_a_logged_out_token_revokes_every_token_of_the_user(
    client_factory: Callable[..., AsyncClient],
    session: AsyncSession,
    make_user: Callable[..., Any],
) -> None:
    user = await make_user()
    phone, laptop = client_factory(), client_factory()
    old = await login(phone)
    await login(laptop)
    assert (await post_with_cookie(phone, "/auth/logout", old)).status_code == 204

    response = await post_with_cookie(phone, "/auth/refresh", old)

    assert_error(response, 401, "unauthorized")
    assert_refresh_cookie_cleared(response)
    assert await active_tokens(session, user.id) == 0


async def test_refresh_with_an_expired_token_is_401_and_clears_the_cookie(
    client: AsyncClient, session: AsyncSession, make_user: Callable[..., Any]
) -> None:
    await make_user()
    raw = await login(client)
    await expire(session, raw, datetime.now(UTC) - timedelta(seconds=1))

    response = await post_with_cookie(client, "/auth/refresh", raw)

    assert_error(response, 401, "unauthorized")
    assert_refresh_cookie_cleared(response)
    assert "access_token" not in response.text


async def test_refresh_with_an_unknown_token_is_401_and_clears_the_cookie(
    client: AsyncClient,
) -> None:
    response = await post_with_cookie(client, "/auth/refresh", "unknown-token-value")

    assert_error(response, 401, "unauthorized")
    assert_refresh_cookie_cleared(response)


async def test_refresh_without_a_cookie_is_401_and_clears_the_cookie(
    client: AsyncClient,
) -> None:
    """A9."""
    response = await post_with_cookie(client, "/auth/refresh", None)

    assert_error(response, 401, "unauthorized")
    assert_refresh_cookie_cleared(response)


async def test_refresh_ignores_an_access_token(
    client: AsyncClient,
    make_user: Callable[..., Any],
    auth_header: Callable[..., dict[str, str]],
) -> None:
    user = await make_user()
    client.cookies.clear()

    response = await client.post("/auth/refresh", headers=auth_header(user))

    assert_error(response, 401, "unauthorized")


async def test_refresh_is_limited_to_60_per_ip_per_minute(
    client_factory: Callable[..., AsyncClient],
) -> None:
    client = client_factory("198.51.100.60")
    for _ in range(60):
        assert (
            await post_with_cookie(client, "/auth/refresh", None)
        ).status_code == 401

    response = await post_with_cookie(client, "/auth/refresh", None)

    assert_error(response, 429, "rate_limited")
    assert int(response.headers["Retry-After"]) >= 1
    other_ip = client_factory("198.51.100.61")
    assert (await post_with_cookie(other_ip, "/auth/refresh", None)).status_code == 401


# --- logout --------------------------------------------------------------------


async def test_logout_revokes_the_token_and_clears_the_cookie(
    client: AsyncClient, session: AsyncSession, make_user: Callable[..., Any]
) -> None:
    await make_user()
    raw = await login(client)

    response = await post_with_cookie(client, "/auth/logout", raw)

    assert response.status_code == 204
    assert response.content == b""
    assert_refresh_cookie_cleared(response)
    assert (await token_row(session, raw)).revoked_at is not None


async def test_logout_needs_no_access_token_and_leaves_it_valid(
    client: AsyncClient, make_user: Callable[..., Any]
) -> None:
    """Issued access tokens stay valid until they expire (max 15 min)."""
    await make_user()
    login_response = await client.post(
        "/auth/login", json={"email": EMAIL, "password": PASSWORD}
    )
    access = login_response.json()["access_token"]
    raw = issued_refresh_token(login_response)

    response = await post_with_cookie(client, "/auth/logout", raw)

    assert response.status_code == 204
    me = await client.get("/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200


async def test_logout_without_a_cookie_is_204(client: AsyncClient) -> None:
    response = await post_with_cookie(client, "/auth/logout", None)

    assert response.status_code == 204
    assert_refresh_cookie_cleared(response)


async def test_logout_with_an_unknown_cookie_is_204(client: AsyncClient) -> None:
    response = await post_with_cookie(client, "/auth/logout", "unknown-token-value")

    assert response.status_code == 204
    assert_refresh_cookie_cleared(response)


async def test_logout_with_a_revoked_token_is_204_without_reuse_revocation(
    client_factory: Callable[..., AsyncClient],
    session: AsyncSession,
    make_user: Callable[..., Any],
) -> None:
    """A8: only refresh treats a revoked token as reuse."""
    user = await make_user()
    phone, laptop = client_factory(), client_factory()
    old = await login(phone)
    rotated = issued_refresh_token(await post_with_cookie(phone, "/auth/refresh", old))
    await login(laptop)

    response = await post_with_cookie(phone, "/auth/logout", old)

    assert response.status_code == 204
    assert_refresh_cookie_cleared(response)
    assert await active_tokens(session, user.id) == 2
    assert (await token_row(session, rotated)).revoked_at is None


async def test_logout_with_an_expired_token_is_204(
    client: AsyncClient, session: AsyncSession, make_user: Callable[..., Any]
) -> None:
    await make_user()
    raw = await login(client)
    await expire(session, raw, datetime.now(UTC) - timedelta(seconds=1))

    response = await post_with_cookie(client, "/auth/logout", raw)

    assert response.status_code == 204
    assert_refresh_cookie_cleared(response)


async def test_logout_is_limited_to_60_per_ip_per_minute(
    client_factory: Callable[..., AsyncClient],
) -> None:
    client = client_factory("198.51.100.70")
    for _ in range(60):
        assert (await post_with_cookie(client, "/auth/logout", None)).status_code == 204

    response = await post_with_cookie(client, "/auth/logout", None)

    assert_error(response, 429, "rate_limited")
    assert int(response.headers["Retry-After"]) >= 1


async def test_refresh_and_logout_have_separate_buckets(
    client_factory: Callable[..., AsyncClient],
) -> None:
    """A3."""
    client = client_factory("198.51.100.80")
    for _ in range(60):
        await post_with_cookie(client, "/auth/refresh", None)
    assert (await post_with_cookie(client, "/auth/refresh", None)).status_code == 429

    response = await post_with_cookie(client, "/auth/logout", None)

    assert response.status_code == 204
