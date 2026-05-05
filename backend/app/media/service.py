"""Media service — presign upload, confirm, presign download."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.media.client import GET_TTL_SECONDS, PUT_MAX_BYTES, PUT_TTL_SECONDS, MediaClient
from app.media.models import MediaAsset, MediaAssetPurpose, MediaAssetStatus
from app.media.repository import MediaAssetRepository
from app.media.schemas import CONTENT_TYPE_EXTENSIONS, MediaUploadCreateIn
from app.platform.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.platform.logging import get_logger

logger = get_logger("app.media.service")


@dataclass(slots=True)
class PresignedUpload:
    asset: MediaAsset
    upload_url: str
    headers: dict[str, str]
    expires_at: datetime
    max_bytes: int


@dataclass(slots=True)
class PresignedDownload:
    asset_id: uuid.UUID
    download_url: str
    expires_at: datetime


class MediaService:
    def __init__(self, *, session: AsyncSession, client: MediaClient, bucket: str) -> None:
        self.session = session
        self.client = client
        self.bucket = bucket
        self.assets = MediaAssetRepository(session)

    # ---- upload --------------------------------------------------------

    async def request_upload(
        self,
        *,
        owner_id: uuid.UUID,
        payload: MediaUploadCreateIn,
    ) -> PresignedUpload:
        """Create a pending asset row and return a presigned PUT URL.

        Object key shape: `{purpose}/{owner_id}/{asset_id}{ext}`. The
        `{owner_id}` segment makes it impossible for one user's URL to
        collide with another's (and turns blind enumeration into a O(N×M)
        pain instead of a O(N) one).
        """
        asset_id = uuid.uuid4()
        ext = CONTENT_TYPE_EXTENSIONS[payload.content_type]
        object_key = f"{payload.purpose.value}/{owner_id}/{asset_id}{ext}"

        asset = await self.assets.create(
            owner_id=owner_id,
            bucket=self.bucket,
            object_key=object_key,
            content_type=payload.content_type,
            purpose=payload.purpose,
        )
        # The repo created with `default=...` from the model — patch the
        # generated id back onto the row so the object_key matches the row.
        asset.id = asset_id
        await self.session.flush()

        upload_url = await self.client.presign_put(
            object_key=object_key,
            content_type=payload.content_type,
            max_bytes=PUT_MAX_BYTES,
        )
        expires_at = datetime.now(UTC) + timedelta(seconds=PUT_TTL_SECONDS)
        # MinIO rejects PUTs that don't echo the same Content-Type the
        # signer used. Returning it here keeps the contract explicit.
        headers: dict[str, str] = {"Content-Type": payload.content_type}
        logger.info(
            "media_upload_presigned",
            asset_id=str(asset.id),
            owner_id=str(owner_id),
            purpose=payload.purpose.value,
        )
        return PresignedUpload(
            asset=asset,
            upload_url=upload_url,
            headers=headers,
            expires_at=expires_at,
            max_bytes=PUT_MAX_BYTES,
        )

    async def confirm_upload(
        self,
        *,
        owner_id: uuid.UUID,
        asset_id: uuid.UUID,
    ) -> MediaAsset:
        """Verify the bytes landed and flip the row to `active`.

        Idempotent: confirming an already-active asset is a no-op (returns
        the row). Confirming a deleted asset raises 409 — clients shouldn't
        race the deletion.
        """
        asset = await self.assets.get_by_id(asset_id)
        if asset is None or asset.owner_id != owner_id:
            # Opaque 404 — never reveal whether someone else's asset id exists.
            raise NotFoundError("Asset not found")
        if asset.status == MediaAssetStatus.deleted:
            raise ConflictError("Asset has been deleted")
        if asset.status == MediaAssetStatus.active:
            return asset

        head = await self.client.head_object(object_key=asset.object_key)
        if head is None:
            raise NotFoundError("Uploaded object not found in storage")

        size = int(head.get("ContentLength", 0))
        if size <= 0 or size > PUT_MAX_BYTES:
            # Storage rejected nothing client-side, but the bytes don't
            # match what we'd accept. Soft-delete the row so the client
            # can re-issue a fresh upload.
            asset.status = MediaAssetStatus.deleted
            await self.session.flush()
            raise ValidationError(f"Uploaded object size {size} outside [1,{PUT_MAX_BYTES}]")

        asset.byte_size = size
        asset.status = MediaAssetStatus.active
        await self.session.flush()
        # `updated_at` carries `onupdate=func.now()`, so flush expires it.
        # Refresh before returning so Pydantic's response-model serialization
        # doesn't trigger a lazy load on a closed greenlet (same class of
        # bug as warehouse.update_sku / businesses.update / ads.pause).
        await self.session.refresh(asset)
        logger.info(
            "media_upload_confirmed",
            asset_id=str(asset.id),
            byte_size=size,
        )
        return asset

    # ---- download -------------------------------------------------------

    async def request_download(
        self,
        *,
        owner_id: uuid.UUID,
        asset_id: uuid.UUID,
    ) -> PresignedDownload:
        """Owner-only download for now. Cross-context viewing (e.g. a driver
        seeing a quote's photos) lands when the marketplace surface needs it
        — for session 6 the simpler "owner only" check is enough."""
        asset = await self.assets.get_by_id(asset_id)
        if asset is None:
            raise NotFoundError("Asset not found")
        if asset.owner_id != owner_id:
            raise ForbiddenError("You do not own this asset")
        if asset.status != MediaAssetStatus.active:
            raise ConflictError("Asset is not active")

        url = await self.client.presign_get(object_key=asset.object_key)
        expires_at = datetime.now(UTC) + timedelta(seconds=GET_TTL_SECONDS)
        return PresignedDownload(asset_id=asset.id, download_url=url, expires_at=expires_at)

    # ---- cross-context helpers -----------------------------------------

    async def validate_asset_ids(
        self,
        *,
        owner_id: uuid.UUID,
        asset_ids: Iterable[uuid.UUID],
        purpose: MediaAssetPurpose,
    ) -> list[MediaAsset]:
        """Return the assets if every id is owned + active + matches `purpose`.

        Raises 422 if any id is missing or doesn't match. Designed for the
        marketplace to call when accepting media references on a domain
        write — `submit_search`, `submit_quote`, `submit_review`.
        """
        id_list = list(asset_ids)
        if not id_list:
            return []
        # Deduplicate: callers sometimes accidentally repeat the same id.
        unique_ids = list(dict.fromkeys(id_list))
        rows = await self.assets.list_active_for_owner(
            owner_id=owner_id, ids=unique_ids, purpose=purpose
        )
        if len(rows) != len(unique_ids):
            found = {r.id for r in rows}
            missing = [str(i) for i in unique_ids if i not in found]
            raise ValidationError(f"Unknown or unusable media_asset_id(s): {sorted(missing)}")
        # Preserve caller order so downstream rendering matches what was sent.
        by_id = {r.id: r for r in rows}
        return [by_id[i] for i in unique_ids]
