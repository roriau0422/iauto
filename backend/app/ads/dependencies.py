"""FastAPI dependencies for the ads context."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ads.service import AdsService
from app.media.dependencies import get_media_service
from app.media.service import MediaService
from app.platform.config import Settings, get_settings
from app.platform.db import get_session


def get_ads_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    media_svc: Annotated[MediaService, Depends(get_media_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AdsService:
    return AdsService(session=session, media_svc=media_svc, settings=settings)
