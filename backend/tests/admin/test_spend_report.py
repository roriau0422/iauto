"""Admin spend-report service tests."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.service import AdminSpendService
from app.ai_mechanic.models import AiSpendEvent
from app.identity.models import User, UserRole


async def _make_user(db_session: AsyncSession, phone: str) -> User:
    user = User(phone=phone, role=UserRole.driver)
    db_session.add(user)
    await db_session.flush()
    return user


async def _add_spend(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    model: str,
    micro_mnt: int,
    prompt: int = 0,
    completion: int = 0,
    audio: int = 0,
) -> None:
    db_session.add(
        AiSpendEvent(
            user_id=user_id,
            session_id=None,
            model=model,
            prompt_tokens=prompt,
            completion_tokens=completion,
            audio_seconds=audio,
            est_cost_micro_mnt=micro_mnt,
        )
    )
    await db_session.flush()


@pytest.mark.asyncio
async def test_spend_report_aggregates_totals_and_breakdowns(
    db_session: AsyncSession,
) -> None:
    alice = await _make_user(db_session, "+97688119001")
    bob = await _make_user(db_session, "+97688119002")

    await _add_spend(
        db_session,
        user_id=alice.id,
        model="gemini/gemini-3-flash-preview",
        micro_mnt=10_000,
        prompt=400,
        completion=200,
    )
    await _add_spend(
        db_session,
        user_id=alice.id,
        model="whisper-1",
        micro_mnt=5_000,
        audio=15,
    )
    await _add_spend(
        db_session,
        user_id=bob.id,
        model="gemini/gemini-3-flash-preview",
        micro_mnt=3_000,
        prompt=100,
        completion=50,
    )

    service = AdminSpendService(session=db_session)
    report = await service.report(window_hours=24)

    assert report.window_hours == 24
    assert report.total_micro_mnt == 18_000

    # Models are sorted by spend desc.
    assert [m.model for m in report.by_model] == [
        "gemini/gemini-3-flash-preview",
        "whisper-1",
    ]
    gem = next(m for m in report.by_model if m.model == "gemini/gemini-3-flash-preview")
    assert gem.micro_mnt == 13_000
    assert gem.prompt_tokens == 500
    assert gem.completion_tokens == 250
    whisper = next(m for m in report.by_model if m.model == "whisper-1")
    assert whisper.audio_seconds == 15

    # Top users sorted by spend desc — alice spent 15k vs bob's 3k.
    user_ids = [u.user_id for u in report.top_users]
    assert user_ids == [alice.id, bob.id]
    alice_row = next(u for u in report.top_users if u.user_id == alice.id)
    assert alice_row.requests == 2
    assert alice_row.micro_mnt == 15_000


@pytest.mark.asyncio
async def test_spend_report_empty_window_returns_zeros(db_session: AsyncSession) -> None:
    service = AdminSpendService(session=db_session)
    report = await service.report(window_hours=24)
    assert report.total_micro_mnt == 0
    assert report.by_model == []
    assert report.top_users == []


@pytest.mark.asyncio
async def test_spend_report_excludes_rows_outside_window(
    db_session: AsyncSession,
) -> None:
    """Rows older than the window must not show up. Asserts the cutoff
    is applied on `created_at` rather than across the whole table."""

    user = await _make_user(db_session, "+97688119003")

    # Add a recent row, then forge an old row by overriding created_at.
    await _add_spend(
        db_session,
        user_id=user.id,
        model="gemini/gemini-3-flash-preview",
        micro_mnt=1_234,
    )

    from datetime import UTC, datetime, timedelta

    old = AiSpendEvent(
        user_id=user.id,
        session_id=None,
        model="gemini/gemini-3-flash-preview",
        prompt_tokens=0,
        completion_tokens=0,
        audio_seconds=0,
        est_cost_micro_mnt=999_999,
        created_at=datetime.now(UTC) - timedelta(hours=48),
    )
    db_session.add(old)
    await db_session.flush()

    service = AdminSpendService(session=db_session)
    report = await service.report(window_hours=24)
    # The old row's 999_999 micro_mnt is excluded.
    assert report.total_micro_mnt == 1_234
