"""Every model, so Base.metadata is complete for Alembic and the tests."""

from app.models.base import Base
from app.models.catalog import (
    Category,
    Product,
    ProductImage,
    ProductVariant,
    Review,
    StorePolicy,
)
from app.models.indexing import KbChunk, ReindexOutbox
from app.models.store import Store
from app.models.usage import UsageLedger
from app.models.user import Address, RefreshToken, User, UserPreferences

__all__ = [
    "Address",
    "Base",
    "Category",
    "KbChunk",
    "Product",
    "ProductImage",
    "ProductVariant",
    "RefreshToken",
    "ReindexOutbox",
    "Review",
    "Store",
    "StorePolicy",
    "UsageLedger",
    "User",
    "UserPreferences",
]
