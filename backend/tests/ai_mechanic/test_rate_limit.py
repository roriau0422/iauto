"""Daily request limit + spend log behavior."""

from __future__ import annotations

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_mechanic.embeddings import FakeEmbeddingClient
from app.ai_mechanic.schemas import MessageCreateIn, SessionCreateIn
from app.ai_mechanic.service import AiMechanicService
from app.identity.models import User, UserRole
from app.platform.config import Settings
from app.platform.errors import RateLimitedError
from tests.ai_mechanic.fakes import FakeAgentRunner


@pytest.fixture
def settings_low_limit(settings: Settings) -> Settings:
    """Override the request limit to 3 so the test runs fast."""
    return settings.model_copy(update={"ai_daily_request_limit_per_user": 3})


@pytest.fixture
def ai_service(
    db_session: AsyncSession,
    redis: Redis,
    settings_low_limit: Settings,
) -> AiMechanicService:
    return AiMechanicService(
        session=db_session,
        redis=redis,
        runner=FakeAgentRunner(),
        embeddings=FakeEmbeddingClient(),
        settings=settings_low_limit,
    )


async def test_daily_limit_rejects_after_quota(
    ai_service: AiMechanicService,
    db_session: AsyncSession,
) -> None:
    user = User(phone="+97688114101", role=UserRole.driver)
    db_session.add(user)
    await db_session.flush()
    sess = await ai_service.create_session(user_id=user.id, payload=SessionCreateIn())

    for _ in range(3):
        await ai_service.post_user_message(
            session_id=sess.id,
            user_id=user.id,
            payload=MessageCreateIn(content="ok"),
        )

    # 4th request → 429.
    with pytest.raises(RateLimitedError):
        await ai_service.post_user_message(
            session_id=sess.id,
            user_id=user.id,
            payload=MessageCreateIn(content="too much"),
        )


async def test_daily_limit_zero_disables_check(
    db_session: AsyncSession,
    redis: Redis,
    settings: Settings,
) -> None:
    """`AI_DAILY_REQUEST_LIMIT_PER_USER=0` disables the rate limiter."""
    s = settings.model_copy(update={"ai_daily_request_limit_per_user": 0})
    service = AiMechanicService(
        session=db_session,
        redis=redis,
        runner=FakeAgentRunner(),
        embeddings=FakeEmbeddingClient(),
        settings=s,
    )
    user = User(phone="+97688114102", role=UserRole.driver)
    db_session.add(user)
    await db_session.flush()
    sess = await service.create_session(user_id=user.id, payload=SessionCreateIn())
    # 50 calls without limit.
    for _ in range(50):
        await service.post_user_message(
            session_id=sess.id,
            user_id=user.id,
            payload=MessageCreateIn(content="ok"),
        )
