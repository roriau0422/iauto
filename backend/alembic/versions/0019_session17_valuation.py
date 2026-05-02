"""phase 4 session 17: car valuation (CatBoost).

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-02

Adds:

1. `valuation_models` — model registry. Each retrain inserts a new
   row in `training` status, evaluates, then flips `active` (with the
   previous active row demoted to `retired`). Partial unique index
   on `status = 'active'` enforces exactly one live model. The
   trained CatBoost binary lives in MinIO at `artifact_object_key`.

2. `valuation_estimates` — per-call audit row. Persists the request
   features as jsonb plus the predicted price + model version so we
   can backtest predictions against the eventual sale price.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    valuation_status_enum = postgresql.ENUM(
        "training",
        "active",
        "retired",
        name="valuation_model_status",
        create_type=False,
    )
    valuation_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "valuation_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("status", valuation_status_enum, nullable=False),
        sa.Column("trained_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mae_mnt", sa.BigInteger(), nullable=True),
        sa.Column("artifact_object_key", sa.Text(), nullable=True),
        sa.Column(
            "feature_columns",
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
        sa.PrimaryKeyConstraint("id", name="pk_valuation_models"),
        sa.UniqueConstraint("version", name="uq_valuation_models_version"),
    )
    # Exactly one active model at a time.
    op.create_index(
        "uq_valuation_models_one_active",
        "valuation_models",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "valuation_estimates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "features",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("predicted_mnt", sa.BigInteger(), nullable=False),
        sa.Column("low_mnt", sa.BigInteger(), nullable=True),
        sa.Column("high_mnt", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_valuation_estimates_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["valuation_models.id"],
            name="fk_valuation_estimates_model_id_valuation_models",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_valuation_estimates"),
    )
    op.create_index(
        "ix_valuation_estimates_user_id_created_at",
        "valuation_estimates",
        ["user_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_valuation_estimates_user_id_created_at", table_name="valuation_estimates"
    )
    op.drop_table("valuation_estimates")
    op.drop_index("uq_valuation_models_one_active", table_name="valuation_models")
    op.drop_table("valuation_models")
    valuation_status_enum = postgresql.ENUM(
        "training", "active", "retired", name="valuation_model_status"
    )
    valuation_status_enum.drop(op.get_bind(), checkfirst=True)
