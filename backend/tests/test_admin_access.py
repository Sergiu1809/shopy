"""The /admin router and brief test 15 (Q2, PATTERN-007).

A test-only `GET /admin/__probe` reuses the admin router's dependency list, so the
parametrized matrix is never empty; GH-6's real /admin routes join it on their own.
Requests send no body: a malformed body would give 422 before 403.
"""

import os
import re
import time
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import router as admin_router
from app.auth.dependencies import require_admin
from app.main import app
from tests.conftest import assert_error

PROBE = "/admin/__probe"


def _probe() -> dict[str, str]:
    return {"status": "admin"}


if not any(getattr(r, "path", None) == PROBE for r in app.routes):
    app.add_api_route(
        PROBE, _probe, methods=["GET"], dependencies=list(admin_router.dependencies)
    )


def admin_routes() -> list[tuple[str, str]]:
    """Every (method, path) under /admin, path parameters filled with 1."""
    found = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path != "/admin" and not route.path.startswith("/admin/"):
            continue
        path = re.sub(r"\{[^}]+\}", "1", route.path)
        for method in sorted(route.methods or ()):
            found.append((method, path))
    return found


ADMIN_ROUTES = admin_routes()


def crafted_token(secret: str | None = None, **claims: Any) -> str:
    """An HS256 token; a claim set to None is left out."""
    import jwt

    now = int(time.time())
    payload = {"iat": now, "exp": now + 900, "type": "access", **claims}
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, secret or os.environ["JWT_SECRET"], algorithm="HS256")


def test_admin_router_carries_require_admin_at_router_level() -> None:
    assert admin_router.prefix == "/admin"
    assert any(d.dependency is require_admin for d in admin_router.dependencies)


def test_there_is_at_least_one_admin_route() -> None:
    assert ("GET", PROBE) in ADMIN_ROUTES


def _depends_on(dependant: Any, target: Any) -> bool:
    return any(
        d.call is target or _depends_on(d, target) for d in dependant.dependencies
    )


@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
def test_every_admin_route_depends_on_require_admin(method: str, path: str) -> None:
    routes = [
        r
        for r in app.routes
        if isinstance(r, APIRoute)
        and re.sub(r"\{[^}]+\}", "1", r.path) == path
        and method in (r.methods or ())
    ]
    assert routes
    assert all(_depends_on(r.dependant, require_admin) for r in routes)


@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
async def test_customer_gets_403_on_every_admin_route(
    client: AsyncClient,
    make_user: Callable[..., Any],
    auth_header: Callable[..., dict[str, str]],
    method: str,
    path: str,
) -> None:
    """Brief test 15."""
    customer = await make_user()

    response = await client.request(method, path, headers=auth_header(customer))

    assert_error(response, 403, "forbidden")


@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
async def test_no_token_gets_401_on_every_admin_route(
    client: AsyncClient, method: str, path: str
) -> None:
    response = await client.request(method, path)

    assert_error(response, 401, "unauthorized")
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_admin_reaches_the_probe(
    client: AsyncClient,
    make_user: Callable[..., Any],
    auth_header: Callable[..., dict[str, str]],
) -> None:
    admin = await make_user(email="admin@example.ro", role="admin")

    response = await client.get(PROBE, headers=auth_header(admin))

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "admin"}


BAD_TOKENS: dict[str, Callable[[str], str]] = {
    "garbage": lambda sub: "not-a-jwt",
    "expired": lambda sub: crafted_token(
        sub=sub, iat=int(time.time()) - 1000, exp=int(time.time()) - 100
    ),
    "wrong-type": lambda sub: crafted_token(sub=sub, type="refresh"),
    "no-type": lambda sub: crafted_token(sub=sub, type=None),
    "no-exp": lambda sub: crafted_token(sub=sub, exp=None),
    "no-sub": lambda sub: crafted_token(sub=None),
    "non-numeric-sub": lambda sub: crafted_token(sub="abc"),
    "wrong-secret": lambda sub: crafted_token(sub=sub, secret="y" * 48),
    "alg-none": lambda sub: _unsigned(sub),
}


def _unsigned(sub: str) -> str:
    import jwt

    now = int(time.time())
    payload = {"sub": sub, "iat": now, "exp": now + 900, "type": "access"}
    return jwt.encode(payload, None, algorithm="none")


@pytest.mark.parametrize("kind", sorted(BAD_TOKENS))
async def test_a_bad_token_of_an_admin_gets_401(
    client: AsyncClient,
    make_user: Callable[..., Any],
    kind: str,
) -> None:
    admin = await make_user(email="admin@example.ro", role="admin")
    token = BAD_TOKENS[kind](str(admin.id))

    response = await client.get(PROBE, headers={"Authorization": f"Bearer {token}"})

    assert_error(response, 401, "unauthorized")
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_a_customer_promoted_in_the_db_reaches_admin_with_the_same_token(
    client: AsyncClient,
    session: AsyncSession,
    make_user: Callable[..., Any],
    auth_header: Callable[..., dict[str, str]],
) -> None:
    """Roles come from the DB on every request, never from the token."""
    customer = await make_user()
    header = auth_header(customer)
    assert (await client.get(PROBE, headers=header)).status_code == 403

    await session.execute(
        text("UPDATE users SET role = 'admin' WHERE id = :id"), {"id": customer.id}
    )

    assert (await client.get(PROBE, headers=header)).status_code == 200
