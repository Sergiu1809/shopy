"""The in-process fixed-window limiter (Q4, A3, A10). No Docker.

The clock is `app.auth.rate_limit._now` (monotonic seconds), monkeypatched here.
"""

import pytest
from starlette.exceptions import HTTPException

from app.auth import rate_limit
from app.auth.rate_limit import FixedWindowLimiter, RateLimited, reset_all


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    # 36 000 is a multiple of every window (60, 900, 3600): windows anchored at the
    # first hit and windows aligned to the clock both start here.
    now = [36_000.0]
    monkeypatch.setattr(rate_limit, "_now", lambda: now[0])
    return now


def retry_after(exc: RateLimited) -> int:
    assert exc.headers is not None
    value = exc.headers["Retry-After"]
    assert value.isdigit(), value
    return int(value)


def test_rate_limited_is_a_429_http_exception() -> None:
    assert issubclass(RateLimited, HTTPException)


def test_allows_up_to_the_limit_then_raises_429(clock: list[float]) -> None:
    limiter = FixedWindowLimiter(limit=3, window_s=60)

    for _ in range(3):
        limiter.hit("1.2.3.4")
    with pytest.raises(RateLimited) as caught:
        limiter.hit("1.2.3.4")

    assert caught.value.status_code == 429
    assert 1 <= retry_after(caught.value) <= 60


def test_keys_are_counted_separately(clock: list[float]) -> None:
    limiter = FixedWindowLimiter(limit=1, window_s=60)

    limiter.hit("a")
    limiter.hit("b")
    with pytest.raises(RateLimited):
        limiter.hit("a")


def test_a_new_window_allows_again(clock: list[float]) -> None:
    limiter = FixedWindowLimiter(limit=1, window_s=60)
    limiter.hit("a")
    with pytest.raises(RateLimited):
        limiter.hit("a")

    clock[0] += 61

    limiter.hit("a")


def test_retry_after_counts_whole_seconds_to_the_window_end(
    clock: list[float],
) -> None:
    limiter = FixedWindowLimiter(limit=1, window_s=60)
    limiter.hit("a")

    with pytest.raises(RateLimited) as at_start:
        limiter.hit("a")
    clock[0] += 59.5
    with pytest.raises(RateLimited) as near_end:
        limiter.hit("a")

    assert retry_after(at_start.value) == 60
    assert retry_after(near_end.value) == 1  # 0.5 s left, rounded up to at least 1


def test_reset_all_empties_the_module_buckets(clock: list[float]) -> None:
    for _ in range(rate_limit.REGISTER_IP.limit):
        rate_limit.REGISTER_IP.hit("9.9.9.9")
    with pytest.raises(RateLimited):
        rate_limit.REGISTER_IP.hit("9.9.9.9")

    reset_all()

    rate_limit.REGISTER_IP.hit("9.9.9.9")


@pytest.mark.parametrize(
    ("name", "limit", "window_s"),
    [
        ("LOGIN_IP", 20, 900),
        ("LOGIN_ACCOUNT_FAILURES", 5, 900),
        ("REGISTER_IP", 5, 3600),
        ("REFRESH_IP", 60, 60),
        ("LOGOUT_IP", 60, 60),
    ],
)
def test_the_five_buckets(name: str, limit: int, window_s: int) -> None:
    bucket = getattr(rate_limit, name)

    assert isinstance(bucket, FixedWindowLimiter)
    assert bucket.limit == limit
    assert bucket.window_s == window_s


def test_buckets_are_distinct_objects() -> None:
    """A3: refresh and logout do not share a bucket."""
    names = ["LOGIN_IP", "LOGIN_ACCOUNT_FAILURES", "REGISTER_IP", "REFRESH_IP"]
    buckets = [getattr(rate_limit, n) for n in [*names, "LOGOUT_IP"]]

    assert len({id(b) for b in buckets}) == 5


# --- Reproduction (GH-4 review round 1): a slot is taken before the awaited work ---
# `check()` then `hit()` leaves a gap across an await; parallel logins all passed the
# check. `reserve(key)` takes a slot at once (or raises), `release(key)` gives it back
# when the attempt turns out not to count (a successful login, A4).


def test_reserve_takes_a_slot_at_once(clock: list[float]) -> None:
    limiter = FixedWindowLimiter(limit=3, window_s=60)

    for _ in range(3):
        limiter.reserve("a")  # no hit() in between: nothing has finished yet
    with pytest.raises(RateLimited) as caught:
        limiter.reserve("a")

    assert caught.value.status_code == 429
    assert 1 <= retry_after(caught.value) <= 60
    limiter.reserve("b")  # per key


def test_release_gives_the_slot_back(clock: list[float]) -> None:
    limiter = FixedWindowLimiter(limit=2, window_s=60)
    limiter.reserve("a")
    limiter.reserve("a")

    limiter.release("a")

    limiter.reserve("a")
    with pytest.raises(RateLimited):
        limiter.reserve("a")


def test_a_kept_reservation_counts_like_a_hit(clock: list[float]) -> None:
    limiter = FixedWindowLimiter(limit=2, window_s=60)
    limiter.reserve("a")
    limiter.reserve("a")

    with pytest.raises(RateLimited):
        limiter.check("a")

    clock[0] += 61
    limiter.check("a")
    limiter.reserve("a")


def test_release_after_the_window_ended_does_not_go_below_zero(
    clock: list[float],
) -> None:
    limiter = FixedWindowLimiter(limit=2, window_s=60)
    limiter.reserve("a")
    clock[0] += 61

    limiter.release("a")  # the old window is gone: nothing to give back

    limiter.reserve("a")
    limiter.reserve("a")
    with pytest.raises(RateLimited):
        limiter.reserve("a")
