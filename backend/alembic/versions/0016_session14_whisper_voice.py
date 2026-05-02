"""phase 3 session 14: Whisper voice → text.

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-02

Adds:

1. `voice` value to `media_asset_purpose` so audio uploads can flow
   through the existing presigned-URL platform from session 6.

2. `audio_seconds` column on `ai_spend_events` so Whisper's per-minute
   billing can be tracked alongside the per-token LLM spend in one log.

3. `ai_voice_transcripts` — append-only audit row for every
   transcription. Persists the source media asset, detected language,
   model name, and raw text. The transcript is also posted into the
   conversation as a `user` message; this table is the forensic record
   of what audio produced what text.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # Same COMMIT/BEGIN dance as session 11/12 — Postgres can't ALTER
    # TYPE inside a transaction.
    op.execute("COMMIT")
    op.execute("ALTER TYPE media_asset_purpose ADD VALUE IF NOT EXISTS 'voice'")
    op.execute("BEGIN")

    op.add_column(
        "ai_spend_events",
        sa.Column("audio_seconds", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "ai_voice_transcripts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
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
            name="fk_ai_voice_transcripts_session_id_ai_sessions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_ai_voice_transcripts_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["media_asset_id"],
            ["media_assets.id"],
            name="fk_ai_voice_transcripts_media_asset_id_media_assets",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_voice_transcripts"),
    )
    op.create_index(
        "ix_ai_voice_transcripts_session_id_created_at",
        "ai_voice_transcripts",
        ["session_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ai_voice_transcripts_session_id_created_at",
        table_name="ai_voice_transcripts",
    )
    op.drop_table("ai_voice_transcripts")
    op.drop_column("ai_spend_events", "audio_seconds")
    # `media_asset_purpose.voice` stays — Postgres can't drop a single
    # enum value safely.
