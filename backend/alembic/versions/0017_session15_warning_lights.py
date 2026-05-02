"""phase 3 session 15: warning-light classifier.

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-02

Per arch §13.5 the warning-light classifier is the *only* path that uses
a fine-tuned MobileNet/EfficientNet (NOT CLIP zero-shot). This session
ships the database contract + audit trail; the ONNX model body lands in
phase 5 alongside the production model serving infra. Today's runtime
classifier is a deterministic placeholder so the end-to-end agent flow
works in dogfooding.

Adds:

1. `warning_light` value to `media_asset_purpose` so dashboard photos
   flow through the existing presigned-URL pipeline.

2. `ai_warning_light_taxonomy` — controlled vocabulary (~150 icons).
   Seeded with the canonical ~25 most common ones; the full ICAO/ISO
   set comes with the model. `code` is the stable machine identifier
   (e.g. `engine_warning_amber`); `display_*` are localized labels.

3. `ai_warning_light_predictions` — append-only audit row per
   classification call. Top-K results with confidences live in a
   single jsonb column to keep the schema flat.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# Canonical seed — the universally common dashboard icons. Expanded by
# a future curator-run when the production model ships.
_TAXONOMY_SEED: list[tuple[str, str, str, str]] = [
    # (code, display_en, display_mn, severity)
    ("engine_warning_amber", "Check engine (amber)", "Хөдөлгүүр шалгах (улбар шар)", "warn"),
    ("engine_warning_red", "Check engine (red)", "Хөдөлгүүр шалгах (улаан)", "critical"),
    ("oil_pressure", "Oil pressure", "Тосны даралт", "critical"),
    ("battery_charging", "Battery / charging", "Батерей", "warn"),
    ("coolant_temp", "Coolant temperature", "Хөргөгчийн температур", "critical"),
    ("brake_warning", "Brake warning", "Тормосны анхаар", "critical"),
    ("abs_warning", "ABS warning", "ABS анхаар", "warn"),
    ("airbag", "Airbag", "Хийлдэг хайрцаг", "critical"),
    ("tire_pressure", "Tire pressure", "Дугуйн даралт", "warn"),
    ("seatbelt", "Seat belt", "Аюулгүй бүс", "warn"),
    ("low_fuel", "Low fuel", "Шатахуун дуусч байна", "info"),
    ("fog_lights_front", "Front fog lights", "Урд манан гэрэл", "info"),
    ("fog_lights_rear", "Rear fog lights", "Хойд манан гэрэл", "info"),
    ("high_beam", "High beam", "Алсын гэрэл", "info"),
    ("turn_signal_left", "Left turn signal", "Зүүн заагч", "info"),
    ("turn_signal_right", "Right turn signal", "Баруун заагч", "info"),
    ("hazard", "Hazard lights", "Анхаарал татсан гэрэл", "info"),
    ("door_ajar", "Door ajar", "Хаалга нээлттэй", "warn"),
    ("trunk_open", "Trunk open", "Ачааны тасалгаа нээлттэй", "warn"),
    ("hood_open", "Hood open", "Капот нээлттэй", "warn"),
    ("windshield_washer", "Windshield washer", "Шил угаагч", "info"),
    ("traction_control_off", "Traction control off", "Хазайлт хяналт идэвхгүй", "warn"),
    ("esp_warning", "ESP / stability warning", "ESP анхаар", "warn"),
    ("transmission_temp", "Transmission temperature", "Хурдны хайрцгийн темп", "critical"),
    ("dpf_filter", "Diesel particulate filter", "DPF шүүр", "warn"),
]


def upgrade() -> None:
    op.execute("COMMIT")
    op.execute(
        "ALTER TYPE media_asset_purpose ADD VALUE IF NOT EXISTS 'warning_light'"
    )
    op.execute("BEGIN")

    warning_light_severity_enum = postgresql.ENUM(
        "info",
        "warn",
        "critical",
        name="ai_warning_light_severity",
        create_type=False,
    )
    warning_light_severity_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "ai_warning_light_taxonomy",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("display_en", sa.Text(), nullable=False),
        sa.Column("display_mn", sa.Text(), nullable=False),
        sa.Column("severity", warning_light_severity_enum, nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_ai_warning_light_taxonomy"),
        sa.UniqueConstraint("code", name="uq_ai_warning_light_taxonomy_code"),
    )

    # Seed via parameterized inserts — keeps Cyrillic + special chars
    # safe against any literal-quoting bug.
    bind = op.get_bind()
    insert_stmt = sa.text(
        """
        INSERT INTO ai_warning_light_taxonomy
            (id, code, display_en, display_mn, severity, created_at, updated_at)
        VALUES (gen_random_uuid(), :code, :en, :mn, :sev, now(), now())
        ON CONFLICT (code) DO NOTHING
        """
    )
    for code, en, mn, sev in _TAXONOMY_SEED:
        bind.execute(insert_stmt, {"code": code, "en": en, "mn": mn, "sev": sev})

    op.create_table(
        "ai_warning_light_predictions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        # JSONB array of `{code, confidence}` ordered by confidence desc.
        sa.Column(
            "predictions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("top_code", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["ai_sessions.id"],
            name="fk_ai_warning_light_predictions_session_id_ai_sessions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_ai_warning_light_predictions_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["media_asset_id"],
            ["media_assets.id"],
            name="fk_ai_warning_light_predictions_media_asset_id_media_assets",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_warning_light_predictions"),
    )
    op.create_index(
        "ix_ai_warning_light_predictions_session_id_created_at",
        "ai_warning_light_predictions",
        ["session_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_warning_light_predictions_session_id_created_at",
        table_name="ai_warning_light_predictions",
    )
    op.drop_table("ai_warning_light_predictions")
    op.drop_table("ai_warning_light_taxonomy")
    warning_light_severity_enum = postgresql.ENUM(
        "info", "warn", "critical", name="ai_warning_light_severity"
    )
    warning_light_severity_enum.drop(op.get_bind(), checkfirst=True)
    # `media_asset_purpose.warning_light` survives — Postgres can't
    # drop enum values without a recreate dance.
