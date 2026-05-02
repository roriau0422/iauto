"""phase 5 session 24: vehicle dues + QPay.

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-03

Spec section 9.1-9.2 + cross-cut on §8: tax / insurance / fines payable
through QPay from the My Car screen. Production ingestion of real
government rows is deferred — this migration ships the schema only and
mobile renders the empty state today.

Changes:

1. New `vehicle_dues` table — one row per (vehicle, kind, period). Has
   its own status lifecycle (`due` | `ok` | `overdue` | `paid`) and a
   nullable FK back to `payment_intents` to track the active QPay
   invoice. `(vehicle_id, status)` is the hot read path.

2. `payment_intents` becomes polymorphic across two payable kinds —
   marketplace sales (the original) and vehicle dues. Concretely:

   - new `payment_intent_kind` enum with `sale_payment` | `vehicle_due_payment`
   - `payment_intents.kind` column, backfilled to `sale_payment` for
     every existing row
   - `payment_intents.sale_id` flips to nullable
   - new `payment_intents.vehicle_due_id` nullable FK
   - new XOR CHECK: exactly one of (sale_id, vehicle_due_id) is set
     and matches the kind
   - `payment_intents.tenant_id` flips to nullable — vehicle dues are
     not tenant-scoped (drivers pay the government, not a business).
   - The existing `uq_payment_intents_sale_id` is replaced with a
     partial unique on `(sale_id) WHERE sale_id IS NOT NULL` so it
     doesn't block null `sale_id` rows for the new due flow.
   - Add a partial unique on `(vehicle_due_id)` for the same reason
     (one in-flight invoice per due).

The `ledger_entries` schema is unchanged — vehicle-due settlements
intentionally do NOT post to the ledger (no business revenue accrues).
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. vehicle_due_kind + vehicle_due_status enums
    # ------------------------------------------------------------------
    vehicle_due_kind_enum = postgresql.ENUM(
        "tax",
        "insurance",
        "fines",
        name="vehicle_due_kind",
        create_type=False,
    )
    vehicle_due_kind_enum.create(op.get_bind(), checkfirst=True)

    vehicle_due_status_enum = postgresql.ENUM(
        "due",
        "ok",
        "overdue",
        "paid",
        name="vehicle_due_status",
        create_type=False,
    )
    vehicle_due_status_enum.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # 2. payment_intent_kind enum (new — must exist before we add the
    #    column that references it)
    # ------------------------------------------------------------------
    payment_intent_kind_enum = postgresql.ENUM(
        "sale_payment",
        "vehicle_due_payment",
        name="payment_intent_kind",
        create_type=False,
    )
    payment_intent_kind_enum.create(op.get_bind(), checkfirst=True)

    # ------------------------------------------------------------------
    # 3. vehicle_dues
    # ------------------------------------------------------------------
    op.create_table(
        "vehicle_dues",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vehicle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", vehicle_due_kind_enum, nullable=False),
        sa.Column("amount_mnt", sa.BigInteger(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", vehicle_due_status_enum, nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_intent_id", postgresql.UUID(as_uuid=True), nullable=True),
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
            ["vehicle_id"],
            ["vehicles.id"],
            name="fk_vehicle_dues_vehicle_id_vehicles",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("amount_mnt >= 0", name="ck_vehicle_dues_amount_non_negative"),
        sa.PrimaryKeyConstraint("id", name="pk_vehicle_dues"),
    )
    op.create_index(
        "ix_vehicle_dues_vehicle_id_status",
        "vehicle_dues",
        ["vehicle_id", "status"],
    )

    # ------------------------------------------------------------------
    # 4. Extend payment_intents for the polymorphic flow.
    # ------------------------------------------------------------------
    # 4a. New kind column. Backfill = sale_payment for every existing row.
    op.add_column(
        "payment_intents",
        sa.Column("kind", payment_intent_kind_enum, nullable=True),
    )
    op.execute("UPDATE payment_intents SET kind = 'sale_payment' WHERE kind IS NULL")
    op.alter_column("payment_intents", "kind", nullable=False)

    # 4b. New vehicle_due_id column.
    op.add_column(
        "payment_intents",
        sa.Column("vehicle_due_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_payment_intents_vehicle_due_id_vehicle_dues",
        "payment_intents",
        "vehicle_dues",
        ["vehicle_due_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # 4c. Now add the FK from vehicle_dues.payment_intent_id back to
    #     payment_intents (a circular ref, but Postgres handles it; the
    #     dues table was created before payment_intents had a vehicle_due
    #     column so we set the FK after the column exists).
    op.create_foreign_key(
        "fk_vehicle_dues_payment_intent_id_payment_intents",
        "vehicle_dues",
        "payment_intents",
        ["payment_intent_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 4d. tenant_id and sale_id flip to nullable. Existing rows already
    #     carry both columns set; the DB only relaxes the NOT NULL.
    op.alter_column(
        "payment_intents",
        "tenant_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.alter_column(
        "payment_intents",
        "sale_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )

    # 4e. Replace the existing total-uniqueness on sale_id with a partial
    #     unique that only applies when sale_id IS NOT NULL.
    op.drop_constraint(
        "uq_payment_intents_sale_id",
        "payment_intents",
        type_="unique",
    )
    op.create_index(
        "uq_payment_intents_sale_id_partial",
        "payment_intents",
        ["sale_id"],
        unique=True,
        postgresql_where=sa.text("sale_id IS NOT NULL"),
    )

    # 4f. Partial unique on vehicle_due_id (one active invoice per due).
    op.create_index(
        "uq_payment_intents_vehicle_due_id_partial",
        "payment_intents",
        ["vehicle_due_id"],
        unique=True,
        postgresql_where=sa.text("vehicle_due_id IS NOT NULL"),
    )

    # 4g. CHECK: kind must match exactly one populated payable column.
    op.create_check_constraint(
        "ck_payment_intents_kind_target_xor",
        "payment_intents",
        (
            "(kind = 'sale_payment'         AND sale_id        IS NOT NULL AND vehicle_due_id IS NULL) "
            "OR "
            "(kind = 'vehicle_due_payment'  AND vehicle_due_id IS NOT NULL AND sale_id        IS NULL)"
        ),
    )

    # 4h. CHECK: when kind = sale_payment, tenant_id MUST be set (sale
    #     intents are tenant-scoped by the marketplace business). When
    #     kind = vehicle_due_payment, tenant_id is null (no tenant).
    op.create_check_constraint(
        "ck_payment_intents_tenant_per_kind",
        "payment_intents",
        (
            "(kind = 'sale_payment'        AND tenant_id IS NOT NULL) "
            "OR "
            "(kind = 'vehicle_due_payment' AND tenant_id IS NULL)"
        ),
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_payment_intents_tenant_per_kind",
        "payment_intents",
        type_="check",
    )
    op.drop_constraint(
        "ck_payment_intents_kind_target_xor",
        "payment_intents",
        type_="check",
    )
    op.drop_index(
        "uq_payment_intents_vehicle_due_id_partial",
        table_name="payment_intents",
    )
    op.drop_index(
        "uq_payment_intents_sale_id_partial",
        table_name="payment_intents",
    )
    op.create_unique_constraint(
        "uq_payment_intents_sale_id",
        "payment_intents",
        ["sale_id"],
    )
    op.alter_column(
        "payment_intents",
        "sale_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.alter_column(
        "payment_intents",
        "tenant_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.drop_constraint(
        "fk_vehicle_dues_payment_intent_id_payment_intents",
        "vehicle_dues",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_payment_intents_vehicle_due_id_vehicle_dues",
        "payment_intents",
        type_="foreignkey",
    )
    op.drop_column("payment_intents", "vehicle_due_id")
    op.drop_column("payment_intents", "kind")

    op.drop_index("ix_vehicle_dues_vehicle_id_status", table_name="vehicle_dues")
    op.drop_table("vehicle_dues")

    payment_intent_kind_enum = postgresql.ENUM(
        "sale_payment",
        "vehicle_due_payment",
        name="payment_intent_kind",
    )
    payment_intent_kind_enum.drop(op.get_bind(), checkfirst=True)

    vehicle_due_status_enum = postgresql.ENUM(
        "due",
        "ok",
        "overdue",
        "paid",
        name="vehicle_due_status",
    )
    vehicle_due_status_enum.drop(op.get_bind(), checkfirst=True)

    vehicle_due_kind_enum = postgresql.ENUM(
        "tax",
        "insurance",
        "fines",
        name="vehicle_due_kind",
    )
    vehicle_due_kind_enum.drop(op.get_bind(), checkfirst=True)
