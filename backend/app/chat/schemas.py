"""HTTP + WebSocket schemas for the chat context."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.chat.models import ChatMessageKind

MAX_BODY = 4000


class ChatThreadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    quote_id: uuid.UUID
    part_search_id: uuid.UUID
    driver_id: uuid.UUID
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ChatThreadListOut(BaseModel):
    items: list[ChatThreadOut]
    total: int


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    thread_id: uuid.UUID
    author_user_id: uuid.UUID | None
    kind: ChatMessageKind
    body: str | None
    media_asset_id: uuid.UUID | None
    created_at: datetime


class ChatMessageListOut(BaseModel):
    items: list[ChatMessageOut]
    has_more: bool


class ChatMessageCreateIn(BaseModel):
    """Body for `POST /v1/chat/threads/{id}/messages`.

    System messages can't be created by API callers — that path is
    server-internal. Media messages take a confirmed `media_asset_id`
    that the caller owns.
    """

    kind: Literal["text", "media"]
    body: str | None = Field(default=None, max_length=MAX_BODY)
    media_asset_id: uuid.UUID | None = None

    @field_validator("body")
    @classmethod
    def _trim_body(cls, v: str | None) -> str | None:
        if v is None:
            return None
        trimmed = v.strip()
        return trimmed or None

    @model_validator(mode="after")
    def _check_shape(self) -> Self:
        if self.kind == "text":
            if not self.body:
                raise ValueError("text messages require a non-empty body")
            if self.media_asset_id is not None:
                raise ValueError("text messages must not carry media_asset_id")
        elif self.kind == "media":
            if self.media_asset_id is None:
                raise ValueError("media messages require media_asset_id")
        return self


# ---------------------------------------------------------------------------
# WebSocket frame envelopes
# ---------------------------------------------------------------------------


class WsSubscribeIn(BaseModel):
    type: Literal["subscribe"] = "subscribe"
    thread_id: uuid.UUID


class WsSendIn(BaseModel):
    type: Literal["send"] = "send"
    thread_id: uuid.UUID
    kind: Literal["text", "media"]
    body: str | None = None
    media_asset_id: uuid.UUID | None = None


class WsMessageOut(BaseModel):
    type: Literal["message"] = "message"
    message: ChatMessageOut


class WsErrorOut(BaseModel):
    type: Literal["error"] = "error"
    error_code: str
    detail: str
