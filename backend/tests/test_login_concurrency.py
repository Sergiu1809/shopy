"""A4 under concurrency: parallel logins for one email cannot pass the 5-failure limit.

Reproduction for a defect found in review round 1 of GH-4: the per-account check ran
before the awaited lookup and verify, and the failure was recorded only after it, so
N parallel requests all passed the check and all had their password verified.

No Docker: `get_session` is replaced by a fake session whose user lookup waits on a
gate the test opens, so every request that gets past the limiter is in flight at the
same time (deterministic interleaving). Each request comes from its own IP, so the
20-per-IP bucket never interferes. `PasswordHasher.verify` is counted (unknown emails
verify too, Q13, so this counts every password check of the route).
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from tests.conftest import BASE_URL, assert_error, password_hash_for

EMAIL = "ana@example.ro"
PASSWORD = "Parola123"
LIMIT = 5  # A4: 5 failures per account per 15 min


class GatedSession:
    """Just enough of an AsyncSession for `/auth/login`; the lookup waits on a gate."""

    def __init__(self, user: Any) -> None:
        self.user = user
        self.gate = asyncio.Event()
        self.arrived = 0

    async def scalar(self, *args: Any, **kwargs: Any) -> Any:
        self.arrived += 1
        await self.gate.wait()
        return self.user

    def add(self, obj: Any) -> None:
        pass

    async def commit(self) -> None:
        pass


@pytest.fixture
def db() -> GatedSession:
    return GatedSession(
        SimpleNamespace(id=1, password_hash=password_hash_for(PASSWORD))
    )


@pytest.fixture
def gated_app(db: GatedSession) -> Iterator[Any]:
    from app.db import get_session
    from app.main import app

    async def _session() -> AsyncIterator[GatedSession]:
        yield db

    app.dependency_overrides[get_session] = _session
    try:
        yield app
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def verifications(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    from argon2 import PasswordHasher

    calls: list[int] = []
    original = PasswordHasher.verify

    def spy(self: PasswordHasher, hash: str | bytes, password: str | bytes) -> bool:
        calls.append(1)
        return original(self, hash, password)

    monkeypatch.setattr(PasswordHasher, "verify", spy)
    return calls


async def post_login(app: Any, n: int, password: str) -> Any:
    """One login from its own IP (198.51.100.<n>)."""
    transport = ASGITransport(app=app, client=(f"198.51.100.{n}", 50000))
    async with AsyncClient(transport=transport, base_url=BASE_URL) as client:
        return await client.post(
            "/auth/login", json={"email": EMAIL, "password": password}
        )


async def settle(db: GatedSession, tasks: list[asyncio.Task[Any]]) -> None:
    """Wait until every task is either held at the gate or already answered."""

    async def poll() -> None:
        while db.arrived + sum(t.done() for t in tasks) < len(tasks):
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), timeout=10)


def launch(app: Any, first: int, passwords: list[str]) -> list[asyncio.Task[Any]]:
    return [
        asyncio.create_task(post_login(app, first + i, password))
        for i, password in enumerate(passwords)
    ]


async def test_a_burst_verifies_at_most_5_passwords_per_account(
    gated_app: Any, db: GatedSession, verifications: list[int]
) -> None:
    """12 parallel wrong passwords: 5 are verified (401), the other 7 get 429."""
    tasks = launch(gated_app, 1, [f"Wrong{i}" for i in range(12)])
    await settle(db, tasks)
    db.gate.set()

    responses = await asyncio.gather(*tasks)

    codes = [r.status_code for r in responses]
    assert len(verifications) <= LIMIT, codes
    assert sorted(codes) == [401] * LIMIT + [429] * (12 - LIMIT), codes
    for response in responses:
        if response.status_code == 429:
            assert_error(response, 429, "rate_limited")
            assert int(response.headers["Retry-After"]) >= 1


async def test_the_right_password_is_refused_while_5_failures_are_in_flight(
    gated_app: Any, db: GatedSession, verifications: list[int]
) -> None:
    """A4: the 6th attempt gets 429 even with the right password, also in parallel."""
    wrong = launch(gated_app, 1, [f"Wrong{i}" for i in range(LIMIT)])
    await settle(db, wrong)
    right = launch(gated_app, 50, [PASSWORD])  # sent while the 5 are still in flight
    await settle(db, [*wrong, *right])
    db.gate.set()

    wrong_codes = [r.status_code for r in await asyncio.gather(*wrong)]
    blocked = (await asyncio.gather(*right))[0]

    assert wrong_codes == [401] * LIMIT
    assert_error(blocked, 429, "rate_limited")
    assert "set-cookie" not in blocked.headers
    assert len(verifications) == LIMIT  # the right password was never checked

    after = await post_login(gated_app, 60, PASSWORD)  # 5 failures now recorded
    assert_error(after, 429, "rate_limited")


async def test_a_parallel_success_does_not_count_as_a_failure(
    gated_app: Any, db: GatedSession
) -> None:
    """A4 kept: 4 failures + 1 success in parallel; one more failure is still allowed.

    Guard for the fix (passes on the current code): a slot taken by a request that
    then succeeds must not stay counted as a failure.
    """
    tasks = launch(gated_app, 1, [*(f"Wrong{i}" for i in range(LIMIT - 1)), PASSWORD])
    await settle(db, tasks)
    db.gate.set()

    codes = [r.status_code for r in await asyncio.gather(*tasks)]

    assert codes == [401] * (LIMIT - 1) + [200]
    assert (await post_login(gated_app, 60, "Wrong9")).status_code == 401  # 5th
    assert_error(await post_login(gated_app, 61, PASSWORD), 429, "rate_limited")
