"""Voice → transcribe → agent flow."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_mechanic.embeddings import FakeEmbeddingClient
from app.ai_mechanic.models import (
    AiMessageRole,
    AiSpendEvent,
    AiVoiceTranscript,
)
from app.ai_mechanic.schemas import SessionCreateIn, VoiceMessageCreateIn
from app.ai_mechanic.service import AiMechanicService
from app.ai_mechanic.whisper import FakeWhisperClient
from app.identity.models import User, UserRole
from app.media.models import MediaAsset, MediaAssetPurpose, MediaAssetStatus
from app.media.service import MediaService
from app.platform.config import Settings
from app.platform.errors import ConflictError, NotFoundError
from tests.ai_mechanic.fakes import FakeAgentRunner
from tests.media.test_service import BUCKET, FakeMediaClient


async def _make_user(db_session: AsyncSession, phone: str) -> User:
    user = User(phone=phone, role=UserRole.driver)
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_voice_asset(
    *,
    db_session: AsyncSession,
    media_client: FakeMediaClient,
    owner_id: uuid.UUID,
    object_key: str,
    audio_bytes: bytes,
) -> MediaAsset:
    asset = MediaAsset(
        owner_id=owner_id,
        bucket=BUCKET,
        object_key=object_key,
        content_type="audio/webm",
        purpose=MediaAssetPurpose.voice,
        status=MediaAssetStatus.active,
        byte_size=len(audio_bytes),
    )
    db_session.add(asset)
    await db_session.flush()
    media_client._objects[object_key] = {
        "ContentLength": len(audio_bytes),
        "Body": audio_bytes,
    }
    return asset


@pytest.fixture
def media_client() -> FakeMediaClient:
    return FakeMediaClient()


@pytest.fixture
def whisper() -> FakeWhisperClient:
    return FakeWhisperClient(text="My brakes are squealing.", audio_seconds=4)


@pytest.fixture
def runner() -> FakeAgentRunner:
    return FakeAgentRunner()


@pytest.fixture
def media_service(db_session: AsyncSession, media_client: FakeMediaClient) -> MediaService:
    return MediaService(session=db_session, client=media_client, bucket=BUCKET)


@pytest.fixture
def ai_service(
    db_session: AsyncSession,
    redis: Redis,
    settings: Settings,
    runner: FakeAgentRunner,
    whisper: FakeWhisperClient,
    media_client: FakeMediaClient,
    media_service: MediaService,
) -> AiMechanicService:
    return AiMechanicService(
        session=db_session,
        redis=redis,
        runner=runner,
        embeddings=FakeEmbeddingClient(),
        settings=settings,
        whisper=whisper,
        media_download=media_client,
    )


async def test_voice_message_runs_whisper_then_agent(
    ai_service: AiMechanicService,
    db_session: AsyncSession,
    media_client: FakeMediaClient,
    runner: FakeAgentRunner,
    whisper: FakeWhisperClient,
) -> None:
    user = await _make_user(db_session, "+97688114201")
    sess = await ai_service.create_session(user_id=user.id, payload=SessionCreateIn())
    asset = await _make_voice_asset(
        db_session=db_session,
        media_client=media_client,
        owner_id=user.id,
        object_key=f"voice/{user.id}/sample.webm",
        audio_bytes=b"FAKE-AUDIO",
    )

    reply = await ai_service.post_voice_message(
        session_id=sess.id,
        user_id=user.id,
        payload=VoiceMessageCreateIn(media_asset_id=asset.id),
    )

    assert reply.transcript.text == "My brakes are squealing."
    assert reply.transcript.audio_seconds == 4
    assert reply.user_message.content == "My brakes are squealing."
    assert reply.assistant_message.role == AiMessageRole.assistant
    # Whisper got called once with the audio bytes.
    assert len(whisper.calls) == 1
    assert whisper.calls[0]["byte_size"] == len(b"FAKE-AUDIO")
    # Agent runner saw the transcript as the user input.
    assert runner.calls[-1]["user_input"] == "My brakes are squealing."

    # Two spend rows: one for Whisper, one for the agent.
    spend_rows = list((await db_session.execute(select(AiSpendEvent))).scalars())
    by_model: dict[str, AiSpendEvent] = {row.model: row for row in spend_rows}
    assert "whisper-1" in by_model
    assert by_model["whisper-1"].audio_seconds == 4
    # 4 seconds × 333 micro-MNT = 1332.
    assert by_model["whisper-1"].est_cost_micro_mnt == 4 * 333
    # Transcript audit row persisted.
    transcripts = list((await db_session.execute(select(AiVoiceTranscript))).scalars())
    assert len(transcripts) == 1
    assert transcripts[0].media_asset_id == asset.id


async def test_voice_message_rejects_stranger_asset(
    ai_service: AiMechanicService,
    db_session: AsyncSession,
    media_client: FakeMediaClient,
) -> None:
    owner = await _make_user(db_session, "+97688114202")
    stranger = await _make_user(db_session, "+97688114203")
    sess = await ai_service.create_session(user_id=stranger.id, payload=SessionCreateIn())
    asset = await _make_voice_asset(
        db_session=db_session,
        media_client=media_client,
        owner_id=owner.id,
        object_key=f"voice/{owner.id}/owner.webm",
        audio_bytes=b"AUDIO",
    )
    with pytest.raises(NotFoundError):
        await ai_service.post_voice_message(
            session_id=sess.id,
            user_id=stranger.id,
            payload=VoiceMessageCreateIn(media_asset_id=asset.id),
        )


async def test_voice_message_rejects_wrong_purpose(
    ai_service: AiMechanicService,
    db_session: AsyncSession,
    media_client: FakeMediaClient,
) -> None:
    user = await _make_user(db_session, "+97688114204")
    sess = await ai_service.create_session(user_id=user.id, payload=SessionCreateIn())
    asset = MediaAsset(
        owner_id=user.id,
        bucket=BUCKET,
        object_key=f"part_search/{user.id}/x.jpg",
        content_type="image/jpeg",
        purpose=MediaAssetPurpose.part_search,
        status=MediaAssetStatus.active,
        byte_size=10,
    )
    db_session.add(asset)
    await db_session.flush()
    media_client._objects[asset.object_key] = {
        "ContentLength": 10,
        "Body": b"NOTAUDIO00",
    }
    with pytest.raises(ConflictError):
        await ai_service.post_voice_message(
            session_id=sess.id,
            user_id=user.id,
            payload=VoiceMessageCreateIn(media_asset_id=asset.id),
        )


async def test_voice_message_blank_transcript_409(
    db_session: AsyncSession,
    redis: Redis,
    settings: Settings,
    media_client: FakeMediaClient,
) -> None:
    """A silent clip → empty transcript is rejected so the agent isn't fed noise."""
    silent_whisper = FakeWhisperClient(text="   ", audio_seconds=1)
    service = AiMechanicService(
        session=db_session,
        redis=redis,
        runner=FakeAgentRunner(),
        embeddings=FakeEmbeddingClient(),
        settings=settings,
        whisper=silent_whisper,
        media_download=media_client,
    )
    user = await _make_user(db_session, "+97688114205")
    sess = await service.create_session(user_id=user.id, payload=SessionCreateIn())
    asset = await _make_voice_asset(
        db_session=db_session,
        media_client=media_client,
        owner_id=user.id,
        object_key=f"voice/{user.id}/silent.webm",
        audio_bytes=b"S",
    )
    with pytest.raises(ConflictError):
        await service.post_voice_message(
            session_id=sess.id,
            user_id=user.id,
            payload=VoiceMessageCreateIn(media_asset_id=asset.id),
        )


# Suppress unused-import warning on the typing alias when the module
# is imported in test discovery.
_ = Any
