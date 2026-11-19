"""CORS (Q15, C-001): exactly APP_ORIGIN, credentials, listed methods and headers.

Only the middleware answers here: no database needed.
"""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.conftest import APP_ORIGIN, BASE_URL

METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


@pytest.fixture
async def plain_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=BASE_URL
    ) as client:
        yield client


def preflight(
    method: str = "POST",
    headers: str = "authorization, content-type",
    origin: str = APP_ORIGIN,
) -> dict[str, str]:
    return {
        "Origin": origin,
        "Access-Control-Request-Method": method,
        "Access-Control-Request-Headers": headers,
    }


async def test_preflight_from_app_origin_is_allowed(plain_client: AsyncClient) -> None:
    response = await plain_client.options("/auth/login", headers=preflight())

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == APP_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    allowed_methods = {
        m.strip() for m in response.headers["access-control-allow-methods"].split(",")
    }
    assert METHODS <= allowed_methods
    allowed_headers = {
        h.strip().lower()
        for h in response.headers["access-control-allow-headers"].split(",")
    }
    assert {"authorization", "content-type"} <= allowed_headers


@pytest.mark.parametrize("method", sorted(METHODS))
async def test_preflight_allows_each_listed_method(
    plain_client: AsyncClient, method: str
) -> None:
    response = await plain_client.options("/me", headers=preflight(method=method))

    assert response.status_code == 200


async def test_preflight_rejects_another_method(plain_client: AsyncClient) -> None:
    response = await plain_client.options("/me", headers=preflight(method="HEAD"))

    assert response.status_code == 400


async def test_preflight_rejects_another_header(plain_client: AsyncClient) -> None:
    response = await plain_client.options("/me", headers=preflight(headers="x-custom"))

    assert response.status_code == 400


@pytest.mark.parametrize(
    "origin", ["https://evil.test", "http://app.test", "https://app.test.evil.test"]
)
async def test_preflight_rejects_other_origins(
    plain_client: AsyncClient, origin: str
) -> None:
    response = await plain_client.options(
        "/auth/login", headers=preflight(origin=origin)
    )

    assert response.status_code == 400
    assert response.headers.get("access-control-allow-origin") != origin


async def test_simple_requests_get_cors_headers_only_for_app_origin(
    plain_client: AsyncClient,
) -> None:
    allowed = await plain_client.get("/health", headers={"Origin": APP_ORIGIN})
    other = await plain_client.get("/health", headers={"Origin": "https://evil.test"})

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == APP_ORIGIN
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert "access-control-allow-origin" not in other.headers
