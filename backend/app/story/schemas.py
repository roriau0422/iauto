"""HTTP schemas for the story context."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.story.models import StoryAuthorKind

MAX_BODY = 4000
MAX_COMMENT_BODY = 2000
MAX_MEDIA = 8


def _dedupe(v: list[uuid.UUID]) -> list[uuid.UUID]:
    seen: set[uuid.UUID] = set()
    out: list[uuid.UUID] = []
    for item in v:
        if item in seen:
            raise ValueError("media_asset_ids must not contain duplicates")
        seen.add(item)
        out.append(item)
    return out


class StoryPostCreateIn(BaseModel):
    body: str = Field(..., min_length=1, max_length=MAX_BODY)
    media_asset_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_MEDIA)

    @field_validator("body")
    @classmethod
    def _trim(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("body must not be blank")
        return trimmed

    @field_validator("media_asset_ids")
    @classmethod
    def _no_dups(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        return _dedupe(v)


class StoryPostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID | None
    author_kind: StoryAuthorKind
    author_user_id: uuid.UUID
    body: str
    media_asset_ids: list[uuid.UUID]
    like_count: int
    comment_count: int
    created_at: datetime
    updated_at: datetime


class StoryFeedOut(BaseModel):
    items: list[StoryPostOut]
    has_more: bool


class StoryPostDeleteOut(BaseModel):
    ok: Literal[True] = True


class StoryLikeOut(BaseModel):
    post_id: uuid.UUID
    user_id: uuid.UUID
    like_count: int


class StoryUnlikeOut(BaseModel):
    post_id: uuid.UUID
    like_count: int


class StoryCommentCreateIn(BaseModel):
    body: str = Field(..., min_length=1, max_length=MAX_COMMENT_BODY)

    @field_validator("body")
    @classmethod
    def _trim(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("body must not be blank")
        return trimmed


class StoryCommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    post_id: uuid.UUID
    author_user_id: uuid.UUID
    body: str
    created_at: datetime


class StoryCommentListOut(BaseModel):
    items: list[StoryCommentOut]
    has_more: bool


class StoryCommentDeleteOut(BaseModel):
    ok: Literal[True] = True
