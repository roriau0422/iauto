"""HTTP routes for the media context."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.identity.dependencies import get_current_user
from app.identity.models import User
from app.media.dependencies import get_media_service
from app.media.schemas import (
    MediaAssetDownloadOut,
    MediaAssetOut,
    MediaUploadCreateIn,
    MediaUploadCreateOut,
)
from app.media.service import MediaService

router = APIRouter(tags=["media"])


@router.post(
    "/media/uploads",
    response_model=MediaUploadCreateOut,
    status_code=status.HTTP_201_CREATED,
    summary="Request a presigned PUT URL for a new asset",
)
async def create_upload(
    body: MediaUploadCreateIn,
    service: Annotated[MediaService, Depends(get_media_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> MediaUploadCreateOut:
    result = await service.request_upload(owner_id=user.id, payload=body)
    return MediaUploadCreateOut(
        asset_id=result.asset.id,
        upload_url=result.upload_url,
        headers=result.headers,
        expires_at=result.expires_at,
        max_bytes=result.max_bytes,
    )


@router.post(
    "/media/uploads/{asset_id}/confirm",
    response_model=MediaAssetOut,
    summary="Confirm an upload — backend HEADs the object and flips status to active",
)
async def confirm_upload(
    asset_id: uuid.UUID,
    service: Annotated[MediaService, Depends(get_media_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> MediaAssetOut:
    asset = await service.confirm_upload(owner_id=user.id, asset_id=asset_id)
    return MediaAssetOut.model_validate(asset)


@router.get(
    "/media/assets/{asset_id}",
    response_model=MediaAssetDownloadOut,
    summary="Issue a presigned GET URL for an asset (owner only)",
)
async def get_asset_download(
    asset_id: uuid.UUID,
    service: Annotated[MediaService, Depends(get_media_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> MediaAssetDownloadOut:
    result = await service.request_download(owner_id=user.id, asset_id=asset_id)
    return MediaAssetDownloadOut(
        asset_id=result.asset_id,
        download_url=result.download_url,
        expires_at=result.expires_at,
    )
