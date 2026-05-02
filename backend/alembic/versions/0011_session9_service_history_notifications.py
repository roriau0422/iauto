"""phase 1 session 9: service-history extras + notification_dispatches.

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-02

Session 9 closes Phase 1. Adds:

1. Two columns on `vehicle_service_logs` left as a stub in 0009:
     - `title text NULL`     — short headline shown in list views.
     - `location text NULL`  — free-text shop name / address.

2. `notification_dispatches` — append-only audit log of every push
   attempt by the notifications context. `provider` enum spans the
   real targets (FCM, APNs) plus a console provider used in dev/test.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. vehicle_service_logs — extras
    # ------------------------------------------------------------------
    op.add_column("vehicle_service_logs", sa.Column("title", sa.Text(), nullable=True))
    op.add_column(
        "vehicle_service_logs", sa.Column("location", sa.Text(), nullable=True)
    )

    # ------------------------------------------------------------------
    # 2. notification_dispatches
    # ------------------------------------------------------------------
    notification_provider_enum = postgresql.ENUM(
        "fcm",
        "apns",
        "console",
        name="notification_provider",
        create_type=False,
    )
    notification_provider_enum.create(op.get_bind(), checkfirst=True)

    notification_status_enum = postgresql.ENUM(
        "queued",
        "sent",
        "failed",
        name="notification_status",
        create_type=False,
    )
    notification_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "notification_dispatches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("provider", notification_provider_enum, nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", notification_status_enum, nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
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
            ["user_id"],
            ["users.id"],
            name="fk_notification_dispatches_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name="fk_notification_dispatches_device_id_devices",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notification_dispatches"),
    )
    op.create_index(
        "ix_notification_dispatches_user_id_created_at",
        "notification_dispatches",
        ["user_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_dispatches_user_id_created_at",
        table_name="notification_dispatches",
    )
    op.drop_table("notification_dispatches")
    notification_status_enum = postgresql.ENUM(
        "queued",
        "sent",
        "failed",
        name="notification_status",
    )
    notification_status_enum.drop(op.get_bind(), checkfirst=True)
    notification_provider_enum = postgresql.ENUM(
        "fcm",
        "apns",
        "console",
        name="notification_provider",
    )
    notification_provider_enum.drop(op.get_bind(), checkfirst=True)

    op.drop_column("vehicle_service_logs", "location")
    op.drop_column("vehicle_service_logs", "title")
