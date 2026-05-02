"""Service-level tests for the media platform.

We don't hit MinIO from these tests — `S3MediaClient` is replaced with a
`FakeMediaClient` that records the calls. This isolates the upload-flow
state machine (pending → active, ownership checks, validation) from
network I/O. A separate live integration smoke test is documented in the
session-6 review.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import User, UserRole
from app.media.client import PUT_MAX_BYTES, MediaClient
from app.media.models import MediaAssetPurpose, MediaAssetStatus
from app.media.schemas import MediaUploadCreateIn
from app.media.service import MediaService
from app.platform.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)

BUCKET = "iauto-media"


class FakeMediaClient(MediaClient):
    """In-memory `MediaClient` that records calls and returns canned values."""

    def __init__(self, *, content_length: int | None = 1024) -> None:
        self.put_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []
        self.head_calls: list[str] = []
        self.delete_calls: list[str] = []
        self._objects: dict[str, dict[str, Any]] = {}
        self._default_size = content_length

    async def presign_put(
        self,
        *,
        object_key: str,
        content_type: str,
        max_bytes: int,
    ) -> str:
        self.put_calls.append(
            {"object_key": object_key, "content_type": content_type, "max_bytes": max_bytes}
        )
        # Simulate the bytes "landing" by registering the object with the
        # default content length unless a test pre-loads a specific size.
        if self._default_size is not None and object_key not in self._objects:
            self._objects[object_key] = {"ContentLength": self._default_size}
        return f"https://example/{object_key}?signed=put"

    async def presign_get(self, *, object_key: str) -> str:
        self.get_calls.append({"object_key": object_key})
        return f"https://example/{object_key}?signed=get"

    async def head_object(self, *, object_key: str) -> dict[str, Any] | None:
        self.head_calls.append(object_key)
        return self._objects.get(object_key)

    async def download_bytes(self, *, object_key: str) -> bytes:
        # Tests that need a real payload pre-load it via `_objects[key]["Body"]`;
        # the default returns an empty buffer so the call still resolves.
        meta = self._objects.get(object_key) or {}
        body = meta.get("Body")
        if isinstance(body, bytes):
            return body
        return b""

    async def delete_object(self, *, object_key: str) -> None:
        self.delete_calls.append(object_key)
        self._objects.pop(object_key, None)


async def _make_user(db_session: AsyncSession, phone: str) -> User:
    user = User(phone=phone, role=UserRole.driver)
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
def fake_client() -> FakeMediaClient:
    return FakeMediaClient()


@pytest.fixture
def media_service(db_session: AsyncSession, fake_client: FakeMediaClient) -> MediaService:
    return MediaService(session=db_session, client=fake_client, bucket=BUCKET)


async def test_request_upload_creates_pending_row_and_returns_url(
    media_service: MediaService, fake_client: FakeMediaClient, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, "+97688110601")
    result = await media_service.request_upload(
        owner_id=user.id,
        payload=MediaUploadCreateIn(
            purpose=MediaAssetPurpose.part_search,
            content_type="image/jpeg",
            byte_size=2048,
        ),
    )
    assert result.asset.status == MediaAssetStatus.pending
    assert result.asset.owner_id == user.id
    assert result.asset.purpose == MediaAssetPurpose.part_search
    assert result.asset.bucket == BUCKET
    # Object key embeds purpose, owner, asset id, and a content-type
    # extension so the layout is forensically inspectable in MinIO.
    assert result.asset.object_key.startswith(f"part_search/{user.id}/")
    assert result.asset.object_key.endswith(".jpg")
    assert "?signed=put" in result.upload_url
    assert result.headers == {"Content-Type": "image/jpeg"}
    assert result.max_bytes == PUT_MAX_BYTES
    assert len(fake_client.put_calls) == 1


async def test_confirm_upload_flips_status_and_records_size(
    media_service: MediaService, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, "+97688110602")
    result = await media_service.request_upload(
        owner_id=user.id,
        payload=MediaUploadCreateIn(
            purpose=MediaAssetPurpose.review,
            content_type="image/png",
            byte_size=4096,
        ),
    )
    confirmed = await media_service.confirm_upload(owner_id=user.id, asset_id=result.asset.id)
    assert confirmed.status == MediaAssetStatus.active
    assert confirmed.byte_size == 1024  # the FakeMediaClient default


async def test_confirm_upload_404_for_stranger(
    media_service: MediaService, db_session: AsyncSession
) -> None:
    owner = await _make_user(db_session, "+97688110603")
    stranger = await _make_user(db_session, "+97688110604")
    result = await media_service.request_upload(
        owner_id=owner.id,
        payload=MediaUploadCreateIn(
            purpose=MediaAssetPurpose.review,
            content_type="image/png",
            byte_size=4096,
        ),
    )
    with pytest.raises(NotFoundError):
        await media_service.confirm_upload(owner_id=stranger.id, asset_id=result.asset.id)


async def test_confirm_upload_404_when_storage_missing(
    db_session: AsyncSession,
) -> None:
    fake = FakeMediaClient(content_length=None)
    svc = MediaService(session=db_session, client=fake, bucket=BUCKET)
    user = await _make_user(db_session, "+97688110605")
    result = await svc.request_upload(
        owner_id=user.id,
        payload=MediaUploadCreateIn(
            purpose=MediaAssetPurpose.quote,
            content_type="image/webp",
            byte_size=4096,
        ),
    )
    with pytest.raises(NotFoundError):
        await svc.confirm_upload(owner_id=user.id, asset_id=result.asset.id)


async def test_confirm_upload_rejects_oversize_object(
    db_session: AsyncSession,
) -> None:
    fake = FakeMediaClient(content_length=PUT_MAX_BYTES + 1)
    svc = MediaService(session=db_session, client=fake, bucket=BUCKET)
    user = await _make_user(db_session, "+97688110606")
    result = await svc.request_upload(
        owner_id=user.id,
        payload=MediaUploadCreateIn(
            purpose=MediaAssetPurpose.quote,
            content_type="image/webp",
            byte_size=4096,
        ),
    )
    with pytest.raises(ValidationError):
        await svc.confirm_upload(owner_id=user.id, asset_id=result.asset.id)
    refreshed = await svc.assets.get_by_id(result.asset.id)
    assert refreshed is not None
    # Soft-deleted so the client can request a fresh upload slot.
    assert refreshed.status == MediaAssetStatus.deleted


async def test_request_download_owner_only(
    media_service: MediaService, db_session: AsyncSession
) -> None:
    owner = await _make_user(db_session, "+97688110607")
    stranger = await _make_user(db_session, "+97688110608")
    result = await media_service.request_upload(
        owner_id=owner.id,
        payload=MediaUploadCreateIn(
            purpose=MediaAssetPurpose.review,
            content_type="image/png",
            byte_size=4096,
        ),
    )
    await media_service.confirm_upload(owner_id=owner.id, asset_id=result.asset.id)

    # Owner can download.
    dl = await media_service.request_download(owner_id=owner.id, asset_id=result.asset.id)
    assert "?signed=get" in dl.download_url

    # Stranger gets 403 (NOT 404, because we already validated that owner is
    # different — there's no enumeration leak when both ids exist).
    with pytest.raises(ForbiddenError):
        await media_service.request_download(owner_id=stranger.id, asset_id=result.asset.id)


async def test_request_download_rejects_non_active_asset(
    media_service: MediaService, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, "+97688110609")
    result = await media_service.request_upload(
        owner_id=user.id,
        payload=MediaUploadCreateIn(
            purpose=MediaAssetPurpose.review,
            content_type="image/png",
            byte_size=4096,
        ),
    )
    # Pending — not yet confirmed.
    with pytest.raises(ConflictError):
        await media_service.request_download(owner_id=user.id, asset_id=result.asset.id)


async def test_validate_asset_ids_happy_path(
    media_service: MediaService, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, "+97688110610")
    a = await media_service.request_upload(
        owner_id=user.id,
        payload=MediaUploadCreateIn(
            purpose=MediaAssetPurpose.part_search,
            content_type="image/jpeg",
            byte_size=2048,
        ),
    )
    b = await media_service.request_upload(
        owner_id=user.id,
        payload=MediaUploadCreateIn(
            purpose=MediaAssetPurpose.part_search,
            content_type="image/jpeg",
            byte_size=2048,
        ),
    )
    await media_service.confirm_upload(owner_id=user.id, asset_id=a.asset.id)
    await media_service.confirm_upload(owner_id=user.id, asset_id=b.asset.id)
    rows = await media_service.validate_asset_ids(
        owner_id=user.id,
        asset_ids=[a.asset.id, b.asset.id],
        purpose=MediaAssetPurpose.part_search,
    )
    assert {r.id for r in rows} == {a.asset.id, b.asset.id}


async def test_validate_asset_ids_rejects_wrong_purpose(
    media_service: MediaService, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, "+97688110611")
    res = await media_service.request_upload(
        owner_id=user.id,
        payload=MediaUploadCreateIn(
            purpose=MediaAssetPurpose.review,
            content_type="image/png",
            byte_size=4096,
        ),
    )
    await media_service.confirm_upload(owner_id=user.id, asset_id=res.asset.id)
    with pytest.raises(ValidationError):
        await media_service.validate_asset_ids(
            owner_id=user.id,
            asset_ids=[res.asset.id],
            purpose=MediaAssetPurpose.part_search,
        )


async def test_validate_asset_ids_rejects_pending_or_unknown(
    media_service: MediaService, db_session: AsyncSession
) -> None:
    user = await _make_user(db_session, "+97688110612")
    pending = await media_service.request_upload(
        owner_id=user.id,
        payload=MediaUploadCreateIn(
            purpose=MediaAssetPurpose.quote,
            content_type="image/jpeg",
            byte_size=2048,
        ),
    )
    # Pending → not yet `active`, must be rejected.
    with pytest.raises(ValidationError):
        await media_service.validate_asset_ids(
            owner_id=user.id,
            asset_ids=[pending.asset.id],
            purpose=MediaAssetPurpose.quote,
        )
    # Random uuid → reject.
    with pytest.raises(ValidationError):
        await media_service.validate_asset_ids(
            owner_id=user.id,
            asset_ids=[uuid.uuid4()],
            purpose=MediaAssetPurpose.quote,
        )


async def test_validate_asset_ids_rejects_other_owners_assets(
    media_service: MediaService, db_session: AsyncSession
) -> None:
    owner = await _make_user(db_session, "+97688110613")
    stranger = await _make_user(db_session, "+97688110614")
    res = await media_service.request_upload(
        owner_id=owner.id,
        payload=MediaUploadCreateIn(
            purpose=MediaAssetPurpose.part_search,
            content_type="image/jpeg",
            byte_size=2048,
        ),
    )
    await media_service.confirm_upload(owner_id=owner.id, asset_id=res.asset.id)
    with pytest.raises(ValidationError):
        await media_service.validate_asset_ids(
            owner_id=stranger.id,
            asset_ids=[res.asset.id],
            purpose=MediaAssetPurpose.part_search,
        )
