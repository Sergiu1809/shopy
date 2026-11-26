"""`python -m seed.seed` (`make seed`): load the demo store, no LLM and no key (D-023).

Inserts only what is missing, in file order, in one transaction (GH-5 Q2, Q9):
- a store row means the catalog is already seeded, so it is skipped whole;
- a user is skipped when their email exists (case-insensitive), with their addresses
  and preferences untouched.
Inserting the catalog also enqueues a full reindex in the same transaction (GH-13 B4,
PATTERN-010); the reindex worker embeds it.
Passwords come only from SEED_ADMIN_PASSWORD / SEED_CUSTOMER_PASSWORD (PATTERN-013)
and must meet the register rule; they are checked before any connection.
"""

import asyncio
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import hash_password
from app.db import create_engine, create_sessionmaker
from app.indexing.outbox import enqueue_full_reindex
from app.models import (
    Address,
    Category,
    Product,
    ProductVariant,
    Review,
    Store,
    StorePolicy,
    User,
    UserPreferences,
)
from app.schemas.auth import Password
from seed.schema import (
    CATALOG_PATH,
    USERS_PATH,
    CatalogFile,
    UserIn,
    UsersFile,
    load_catalog,
    load_users,
)
from seed.validate_catalog import describe

PASSWORD_VARIABLES = {
    "admin": "SEED_ADMIN_PASSWORD",
    "customer": "SEED_CUSTOMER_PASSWORD",
}
PASSWORD_RULE = "8–128 characters, at least one uppercase letter and one digit"
_password = TypeAdapter(Password)


class SeedError(Exception):
    """The seed refuses to run; the message never contains a secret."""


@dataclass
class SeedReport:
    catalog_inserted: bool = False
    categories: int = 0
    products: int = 0
    variants: int = 0
    reviews: int = 0
    policies: int = 0
    users: list[tuple[str, str, bool]] = field(default_factory=list)  # email, role, new


def seed_passwords(env: Mapping[str, str]) -> dict[str, str]:
    """The password per role, or SeedError naming the variable (never the value)."""
    passwords = {}
    for role, variable in PASSWORD_VARIABLES.items():
        value = env.get(variable)
        if not value:
            raise SeedError(f"{variable} is not set. It must have {PASSWORD_RULE}.")
        try:
            _password.validate_python(value)
        except ValidationError:
            # `from None`: the ValidationError would carry the value.
            raise SeedError(
                f"{variable} does not meet the password rule: {PASSWORD_RULE}."
            ) from None
        passwords[role] = value
    return passwords


def rating_summary(ratings: Sequence[int]) -> tuple[Decimal | None, int]:
    """(rating_avg half-up to 2 decimals, rating_count); avg None without ratings."""
    if not ratings:
        return None, 0
    average = Decimal(sum(ratings)) / len(ratings)
    return average.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), len(ratings)


async def load(
    session: AsyncSession,
    catalog: CatalogFile,
    users: UsersFile,
    passwords: Mapping[str, str],
) -> SeedReport:
    """Add what is missing and flush; never commit (the caller owns the transaction)."""
    report = SeedReport()
    if await session.scalar(select(Store.id).limit(1)) is None:
        await _insert_catalog(session, catalog, report)
    for user in users.users:
        existing = await session.scalar(
            select(User.id).where(func.lower(User.email) == user.email.lower())
        )
        if existing is None:
            await _insert_user(session, user, passwords[user.role])
        report.users.append((user.email, user.role, existing is None))
    return report


async def _insert_catalog(
    session: AsyncSession, catalog: CatalogFile, report: SeedReport
) -> None:
    """File order, flushed step by step, so IDs follow the file (D-024)."""
    store = Store(name=catalog.store.name, currency=catalog.store.currency)
    session.add(store)
    await session.flush()

    categories = [
        Category(store_id=store.id, slug=c.slug, name=c.name)
        for c in catalog.categories
    ]
    session.add_all(categories)
    await session.flush()

    for category, category_in in zip(categories, catalog.categories, strict=True):
        for item in category_in.products:
            rating_avg, rating_count = rating_summary([r.rating for r in item.reviews])
            product = Product(
                store_id=store.id,
                category_id=category.id,
                brand=item.brand,
                name=item.name,
                description=item.description,
                attributes=item.attributes,
                rating_avg=rating_avg,
                rating_count=rating_count,
            )
            session.add(product)
            await session.flush()
            session.add_all(
                ProductVariant(
                    product_id=product.id,
                    sku=v.sku,
                    attributes=v.attributes,
                    price_minor=v.price_minor,
                    stock=v.stock,
                )
                for v in item.variants
            )
            await session.flush()
            # Bodies verbatim, never escaped or stripped (PATTERN-003, PATTERN-009).
            session.add_all(
                Review(
                    product_id=product.id,
                    author_display_name=r.author_display_name,
                    rating=r.rating,
                    title=r.title,
                    body=r.body,
                    created_at=r.created_at,
                )
                for r in item.reviews
            )
            await session.flush()
            report.products += 1
            report.variants += len(item.variants)
            report.reviews += len(item.reviews)

    session.add_all(
        StorePolicy(store_id=store.id, kind=p.kind, title=p.title, body=p.body)
        for p in catalog.policies
    )
    await session.flush()
    await enqueue_full_reindex(session)

    report.catalog_inserted = True
    report.categories = len(categories)
    report.policies = len(catalog.policies)


async def _insert_user(session: AsyncSession, user_in: UserIn, password: str) -> None:
    user = User(
        email=user_in.email, password_hash=hash_password(password), role=user_in.role
    )
    session.add(user)
    await session.flush()
    session.add_all(
        Address(
            user_id=user.id,
            label=a.label,
            full_name=a.full_name,
            phone=a.phone,
            street=a.street,
            city=a.city,
            county=a.county,
            postal_code=a.postal_code,
            is_default=a.is_default,
        )
        for a in user_in.addresses
    )
    if user_in.preferences is not None:
        session.add(
            UserPreferences(
                user_id=user.id,
                sizes=user_in.preferences.sizes,
                preferred_brands=user_in.preferences.preferred_brands,
            )
        )
    await session.flush()


async def _run(
    catalog: CatalogFile, users: UsersFile, passwords: Mapping[str, str]
) -> SeedReport:
    engine = create_engine()
    try:
        sessionmaker = create_sessionmaker(engine)
        async with sessionmaker() as session, session.begin():
            return await load(session, catalog, users, passwords)
    finally:
        await engine.dispose()


def _print_report(report: SeedReport) -> None:
    if report.catalog_inserted:
        print(
            f"Catalog: inserted 1 store, {report.categories} categories,"
            f" {report.products} products, {report.variants} variants,"
            f" {report.reviews} reviews, {report.policies} policies."
        )
    else:
        print("Catalog: already seeded, skipped.")
    for email, role, inserted in report.users:
        print(f"User {email} ({role}): {'inserted' if inserted else 'exists, skipped'}")


def main() -> int:
    """0 on success; 1 on a refused password or invalid files. Others propagate."""
    try:
        passwords = seed_passwords(os.environ)
    except SeedError as exc:
        print(f"seed: {exc}", file=sys.stderr)
        return 1
    try:
        catalog, users = load_catalog(CATALOG_PATH), load_users(USERS_PATH)
    except ValidationError as exc:
        print("seed: the seed files are invalid:", file=sys.stderr)
        print("\n".join(describe(str(exc.title), exc)), file=sys.stderr)
        return 1
    _print_report(asyncio.run(_run(catalog, users, passwords)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
