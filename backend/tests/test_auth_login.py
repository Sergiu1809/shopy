"""POST /auth/login (Q7, Q11, Q13, A4, A6): token body, cookie, generic 401, limits."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import (
    REFRESH_MAX_AGE,
    assert_error,
    assert_token_body,
    issued_refresh_token,
    sha256_hex,
)

EMAIL = "ana@example.ro"
PASSWORD = "Parola123"


async def login(
    client: AsyncClient, email: str = EMAIL, password: str = PASSWORD
) -> Any:
    return await client.post("/auth/login", json={"email": email, "password": password})


async def stored_hash(session: AsyncSession, user_id: int) -> str:
    sql = "SELECT password_hash FROM users WHERE id = :id"
    return str((await session.execute(text(sql), {"id": user_id})).scalar_one())


async def test_login_returns_the_token_body_and_the_refresh_cookie(
    client: AsyncClient, session: AsyncSession, make_user: Callable[..., Any]
) -> None:
    user = await make_user()

    response = await login(client)

    assert response.status_code == 200, response.text
    access = assert_token_body(response.json())
    raw = issued_refresh_token(response)
    row = (
        await session.execute(
            text(
                "SELECT user_id, expires_at, revoked_at FROM refresh_tokens"
                " WHERE token_hash = :h"
            ),
            {"h": sha256_hex(raw)},
        )
    ).one()
    assert row.user_id == user.id
    assert row.revoked_at is None
    expected = datetime.now(UTC) + timedelta(seconds=REFRESH_MAX_AGE)
    assert abs((row.expires_at - expected).total_seconds()) < 60

    me = await client.get("/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 200
    assert me.json()["id"] == user.id


async def test_login_trims_and_lowercases_the_email(
    client: AsyncClient, make_user: Callable[..., Any]
) -> None:
    await make_user()

    response = await login(client, email="  ANA@Example.ro ")

    assert response.status_code == 200, response.text


async def test_login_works_for_an_admin(
    client: AsyncClient, make_user: Callable[..., Any]
) -> None:
    await make_user(email="admin@example.ro", role="admin")

    response = await login(client, email="admin@example.ro")

    assert response.status_code == 200, response.text


async def test_wrong_password_and_unknown_email_get_the_same_generic_401(
    client: AsyncClient, make_user: Callable[..., Any]
) -> None:
    await make_user()

    wrong = await login(client, password="Parola124")
    unknown = await login(client, email="nobody@example.ro")

    error = assert_error(wrong, 401, "invalid_credentials")
    assert "invalid email or password" in error["message"].lower()
    assert unknown.status_code == wrong.status_code
    assert unknown.json() == wrong.json()
    assert "set-cookie" not in wrong.headers
    assert "set-cookie" not in unknown.headers


async def test_unknown_email_still_runs_an_argon2_verify(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Q13: a dummy-hash verify, so timing does not reveal unknown emails."""
    from argon2 import PasswordHasher

    calls: list[int] = []
    original = PasswordHasher.verify

    def spy(self: PasswordHasher, hash: str | bytes, password: str | bytes) -> bool:
        calls.append(1)
        return original(self, hash, password)

    monkeypatch.setattr(PasswordHasher, "verify", spy)

    response = await login(client, email="nobody@example.ro")

    assert response.status_code == 401
    assert len(calls) == 1


async def test_login_rehashes_a_weak_hash(
    client: AsyncClient, session: AsyncSession, make_user: Callable[..., Any]
) -> None:
    from argon2 import PasswordHasher

    weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(PASSWORD)
    user = await make_user(password_hash=weak)

    response = await login(client)

    assert response.status_code == 200, response.text
    new_hash = await stored_hash(session, user.id)
    assert new_hash != weak
    assert not PasswordHasher().check_needs_rehash(new_hash)
    assert PasswordHasher().verify(new_hash, PASSWORD)


async def test_login_keeps_a_current_hash(
    client: AsyncClient, session: AsyncSession, make_user: Callable[..., Any]
) -> None:
    user = await make_user()
    before = await stored_hash(session, user.id)

    response = await login(client)

    assert response.status_code == 200, response.text
    assert await stored_hash(session, user.id) == before


async def test_login_takes_json_only(
    client: AsyncClient, make_user: Callable[..., Any]
) -> None:
    await make_user()

    response = await client.post(
        "/auth/login", data={"email": EMAIL, "password": PASSWORD}
    )

    assert_error(response, 422, "validation_error", fields=True)


async def test_login_rejects_unknown_fields(
    client: AsyncClient, make_user: Callable[..., Any]
) -> None:
    await make_user()

    response = await client.post(
        "/auth/login", json={"email": EMAIL, "password": PASSWORD, "role": "admin"}
    )

    error = assert_error(response, 422, "validation_error", fields=True)
    assert "body" in [f["field"] for f in error["fields"]]
    assert "role" not in response.text  # the unknown name is not echoed (C-001)


async def test_login_malformed_email_is_422_with_the_fixed_message(
    client: AsyncClient,
) -> None:
    response = await login(client, email="not-an-email")

    error = assert_error(response, 422, "validation_error", fields=True)
    assert error["fields"] == [{"field": "email", "message": "Invalid email address."}]


@pytest.mark.parametrize("password", ["", "A1" + "b" * 127])
async def test_login_password_must_be_1_to_128_characters(
    client: AsyncClient, password: str
) -> None:
    response = await login(client, password=password)

    error = assert_error(response, 422, "validation_error", fields=True)
    assert [f["field"] for f in error["fields"]] == ["password"]


async def test_login_password_has_no_composition_rule(
    client: AsyncClient, make_user: Callable[..., Any]
) -> None:
    """A6: an old password that fails today's register rule can still sign in."""
    await make_user(password="weakpass")

    response = await login(client, password="weakpass")

    assert response.status_code == 200, response.text


async def test_login_is_limited_to_20_attempts_per_ip(
    client_factory: Callable[..., AsyncClient], make_user: Callable[..., Any]
) -> None:
    await make_user()
    client = client_factory("198.51.100.20")
    for i in range(20):  # distinct emails: the per-account bucket never fills
        attempt = await login(client, email=f"nobody{i}@example.ro")
        assert attempt.status_code == 401

    response = await login(client)  # even the right password

    assert_error(response, 429, "rate_limited")
    assert int(response.headers["Retry-After"]) >= 1
    other_ip = await login(client_factory("198.51.100.21"))
    assert other_ip.status_code == 200, other_ip.text


async def test_login_is_limited_to_5_failures_per_account(
    client_factory: Callable[..., AsyncClient], make_user: Callable[..., Any]
) -> None:
    await make_user()
    await make_user(email="ion@example.ro")
    for i in range(5):  # from different IPs: the limit is per account
        attempt = await login(client_factory(f"198.51.100.{30 + i}"), password="Wrong1")
        assert attempt.status_code == 401

    blocked = await login(client_factory("198.51.100.40"))  # right password

    assert_error(blocked, 429, "rate_limited")
    assert int(blocked.headers["Retry-After"]) >= 1
    other_account = await login(client_factory("198.51.100.40"), email="ion@example.ro")
    assert other_account.status_code == 200, other_account.text


async def test_account_limit_uses_the_normalized_email(
    client: AsyncClient, make_user: Callable[..., Any]
) -> None:
    await make_user()
    for email in [
        "ana@example.ro",
        "ANA@example.ro",
        " Ana@Example.RO",
        "aNa@example.ro",
    ]:
        assert (await login(client, email=email, password="Wrong1")).status_code == 401
    assert (await login(client, password="Wrong1")).status_code == 401

    assert_error(await login(client), 429, "rate_limited")


async def test_account_limit_also_counts_unknown_emails(client: AsyncClient) -> None:
    """A4: keyed by the submitted email whether or not the account exists."""
    for _ in range(5):
        attempt = await login(client, email="ghost@example.ro")
        assert attempt.status_code == 401

    assert_error(await login(client, email="ghost@example.ro"), 429, "rate_limited")


async def test_a_success_does_not_reset_the_failure_count(
    client: AsyncClient, make_user: Callable[..., Any]
) -> None:
    """A4: 4 failures, a success, a 5th failure: the next attempt is limited."""
    await make_user()
    for _ in range(4):
        assert (await login(client, password="Wrong1")).status_code == 401
    assert (await login(client)).status_code == 200
    assert (await login(client, password="Wrong1")).status_code == 401

    assert_error(await login(client), 429, "rate_limited")


async def test_no_lockout_the_account_works_again_after_the_window(
    client: AsyncClient,
    make_user: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time

    from app.auth import rate_limit

    await make_user()
    for _ in range(5):
        assert (await login(client, password="Wrong1")).status_code == 401
    assert (await login(client)).status_code == 429

    later = time.monotonic() + 901
    monkeypatch.setattr(rate_limit, "_now", lambda: later)

    response = await login(client)

    assert response.status_code == 200, response.text
