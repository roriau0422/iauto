"""Agent dispatch flow: session creation, message persistence, spend log."""

from __future__ import annotations

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_mechanic.agent import AgentRunResult
from app.ai_mechanic.embeddings import FakeEmbeddingClient
from app.ai_mechanic.models import AiMessage, AiMessageRole, AiSpendEvent
from app.ai_mechanic.schemas import MessageCreateIn, SessionCreateIn
from app.ai_mechanic.service import AiMechanicService
from app.identity.models import User, UserRole
from app.platform.config import Settings
from tests.ai_mechanic.fakes import FakeAgentRunner


async def _make_user(db_session: AsyncSession, phone: str) -> User:
    user = User(phone=phone, role=UserRole.driver)
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
def runner() -> FakeAgentRunner:
    return FakeAgentRunner()


@pytest.fixture
def ai_service(
    db_session: AsyncSession,
    redis: Redis,
    settings: Settings,
    runner: FakeAgentRunner,
) -> AiMechanicService:
    return AiMechanicService(
        session=db_session,
        redis=redis,
        runner=runner,
        embeddings=FakeEmbeddingClient(),
        settings=settings,
    )


async def test_create_session_and_post_message(
    ai_service: AiMechanicService,
    db_session: AsyncSession,
    runner: FakeAgentRunner,
) -> None:
    user = await _make_user(db_session, "+97688114001")
    sess = await ai_service.create_session(
        user_id=user.id, payload=SessionCreateIn(title="Brake noise")
    )
    reply = await ai_service.post_user_message(
        session_id=sess.id,
        user_id=user.id,
        payload=MessageCreateIn(content="My brakes squeal at low speed."),
    )
    assert reply.user_message.content == "My brakes squeal at low speed."
    assert reply.assistant_message.content.startswith("Mock reply:")
    assert reply.prompt_tokens == 42
    assert reply.completion_tokens == 17

    # Runner saw exactly one call with no prior history.
    assert len(runner.calls) == 1
    assert runner.calls[0]["history_len"] == 0
    assert runner.calls[0]["user_input"] == "My brakes squeal at low speed."

    # Spend row was written.
    spend = (await db_session.execute(select(AiSpendEvent))).scalars().all()
    assert len(spend) == 1
    assert spend[0].user_id == user.id
    assert spend[0].prompt_tokens == 42
    assert spend[0].completion_tokens == 17


async def test_history_threaded_into_runner(
    ai_service: AiMechanicService,
    db_session: AsyncSession,
    runner: FakeAgentRunner,
) -> None:
    user = await _make_user(db_session, "+97688114002")
    sess = await ai_service.create_session(user_id=user.id, payload=SessionCreateIn())
    await ai_service.post_user_message(
        session_id=sess.id,
        user_id=user.id,
        payload=MessageCreateIn(content="What is brake fluid?"),
    )
    await ai_service.post_user_message(
        session_id=sess.id,
        user_id=user.id,
        payload=MessageCreateIn(content="When should I replace it?"),
    )
    # Second call sees the first turn (user + assistant) in its history.
    assert runner.calls[1]["history_len"] == 2


async def test_post_message_404_for_stranger(
    ai_service: AiMechanicService,
    db_session: AsyncSession,
) -> None:
    owner = await _make_user(db_session, "+97688114003")
    stranger = await _make_user(db_session, "+97688114004")
    sess = await ai_service.create_session(user_id=owner.id, payload=SessionCreateIn())
    from app.platform.errors import NotFoundError

    with pytest.raises(NotFoundError):
        await ai_service.post_user_message(
            session_id=sess.id,
            user_id=stranger.id,
            payload=MessageCreateIn(content="trespass"),
        )


async def test_tool_calls_persisted_as_tool_rows(
    ai_service: AiMechanicService,
    db_session: AsyncSession,
    runner: FakeAgentRunner,
) -> None:
    user = await _make_user(db_session, "+97688114005")
    sess = await ai_service.create_session(user_id=user.id, payload=SessionCreateIn())
    runner.next_result = AgentRunResult(
        final_output="Replace your brake pads.",
        prompt_tokens=100,
        completion_tokens=20,
        tool_calls=[
            {"name": "get_vehicle_context", "arguments": "{}"},
            {"name": "search_parts", "arguments": '{"query":"brake pads"}'},
        ],
    )
    await ai_service.post_user_message(
        session_id=sess.id,
        user_id=user.id,
        payload=MessageCreateIn(content="Help, my brakes are noisy."),
    )
    rows = (
        (
            await db_session.execute(
                select(AiMessage)
                .where(AiMessage.session_id == sess.id)
                .order_by(AiMessage.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    roles = [r.role for r in rows]
    assert AiMessageRole.user in roles
    assert AiMessageRole.assistant in roles
    tool_rows = [r for r in rows if r.role == AiMessageRole.tool]
    assert {r.tool_name for r in tool_rows} == {
        "get_vehicle_context",
        "search_parts",
    }


async def test_session_listing_scoped_to_user(
    ai_service: AiMechanicService, db_session: AsyncSession
) -> None:
    a = await _make_user(db_session, "+97688114006")
    b = await _make_user(db_session, "+97688114007")
    await ai_service.create_session(user_id=a.id, payload=SessionCreateIn(title="A1"))
    await ai_service.create_session(user_id=a.id, payload=SessionCreateIn(title="A2"))
    await ai_service.create_session(user_id=b.id, payload=SessionCreateIn(title="B1"))

    a_items, a_total = await ai_service.list_sessions(user_id=a.id, limit=20, offset=0)
    assert a_total == 2
    assert {s.title for s in a_items} == {"A1", "A2"}

    b_items, b_total = await ai_service.list_sessions(user_id=b.id, limit=20, offset=0)
    assert b_total == 1
    # Suppress unused.
    _ = b_items
