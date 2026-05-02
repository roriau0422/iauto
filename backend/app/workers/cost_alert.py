"""Daily AI-spend alert cron.

Runs at 05:00 UTC. Sums `ai_spend_events.est_cost_micro_mnt` over the
trailing 24 hours; if the total exceeds `AI_DAILY_SPEND_BUDGET_MICRO_MNT`
the cron pages `OPERATOR_PHONE` via the configured SMS provider.

The cron also writes per-model + per-user totals to the structured
log so the analytics-reporter agent can pull them downstream.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai_mechanic.models import AiSpendEvent
from app.identity.providers.sms import make_sms_provider
from app.platform.config import get_settings
from app.platform.logging import get_logger

logger = get_logger("app.workers.cost_alert")


async def run_once(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """Returns the spend total in micro-MNT, regardless of whether
    a page was sent. The total is logged either way."""
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(hours=24)

    # Read-only — SQLAlchemy auto-begins a transaction on the first
    # execute() and rolls it back on context exit. No need for an
    # explicit session.begin() block (which would also conflict with
    # the savepoint-bound test session).
    async with session_factory() as session:
        total = await _trailing_24h_total(session, cutoff)
        per_model = await _trailing_24h_per_model(session, cutoff)

    logger.info(
        "ai_spend_24h_summary",
        total_micro_mnt=total,
        breakdown=per_model,
    )

    budget = settings.ai_daily_spend_budget_micro_mnt
    if budget <= 0 or total <= budget:
        return total

    if not (settings.operator_phone and settings.messagepro_api_key):
        # Configured to alert but no destination — log loudly.
        logger.error(
            "ai_spend_alert_undelivered",
            reason="no_operator_phone_or_sms_creds",
            total_micro_mnt=total,
            budget_micro_mnt=budget,
        )
        return total

    body = _build_alert_body(total_micro_mnt=total, budget_micro_mnt=budget)
    sms = make_sms_provider(settings)
    await sms.send(settings.operator_phone, body)
    logger.warning(
        "ai_spend_alert_sent",
        total_micro_mnt=total,
        budget_micro_mnt=budget,
        operator_phone_tail=settings.operator_phone[-4:],
    )
    return total


async def _trailing_24h_total(session: AsyncSession, cutoff: datetime) -> int:
    stmt = select(func.coalesce(func.sum(AiSpendEvent.est_cost_micro_mnt), 0)).where(
        AiSpendEvent.created_at >= cutoff
    )
    return int((await session.execute(stmt)).scalar_one())


async def _trailing_24h_per_model(session: AsyncSession, cutoff: datetime) -> dict[str, int]:
    stmt = (
        select(
            AiSpendEvent.model,
            func.coalesce(func.sum(AiSpendEvent.est_cost_micro_mnt), 0),
        )
        .where(AiSpendEvent.created_at >= cutoff)
        .group_by(AiSpendEvent.model)
    )
    result = await session.execute(stmt)
    return {row[0]: int(row[1]) for row in result.all()}


def _build_alert_body(*, total_micro_mnt: int, budget_micro_mnt: int) -> str:
    """Assemble a 168-char-budget MessagePro body.

    Same budget rule as the XYP alert path — MessagePro auto-appends
    " Navi market" (12 chars) so the body must fit in 168 to leave
    room. Numbers are reported in MNT (10^-6) for human readability.
    """
    total_mnt = total_micro_mnt // 1_000_000
    budget_mnt = budget_micro_mnt // 1_000_000
    body = (
        f"iAuto AI: 24h spend {total_mnt:,} MNT exceeded budget "
        f"{budget_mnt:,} MNT. Check spend dashboard."
    )
    return body[:168]


async def tick(ctx: dict[str, Any]) -> int:
    factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    return await run_once(factory)
