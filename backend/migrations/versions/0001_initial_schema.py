"""initial schema: extensions and the P1 tables (GH-3)

Revision ID: 0001
Revises:
Create Date: 2026-11-18 18:06:27.158466

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Also where no init script runs (e.g. Neon); the Compose db already has both.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.create_table(
        "stores",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "currency",
            sa.CHAR(length=3),
            server_default=sa.text("'RON'"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stores")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "role", sa.Text(), server_default=sa.text("'customer'"), nullable=False
        ),
        sa.Column("stripe_customer_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('customer', 'admin')", name=op.f("ck_users_role")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(
        "uq_users_email_lower",
        "users",
        [sa.literal_column("lower(email)")],
        unique=True,
    )
    op.create_table(
        "addresses",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=False),
        sa.Column("street", sa.Text(), nullable=False),
        sa.Column("city", sa.Text(), nullable=False),
        sa.Column("county", sa.Text(), nullable=False),
        sa.Column("postal_code", sa.Text(), nullable=False),
        sa.Column(
            "is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_addresses_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_addresses")),
    )
    op.create_index(
        op.f("ix_addresses_user_id"), "addresses", ["user_id"], unique=False
    )
    op.create_index(
        "uq_addresses_user_id_default",
        "addresses",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_table(
        "categories",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("store_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name=op.f("fk_categories_store_id_stores"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint(
            "store_id", "slug", name=op.f("uq_categories_store_id_slug")
        ),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False
    )
    op.create_table(
        "store_policies",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("store_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "kind IN ('shipping', 'returns', 'warranty', 'payment', 'size_guide')",
            name=op.f("ck_store_policies_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name=op.f("fk_store_policies_store_id_stores"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_store_policies")),
        sa.UniqueConstraint(
            "store_id", "kind", name=op.f("uq_store_policies_store_id_kind")
        ),
    )
    op.create_table(
        "user_preferences",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "sizes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "preferred_brands",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_preferences_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_preferences")),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("store_id", sa.BigInteger(), nullable=False),
        sa.Column("category_id", sa.BigInteger(), nullable=False),
        sa.Column("brand", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("rating_avg", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column(
            "rating_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "rating_avg >= 0 AND rating_avg <= 5",
            name=op.f("ck_products_rating_avg_range"),
        ),
        sa.CheckConstraint(
            "rating_count >= 0", name=op.f("ck_products_rating_count_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_products_category_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name=op.f("fk_products_store_id_stores"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
    )
    op.create_index(
        op.f("ix_products_category_id"), "products", ["category_id"], unique=False
    )
    op.create_index(
        op.f("ix_products_store_id"), "products", ["store_id"], unique=False
    )
    op.create_table(
        "product_images",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("alt_text", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_product_images_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_images")),
    )
    op.create_index(
        op.f("ix_product_images_product_id"),
        "product_images",
        ["product_id"],
        unique=False,
    )
    op.create_table(
        "product_variants",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("price_minor", sa.Integer(), nullable=False),
        sa.Column("stock", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "price_minor >= 0",
            name=op.f("ck_product_variants_price_minor_non_negative"),
        ),
        sa.CheckConstraint(
            "stock >= 0", name=op.f("ck_product_variants_stock_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_product_variants_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_variants")),
        sa.UniqueConstraint("sku", name=op.f("uq_product_variants_sku")),
    )
    op.create_index(
        op.f("ix_product_variants_product_id"),
        "product_variants",
        ["product_id"],
        unique=False,
    )
    op.create_table(
        "reviews",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("author_display_name", sa.Text(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "rating BETWEEN 1 AND 5", name=op.f("ck_reviews_rating_range")
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_reviews_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviews")),
    )
    op.create_index(
        op.f("ix_reviews_product_id"), "reviews", ["product_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Drops the tables in reverse dependency order and keeps the extensions (Q10).
    op.drop_index(op.f("ix_reviews_product_id"), table_name="reviews")
    op.drop_table("reviews")
    op.drop_index(op.f("ix_product_variants_product_id"), table_name="product_variants")
    op.drop_table("product_variants")
    op.drop_index(op.f("ix_product_images_product_id"), table_name="product_images")
    op.drop_table("product_images")
    op.drop_index(op.f("ix_products_store_id"), table_name="products")
    op.drop_index(op.f("ix_products_category_id"), table_name="products")
    op.drop_table("products")
    op.drop_table("user_preferences")
    op.drop_table("store_policies")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_table("categories")
    op.drop_index(
        "uq_addresses_user_id_default",
        table_name="addresses",
        postgresql_where=sa.text("is_default"),
    )
    op.drop_index(op.f("ix_addresses_user_id"), table_name="addresses")
    op.drop_table("addresses")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_table("users")
    op.drop_table("stores")
