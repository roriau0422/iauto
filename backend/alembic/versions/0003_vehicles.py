"""vehicles: vehicles, ownerships, lookup plans, lookup reports.

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-15
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


VERIFICATION_SOURCE = postgresql.ENUM(
    "xyp_public",
    "manual",
    name="vehicle_verification_source",
    create_type=False,
)


# Initial lookup plan — ported verbatim from the smartcar.mn curl the user
# pasted. Keep this in sync with real anti-bot header rotations; add a new
# plan row with is_active=true and flip the old one off in the same tx.
INITIAL_PLAN = {
    "plan_version": "2026-04-15.1",
    "is_active": True,
    "service_code": "WS100401_getVehicleInfo",
    "endpoint_method": "POST",
    "endpoint_url": "https://xyp-api.smartcar.mn/xyp-api/v1/xyp/get-data-public",
    "headers": {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Origin": "https://smartcar.mn",
        "Referer": "https://smartcar.mn/",
        "os": "web",
        "version": "3.2.0",
        "Accept-Language": "mn",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.0.0 Safari/537.36"
        ),
    },
    "body_template": {
        "serviceCode": "WS100401_getVehicleInfo",
        "customFields": {"plateNumber": "{{plate}}"},
    },
    "slots": {"plate": {"type": "string", "source": "user_input"}},
    "expected": {
        # smartcar.mn returns a flat JSON object on success (no `result`
        # envelope), so `success_path` is empty meaning "use the whole body".
        "success_path": "",
        "fields": [
            "markName",
            "modelName",
            "buildYear",
            "cabinNumber",
            "motorNumber",
            "colorName",
            "capacity",
            "fuelType",
            "importDate",
        ],
        # On error smartcar.mn returns a plain text/plain body (NOT JSON),
        # e.g. HTTP 400 with body `0000ЖХУ дугаартай тээврийн хэрэгслийн
        # мэдээлэл олдсонгүй` when the plate doesn't exist. The mobile
        # client classifies the failure against these signatures first:
        #  - matching signature → show `client_message_mn`, do NOT call
        #    POST /v1/vehicles/lookup/report (user-input error, not an
        #    outage)
        #  - no matching signature → call the report endpoint, which pages
        #    the operator via SMS
        # The backend independently checks the same pattern in the report
        # handler as a defence against buggy/malicious clients.
        "error_signatures": [
            {
                "category": "not_found",
                "match": {
                    "status": 400,
                    "body_contains_any": ["олдсонгүй"],
                },
                "alert_operator": False,
                "client_message_mn": (
                    "Энэ дугаартай тээврийн хэрэгслийн мэдээлэл олдсонгүй"
                ),
                "client_message_en": (
                    "No vehicle information found for this plate"
                ),
            }
        ],
    },
    "ttl_seconds": 3600,
}


def upgrade() -> None:
    op.execute(
        "CREATE TYPE vehicle_verification_source "
        "AS ENUM ('xyp_public', 'manual')"
    )

    op.create_table(
        "vehicles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vin", sa.Text(), nullable=True),
        sa.Column("plate", sa.Text(), nullable=False),
        sa.Column("make", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("build_year", sa.Integer(), nullable=True),
        sa.Column("color", sa.Text(), nullable=True),
        sa.Column("engine_number", sa.Text(), nullable=True),
        sa.Column("capacity_cc", sa.Integer(), nullable=True),
        sa.Column("raw_xyp", postgresql.JSONB(), nullable=True),
        sa.Column("verification_source", VERIFICATION_SOURCE, nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
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
        sa.PrimaryKeyConstraint("id", name="pk_vehicles"),
    )
    # Partial unique index: dedup physical cars by VIN when present, but
    # let rows with NULL VIN coexist (legacy / XYP-unavailable).
    op.execute(
        "CREATE UNIQUE INDEX uq_vehicles_vin "
        "ON vehicles (vin) WHERE vin IS NOT NULL"
    )
    op.create_index("ix_vehicles_plate", "vehicles", ["plate"])

    op.create_table(
        "vehicle_ownerships",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vehicle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_vehicle_ownerships_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["vehicles.id"],
            name="fk_vehicle_ownerships_vehicle_id_vehicles",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "vehicle_id", name="pk_vehicle_ownerships"
        ),
    )
    op.create_index(
        "ix_vehicle_ownerships_vehicle_id",
        "vehicle_ownerships",
        ["vehicle_id"],
    )

    op.create_table(
        "vehicle_lookup_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_version", sa.Text(), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("service_code", sa.Text(), nullable=False),
        sa.Column("endpoint_method", sa.Text(), nullable=False),
        sa.Column("endpoint_url", sa.Text(), nullable=False),
        sa.Column("headers", postgresql.JSONB(), nullable=False),
        sa.Column("body_template", postgresql.JSONB(), nullable=False),
        sa.Column("slots", postgresql.JSONB(), nullable=False),
        sa.Column("expected", postgresql.JSONB(), nullable=False),
        sa.Column(
            "ttl_seconds",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("3600"),
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
        sa.PrimaryKeyConstraint("id", name="pk_vehicle_lookup_plans"),
        sa.UniqueConstraint(
            "plan_version", name="uq_vehicle_lookup_plans_plan_version"
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_vehicle_lookup_plans_active "
        "ON vehicle_lookup_plans (is_active) WHERE is_active = true"
    )

    op.create_table(
        "vehicle_lookup_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plate_masked", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("error_snippet", sa.Text(), nullable=True),
        sa.Column(
            "reported_by_user_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("plan_version", sa.Text(), nullable=True),
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
            ["reported_by_user_id"],
            ["users.id"],
            name="fk_vehicle_lookup_reports_reported_by_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_vehicle_lookup_reports"),
    )
    op.create_index(
        "ix_vehicle_lookup_reports_created_at",
        "vehicle_lookup_reports",
        ["created_at"],
    )
    op.create_index(
        "ix_vehicle_lookup_reports_status_code",
        "vehicle_lookup_reports",
        ["status_code"],
    )

    # Seed the initial lookup plan row.
    op.execute(
        sa.text(
            """
            INSERT INTO vehicle_lookup_plans (
                id, plan_version, is_active, service_code, endpoint_method,
                endpoint_url, headers, body_template, slots, expected,
                ttl_seconds
            )
            VALUES (
                gen_random_uuid(),
                :plan_version,
                :is_active,
                :service_code,
                :endpoint_method,
                :endpoint_url,
                CAST(:headers AS jsonb),
                CAST(:body_template AS jsonb),
                CAST(:slots AS jsonb),
                CAST(:expected AS jsonb),
                :ttl_seconds
            )
            """
        ).bindparams(
            plan_version=INITIAL_PLAN["plan_version"],
            is_active=INITIAL_PLAN["is_active"],
            service_code=INITIAL_PLAN["service_code"],
            endpoint_method=INITIAL_PLAN["endpoint_method"],
            endpoint_url=INITIAL_PLAN["endpoint_url"],
            headers=json.dumps(INITIAL_PLAN["headers"]),
            body_template=json.dumps(INITIAL_PLAN["body_template"]),
            slots=json.dumps(INITIAL_PLAN["slots"]),
            expected=json.dumps(INITIAL_PLAN["expected"]),
            ttl_seconds=INITIAL_PLAN["ttl_seconds"],
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_vehicle_lookup_reports_status_code",
        table_name="vehicle_lookup_reports",
    )
    op.drop_index(
        "ix_vehicle_lookup_reports_created_at",
        table_name="vehicle_lookup_reports",
    )
    op.drop_table("vehicle_lookup_reports")

    op.execute("DROP INDEX IF EXISTS uq_vehicle_lookup_plans_active")
    op.drop_table("vehicle_lookup_plans")

    op.drop_index(
        "ix_vehicle_ownerships_vehicle_id", table_name="vehicle_ownerships"
    )
    op.drop_table("vehicle_ownerships")

    op.drop_index("ix_vehicles_plate", table_name="vehicles")
    op.execute("DROP INDEX IF EXISTS uq_vehicles_vin")
    op.drop_table("vehicles")

    op.execute("DROP TYPE IF EXISTS vehicle_verification_source")
