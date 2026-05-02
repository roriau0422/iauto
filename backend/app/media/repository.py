"""Database access for the media context."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.media.models import MediaAsset, MediaAssetPurpose, MediaAssetStatus


class MediaAssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, asset_id: uuid.UUID) -> MediaAsset | None:
        return await self.session.get(MediaAsset, asset_id)

    async def create(
        self,
        *,
        owner_id: uuid.UUID,
        bucket: str,
        object_key: str,
        content_type: str,
        purpose: MediaAssetPurpose,
    ) -> MediaAsset:
        asset = MediaAsset(
            owner_id=owner_id,
            bucket=bucket,
            object_key=object_key,
            content_type=content_type,
            purpose=purpose,
            status=MediaAssetStatus.pending,
        )
        self.session.add(asset)
        await self.session.flush()
        return asset

    async def list_active_for_owner(
        self,
        *,
        owner_id: uuid.UUID,
        ids: Iterable[uuid.UUID],
        purpose: MediaAssetPurpose,
    ) -> list[MediaAsset]:
        """Return the subset of `ids` that are owned, purpose-matched, and active."""
        id_list = list(ids)
        if not id_list:
            return []
        stmt = select(MediaAsset).where(
            MediaAsset.id.in_(id_list),
            MediaAsset.owner_id == owner_id,
            MediaAsset.purpose == purpose,
            MediaAsset.status == MediaAssetStatus.active,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars())
