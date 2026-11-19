"""One error envelope for every error (Q1, C-001, PATTERN-006, brief test 17).

`{"error": {"code", "message", "fields"?}}`; `fields` only for validation errors;
the submitted input is never sent back.
"""

from collections.abc import Callable
from typing import Any

from httpx import AsyncClient

from tests.conftest import assert_error

PROBE_PASSWORD = "Ecou-Parola-987"


async def test_bad_email_gives_422_with_a_useful_message(client: AsyncClient) -> None:
    """Brief test 17."""
    response = await client.post(
        "/auth/register", json={"email": "ana.example.ro", "password": "Parola123"}
    )

    error = assert_error(response, 422, "validation_error", fields=True)
    assert error["fields"] == [{"field": "email", "message": "Invalid email address."}]
    assert "ana.example.ro" not in response.text


async def test_422_never_echoes_the_password(client: AsyncClient) -> None:
    bad = "x" + PROBE_PASSWORD.lower()  # no uppercase letter: invalid
    response = await client.post(
        "/auth/register", json={"email": "ana@example.ro", "password": bad}
    )

    error = assert_error(response, 422, "validation_error", fields=True)
    assert [f["field"] for f in error["fields"]] == ["password"]
    assert bad not in response.text  # and no `input`/`ctx` keys (assert_error)


async def test_422_for_a_wrong_type_does_not_echo_the_value(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/auth/login", json={"email": "ana@example.ro", "password": [PROBE_PASSWORD]}
    )

    error = assert_error(response, 422, "validation_error", fields=True)
    assert [f["field"] for f in error["fields"]] == ["password"]
    assert PROBE_PASSWORD not in response.text


async def test_malformed_json_gives_the_envelope(client: AsyncClient) -> None:
    response = await client.post(
        "/auth/login",
        content=b'{"email": "ana@example.ro", "password": "' + PROBE_PASSWORD.encode(),
        headers={"Content-Type": "application/json"},
    )

    assert_error(response, 422, "validation_error", fields=True)
    assert PROBE_PASSWORD not in response.text


async def test_every_field_error_is_listed(client: AsyncClient) -> None:
    response = await client.post(
        "/auth/register", json={"email": "nope", "password": "short"}
    )

    error = assert_error(response, 422, "validation_error", fields=True)
    assert sorted(f["field"] for f in error["fields"]) == ["email", "password"]
    for item in error["fields"]:
        assert isinstance(item["message"], str) and item["message"]


async def test_unknown_route_is_404_in_the_envelope(client: AsyncClient) -> None:
    response = await client.get("/no-such-route")

    assert_error(response, 404, "not_found")


async def test_wrong_method_is_405_in_the_envelope(client: AsyncClient) -> None:
    response = await client.get("/auth/login")

    assert_error(response, 405, "method_not_allowed")


async def test_401_409_429_use_the_envelope(
    client: AsyncClient, make_user: Callable[..., Any]
) -> None:
    """One shape for every code (A1); 403 is asserted in test_admin_access."""
    await make_user()

    unauthorized = await client.get("/me")
    taken = await client.post(
        "/auth/register", json={"email": "ana@example.ro", "password": "Parola123"}
    )
    for _ in range(5):
        await client.post(
            "/auth/login", json={"email": "ghost@example.ro", "password": "Wrong1"}
        )
    limited = await client.post(
        "/auth/login", json={"email": "ghost@example.ro", "password": "Wrong1"}
    )

    assert_error(unauthorized, 401, "unauthorized")
    assert_error(taken, 409, "email_taken")
    assert_error(limited, 429, "rate_limited")
    assert "Retry-After" in limited.headers
