"""FastAPI dependencies for the media context."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.media.client import MediaClient, S3MediaClient
from app.media.service import MediaService
from app.platform.config import Settings, get_settings
from app.platform.db import get_session


@lru_cache(maxsize=1)
def _build_default_client() -> S3MediaClient:
    """One process-wide S3 client.

    boto3 clients are thread-safe; sharing a single instance keeps the
    botocore session warm and avoids re-loading credentials on every
    request. Tests substitute their own client by overriding
    `get_media_client` via FastAPI's `dependency_overrides`.
    """
    return S3MediaClient(get_settings())


def get_media_client() -> MediaClient:
    return _build_default_client()


def get_media_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    client: Annotated[MediaClient, Depends(get_media_client)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MediaService:
    return MediaService(
        session=session,
        client=client,
        bucket=settings.s3_bucket_media,
    )
