"""FastAPI dependencies for the story context."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.media.dependencies import get_media_service
from app.media.service import MediaService
from app.platform.db import get_session
from app.story.service import StoryService


def get_story_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    media_svc: Annotated[MediaService, Depends(get_media_service)],
) -> StoryService:
    return StoryService(session=session, media_svc=media_svc)
