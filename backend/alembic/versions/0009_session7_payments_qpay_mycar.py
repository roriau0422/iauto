"""phase 1 session 7: payments + qpay + my car.

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-02

Session 7 adds:

1. `payment_intents` — one per QPay invoice attempt. Status enum tracks
   the lifecycle (pending/settled/failed/cancelled/expired). Unique on
   `sale_id` for now (refunds will get their own table later).

2. `payment_events` — append-only audit log of QPay interactions. Every
   callback body, every check-poll response.

3. `ledger_entries` — double-entry bookkeeping. Settlement creates a
   debit+credit pair; refunds create the reverse pair. Account enum
   spans cash, business_revenue, platform_fee, refund_payable.

4. `vehicle_service_logs` — empty stub for the My Car service-history
   endpoint shipped this session. Session 9 fills the model out fully
   per spec §9.3.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. payment_intents
    # ------------------------------------------------------------------
    payment_intent_status_enum = postgresql.ENUM(
        "pending",
        "settled",
        "failed",
        "cancelled",
        "expired",
        name="payment_intent_status",
        create_type=False,
    )
    payment_intent_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "payment_intents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sale_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amount_mnt", sa.Integer(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False, server_default=sa.text("'MNT'")),
        sa.Column("qpay_invoice_id", sa.Text(), nullable=True),
        sa.Column("qpay_invoice_code", sa.Text(), nullable=False),
        sa.Column("sender_invoice_no", sa.Text(), nullable=False),
        sa.Column("status", payment_intent_status_enum, nullable=False),
        sa.Column("last_qpay_status", sa.Text(), nullable=True),
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
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["businesses.id"],
            name="fk_payment_intents_tenant_id_businesses",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sale_id"],
            ["sales.id"],
            name="fk_payment_intents_sale_id_sales",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payment_intents"),
        sa.UniqueConstraint("sale_id", name="uq_payment_intents_sale_id"),
        sa.UniqueConstraint(
            "sender_invoice_no", name="uq_payment_intents_sender_invoice_no"
        ),
    )
    op.create_index("ix_payment_intents_tenant_id", "payment_intents", ["tenant_id"])
    op.create_index(
        "ix_payment_intents_tenant_id_created_at",
        "payment_intents",
        ["tenant_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_payment_intents_qpay_invoice_id",
        "payment_intents",
        ["qpay_invoice_id"],
        postgresql_where=sa.text("qpay_invoice_id IS NOT NULL"),
    )

    # ------------------------------------------------------------------
    # 2. payment_events
    # ------------------------------------------------------------------
    payment_event_kind_enum = postgresql.ENUM(
        "invoice_created",
        "callback",
        "check",
        "status_change",
        "webhook_signature_failed",
        name="payment_event_kind",
        create_type=False,
    )
    payment_event_kind_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "payment_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payment_intent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", payment_event_kind_enum, nullable=False),
        sa.Column(
            "qpay_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("signature_ok", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["payment_intent_id"],
            ["payment_intents.id"],
            name="fk_payment_events_payment_intent_id_payment_intents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payment_events"),
    )
    op.create_index(
        "ix_payment_events_payment_intent_id_created_at",
        "payment_events",
        ["payment_intent_id", sa.text("created_at DESC")],
    )

    # ------------------------------------------------------------------
    # 3. ledger_entries
    # ------------------------------------------------------------------
    ledger_account_enum = postgresql.ENUM(
        "cash",
        "business_revenue",
        "platform_fee",
        "refund_payable",
        name="ledger_account",
        create_type=False,
    )
    ledger_account_enum.create(op.get_bind(), checkfirst=True)

    ledger_direction_enum = postgresql.ENUM(
        "debit",
        "credit",
        name="ledger_direction",
        create_type=False,
    )
    ledger_direction_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "ledger_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account", ledger_account_enum, nullable=False),
        sa.Column("direction", ledger_direction_enum, nullable=False),
        sa.Column("amount_mnt", sa.Integer(), nullable=False),
        sa.Column("payment_intent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sale_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["businesses.id"],
            name="fk_ledger_entries_tenant_id_businesses",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["payment_intent_id"],
            ["payment_intents.id"],
            name="fk_ledger_entries_payment_intent_id_payment_intents",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sale_id"],
            ["sales.id"],
            name="fk_ledger_entries_sale_id_sales",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ledger_entries"),
        sa.CheckConstraint("amount_mnt > 0", name="ck_ledger_entries_amount_positive"),
    )
    op.create_index("ix_ledger_entries_tenant_id", "ledger_entries", ["tenant_id"])
    op.create_index(
        "ix_ledger_entries_tenant_id_created_at",
        "ledger_entries",
        ["tenant_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_ledger_entries_payment_intent_id",
        "ledger_entries",
        ["payment_intent_id"],
        postgresql_where=sa.text("payment_intent_id IS NOT NULL"),
    )

    # ------------------------------------------------------------------
    # 4. vehicle_service_logs (stub for session 9)
    # ------------------------------------------------------------------
    vehicle_service_log_kind_enum = postgresql.ENUM(
        "oil",
        "filter",
        "tire",
        "battery",
        "misc",
        name="vehicle_service_log_kind",
        create_type=False,
    )
    vehicle_service_log_kind_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "vehicle_service_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vehicle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", vehicle_service_log_kind_enum, nullable=False),
        sa.Column("noted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("mileage_km", sa.Integer(), nullable=True),
        sa.Column("cost_mnt", sa.Integer(), nullable=True),
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
            name="fk_vehicle_service_logs_vehicle_id_vehicles",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_vehicle_service_logs"),
    )
    op.create_index(
        "ix_vehicle_service_logs_vehicle_id_noted_at",
        "vehicle_service_logs",
        ["vehicle_id", sa.text("noted_at DESC")],
    )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    # vehicle_service_logs
    op.drop_index(
        "ix_vehicle_service_logs_vehicle_id_noted_at",
        table_name="vehicle_service_logs",
    )
    op.drop_table("vehicle_service_logs")
    vehicle_service_log_kind_enum = postgresql.ENUM(
        "oil",
        "filter",
        "tire",
        "battery",
        "misc",
        name="vehicle_service_log_kind",
    )
    vehicle_service_log_kind_enum.drop(op.get_bind(), checkfirst=True)

    # ledger_entries
    op.drop_index("ix_ledger_entries_payment_intent_id", table_name="ledger_entries")
    op.drop_index("ix_ledger_entries_tenant_id_created_at", table_name="ledger_entries")
    op.drop_index("ix_ledger_entries_tenant_id", table_name="ledger_entries")
    op.drop_table("ledger_entries")
    ledger_direction_enum = postgresql.ENUM("debit", "credit", name="ledger_direction")
    ledger_direction_enum.drop(op.get_bind(), checkfirst=True)
    ledger_account_enum = postgresql.ENUM(
        "cash",
        "business_revenue",
        "platform_fee",
        "refund_payable",
        name="ledger_account",
    )
    ledger_account_enum.drop(op.get_bind(), checkfirst=True)

    # payment_events
    op.drop_index(
        "ix_payment_events_payment_intent_id_created_at",
        table_name="payment_events",
    )
    op.drop_table("payment_events")
    payment_event_kind_enum = postgresql.ENUM(
        "invoice_created",
        "callback",
        "check",
        "status_change",
        "webhook_signature_failed",
        name="payment_event_kind",
    )
    payment_event_kind_enum.drop(op.get_bind(), checkfirst=True)

    # payment_intents
    op.drop_index("ix_payment_intents_qpay_invoice_id", table_name="payment_intents")
    op.drop_index(
        "ix_payment_intents_tenant_id_created_at", table_name="payment_intents"
    )
    op.drop_index("ix_payment_intents_tenant_id", table_name="payment_intents")
    op.drop_table("payment_intents")
    payment_intent_status_enum = postgresql.ENUM(
        "pending",
        "settled",
        "failed",
        "cancelled",
        "expired",
        name="payment_intent_status",
    )
    payment_intent_status_enum.drop(op.get_bind(), checkfirst=True)
