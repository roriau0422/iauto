"""ORM models for the AI Mechanic context."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.base import Base, Timestamped, UuidPrimaryKey


class AiSessionStatus(StrEnum):
    active = "active"
    closed = "closed"


class AiMessageRole(StrEnum):
    user = "user"
    assistant = "assistant"
    tool = "tool"
    system = "system"


class AiEmbeddingScope(StrEnum):
    vehicle = "vehicle"
    kb_document = "kb_document"
    global_ = "global"  # `global` is a reserved word; suffix with underscore.


class AiKbDocument(UuidPrimaryKey, Timestamped, Base):
    """One curated knowledge entry. Versioned by `content_hash`.

    `vehicle_brand_id` and `vehicle_model_id` are optional retrieval
    anchors — when set, the agent's `search_knowledge_base` tool can
    bias toward documents matching the active vehicle's brand/model.
    """

    __tablename__ = "ai_kb_documents"

    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(Text, nullable=False, server_default="mn")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    vehicle_brand_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("vehicle_brands.id", ondelete="SET NULL"),
        nullable=True,
    )
    vehicle_model_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("vehicle_models.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (UniqueConstraint("content_hash", name="uq_ai_kb_documents_content_hash"),)


class AiKbChunk(UuidPrimaryKey, Base):
    """Chunked text + pgvector embedding.

    `embedding` is `vector(1536)` (OpenAI `text-embedding-3-small`).
    The column is declared on the migration via raw SQL because pgvector
    isn't a first-class SQLAlchemy type by default; the ORM exposes it
    as `Any` here because we never read/write it through the ORM —
    embedding writes go through the dedicated repository's raw SQL.
    """

    __tablename__ = "ai_kb_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("ai_kb_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # `embedding vector(1536)` — handled in raw SQL by the repository.
    # We don't expose it on the ORM to keep SQLAlchemy out of the
    # vector-type business.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "document_id", "chunk_index", name="uq_ai_kb_chunks_document_id_chunk_index"
        ),
    )


class AiSession(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "ai_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("vehicles.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[AiSessionStatus] = mapped_column(
        SAEnum(AiSessionStatus, name="ai_session_status", native_enum=True),
        nullable=False,
        default=AiSessionStatus.active,
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)


class AiMessage(UuidPrimaryKey, Base):
    __tablename__ = "ai_messages"

    session_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("ai_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[AiMessageRole] = mapped_column(
        SAEnum(AiMessageRole, name="ai_message_role", native_enum=True),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AiSpendEvent(UuidPrimaryKey, Base):
    """One row per AI call.

    `audio_seconds` is populated for Whisper transcription rows so the
    daily-spend cron sums minute-billing alongside token billing
    without joining a second table.
    """

    __tablename__ = "ai_spend_events"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("ai_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    model: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    audio_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    est_cost_micro_mnt: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AiVoiceTranscript(UuidPrimaryKey, Base):
    """Append-only audit row per Whisper transcription.

    The transcribed text is also posted into the conversation as a
    `user` message (so the agent loop sees it); this table preserves
    the source-asset linkage for forensics + retraining datasets.
    """

    __tablename__ = "ai_voice_transcripts"

    session_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("ai_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    media_asset_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("media_assets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    language: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    audio_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AiWarningLightSeverity(StrEnum):
    info = "info"
    warn = "warn"
    critical = "critical"


class AiWarningLightTaxonomy(UuidPrimaryKey, Timestamped, Base):
    """Curated icon vocabulary the classifier returns codes from."""

    __tablename__ = "ai_warning_light_taxonomy"

    code: Mapped[str] = mapped_column(Text, nullable=False)
    display_en: Mapped[str] = mapped_column(Text, nullable=False)
    display_mn: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[AiWarningLightSeverity] = mapped_column(
        SAEnum(
            AiWarningLightSeverity,
            name="ai_warning_light_severity",
            native_enum=True,
        ),
        nullable=False,
    )

    __table_args__ = (UniqueConstraint("code", name="uq_ai_warning_light_taxonomy_code"),)


class AiWarningLightPrediction(UuidPrimaryKey, Base):
    """Append-only audit row per classifier call.

    `predictions` is a jsonb array of `{code, confidence}` ordered by
    confidence desc. `top_code` mirrors the highest-confidence label
    so the inbox feed can index it without unnesting jsonb.
    """

    __tablename__ = "ai_warning_light_predictions"

    session_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("ai_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    media_asset_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("media_assets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    model: Mapped[str] = mapped_column(Text, nullable=False)
    predictions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    top_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
