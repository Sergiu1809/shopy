"""Cost control for paid calls (PATTERN-011, D-019; GH-13 B3, N8, N9; Q-013).

Before a paid call: the cap and the unit price, read from the environment. After it:
one usage_ledger row. Messages name a variable, never its value.
"""

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UsageLedger

DAILY_COST_CAP_VARIABLE = "DAILY_COST_CAP_EUR"
# Q-013: 1 EUR per UTC day, all providers, until the question is answered.
DEFAULT_DAILY_COST_CAP_EUR = Decimal("1")
COST_PLACES = Decimal("0.00000001")  # numeric(12,8)


class ConfigError(Exception):
    """A missing or invalid cost setting: no paid call until it is fixed."""


def _decimal(raw: str) -> Decimal | None:
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def daily_cap_eur(env: Mapping[str, str]) -> Decimal:
    """The global cap per UTC day; 1 EUR when unset or empty; invalid fails closed."""
    raw = env.get(DAILY_COST_CAP_VARIABLE, "").strip()
    if not raw:
        return DEFAULT_DAILY_COST_CAP_EUR
    cap = _decimal(raw)
    if cap is None or cap < 0:
        raise ConfigError(f"{DAILY_COST_CAP_VARIABLE} is invalid")
    return cap


def unit_price_eur(env: Mapping[str, str], name: str) -> Decimal:
    """A `PRICE_*` value, never defaulted in code: a price of 0 would void the cap."""
    raw = env.get(name, "").strip()
    if not raw:
        raise ConfigError(f"{name} is not set")
    price = _decimal(raw)
    if price is None or price <= 0:
        raise ConfigError(f"{name} is invalid")
    return price


def estimate_cost_eur(units: int, price_per_1m: Decimal) -> Decimal:
    """Units (tokens) at a price per million units, to 8 places."""
    return (Decimal(units) * price_per_1m / 1_000_000).quantize(COST_PLACES)


async def spent_today_eur(session: AsyncSession) -> Decimal:
    """Everything spent since the start of the current UTC day, all providers."""
    start_of_day = func.date_trunc("day", func.now(), "UTC")
    spent = await session.scalar(
        select(func.coalesce(func.sum(UsageLedger.estimated_cost_eur), 0)).where(
            UsageLedger.created_at >= start_of_day
        )
    )
    return Decimal(spent or 0)


async def record(
    session: AsyncSession,
    *,
    provider: str,
    operation: str,
    units: int,
    estimated_cost_eur: Decimal,
    user_id: int | None = None,
) -> None:
    """One ledger row in the caller's transaction (the caller commits it at once)."""
    session.add(
        UsageLedger(
            user_id=user_id,
            provider=provider,
            operation=operation,
            units=units,
            estimated_cost_eur=estimated_cost_eur,
        )
    )
    await session.flush()
