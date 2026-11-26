"""The search index and its outbox (GH-13; brief §7, §11; D-006, PATTERN-010)."""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# text-embedding-3-small (D-009); the column refuses any other length.
EMBEDDING_DIM = 1536


class KbChunk(Base):
    __tablename__ = "kb_chunks"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('product', 'reviews', 'policy')", name="source_type"
        ),
        # One chunk set per source; the worker replaces it whole (A1).
        UniqueConstraint("source_type", "source_id", "chunk_index"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    store_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("stores.id", ondelete="RESTRICT"), index=True
    )
    source_type: Mapped[str] = mapped_column(Text)
    # No FK: three source tables; a deleted source's chunks wait for the worker (B6).
    source_id: Mapped[int] = mapped_column(BigInteger)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    # Filled by GH-14, which owns the text search configuration (B5).
    tsv: Mapped[str | None] = mapped_column(TSVECTOR)
    # products.version or store_policies.version; NULL for reviews (N2).
    source_version: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(Text)


class ReindexOutbox(Base):
    """One row per source to rebuild; duplicates are allowed (N4)."""

    __tablename__ = "reindex_outbox"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('product', 'reviews', 'policy')", name="source_type"
        ),
        CheckConstraint(
            "reason IN ('create', 'update', 'delete', 'full')", name="reason"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    source_type: Mapped[str] = mapped_column(Text)
    source_id: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(Text)
    enqueued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
