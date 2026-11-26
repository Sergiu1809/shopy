"""Cost rules for paid calls (GH-13 B3, N8, N9, A7; PATTERN-011, D-019, Q-013).

Parsing and cost math are pure; the UTC-day sum runs in the rolled-back `session`.
Messages name the variable, never its value.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.usage.ledger import (
    ConfigError,
    daily_cap_eur,
    estimate_cost_eur,
    spent_today_eur,
    unit_price_eur,
)

CAP = "DAILY_COST_CAP_EUR"
PRICE = "PRICE_OPENAI_EMBEDDING_EUR_PER_1M_TOKENS"


# --- the daily cap (Q-013: 1 EUR when unset) --------------------------------------


@pytest.mark.parametrize("env", [{}, {CAP: ""}], ids=["unset", "empty"])
def test_cap_defaults_to_one_euro(env: dict[str, str]) -> None:
    assert daily_cap_eur(env) == Decimal("1")


@pytest.mark.parametrize(("value", "cap"), [("2.5", "2.5"), ("0", "0"), ("1", "1")])
def test_cap_is_read_as_a_decimal(value: str, cap: str) -> None:
    result = daily_cap_eur({CAP: value})

    assert isinstance(result, Decimal)
    assert result == Decimal(cap)


@pytest.mark.parametrize("value", ["not-a-number", "-1", "-0.01", "NaN"])
def test_invalid_cap_fails_closed(value: str) -> None:
    with pytest.raises(ConfigError) as raised:
        daily_cap_eur({CAP: value})

    assert str(raised.value) == f"{CAP} is invalid"


# --- unit prices (B3: never defaulted in code) ------------------------------------


@pytest.mark.parametrize("env", [{}, {PRICE: ""}], ids=["unset", "empty"])
def test_missing_price_is_not_set(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError) as raised:
        unit_price_eur(env, PRICE)

    assert str(raised.value) == f"{PRICE} is not set"


@pytest.mark.parametrize("value", ["not-a-number", "0", "-0.02", "NaN"])
def test_invalid_price(value: str) -> None:
    with pytest.raises(ConfigError) as raised:
        unit_price_eur({PRICE: value}, PRICE)

    assert str(raised.value) == f"{PRICE} is invalid"


def test_price_is_read_as_a_decimal() -> None:
    price = unit_price_eur({PRICE: "0.02"}, PRICE)

    assert isinstance(price, Decimal)
    assert price == Decimal("0.02")


# --- cost math (numeric(12,8)) ------------------------------------------------------


@pytest.mark.parametrize(
    ("units", "price", "cost"),
    [
        (1234, "0.02", "0.00002468"),
        (1_000_000, "0.02", "0.02000000"),
        (1, "0.02", "0.00000002"),
        (0, "0.02", "0.00000000"),
        (250_000, "0.13", "0.03250000"),
    ],
)
def test_cost_math(units: int, price: str, cost: str) -> None:
    result = estimate_cost_eur(units, Decimal(price))

    assert isinstance(result, Decimal)
    assert result == Decimal(cost)
    assert result.as_tuple().exponent == -8


# --- the global spend of the current UTC day ----------------------------------------


async def add_cost(
    session: AsyncSession, cost: str, created_at_sql: str, provider: str = "openai"
) -> None:
    # `created_at_sql` is one of the fixed expressions below, never input.
    await session.execute(
        text(
            "INSERT INTO usage_ledger (provider, operation, units, estimated_cost_eur,"
            f" created_at) VALUES (:provider, 'embedding', 1, :cost, {created_at_sql})"
        ),
        {"provider": provider, "cost": Decimal(cost)},
    )


START_OF_UTC_DAY = "date_trunc('day', now(), 'UTC')"


async def test_nothing_spent_is_zero(session: AsyncSession) -> None:
    spent = await spent_today_eur(session)

    assert isinstance(spent, Decimal)
    assert spent == 0


async def test_spend_sums_every_provider_of_the_utc_day(session: AsyncSession) -> None:
    await add_cost(session, "0.25000000", "now()")
    await add_cost(session, "0.12500000", "now()", provider="anthropic")
    await add_cost(session, "0.00000001", START_OF_UTC_DAY)  # counts (>=)
    await add_cost(session, "5.00000000", f"{START_OF_UTC_DAY} - interval '1 second'")
    await add_cost(session, "7.00000000", "now() - interval '2 days'")

    assert await spent_today_eur(session) == Decimal("0.37500001")
