from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Category(Base):
    __tablename__ = "categories"
    # Leads with store_id, so it also serves as the store_id foreign key index.
    __table_args__ = (UniqueConstraint("store_id", "slug"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    store_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("stores.id", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("rating_avg >= 0 AND rating_avg <= 5", name="rating_avg_range"),
        CheckConstraint("rating_count >= 0", name="rating_count_non_negative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    store_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("stores.id", ondelete="RESTRICT"), index=True
    )
    category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("categories.id", ondelete="RESTRICT"), index=True
    )
    brand: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'")
    )
    # NULL until the product has reviews; GH-5 computes it at seed time.
    rating_avg: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    rating_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # Incremented by app code (GH-6); no trigger, no version_id_col.
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    # Filled by the reindex worker (P2, D-006).
    content_hash: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProductVariant(Base):
    __tablename__ = "product_variants"
    __table_args__ = (
        CheckConstraint("price_minor >= 0", name="price_minor_non_negative"),
        CheckConstraint("stock >= 0", name="stock_non_negative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    sku: Mapped[str] = mapped_column(Text, unique=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'")
    )
    # Money in bani (PATTERN-001).
    price_minor: Mapped[int] = mapped_column(Integer)
    stock: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class ProductImage(Base):
    __tablename__ = "product_images"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    storage_key: Mapped[str] = mapped_column(Text)
    alt_text: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    author_display_name: Mapped[str] = mapped_column(Text)
    rating: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class StorePolicy(Base):
    __tablename__ = "store_policies"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('shipping', 'returns', 'warranty', 'payment', 'size_guide')",
            name="kind",
        ),
        # Leads with store_id, so it also serves as the store_id foreign key index.
        UniqueConstraint("store_id", "kind"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    store_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("stores.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
