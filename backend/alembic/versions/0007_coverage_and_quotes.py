"""phase 1 session 5: business vehicle coverage + quotes.

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-16

Session 5. Adds:

1. `business_vehicle_brands` pivot — a business declares which vehicle
   brands (optionally filtered by year range + steering side) it
   services. Composite PK on (business_id, vehicle_brand_id) — one
   coverage entry per brand per business. Matches the `vehicle_ownerships`
   pattern. Reuses the existing `vehicle_steering_side` enum from 0006.

2. `quotes` table — a business's price quote for a driver's part
   search. Surrogate UUID PK + tenant_id column (= business_id). Unique
   on (part_search_id, tenant_id) — one quote per business per search.
   Quote condition enum: new / used / imported.

Downgrade drops both tables and the new enum in reverse order. The
`vehicle_steering_side` enum survives because 0006 still owns it.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. business_vehicle_brands — pivot (composite PK)
    # ------------------------------------------------------------------
    # The vehicle_steering_side enum already exists (migration 0006).
    # create_type=False suppresses `CREATE TYPE` emission so reuse is safe.
    steering_side_enum = postgresql.ENUM(
        "LHD",
        "RHD",
        name="vehicle_steering_side",
        create_type=False,
    )

    op.create_table(
        "business_vehicle_brands",
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vehicle_brand_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("year_start", sa.Integer(), nullable=True),
        sa.Column("year_end", sa.Integer(), nullable=True),
        sa.Column("steering_side", steering_side_enum, nullable=True),
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
            ["business_id"],
            ["businesses.id"],
            name="fk_business_vehicle_brands_business_id_businesses",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_brand_id"],
            ["vehicle_brands.id"],
            name="fk_business_vehicle_brands_vehicle_brand_id_vehicle_brands",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "business_id",
            "vehicle_brand_id",
            name="pk_business_vehicle_brands",
        ),
    )
    # Reverse lookup "which businesses service this brand" (future feature).
    op.create_index(
        "ix_business_vehicle_brands_vehicle_brand_id",
        "business_vehicle_brands",
        ["vehicle_brand_id"],
    )

    # ------------------------------------------------------------------
    # 2. quotes
    # ------------------------------------------------------------------
    quote_condition_enum = postgresql.ENUM(
        "new",
        "used",
        "imported",
        name="quote_condition",
        create_type=False,
    )
    quote_condition_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "quotes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("part_search_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("price_mnt", sa.Integer(), nullable=False),
        sa.Column("condition", quote_condition_enum, nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "media_urls",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
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
            name="fk_quotes_tenant_id_businesses",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["part_search_id"],
            ["part_search_requests.id"],
            name="fk_quotes_part_search_id_part_search_requests",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_quotes"),
        sa.UniqueConstraint(
            "part_search_id",
            "tenant_id",
            name="uq_quotes_part_search_id_tenant_id",
        ),
    )
    op.create_index("ix_quotes_tenant_id", "quotes", ["tenant_id"])
    op.create_index("ix_quotes_part_search_id", "quotes", ["part_search_id"])


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    # quotes
    op.drop_index("ix_quotes_part_search_id", table_name="quotes")
    op.drop_index("ix_quotes_tenant_id", table_name="quotes")
    op.drop_table("quotes")
    quote_condition_enum = postgresql.ENUM(
        "new",
        "used",
        "imported",
        name="quote_condition",
    )
    quote_condition_enum.drop(op.get_bind(), checkfirst=True)

    # business_vehicle_brands
    op.drop_index(
        "ix_business_vehicle_brands_vehicle_brand_id",
        table_name="business_vehicle_brands",
    )
    op.drop_table("business_vehicle_brands")
