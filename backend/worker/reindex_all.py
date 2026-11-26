"""`python -m worker.reindex_all` (`make reindex`): enqueue every source (GH-13 B4).

For databases seeded before P2a; the running worker embeds what changed (a source
whose text is unchanged makes no paid call).
"""

import asyncio
import sys

from app.db import create_engine, create_sessionmaker
from app.indexing.outbox import enqueue_full_reindex


async def _run() -> int:
    engine = create_engine()
    try:
        async with create_sessionmaker(engine)() as session, session.begin():
            return await enqueue_full_reindex(session)
    finally:
        await engine.dispose()


def main() -> int:
    count = asyncio.run(_run())
    print(f"Reindex: enqueued {count} sources.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
