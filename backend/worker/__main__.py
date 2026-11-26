"""`python -m worker`: the reindex worker loop (GH-13; D-004, D-006, PATTERN-010).

One outbox row at a time (`worker.process`); rows back to back while there is work,
then a poll every IDLE_SECONDS. SIGTERM/SIGINT stop it after the current row.
"""

import asyncio
import contextlib
import logging
import os
import signal
from collections.abc import Mapping

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import create_engine, create_sessionmaker
from app.indexing.embeddings import EmbeddingProvider, OpenAIEmbeddingProvider
from worker.process import IDLE_SECONDS, IndexingConfig, Outcome, process_next

log = logging.getLogger("worker")

UNDEFINED_TABLE = "42P01"


def _log_unavailable(exc: Exception) -> None:
    """The api migrates the db on start; until then the tables are missing (A9)."""
    orig = getattr(exc, "orig", None)
    if getattr(orig, "sqlstate", None) == UNDEFINED_TABLE:
        log.info("reindex_outbox missing; waiting for migrations")
    else:
        log.warning("database unavailable (%s); retrying", type(exc).__name__)


async def run(
    sessionmaker: async_sessionmaker[AsyncSession],
    provider: EmbeddingProvider | None,
    stop: asyncio.Event,
) -> None:
    """Process rows until `stop` is set; the environment is read for every row."""
    blocked = False
    while not stop.is_set():
        try:
            outcome = await process_next(
                sessionmaker, provider, IndexingConfig.from_env(os.environ)
            )
        except (DBAPIError, OSError) as exc:
            _log_unavailable(exc)
            outcome = Outcome.IDLE
        if outcome is Outcome.BLOCKED and not blocked:
            log.warning("paid calls blocked; see reindex_outbox.last_error")
        blocked = outcome is Outcome.BLOCKED
        if outcome in (Outcome.IDLE, Outcome.BLOCKED):
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), IDLE_SECONDS)


def provider_from_env(env: Mapping[str, str]) -> EmbeddingProvider | None:
    """The real provider, or None while the key or the model is unset."""
    api_key = env.get("OPENAI_API_KEY", "").strip()
    model = env.get("EMBEDDING_MODEL", "").strip()
    if not api_key or not model:
        return None
    return OpenAIEmbeddingProvider(api_key=api_key, model=model)


async def _main() -> None:
    engine = create_engine()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        log.info("worker started")
        await run(create_sessionmaker(engine), provider_from_env(os.environ), stop)
    finally:
        await engine.dispose()
    log.info("worker stopped")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    asyncio.run(_main())


if __name__ == "__main__":
    main()
