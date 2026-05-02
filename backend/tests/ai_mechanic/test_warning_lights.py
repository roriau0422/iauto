"""Warning-light classifier flow."""

from __future__ import annotations

import uuid

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_mechanic.embeddings import FakeEmbeddingClient
from app.ai_mechanic.models import (
    AiMessageRole,
    AiWarningLightPrediction,
)
from app.ai_mechanic.schemas import (
    SessionCreateIn,
    WarningLightMessageCreateIn,
)
from app.ai_mechanic.service import AiMechanicService
from app.ai_mechanic.warning_lights import (
    ClassificationResult,
    FakeWarningLightClassifier,
    HashHeuristicClassifier,
    WarningLightPrediction,
)
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


async def _make_warning_light_asset(
    *,
    db_session: AsyncSession,
    media_client: FakeMediaClient,
    owner_id: uuid.UUID,
    object_key: str,
    image_bytes: bytes,
) -> MediaAsset:
    asset = MediaAsset(
        owner_id=owner_id,
        bucket=BUCKET,
        object_key=object_key,
        content_type="image/jpeg",
        purpose=MediaAssetPurpose.warning_light,
        status=MediaAssetStatus.active,
        byte_size=len(image_bytes),
    )
    db_session.add(asset)
    await db_session.flush()
    media_client._objects[object_key] = {
        "ContentLength": len(image_bytes),
        "Body": image_bytes,
    }
    return asset


@pytest.fixture
def media_client() -> FakeMediaClient:
    return FakeMediaClient()


@pytest.fixture
def classifier() -> FakeWarningLightClassifier:
    return FakeWarningLightClassifier()


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
    classifier: FakeWarningLightClassifier,
) -> AiMechanicService:
    return AiMechanicService(
        session=db_session,
        redis=redis,
        runner=runner,
        embeddings=FakeEmbeddingClient(),
        settings=settings,
        media_download=media_client,
        warning_light_classifier=classifier,
    )


async def test_classify_runs_then_agent(
    ai_service: AiMechanicService,
    db_session: AsyncSession,
    media_client: FakeMediaClient,
    runner: FakeAgentRunner,
    classifier: FakeWarningLightClassifier,
) -> None:
    user = await _make_user(db_session, "+97688114301")
    sess = await ai_service.create_session(user_id=user.id, payload=SessionCreateIn())
    asset = await _make_warning_light_asset(
        db_session=db_session,
        media_client=media_client,
        owner_id=user.id,
        object_key=f"warning_light/{user.id}/dashboard.jpg",
        image_bytes=b"FAKE-DASHBOARD-IMAGE",
    )
    classifier.next_result = ClassificationResult(
        model="warning-light-test",
        predictions=[
            WarningLightPrediction(code="oil_pressure", confidence=0.92),
            WarningLightPrediction(code="engine_warning_amber", confidence=0.45),
            WarningLightPrediction(code="seatbelt", confidence=0.05),
        ],
    )

    reply = await ai_service.post_warning_light_message(
        session_id=sess.id,
        user_id=user.id,
        payload=WarningLightMessageCreateIn(media_asset_id=asset.id),
    )

    # Top-K labels with confidence above the floor (0.20). seatbelt at
    # 0.05 dropped from the LLM-facing summary.
    codes = [label["code"] for label in reply.labels]
    assert codes == ["oil_pressure", "engine_warning_amber"]
    assert reply.labels[0]["display_en"] == "Oil pressure"
    assert reply.labels[0]["severity"] == "critical"

    # User message handed to the agent runner contains the labels.
    assert runner.calls[-1]["user_input"].startswith("[warning-light scan]")
    assert "oil_pressure" in runner.calls[-1]["user_input"]
    assert "seatbelt" not in runner.calls[-1]["user_input"]

    # Audit row + assistant reply persisted.
    rows = list((await db_session.execute(select(AiWarningLightPrediction))).scalars())
    assert len(rows) == 1
    assert rows[0].top_code == "oil_pressure"
    assert rows[0].model == "warning-light-test"
    assert reply.assistant_message.role == AiMessageRole.assistant
    # Classifier is self-hosted → 0 cost on the spend log.
    assert reply.classifier_micro_mnt == 0


async def test_classify_no_confident_labels_still_dispatches(
    ai_service: AiMechanicService,
    db_session: AsyncSession,
    media_client: FakeMediaClient,
    runner: FakeAgentRunner,
    classifier: FakeWarningLightClassifier,
) -> None:
    user = await _make_user(db_session, "+97688114302")
    sess = await ai_service.create_session(user_id=user.id, payload=SessionCreateIn())
    asset = await _make_warning_light_asset(
        db_session=db_session,
        media_client=media_client,
        owner_id=user.id,
        object_key=f"warning_light/{user.id}/blurry.jpg",
        image_bytes=b"BLURRY",
    )
    classifier.next_result = ClassificationResult(
        model="warning-light-test",
        predictions=[
            WarningLightPrediction(code="seatbelt", confidence=0.10),
            WarningLightPrediction(code="low_fuel", confidence=0.05),
        ],
    )
    reply = await ai_service.post_warning_light_message(
        session_id=sess.id,
        user_id=user.id,
        payload=WarningLightMessageCreateIn(media_asset_id=asset.id),
    )
    assert reply.labels == []
    # Agent still ran with a "no confident labels" prompt.
    assert "no confident labels" in runner.calls[-1]["user_input"]


async def test_classify_rejects_wrong_purpose(
    ai_service: AiMechanicService,
    db_session: AsyncSession,
    media_client: FakeMediaClient,
) -> None:
    user = await _make_user(db_session, "+97688114303")
    sess = await ai_service.create_session(user_id=user.id, payload=SessionCreateIn())
    asset = MediaAsset(
        owner_id=user.id,
        bucket=BUCKET,
        object_key=f"voice/{user.id}/audio.webm",
        content_type="audio/webm",
        purpose=MediaAssetPurpose.voice,
        status=MediaAssetStatus.active,
        byte_size=10,
    )
    db_session.add(asset)
    await db_session.flush()
    media_client._objects[asset.object_key] = {
        "ContentLength": 10,
        "Body": b"AUDIONOTPHOTO",
    }
    with pytest.raises(ConflictError):
        await ai_service.post_warning_light_message(
            session_id=sess.id,
            user_id=user.id,
            payload=WarningLightMessageCreateIn(media_asset_id=asset.id),
        )


async def test_classify_rejects_stranger_asset(
    ai_service: AiMechanicService,
    db_session: AsyncSession,
    media_client: FakeMediaClient,
) -> None:
    owner = await _make_user(db_session, "+97688114304")
    stranger = await _make_user(db_session, "+97688114305")
    sess = await ai_service.create_session(user_id=stranger.id, payload=SessionCreateIn())
    asset = await _make_warning_light_asset(
        db_session=db_session,
        media_client=media_client,
        owner_id=owner.id,
        object_key=f"warning_light/{owner.id}/owner.jpg",
        image_bytes=b"X",
    )
    with pytest.raises(NotFoundError):
        await ai_service.post_warning_light_message(
            session_id=sess.id,
            user_id=stranger.id,
            payload=WarningLightMessageCreateIn(media_asset_id=asset.id),
        )


async def test_hash_heuristic_classifier_is_deterministic() -> None:
    """Same image bytes → same prediction across runs."""
    classifier = HashHeuristicClassifier()
    candidates = ["oil_pressure", "battery_charging", "low_fuel"]
    a = await classifier.classify(image_bytes=b"abc", candidate_codes=candidates)
    b = await classifier.classify(image_bytes=b"abc", candidate_codes=candidates)
    assert a.predictions[0].code == b.predictions[0].code
    assert a.predictions[0].confidence == b.predictions[0].confidence
    assert a.model == "warning-light-heuristic-v1"
