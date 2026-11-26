"""Every paid call, for the daily cap and the cost views (GH-13; D-019, PATTERN-011)."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Numeric,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UsageLedger(Base):
    __tablename__ = "usage_ledger"
    __table_args__ = (
        # P3 widens this with its operations; provider has no CHECK (A2).
        CheckConstraint("operation IN ('embedding')", name="operation"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    # NULL for work no user caused (the reindex worker); kept when a user goes (N13).
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    provider: Mapped[str] = mapped_column(Text)
    operation: Mapped[str] = mapped_column(Text)
    # Tokens for embeddings.
    units: Mapped[int] = mapped_column(BigInteger)
    # EUR, fractions of a cent (B3).
    estimated_cost_eur: Mapped[Decimal] = mapped_column(Numeric(12, 8))
    # Indexed for the sum of the current UTC day.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
