"""Database access: the URL comes only from DATABASE_URL (PATTERN-013).

Nothing connects at import time; callers create the engine they need.
"""

import os

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def create_engine(url: str | None = None) -> AsyncEngine:
    return create_async_engine(url or database_url())


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
