"""phase 1 core: businesses, part_search_requests, vehicles XYP extras.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-16

Session 4 of Phase 1. Adds:

1. New nullable columns on `vehicles`:
     - `class_code`       text   — XYP `className`
     - `fuel_type`        text   — XYP `fuelType`
     - `import_month`     date   — XYP `importDate` truncated to day=01
     - `steering_side`    enum   — LHD / RHD from XYP `wheelPosition`
   All four are nullable with no backfill — existing rows were registered
   before we parsed these fields and stay null.

2. `businesses` table — profile per `users.role='business'`. `owner_id`
   has a partial unique index so one owner → one business. Contact phone
   stored encrypted with the session-3 envelope pattern (Fernet + HMAC
   blind index).

3. `part_search_requests` table — driver-side RFQ rows. pg_trgm GIN on
   `description` makes session 5's incoming feed's text search feasible.
   FK to vehicles uses ON DELETE RESTRICT so active searches block
   vehicle unregistration.

Downgrade drops everything in reverse order.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. vehicles — extra XYP-derived columns
    # ------------------------------------------------------------------
    steering_side_enum = postgresql.ENUM(
        "LHD",
        "RHD",
        name="vehicle_steering_side",
        create_type=False,
    )
    steering_side_enum.create(op.get_bind(), checkfirst=True)

    op.add_column("vehicles", sa.Column("class_code", sa.Text(), nullable=True))
    op.add_column("vehicles", sa.Column("fuel_type", sa.Text(), nullable=True))
    op.add_column("vehicles", sa.Column("import_month", sa.Date(), nullable=True))
    op.add_column(
        "vehicles",
        sa.Column("steering_side", steering_side_enum, nullable=True),
    )
    op.create_index(
        "ix_vehicles_steering_side",
        "vehicles",
        ["steering_side"],
    )

    # ------------------------------------------------------------------
    # 2. businesses
    # ------------------------------------------------------------------
    op.create_table(
        "businesses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("contact_phone_cipher", sa.LargeBinary(), nullable=True),
        sa.Column("contact_phone_search", sa.Text(), nullable=True),
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
            name="fk_businesses_owner_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_businesses"),
    )
    # Partial unique: one business row per owner. `WHERE owner_id IS NOT NULL`
    # is a no-op filter (NOT NULL column) but makes the index explicit and
    # symmetric with the other partial indexes in the schema.
    op.create_index(
        "uq_businesses_owner_id",
        "businesses",
        ["owner_id"],
        unique=True,
    )

    # ------------------------------------------------------------------
    # 3. part_search_requests
    # ------------------------------------------------------------------
    part_search_status_enum = postgresql.ENUM(
        "open",
        "cancelled",
        "expired",
        "fulfilled",
        name="part_search_status",
        create_type=False,
    )
    part_search_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "part_search_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("driver_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vehicle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "media_urls",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("status", part_search_status_enum, nullable=False),
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
            ["driver_id"],
            ["users.id"],
            name="fk_part_search_requests_driver_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["vehicles.id"],
            name="fk_part_search_requests_vehicle_id_vehicles",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_part_search_requests"),
    )
    op.create_index(
        "ix_part_search_requests_driver_id",
        "part_search_requests",
        ["driver_id"],
    )
    op.create_index(
        "ix_part_search_requests_vehicle_id",
        "part_search_requests",
        ["vehicle_id"],
    )
    # Compound index for the driver-side "my searches, newest first" feed.
    op.create_index(
        "ix_part_search_requests_driver_id_created_at",
        "part_search_requests",
        ["driver_id", sa.text("created_at DESC")],
    )
    # Compound index for the business-side incoming feed (session 5).
    op.create_index(
        "ix_part_search_requests_status_created_at",
        "part_search_requests",
        ["status", sa.text("created_at DESC")],
    )
    # pg_trgm GIN on description — enables ILIKE / similarity search over
    # Mongolian free-text without dragging in a full-text search config
    # that tokenizes Cyrillic badly.
    op.execute(
        "CREATE INDEX ix_part_search_requests_description_trgm "
        "ON part_search_requests USING gin (description gin_trgm_ops)"
    )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    # part_search_requests
    op.execute("DROP INDEX IF EXISTS ix_part_search_requests_description_trgm")
    op.drop_index(
        "ix_part_search_requests_status_created_at",
        table_name="part_search_requests",
    )
    op.drop_index(
        "ix_part_search_requests_driver_id_created_at",
        table_name="part_search_requests",
    )
    op.drop_index(
        "ix_part_search_requests_vehicle_id",
        table_name="part_search_requests",
    )
    op.drop_index(
        "ix_part_search_requests_driver_id",
        table_name="part_search_requests",
    )
    op.drop_table("part_search_requests")
    part_search_status_enum = postgresql.ENUM(
        "open",
        "cancelled",
        "expired",
        "fulfilled",
        name="part_search_status",
    )
    part_search_status_enum.drop(op.get_bind(), checkfirst=True)

    # businesses
    op.drop_index("uq_businesses_owner_id", table_name="businesses")
    op.drop_table("businesses")

    # vehicles
    op.drop_index("ix_vehicles_steering_side", table_name="vehicles")
    op.drop_column("vehicles", "steering_side")
    op.drop_column("vehicles", "import_month")
    op.drop_column("vehicles", "fuel_type")
    op.drop_column("vehicles", "class_code")
    steering_side_enum = postgresql.ENUM(
        "LHD",
        "RHD",
        name="vehicle_steering_side",
    )
    steering_side_enum.drop(op.get_bind(), checkfirst=True)
