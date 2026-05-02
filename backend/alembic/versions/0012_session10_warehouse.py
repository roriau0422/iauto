"""phase 2 session 10: warehouse + business_members.

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-02

Phase 2 opens with multi-staff business membership and a warehouse
inventory model:

1. `business_members` — (business_id, user_id) composite PK pivot.
   Role enum spans owner / manager / staff. The phase-1 1:1
   `businesses.owner_id` invariant survives — the owner row is just
   the canonical default; business_members is the source of truth
   for access checks from session 10 onward.

2. `warehouse_skus` — tenant-scoped catalog of stocked SKUs. Reuses
   the `quote_condition` enum (new / used / imported) so the
   marketplace-side coverage and the warehouse-side stock share a
   vocabulary.

3. `warehouse_stock_movements` — append-only inventory ledger.
   `kind` (receive / issue / adjust) plus a denormalized
   `signed_quantity` column so `SUM()` can compute on_hand without
   a CASE branch.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. business_members
    # ------------------------------------------------------------------
    business_member_role_enum = postgresql.ENUM(
        "owner",
        "manager",
        "staff",
        name="business_member_role",
        create_type=False,
    )
    business_member_role_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "business_members",
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", business_member_role_enum, nullable=False),
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
            name="fk_business_members_business_id_businesses",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_business_members_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "business_id", "user_id", name="pk_business_members"
        ),
    )
    op.create_index(
        "ix_business_members_user_id", "business_members", ["user_id"]
    )

    # Backfill: every existing business gets its `owner_id` rolled into the
    # pivot as the canonical owner. Idempotent via ON CONFLICT.
    op.execute(
        """
        INSERT INTO business_members (business_id, user_id, role, created_at, updated_at)
        SELECT id, owner_id, 'owner', now(), now()
        FROM businesses
        ON CONFLICT (business_id, user_id) DO NOTHING
        """
    )

    # ------------------------------------------------------------------
    # 2. warehouse_skus
    # ------------------------------------------------------------------
    quote_condition_enum = postgresql.ENUM(
        "new",
        "used",
        "imported",
        name="quote_condition",
        create_type=False,
    )

    op.create_table(
        "warehouse_skus",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sku_code", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("vehicle_brand_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("vehicle_model_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("condition", quote_condition_enum, nullable=False),
        sa.Column("unit_price_mnt", sa.Integer(), nullable=True),
        sa.Column("low_stock_threshold", sa.Integer(), nullable=True),
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
            name="fk_warehouse_skus_tenant_id_businesses",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_brand_id"],
            ["vehicle_brands.id"],
            name="fk_warehouse_skus_vehicle_brand_id_vehicle_brands",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_model_id"],
            ["vehicle_models.id"],
            name="fk_warehouse_skus_vehicle_model_id_vehicle_models",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_warehouse_skus"),
        sa.UniqueConstraint(
            "tenant_id", "sku_code", name="uq_warehouse_skus_tenant_id_sku_code"
        ),
    )
    op.create_index("ix_warehouse_skus_tenant_id", "warehouse_skus", ["tenant_id"])
    op.create_index(
        "ix_warehouse_skus_tenant_id_created_at",
        "warehouse_skus",
        ["tenant_id", sa.text("created_at DESC")],
    )
    op.execute(
        "CREATE INDEX ix_warehouse_skus_display_name_trgm "
        "ON warehouse_skus USING gin (display_name gin_trgm_ops)"
    )

    # ------------------------------------------------------------------
    # 3. warehouse_stock_movements
    # ------------------------------------------------------------------
    movement_kind_enum = postgresql.ENUM(
        "receive",
        "issue",
        "adjust",
        name="warehouse_movement_kind",
        create_type=False,
    )
    movement_kind_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "warehouse_stock_movements",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Nullable so a zero-on_hand SKU delete doesn't fight the FK.
        # The service requires on_hand=0 before allowing the delete, so
        # SUM(signed_quantity) is preserved across the deletion boundary.
        sa.Column("sku_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", movement_kind_enum, nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("signed_quantity", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sale_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["businesses.id"],
            name="fk_warehouse_stock_movements_tenant_id_businesses",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sku_id"],
            ["warehouse_skus.id"],
            name="fk_warehouse_stock_movements_sku_id_warehouse_skus",
            # SET NULL preserves the movement history when an owner deletes
            # a zero-on_hand SKU. The service requires on_hand=0 before
            # delete, so the historical sum stays at zero across the
            # deletion boundary.
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_warehouse_stock_movements_actor_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sale_id"],
            ["sales.id"],
            name="fk_warehouse_stock_movements_sale_id_sales",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_warehouse_stock_movements"),
        sa.CheckConstraint(
            "quantity > 0", name="ck_warehouse_stock_movements_quantity_positive"
        ),
        sa.CheckConstraint(
            "(kind = 'receive' AND signed_quantity = quantity) "
            "OR (kind = 'issue' AND signed_quantity = -quantity) "
            "OR (kind = 'adjust' AND ABS(signed_quantity) = quantity)",
            name="ck_warehouse_stock_movements_signed_quantity_consistent",
        ),
    )
    op.create_index(
        "ix_warehouse_stock_movements_tenant_id_sku_id_created_at",
        "warehouse_stock_movements",
        ["tenant_id", "sku_id", sa.text("created_at DESC")],
    )

    # Suppress the ENUM that wasn't owned by this migration but is reused
    # via reference (quote_condition is owned by 0007).
    del quote_condition_enum


def downgrade() -> None:
    op.drop_index(
        "ix_warehouse_stock_movements_tenant_id_sku_id_created_at",
        table_name="warehouse_stock_movements",
    )
    op.drop_table("warehouse_stock_movements")
    movement_kind_enum = postgresql.ENUM(
        "receive",
        "issue",
        "adjust",
        name="warehouse_movement_kind",
    )
    movement_kind_enum.drop(op.get_bind(), checkfirst=True)

    op.execute("DROP INDEX IF EXISTS ix_warehouse_skus_display_name_trgm")
    op.drop_index(
        "ix_warehouse_skus_tenant_id_created_at", table_name="warehouse_skus"
    )
    op.drop_index("ix_warehouse_skus_tenant_id", table_name="warehouse_skus")
    op.drop_table("warehouse_skus")

    op.drop_index("ix_business_members_user_id", table_name="business_members")
    op.drop_table("business_members")
    business_member_role_enum = postgresql.ENUM(
        "owner",
        "manager",
        "staff",
        name="business_member_role",
    )
    business_member_role_enum.drop(op.get_bind(), checkfirst=True)
