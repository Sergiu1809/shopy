"""The api refuses to start without a strong JWT_SECRET (Q10); `get_session` (plan).

The lifespan is entered directly; DATABASE_URL points at a host that never resolves,
so building the engine must not connect. No Docker.
"""

import secrets

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.main import app

UNREACHABLE_DB = "postgresql+asyncpg://shopy:secret@db.invalid:5432/shopy"


async def run_lifespan() -> None:
    async with app.router.lifespan_context(app):
        pass


async def test_startup_fails_without_jwt_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DB)

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        await run_lifespan()


@pytest.mark.parametrize("value", ["change-me", "x" * 31])
async def test_startup_fails_with_a_short_jwt_secret(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("JWT_SECRET", value)
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DB)

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        await run_lifespan()


async def test_secret_is_checked_before_the_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        await run_lifespan()


async def test_startup_with_a_strong_secret_keeps_a_sessionmaker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JWT_SECRET", secrets.token_urlsafe(48))
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DB)

    async with app.router.lifespan_context(app):
        assert isinstance(app.state.sessionmaker, async_sessionmaker)


async def test_get_session_yields_a_session_from_app_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from starlette.requests import Request

    from app.db import get_session

    monkeypatch.setenv("JWT_SECRET", secrets.token_urlsafe(48))
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DB)

    async with app.router.lifespan_context(app):
        request = Request({"type": "http", "app": app, "headers": []})
        sessions = get_session(request)
        db = await anext(sessions)
        assert isinstance(db, AsyncSession)
        await sessions.aclose()


def test_app_origin_is_required_at_import() -> None:
    """A2: without APP_ORIGIN the app module does not import."""
    import os
    import subprocess
    import sys

    from tests.conftest import BACKEND_DIR

    env = {k: v for k, v in os.environ.items() if k != "APP_ORIGIN"}
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode != 0
    assert "APP_ORIGIN" in result.stderr
