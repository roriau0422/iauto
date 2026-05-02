"""Gemini multimodal: visual Q&A + engine-sound diagnosis."""

from __future__ import annotations

import uuid

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_mechanic.embeddings import FakeEmbeddingClient
from app.ai_mechanic.models import (
    AiMessageRole,
    AiMultimodalCall,
    AiMultimodalKind,
    AiSpendEvent,
)
from app.ai_mechanic.multimodal import FakeMultimodalClient
from app.ai_mechanic.schemas import (
    EngineSoundMessageCreateIn,
    SessionCreateIn,
    VisualMessageCreateIn,
)
from app.ai_mechanic.service import AiMechanicService
from app.identity.models import User, UserRole
from app.media.models import MediaAsset, MediaAssetPurpose, MediaAssetStatus
from app.platform.config import Settings
from app.platform.errors import ConflictError, NotFoundError
from tests.ai_mechanic.fakes import FakeAgentRunner
from tests.media.test_service import BUCKET, FakeMediaClient


async def _make_user(db_session: AsyncSession, phone: str) -> User:
    user = User(phone=phone, role=UserRole.driver)
    db_session.add(user)
    await db_session.flush()
    return user


async def _seed_asset(
    *,
    db_session: AsyncSession,
    media_client: FakeMediaClient,
    owner_id: uuid.UUID,
    purpose: MediaAssetPurpose,
    object_key: str,
    content_type: str,
    body_bytes: bytes,
) -> MediaAsset:
    asset = MediaAsset(
        owner_id=owner_id,
        bucket=BUCKET,
        object_key=object_key,
        content_type=content_type,
        purpose=purpose,
        status=MediaAssetStatus.active,
        byte_size=len(body_bytes),
    )
    db_session.add(asset)
    await db_session.flush()
    media_client._objects[object_key] = {
        "ContentLength": len(body_bytes),
        "Body": body_bytes,
    }
    return asset


@pytest.fixture
def media_client() -> FakeMediaClient:
    return FakeMediaClient()


@pytest.fixture
def multimodal() -> FakeMultimodalClient:
    return FakeMultimodalClient(
        text="Looks like a worn timing belt — you should replace it soon.",
        prompt_tokens=120,
        completion_tokens=40,
    )


@pytest.fixture
def runner() -> FakeAgentRunner:
    return FakeAgentRunner()


@pytest.fixture
def ai_service(
    db_session: AsyncSession,
    redis: Redis,
    settings: Settings,
    runner: FakeAgentRunner,
    media_client: FakeMediaClient,
    multimodal: FakeMultimodalClient,
) -> AiMechanicService:
    return AiMechanicService(
        session=db_session,
        redis=redis,
        runner=runner,
        embeddings=FakeEmbeddingClient(),
        settings=settings,
        media_download=media_client,
        multimodal=multimodal,
    )


async def test_visual_message_runs_multimodal_then_agent(
    ai_service: AiMechanicService,
    db_session: AsyncSession,
    media_client: FakeMediaClient,
    runner: FakeAgentRunner,
    multimodal: FakeMultimodalClient,
) -> None:
    user = await _make_user(db_session, "+97688114401")
    sess = await ai_service.create_session(user_id=user.id, payload=SessionCreateIn())
    asset = await _seed_asset(
        db_session=db_session,
        media_client=media_client,
        owner_id=user.id,
        purpose=MediaAssetPurpose.part_search,
        object_key=f"part_search/{user.id}/photo.jpg",
        content_type="image/jpeg",
        body_bytes=b"FAKE-IMAGE-BYTES",
    )
    reply = await ai_service.post_visual_message(
        session_id=sess.id,
        user_id=user.id,
        payload=VisualMessageCreateIn(
            media_asset_id=asset.id,
            prompt="What part is this and is it worn?",
        ),
    )
    assert reply.call.kind == AiMultimodalKind.visual
    assert reply.call.model == "gemini-multimodal-visual"
    assert reply.call.prompt_tokens == 120
    assert reply.call.completion_tokens == 40
    # Cost = (120/1000)*60 + (40/1000)*180 = 7 + 7 = 14 micro-MNT.
    assert reply.multimodal_micro_mnt == 14
    # Multimodal client called once with the right kind.
    assert len(multimodal.calls) == 1
    assert multimodal.calls[0]["kind"] == "visual"
    # Agent runner saw the wrapped multimodal output.
    assert runner.calls[-1]["user_input"].startswith("[visual analysis]")
    assert "worn timing belt" in runner.calls[-1]["user_input"]
    # Persisted: assistant reply + multimodal audit row + spend row.
    assert reply.assistant_message.role == AiMessageRole.assistant
    audit = list((await db_session.execute(select(AiMultimodalCall))).scalars())
    assert len(audit) == 1
    assert audit[0].kind == AiMultimodalKind.visual
    spend = list((await db_session.execute(select(AiSpendEvent))).scalars())
    assert any(s.model == "gemini-multimodal-visual" for s in spend)


async def test_visual_message_rejects_voice_asset(
    ai_service: AiMechanicService,
    db_session: AsyncSession,
    media_client: FakeMediaClient,
) -> None:
    user = await _make_user(db_session, "+97688114402")
    sess = await ai_service.create_session(user_id=user.id, payload=SessionCreateIn())
    asset = await _seed_asset(
        db_session=db_session,
        media_client=media_client,
        owner_id=user.id,
        purpose=MediaAssetPurpose.voice,
        object_key=f"voice/{user.id}/audio.webm",
        content_type="audio/webm",
        body_bytes=b"AUDIO",
    )
    with pytest.raises(ConflictError):
        await ai_service.post_visual_message(
            session_id=sess.id,
            user_id=user.id,
            payload=VisualMessageCreateIn(media_asset_id=asset.id, prompt="?"),
        )


async def test_engine_sound_message_uses_audio_modality(
    ai_service: AiMechanicService,
    db_session: AsyncSession,
    media_client: FakeMediaClient,
    multimodal: FakeMultimodalClient,
) -> None:
    user = await _make_user(db_session, "+97688114403")
    sess = await ai_service.create_session(user_id=user.id, payload=SessionCreateIn())
    # ~6 KB audio → 6000 / 2000 = 3 seconds at our heuristic conversion.
    audio = b"E" * 6000
    asset = await _seed_asset(
        db_session=db_session,
        media_client=media_client,
        owner_id=user.id,
        purpose=MediaAssetPurpose.engine_sound,
        object_key=f"engine_sound/{user.id}/clip.webm",
        content_type="audio/webm",
        body_bytes=audio,
    )
    reply = await ai_service.post_engine_sound_message(
        session_id=sess.id,
        user_id=user.id,
        payload=EngineSoundMessageCreateIn(media_asset_id=asset.id),
    )
    assert reply.call.kind == AiMultimodalKind.engine_sound
    assert reply.call.model == "gemini-multimodal-audio"
    assert reply.call.audio_seconds == 3
    # Cost = 3 * 700 = 2100 micro-MNT.
    assert reply.multimodal_micro_mnt == 2100
    assert multimodal.calls[-1]["kind"] == "audio"


async def test_engine_sound_rejects_image_asset(
    ai_service: AiMechanicService,
    db_session: AsyncSession,
    media_client: FakeMediaClient,
) -> None:
    user = await _make_user(db_session, "+97688114404")
    sess = await ai_service.create_session(user_id=user.id, payload=SessionCreateIn())
    asset = await _seed_asset(
        db_session=db_session,
        media_client=media_client,
        owner_id=user.id,
        purpose=MediaAssetPurpose.warning_light,
        object_key=f"warning_light/{user.id}/x.jpg",
        content_type="image/jpeg",
        body_bytes=b"X",
    )
    with pytest.raises(ConflictError):
        await ai_service.post_engine_sound_message(
            session_id=sess.id,
            user_id=user.id,
            payload=EngineSoundMessageCreateIn(media_asset_id=asset.id),
        )


async def test_visual_rejects_stranger_asset(
    ai_service: AiMechanicService,
    db_session: AsyncSession,
    media_client: FakeMediaClient,
) -> None:
    owner = await _make_user(db_session, "+97688114405")
    stranger = await _make_user(db_session, "+97688114406")
    sess = await ai_service.create_session(user_id=stranger.id, payload=SessionCreateIn())
    asset = await _seed_asset(
        db_session=db_session,
        media_client=media_client,
        owner_id=owner.id,
        purpose=MediaAssetPurpose.part_search,
        object_key=f"part_search/{owner.id}/owner.jpg",
        content_type="image/jpeg",
        body_bytes=b"X",
    )
    with pytest.raises(NotFoundError):
        await ai_service.post_visual_message(
            session_id=sess.id,
            user_id=stranger.id,
            payload=VisualMessageCreateIn(media_asset_id=asset.id, prompt="?"),
        )


async def test_empty_multimodal_response_409(
    db_session: AsyncSession,
    redis: Redis,
    settings: Settings,
    media_client: FakeMediaClient,
) -> None:
    silent = FakeMultimodalClient(text="   ")
    service = AiMechanicService(
        session=db_session,
        redis=redis,
        runner=FakeAgentRunner(),
        embeddings=FakeEmbeddingClient(),
        settings=settings,
        media_download=media_client,
        multimodal=silent,
    )
    user = await _make_user(db_session, "+97688114407")
    sess = await service.create_session(user_id=user.id, payload=SessionCreateIn())
    asset = await _seed_asset(
        db_session=db_session,
        media_client=media_client,
        owner_id=user.id,
        purpose=MediaAssetPurpose.engine_sound,
        object_key=f"engine_sound/{user.id}/silent.webm",
        content_type="audio/webm",
        body_bytes=b"S",
    )
    with pytest.raises(ConflictError):
        await service.post_engine_sound_message(
            session_id=sess.id,
            user_id=user.id,
            payload=EngineSoundMessageCreateIn(media_asset_id=asset.id),
        )
