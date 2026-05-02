"""phase 3 session 16: Gemini multimodal — visual + engine sound.

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-02

Adds:

1. `engine_sound` value on `media_asset_purpose` so engine recordings
   flow through the existing presigned-URL platform.

2. `ai_multimodal_calls` — append-only audit row per multimodal LLM
   invocation. Mirrors the voice-transcript / warning-light shape:
   `(kind, asset_id, model, prompt, response, tokens, audio_seconds)`.

The `kind` enum is intentionally narrow (`visual` vs `engine_sound`).
Future modalities (`pdf`, `multi_image`, etc.) extend additively.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute("COMMIT")
    op.execute(
        "ALTER TYPE media_asset_purpose ADD VALUE IF NOT EXISTS 'engine_sound'"
    )
    op.execute("BEGIN")

    multimodal_kind_enum = postgresql.ENUM(
        "visual",
        "engine_sound",
        name="ai_multimodal_kind",
        create_type=False,
    )
    multimodal_kind_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "ai_multimodal_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", multimodal_kind_enum, nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("audio_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["ai_sessions.id"],
            name="fk_ai_multimodal_calls_session_id_ai_sessions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_ai_multimodal_calls_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["media_asset_id"],
            ["media_assets.id"],
            name="fk_ai_multimodal_calls_media_asset_id_media_assets",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_multimodal_calls"),
    )
    op.create_index(
        "ix_ai_multimodal_calls_session_id_created_at",
        "ai_multimodal_calls",
        ["session_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_multimodal_calls_session_id_created_at",
        table_name="ai_multimodal_calls",
    )
    op.drop_table("ai_multimodal_calls")
    multimodal_kind_enum = postgresql.ENUM(
        "visual", "engine_sound", name="ai_multimodal_kind"
    )
    multimodal_kind_enum.drop(op.get_bind(), checkfirst=True)
    # `media_asset_purpose.engine_sound` survives.
