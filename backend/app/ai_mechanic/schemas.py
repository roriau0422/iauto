"""HTTP schemas for the AI Mechanic context."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ai_mechanic.models import AiMessageRole, AiSessionStatus

MAX_TITLE = 200
MAX_BODY = 200_000  # KB ingest accepts long docs; chunking happens server-side
MAX_QUERY = 4000


class SessionCreateIn(BaseModel):
    vehicle_id: uuid.UUID | None = None
    title: str | None = Field(default=None, max_length=MAX_TITLE)


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    vehicle_id: uuid.UUID | None
    status: AiSessionStatus
    title: str | None
    created_at: datetime
    updated_at: datetime


class SessionListOut(BaseModel):
    items: list[SessionOut]
    total: int


class MessageCreateIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=MAX_QUERY)

    @field_validator("content")
    @classmethod
    def _trim(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("content must not be blank")
        return trimmed


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    role: AiMessageRole
    content: str
    tool_name: str | None
    tool_payload: dict[str, Any] | None
    created_at: datetime


class MessageListOut(BaseModel):
    items: list[MessageOut]


class AssistantReplyOut(BaseModel):
    """Wraps the assistant's reply + spend telemetry for the caller."""

    user_message: MessageOut
    assistant_message: MessageOut
    prompt_tokens: int
    completion_tokens: int
    est_cost_micro_mnt: int


# ---------------------------------------------------------------------------
# Knowledge base ingestion (admin / phase-3 dev surface)
# ---------------------------------------------------------------------------


class KbDocumentCreateIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=MAX_TITLE)
    body: str = Field(..., min_length=1, max_length=MAX_BODY)
    source_url: str | None = Field(default=None, max_length=2000)
    language: str = Field(default="mn", min_length=2, max_length=8)
    vehicle_brand_id: uuid.UUID | None = None
    vehicle_model_id: uuid.UUID | None = None

    @field_validator("title")
    @classmethod
    def _trim_title(cls, v: str) -> str:
        return v.strip()


class KbDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    source_url: str | None
    language: str
    vehicle_brand_id: uuid.UUID | None
    vehicle_model_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class KbDocumentIngestedOut(BaseModel):
    document: KbDocumentOut
    chunks_added: int
    embeddings_cached: int
