"""Shared database fixtures: one real Postgres + pgvector container per session (Q11).

There is no skip anywhere: without Docker the DB fixtures error loudly.

App, SQLAlchemy and Alembic imports stay inside the fixtures, so tests that need no
database (test_health, the unit tests in test_db_config) still run on their own.

GH-4: the auth settings are force-set below, before any test module imports the app.
GH-13: `OPENAI_API_KEY` is removed at import and an autouse guard fails any test that
builds the real `AsyncOpenAI` client (N12); worker tests use `indexing_db`, a committed
database per test cloned from a migrated template (the worker opens its own
transactions, so the rolled-back `session` cannot serve it).
API tests call the app through httpx `AsyncClient` + `ASGITransport` (same event loop
as asyncpg), never `TestClient` with DB fixtures; `get_session` is overridden with the
rolled-back `session`, so nothing an API test writes survives it.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from testcontainers.community.postgres import PostgresContainer

if TYPE_CHECKING:
    from alembic.config import Config
    from fastapi import FastAPI
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


# GH-4 (A12): a generated secret (no literal for gitleaks; a developer's `change-me`
# can never leak into a test run) and the one CORS origin. Force-set, not setdefault.
os.environ["JWT_SECRET"] = secrets.token_urlsafe(48)
os.environ["APP_ORIGIN"] = "https://app.test"
# GH-13 (N12): no test run ever holds a real OpenAI key, whatever the shell exports.
os.environ.pop("OPENAI_API_KEY", None)
APP_ORIGIN = "https://app.test"
BASE_URL = "https://test"  # https, so httpx sends the Secure refresh cookie back
DEFAULT_PASSWORD = "Parola123"

# Same image as the `db` service in docker-compose.yml (checked by test_db_config).
PG_IMAGE = "pgvector/pgvector:0.8.7-pg16"

BACKEND_DIR = Path(__file__).resolve().parents[1]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


def alembic_config() -> Config:
    """The project's Alembic config; the URL comes from DATABASE_URL via env.py."""
    from alembic.config import Config

    assert ALEMBIC_INI.is_file(), f"{ALEMBIC_INI} is missing"
    return Config(str(ALEMBIC_INI))


def with_database(url: str, name: str) -> str:
    """The same server URL, pointing at another database."""
    from sqlalchemy.engine import make_url

    return make_url(url).set(database=name).render_as_string(hide_password=False)


async def _fetch(url: str, sql: str, autocommit: bool = False) -> list[Any]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    options: dict[str, Any] = {"isolation_level": "AUTOCOMMIT"} if autocommit else {}
    engine = create_async_engine(url, **options)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(sql))
            return list(result.all()) if result.returns_rows else []
    finally:
        await engine.dispose()


def fetch(url: str, sql: str, autocommit: bool = False) -> list[Any]:
    """Run one SQL statement from a sync test or fixture and return its rows."""
    return asyncio.run(_fetch(url, sql, autocommit))


@pytest.fixture(scope="session")
def pg() -> Iterator[PostgresContainer]:
    # No init script is mounted: the migration alone must create the extensions.
    with PostgresContainer(PG_IMAGE, driver="asyncpg") as container:
        yield container


@pytest.fixture(scope="session")
def migrated_url(pg: PostgresContainer) -> Iterator[str]:
    """The container's database, migrated to head through the real Alembic path."""
    from alembic import command

    url = pg.get_connection_url()
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(alembic_config(), "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.fixture
async def session(migrated_url: str) -> AsyncIterator[AsyncSession]:
    """An AsyncSession inside one transaction that is rolled back after the test."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.db import create_engine

    engine = create_engine(migrated_url)
    try:
        async with engine.connect() as conn:
            transaction = await conn.begin()
            db = AsyncSession(
                bind=conn,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            try:
                yield db
            finally:
                await db.close()
                if transaction.is_active:
                    await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.fixture
def fresh_db_url(pg: PostgresContainer) -> Iterator[str]:
    """A new, empty database in the session container (no extensions, no tables)."""
    admin_url = pg.get_connection_url()
    name = f"fresh_{uuid.uuid4().hex[:12]}"
    fetch(admin_url, f'CREATE DATABASE "{name}"', autocommit=True)
    try:
        yield with_database(admin_url, name)
    finally:
        fetch(admin_url, f'DROP DATABASE "{name}" WITH (FORCE)', autocommit=True)


# --- GH-4: API test harness ---------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_rate_limits() -> Iterator[None]:
    """Every test starts with empty rate-limit buckets (in-process limiter, Q4)."""
    try:
        from app.auth.rate_limit import reset_all
    except ModuleNotFoundError as exc:
        # Only before GH-4 is built: the GH-3 tests must keep running on their own.
        if not (exc.name or "").startswith("app.auth"):
            raise
        yield
        return
    reset_all()
    yield
    reset_all()


@pytest.fixture
def api_app(session: AsyncSession) -> Iterator[FastAPI]:
    """The real app with `get_session` bound to the rolled-back test session."""
    from app.db import get_session
    from app.main import app

    async def _session() -> AsyncIterator[AsyncSession]:
        # Each request starts like a fresh per-request session: no transaction open
        # (the commit only releases a savepoint; the outer transaction still rolls
        # back) and no stale objects (tests change rows with plain SQL in between).
        if session.in_transaction():
            await session.commit()
        session.expire_all()
        yield session

    app.dependency_overrides[get_session] = _session
    try:
        yield app
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.fixture
async def client_factory(
    api_app: FastAPI,
) -> AsyncIterator[Callable[..., AsyncClient]]:
    """Build clients that call the app from a given IP (rate limits key on it)."""
    from httpx import ASGITransport, AsyncClient

    clients: list[AsyncClient] = []

    def make(ip: str = "203.0.113.1") -> AsyncClient:
        transport = ASGITransport(app=api_app, client=(ip, 50000))
        client = AsyncClient(transport=transport, base_url=BASE_URL)
        clients.append(client)
        return client

    try:
        yield make
    finally:
        for client in clients:
            await client.aclose()


@pytest.fixture
def client(client_factory: Callable[..., AsyncClient]) -> AsyncClient:
    return client_factory()


_HASHES: dict[str, str] = {}


def password_hash_for(password: str) -> str:
    """Argon2 is slow on purpose; fixtures reuse one hash per password."""
    from app.auth.passwords import hash_password

    if password not in _HASHES:
        _HASHES[password] = hash_password(password)
    return _HASHES[password]


@dataclass(frozen=True)
class UserRow:
    """A snapshot of an inserted user; never an ORM object the app could share."""

    id: int
    email: str
    role: str
    created_at: datetime


@pytest.fixture
def make_user(session: AsyncSession) -> Callable[..., Any]:
    """Insert a user directly (admins exist only through the seed, GH-5)."""
    from app.models import User

    async def make(
        email: str = "ana@example.ro",
        password: str = DEFAULT_PASSWORD,
        role: str = "customer",
        password_hash: str | None = None,
        **values: Any,
    ) -> UserRow:
        user = User(
            email=email,
            password_hash=password_hash or password_hash_for(password),
            role=role,
            **values,
        )
        session.add(user)
        await session.commit()  # releases a savepoint: survives an app rollback
        await session.refresh(user)
        snapshot = UserRow(user.id, user.email, user.role, user.created_at)
        session.expunge(user)
        return snapshot

    return make


@pytest.fixture
def auth_header() -> Callable[[UserRow], dict[str, str]]:
    """`Authorization: Bearer <access token>` for a user."""
    from app.auth.tokens import create_access_token

    def make(user: UserRow) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(user.id)}"}

    return make


# --- GH-4: helpers for the auth tests (plain functions, no app imports) --------

REFRESH_COOKIE = "refresh_token"
REFRESH_MAX_AGE = 30 * 24 * 3600  # 30 days, sliding (Q5, Q12)
ACCESS_TTL = 900  # 15 minutes (Q9)


def refresh_cookies(response: Any) -> list[Any]:
    """Every `Set-Cookie: refresh_token=…` of a response, parsed into Morsels."""
    from http.cookies import SimpleCookie

    found = []
    for header in response.headers.get_list("set-cookie"):
        jar: SimpleCookie = SimpleCookie()
        jar.load(header)
        if REFRESH_COOKIE in jar:
            found.append(jar[REFRESH_COOKIE])
    return found


def issued_refresh_token(response: Any) -> str:
    """The raw refresh token a response sets; asserts the Q7 cookie attributes."""
    morsels = refresh_cookies(response)
    assert len(morsels) == 1, response.headers.get_list("set-cookie")
    morsel = morsels[0]
    assert morsel.value, "the refresh cookie is empty"
    assert morsel["httponly"] is True
    assert morsel["secure"] is True
    assert str(morsel["samesite"]).lower() == "strict"
    assert morsel["path"] == "/auth"
    assert str(morsel["max-age"]) == str(REFRESH_MAX_AGE)
    return str(morsel.value)


def assert_refresh_cookie_cleared(response: Any) -> None:
    morsels = refresh_cookies(response)
    assert len(morsels) == 1, response.headers.get_list("set-cookie")
    morsel = morsels[0]
    assert morsel.value == ""
    assert str(morsel["max-age"]) == "0"
    assert morsel["path"] == "/auth"


def cookie_header(raw: str) -> dict[str, str]:
    """Send one exact refresh cookie (the client's own jar must be cleared first)."""
    return {"Cookie": f"{REFRESH_COOKIE}={raw}"}


def sha256_hex(raw: str) -> str:
    import hashlib

    return hashlib.sha256(raw.encode()).hexdigest()


def assert_token_body(body: Any) -> str:
    """The Q7 token body; returns the access token."""
    assert set(body) == {"access_token", "token_type", "expires_in"}
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == ACCESS_TTL
    assert isinstance(body["access_token"], str) and body["access_token"]
    return str(body["access_token"])


def assert_error(
    response: Any, status: int, code: str, *, fields: bool = False
) -> dict[str, Any]:
    """The one C-001 error envelope; returns the inner `error` object."""
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert isinstance(error, dict)
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    if fields:
        assert set(error) == {"code", "message", "fields"}
        assert isinstance(error["fields"], list) and error["fields"]
        for item in error["fields"]:
            assert set(item) == {"field", "message"}
    else:
        assert set(error) == {"code", "message"}
    return error


# --- GH-13: no real OpenAI client; committed databases for the worker ----------


def _forbidden_openai_client(*args: Any, **kwargs: Any) -> Any:
    pytest.fail("real OpenAI client constructed in a test")


@pytest.fixture(autouse=True)
def _no_real_openai_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """N12: building the real client in any test fails it (A5); tests inject a stub."""
    try:
        import openai
        from app.indexing import embeddings
    except ModuleNotFoundError as exc:
        # Only before GH-13 is built: the earlier tests must keep running on their own.
        if not (exc.name or "").startswith(("app.indexing", "openai")):
            raise
        yield
        return
    monkeypatch.setattr(embeddings, "AsyncOpenAI", _forbidden_openai_client)
    monkeypatch.setattr(openai, "AsyncOpenAI", _forbidden_openai_client)
    yield


INDEXING_TEMPLATE = "indexing_template"


@pytest.fixture(scope="session")
def indexing_template(pg: PostgresContainer) -> Iterator[str]:
    """A database migrated to head once, cloned by `indexing_db` for every test."""
    from alembic import command

    admin_url = pg.get_connection_url()
    fetch(admin_url, f'CREATE DATABASE "{INDEXING_TEMPLATE}"', autocommit=True)
    url = with_database(admin_url, INDEXING_TEMPLATE)
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(alembic_config(), "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
    yield url


@pytest.fixture
def indexing_db(pg: PostgresContainer, indexing_template: str) -> Iterator[str]:
    """A committed, migrated database of its own, dropped after the test."""
    admin_url = pg.get_connection_url()
    name = f"t_{uuid.uuid4().hex[:12]}"
    fetch(
        admin_url,
        f'CREATE DATABASE "{name}" TEMPLATE "{INDEXING_TEMPLATE}"',
        autocommit=True,
    )
    try:
        yield with_database(admin_url, name)
    finally:
        fetch(admin_url, f'DROP DATABASE "{name}" WITH (FORCE)', autocommit=True)


@pytest.fixture
async def indexing_sessionmaker(
    indexing_db: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """The app's engine and sessionmaker on `indexing_db`; every commit is real."""
    from app.db import create_engine, create_sessionmaker

    engine = create_engine(indexing_db)
    try:
        yield create_sessionmaker(engine)
    finally:
        await engine.dispose()
