"""In-process fixed-window rate limits for the auth routes (Q4, A3, A4, A5, A10, A11).

Memory only: one api process, counters reset on restart, wrong with several
processes or behind a proxy (production topology: Q-014). The key is the client
address Starlette sees; no forwarded header is trusted.
"""

import math
import time
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request

from app.errors import ApiError

_SWEEP_ABOVE = 10_000  # A11: drop expired keys once a bucket holds more than this


def _now() -> float:
    return time.monotonic()


class RateLimited(ApiError):
    """429 with `Retry-After` in whole seconds (at least 1)."""

    def __init__(self, retry_after: float) -> None:
        seconds = max(1, math.ceil(retry_after))
        super().__init__(
            429,
            "rate_limited",
            "Too many requests. Try again later.",
            headers={"Retry-After": str(seconds)},
        )


class FixedWindowLimiter:
    """At most `limit` hits per key per `window_s` window from the key's first hit."""

    def __init__(self, limit: int, window_s: int) -> None:
        self.limit = limit
        self.window_s = window_s
        self._windows: dict[str, tuple[float, int]] = {}  # key -> (start, count)

    def _current(self, key: str, now: float) -> tuple[float, int]:
        start, count = self._windows.get(key, (now, 0))
        if now - start >= self.window_s:
            return now, 0
        return start, count

    def check(self, key: str) -> None:
        """Raise `RateLimited` if the key has used its limit; record nothing."""
        now = _now()
        start, count = self._current(key, now)
        if count >= self.limit:
            raise RateLimited(start + self.window_s - now)

    def hit(self, key: str) -> None:
        """Record one hit; raise `RateLimited` once the limit is passed."""
        now = _now()
        start, count = self._current(key, now)
        self._windows[key] = (start, count + 1)
        if len(self._windows) > _SWEEP_ABOVE:
            self._sweep(now)
        if count + 1 > self.limit:
            raise RateLimited(start + self.window_s - now)

    def reset(self) -> None:
        self._windows.clear()

    def _sweep(self, now: float) -> None:
        expired = [
            key
            for key, (start, _) in self._windows.items()
            if now - start >= self.window_s
        ]
        for key in expired:
            del self._windows[key]


LOGIN_IP = FixedWindowLimiter(limit=20, window_s=900)
LOGIN_ACCOUNT_FAILURES = FixedWindowLimiter(limit=5, window_s=900)
REGISTER_IP = FixedWindowLimiter(limit=5, window_s=3600)
REFRESH_IP = FixedWindowLimiter(limit=60, window_s=60)
LOGOUT_IP = FixedWindowLimiter(limit=60, window_s=60)

_BUCKETS = (LOGIN_IP, LOGIN_ACCOUNT_FAILURES, REGISTER_IP, REFRESH_IP, LOGOUT_IP)


def reset_all() -> None:
    for bucket in _BUCKETS:
        bucket.reset()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def limit_by_ip(
    bucket: FixedWindowLimiter,
) -> Callable[[Request], Coroutine[Any, Any, None]]:
    """A dependency that counts every request, valid or not (A5).

    Async, so it runs on the event loop and the counters need no lock.
    """

    async def dependency(request: Request) -> None:
        bucket.hit(client_ip(request))

    return dependency
