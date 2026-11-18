"""Reindex worker placeholder: idles until P2 adds the outbox."""

import logging
import signal
import threading
from types import FrameType

log = logging.getLogger("worker")
IDLE_SECONDS = 60


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    stop = threading.Event()

    def handle_stop(signum: int, frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    while not stop.is_set():
        log.info("worker idle (P2 adds the outbox)")
        stop.wait(IDLE_SECONDS)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
