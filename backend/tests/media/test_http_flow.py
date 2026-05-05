"""HTTP-level regression tests for the media routes.

Specifically guards `POST /v1/media/uploads/{id}/confirm` against the
MissingGreenlet bug — the same shape we hit in `update_sku`,
`businesses.update`, and `ads.pause/resume/activate`. The fix is
`await session.refresh(asset)` after flush; this test locks it in.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.dependencies import get_redis_dep
from app.main import create_app
from app.media.client import MediaClient
from app.media.dependencies import get_media_client
from app.media.models import MediaAsset, MediaAssetPurpose, MediaAssetStatus
from app.platform.db import get_session

PHONE = "+97688118802"


class _FakeMediaClient:
    """Stub that pretends MinIO holds an object of the expected size."""

    async def head_object(self, *, object_key: str) -> dict[str, Any]:
        return {"ContentLength": 256}

    async def presign_put(self, **_: Any) -> dict[str, Any]:
        return {"upload_url": "http://x/y", "headers": {}, "expires_at": "2099-01-01T00:00:00Z"}


@pytest_asyncio.fixture(loop_scope="session")
async def client(db_session: AsyncSession, redis: Redis) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    def _override_redis() -> Redis:
        return redis

    def _override_media() -> MediaClient:
        return _FakeMediaClient()  # type: ignore[return-value]

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_redis_dep] = _override_redis
    app.dependency_overrides[get_media_client] = _override_media

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _login(client: AsyncClient) -> tuple[str, uuid.UUID]:
    """Hit the OTP flow and return (access_token, user_id from JWT sub)."""
    import base64
    import json as _json

    r = await client.post("/v1/auth/otp/request", json={"phone": PHONE})
    assert r.status_code == 202, r.text
    code = r.json()["debug_code"]
    r = await client.post(
        "/v1/auth/otp/verify",
        json={
            "phone": PHONE,
            "code": code,
            "device": {"platform": "ios", "label": "pytest"},
        },
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    sub = _json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))["sub"]
    return token, uuid.UUID(sub)


async def test_confirm_upload_serializes_response(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Regression: `POST /v1/media/uploads/{id}/confirm` must return a
    serialized MediaAssetOut without a `MissingGreenlet` lazy-load on
    `updated_at`.
    """
    token, user_id = await _login(client)
    auth = {"Authorization": f"Bearer {token}"}

    asset = MediaAsset(
        owner_id=user_id,
        purpose=MediaAssetPurpose.warning_light,
        content_type="image/png",
        byte_size=256,
        bucket="iauto-media",
        object_key=f"warning_light/{user_id}/{uuid.uuid4()}.png",
        status=MediaAssetStatus.pending,
    )
    db_session.add(asset)
    await db_session.flush()
    asset_id = asset.id
    await db_session.commit()

    r = await client.post(f"/v1/media/uploads/{asset_id}/confirm", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "active"
    assert body["updated_at"] is not None
