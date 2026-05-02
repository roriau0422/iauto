"""phase 3 session 13: AI Mechanic — knowledge base + agent persistence + cost.

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-02

Stands up the AI Mechanic spine per arch §13:

1. `ai_kb_documents` — versioned curated knowledge entries. `content_hash`
   is the de-dup key so re-ingesting the same body is a no-op.

2. `ai_kb_chunks` — chunked + embedded text for retrieval. `embedding`
   is `vector(1536)` for OpenAI `text-embedding-3-small`. IVFFlat index
   keeps cosine ANN cheap; we'll re-tune `lists` once we know corpus size.

3. `ai_sessions` + `ai_messages` — append-only conversation persistence.
   Sessions are scoped to a user (and optionally a vehicle).

4. `ai_spend_events` — every LLM call logs `(prompt_tokens,
   completion_tokens, est_cost_mnt, model)`. Phase 5 cost-alert cron
   sums these into the daily-spend dashboard.

5. `ai_embedding_cache` — `(scope_kind, scope_id, content_hash)` keyed
   short-circuit so the same content for the same vehicle never
   re-embeds. Critical cost control.

The `vector` extension was created in baseline migration 0001.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # ai_kb_documents
    # ------------------------------------------------------------------
    op.create_table(
        "ai_kb_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=False, server_default=sa.text("'mn'")),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        # Optional vehicle-brand / model anchors for retrieval scoping.
        sa.Column("vehicle_brand_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("vehicle_model_id", postgresql.UUID(as_uuid=True), nullable=True),
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
            ["vehicle_brand_id"],
            ["vehicle_brands.id"],
            name="fk_ai_kb_documents_vehicle_brand_id_vehicle_brands",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_model_id"],
            ["vehicle_models.id"],
            name="fk_ai_kb_documents_vehicle_model_id_vehicle_models",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_kb_documents"),
        sa.UniqueConstraint("content_hash", name="uq_ai_kb_documents_content_hash"),
    )
    op.create_index(
        "ix_ai_kb_documents_vehicle_brand_id",
        "ai_kb_documents",
        ["vehicle_brand_id"],
        postgresql_where=sa.text("vehicle_brand_id IS NOT NULL"),
    )

    # ------------------------------------------------------------------
    # ai_kb_chunks (vector(1536) for text-embedding-3-small)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE ai_kb_chunks (
            id uuid PRIMARY KEY,
            document_id uuid NOT NULL REFERENCES ai_kb_documents(id) ON DELETE CASCADE,
            chunk_index int NOT NULL,
            body text NOT NULL,
            embedding vector(1536),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (document_id, chunk_index)
        )
        """
    )
    # No vector index for the dogfooding phase. At sub-1000-row corpus
    # size sequential scan beats HNSW/IVFFlat build cost. HNSW also has
    # known visibility issues with rows committed inside a SAVEPOINT
    # (which our test fixture relies on for isolation), so the index
    # would silently break the test suite. A later migration adds an
    # HNSW index once the curated corpus crosses ~1000 chunks.
    op.create_index(
        "ix_ai_kb_chunks_document_id", "ai_kb_chunks", ["document_id"]
    )

    # ------------------------------------------------------------------
    # ai_sessions
    # ------------------------------------------------------------------
    ai_session_status_enum = postgresql.ENUM(
        "active",
        "closed",
        name="ai_session_status",
        create_type=False,
    )
    ai_session_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "ai_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vehicle_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", ai_session_status_enum, nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
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
            name="fk_ai_sessions_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["vehicle_id"],
            ["vehicles.id"],
            name="fk_ai_sessions_vehicle_id_vehicles",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_sessions"),
    )
    op.create_index(
        "ix_ai_sessions_user_id_created_at",
        "ai_sessions",
        ["user_id", sa.text("created_at DESC")],
    )

    # ------------------------------------------------------------------
    # ai_messages
    # ------------------------------------------------------------------
    ai_message_role_enum = postgresql.ENUM(
        "user",
        "assistant",
        "tool",
        "system",
        name="ai_message_role",
        create_type=False,
    )
    ai_message_role_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "ai_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", ai_message_role_enum, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        # Tool name for `role='tool'` rows; tool args/result captured as JSONB.
        sa.Column("tool_name", sa.Text(), nullable=True),
        sa.Column(
            "tool_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["ai_sessions.id"],
            name="fk_ai_messages_session_id_ai_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_messages"),
    )
    op.create_index(
        "ix_ai_messages_session_id_created_at",
        "ai_messages",
        ["session_id", sa.text("created_at ASC")],
    )

    # ------------------------------------------------------------------
    # ai_spend_events
    # ------------------------------------------------------------------
    op.create_table(
        "ai_spend_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        # Estimated cost in micro-MNT (cost_mnt × 1_000_000) for sub-MNT fidelity.
        sa.Column("est_cost_micro_mnt", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_ai_spend_events_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["ai_sessions.id"],
            name="fk_ai_spend_events_session_id_ai_sessions",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_spend_events"),
    )
    op.create_index(
        "ix_ai_spend_events_user_id_created_at",
        "ai_spend_events",
        ["user_id", sa.text("created_at DESC")],
    )

    # ------------------------------------------------------------------
    # ai_embedding_cache
    # ------------------------------------------------------------------
    ai_embedding_scope_enum = postgresql.ENUM(
        "vehicle",
        "kb_document",
        "global",
        name="ai_embedding_scope",
        create_type=False,
    )
    ai_embedding_scope_enum.create(op.get_bind(), checkfirst=True)

    op.execute(
        """
        CREATE TABLE ai_embedding_cache (
            id uuid PRIMARY KEY,
            scope_kind ai_embedding_scope NOT NULL,
            scope_id uuid,
            content_hash text NOT NULL,
            embedding vector(1536) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (scope_kind, scope_id, content_hash)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE ai_embedding_cache")
    ai_embedding_scope_enum = postgresql.ENUM(
        "vehicle", "kb_document", "global", name="ai_embedding_scope"
    )
    ai_embedding_scope_enum.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_ai_spend_events_user_id_created_at", table_name="ai_spend_events")
    op.drop_table("ai_spend_events")

    op.drop_index("ix_ai_messages_session_id_created_at", table_name="ai_messages")
    op.drop_table("ai_messages")
    ai_message_role_enum = postgresql.ENUM(
        "user", "assistant", "tool", "system", name="ai_message_role"
    )
    ai_message_role_enum.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_ai_sessions_user_id_created_at", table_name="ai_sessions")
    op.drop_table("ai_sessions")
    ai_session_status_enum = postgresql.ENUM(
        "active", "closed", name="ai_session_status"
    )
    ai_session_status_enum.drop(op.get_bind(), checkfirst=True)

    op.drop_index("ix_ai_kb_chunks_document_id", table_name="ai_kb_chunks")
    op.execute("DROP TABLE ai_kb_chunks")

    op.drop_index("ix_ai_kb_documents_vehicle_brand_id", table_name="ai_kb_documents")
    op.drop_table("ai_kb_documents")
