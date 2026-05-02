"""phase 1 session 6: reservations, sales, reviews, media platform.

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-02

Session 6 closes the marketplace transaction loop:

1. `media_assets` — single source of truth for uploaded blobs (presigned
   PUT/GET via MinIO). Marketplace tables reference asset IDs instead of
   opaque URL strings.

2. `reservations` — driver reserves a quote for a 24-hour hold. Status
   enum (active|cancelled|expired|completed). Unique on `quote_id` so a
   quote can only be reserved once.

3. `sales` — created when a business marks a reservation completed.
   Denormalizes `driver_id`, `tenant_id`, `part_search_id`, and
   `price_mnt` from the reservation/quote chain so the sales feed can
   answer common queries without joins.

4. `reviews` — bidirectional. Public buyer→seller (rating + body) and
   private seller→buyer (rating only, used for moderation flags). One
   review per direction per sale.

5. `media_assets.purpose` extends without breaking — the enum starts with
   `part_search|quote|review` but session 9 will add `service_log`.

Note: this migration also drops the legacy `media_urls` jsonb columns from
`part_search_requests` and `quotes`. Those columns were stub strings since
session 4 with no real consumer. We replace them with `media_asset_ids`
jsonb arrays of UUID — typed strings the new media platform validates.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. media_assets
    # ------------------------------------------------------------------
    media_asset_status_enum = postgresql.ENUM(
        "pending",
        "active",
        "deleted",
        name="media_asset_status",
        create_type=False,
    )
    media_asset_status_enum.create(op.get_bind(), checkfirst=True)

    media_asset_purpose_enum = postgresql.ENUM(
        "part_search",
        "quote",
        "review",
        name="media_asset_purpose",
        create_type=False,
    )
    media_asset_purpose_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "media_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bucket", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("purpose", media_asset_purpose_enum, nullable=False),
        sa.Column("status", media_asset_status_enum, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name="fk_media_assets_owner_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_media_assets"),
        sa.UniqueConstraint("object_key", name="uq_media_assets_object_key"),
    )
    op.create_index(
        "ix_media_assets_owner_id_created_at",
        "media_assets",
        ["owner_id", sa.text("created_at DESC")],
    )

    # ------------------------------------------------------------------
    # 2. Replace `media_urls` jsonb with `media_asset_ids` jsonb on the
    #    two tables that already had a stubbed media field. Both columns
    #    are session-4/5 additions that no production client consumes,
    #    so a hard rename is fine.
    # ------------------------------------------------------------------
    op.drop_column("part_search_requests", "media_urls")
    op.add_column(
        "part_search_requests",
        sa.Column(
            "media_asset_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.drop_column("quotes", "media_urls")
    op.add_column(
        "quotes",
        sa.Column(
            "media_asset_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    # ------------------------------------------------------------------
    # 3. reservations
    # ------------------------------------------------------------------
    reservation_status_enum = postgresql.ENUM(
        "active",
        "cancelled",
        "expired",
        "completed",
        name="reservation_status",
        create_type=False,
    )
    reservation_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quote_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("part_search_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("driver_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", reservation_status_enum, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["businesses.id"],
            name="fk_reservations_tenant_id_businesses",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["quote_id"],
            ["quotes.id"],
            name="fk_reservations_quote_id_quotes",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["part_search_id"],
            ["part_search_requests.id"],
            name="fk_reservations_part_search_id_part_search_requests",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"],
            ["users.id"],
            name="fk_reservations_driver_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reservations"),
        sa.UniqueConstraint("quote_id", name="uq_reservations_quote_id"),
    )
    op.create_index("ix_reservations_tenant_id", "reservations", ["tenant_id"])
    op.create_index(
        "ix_reservations_driver_id_created_at",
        "reservations",
        ["driver_id", sa.text("created_at DESC")],
    )
    # Compound index for the expiry sweep — partial on `active` keeps it tiny.
    op.create_index(
        "ix_reservations_active_expires_at",
        "reservations",
        ["expires_at"],
        postgresql_where=sa.text("status = 'active'"),
    )
    # Tenant inbox: business sees its active reservations newest first.
    op.create_index(
        "ix_reservations_tenant_status_created_at",
        "reservations",
        ["tenant_id", "status", sa.text("created_at DESC")],
    )

    # ------------------------------------------------------------------
    # 4. sales
    # ------------------------------------------------------------------
    op.create_table(
        "sales",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reservation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quote_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("part_search_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("driver_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("price_mnt", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["businesses.id"],
            name="fk_sales_tenant_id_businesses",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id"],
            ["reservations.id"],
            name="fk_sales_reservation_id_reservations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["quote_id"],
            ["quotes.id"],
            name="fk_sales_quote_id_quotes",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["part_search_id"],
            ["part_search_requests.id"],
            name="fk_sales_part_search_id_part_search_requests",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["driver_id"],
            ["users.id"],
            name="fk_sales_driver_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sales"),
        sa.UniqueConstraint("reservation_id", name="uq_sales_reservation_id"),
    )
    op.create_index("ix_sales_tenant_id", "sales", ["tenant_id"])
    op.create_index(
        "ix_sales_tenant_id_created_at",
        "sales",
        ["tenant_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_sales_driver_id_created_at",
        "sales",
        ["driver_id", sa.text("created_at DESC")],
    )

    # ------------------------------------------------------------------
    # 5. reviews
    # ------------------------------------------------------------------
    review_direction_enum = postgresql.ENUM(
        "buyer_to_seller",
        "seller_to_buyer",
        name="review_direction",
        create_type=False,
    )
    review_direction_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sale_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("direction", review_direction_enum, nullable=False),
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_business_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["sale_id"],
            ["sales.id"],
            name="fk_reviews_sale_id_sales",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["users.id"],
            name="fk_reviews_author_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subject_business_id"],
            ["businesses.id"],
            name="fk_reviews_subject_business_id_businesses",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subject_user_id"],
            ["users.id"],
            name="fk_reviews_subject_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reviews"),
        sa.UniqueConstraint("sale_id", "direction", name="uq_reviews_sale_id_direction"),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_reviews_rating_range"),
        # Exactly one of (subject_business_id, subject_user_id) is set.
        sa.CheckConstraint(
            "(subject_business_id IS NOT NULL)::int + (subject_user_id IS NOT NULL)::int = 1",
            name="ck_reviews_subject_xor",
        ),
    )
    op.create_index(
        "ix_reviews_subject_business_id_created_at",
        "reviews",
        ["subject_business_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("subject_business_id IS NOT NULL"),
    )
    op.create_index(
        "ix_reviews_subject_user_id_created_at",
        "reviews",
        ["subject_user_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("subject_user_id IS NOT NULL"),
    )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    # reviews
    op.drop_index("ix_reviews_subject_user_id_created_at", table_name="reviews")
    op.drop_index("ix_reviews_subject_business_id_created_at", table_name="reviews")
    op.drop_table("reviews")
    review_direction_enum = postgresql.ENUM(
        "buyer_to_seller",
        "seller_to_buyer",
        name="review_direction",
    )
    review_direction_enum.drop(op.get_bind(), checkfirst=True)

    # sales
    op.drop_index("ix_sales_driver_id_created_at", table_name="sales")
    op.drop_index("ix_sales_tenant_id_created_at", table_name="sales")
    op.drop_index("ix_sales_tenant_id", table_name="sales")
    op.drop_table("sales")

    # reservations
    op.drop_index("ix_reservations_tenant_status_created_at", table_name="reservations")
    op.drop_index("ix_reservations_active_expires_at", table_name="reservations")
    op.drop_index("ix_reservations_driver_id_created_at", table_name="reservations")
    op.drop_index("ix_reservations_tenant_id", table_name="reservations")
    op.drop_table("reservations")
    reservation_status_enum = postgresql.ENUM(
        "active",
        "cancelled",
        "expired",
        "completed",
        name="reservation_status",
    )
    reservation_status_enum.drop(op.get_bind(), checkfirst=True)

    # quotes / part_search_requests rename-back
    op.drop_column("quotes", "media_asset_ids")
    op.add_column(
        "quotes",
        sa.Column(
            "media_urls",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.drop_column("part_search_requests", "media_asset_ids")
    op.add_column(
        "part_search_requests",
        sa.Column(
            "media_urls",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    # media_assets
    op.drop_index("ix_media_assets_owner_id_created_at", table_name="media_assets")
    op.drop_table("media_assets")
    media_asset_purpose_enum = postgresql.ENUM(
        "part_search",
        "quote",
        "review",
        name="media_asset_purpose",
    )
    media_asset_purpose_enum.drop(op.get_bind(), checkfirst=True)
    media_asset_status_enum = postgresql.ENUM(
        "pending",
        "active",
        "deleted",
        name="media_asset_status",
    )
    media_asset_status_enum.drop(op.get_bind(), checkfirst=True)
