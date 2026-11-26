"""indexing and usage ledger: kb_chunks, reindex_outbox, usage_ledger (GH-13)

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-26 22:29:19.350025

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # The vector extension exists since 0001. No HNSW index and no tsv fill yet:
    # GH-14 owns search (B5). No unique index on pending outbox rows (N4).
    op.create_table(
        "reindex_outbox",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "enqueued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "attempts", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "reason IN ('create', 'update', 'delete', 'full')",
            name=op.f("ck_reindex_outbox_reason"),
        ),
        sa.CheckConstraint(
            "source_type IN ('product', 'reviews', 'policy')",
            name=op.f("ck_reindex_outbox_source_type"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reindex_outbox")),
    )
    op.create_table(
        "kb_chunks",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("store_id", sa.BigInteger(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(dim=1536), nullable=False),
        sa.Column("tsv", postgresql.TSVECTOR(), nullable=True),
        sa.Column("source_version", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "source_type IN ('product', 'reviews', 'policy')",
            name=op.f("ck_kb_chunks_source_type"),
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name=op.f("fk_kb_chunks_store_id_stores"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kb_chunks")),
        sa.UniqueConstraint(
            "source_type",
            "source_id",
            "chunk_index",
            name=op.f("uq_kb_chunks_source_type_source_id_chunk_index"),
        ),
    )
    op.create_index(
        op.f("ix_kb_chunks_store_id"), "kb_chunks", ["store_id"], unique=False
    )
    op.create_table(
        "usage_ledger",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("units", sa.BigInteger(), nullable=False),
        sa.Column(
            "estimated_cost_eur", sa.Numeric(precision=12, scale=8), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "operation IN ('embedding')", name=op.f("ck_usage_ledger_operation")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_usage_ledger_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_ledger")),
    )
    op.create_index(
        op.f("ix_usage_ledger_created_at"), "usage_ledger", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_usage_ledger_user_id"), "usage_ledger", ["user_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Drops the three tables and keeps the extensions (as 0001, Q10).
    op.drop_index(op.f("ix_usage_ledger_user_id"), table_name="usage_ledger")
    op.drop_index(op.f("ix_usage_ledger_created_at"), table_name="usage_ledger")
    op.drop_table("usage_ledger")
    op.drop_index(op.f("ix_kb_chunks_store_id"), table_name="kb_chunks")
    op.drop_table("kb_chunks")
    op.drop_table("reindex_outbox")
