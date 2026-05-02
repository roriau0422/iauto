"""Read-only spend reporting for the admin surface."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.schemas import SpendByModelOut, SpendByUserOut, SpendReportOut
from app.ai_mechanic.models import AiSpendEvent

_TOP_USERS_LIMIT = 10


class AdminSpendService:
    def __init__(self, *, session: AsyncSession) -> None:
        self.session = session

    async def report(self, *, window_hours: int) -> SpendReportOut:
        cutoff = datetime.now(UTC) - timedelta(hours=window_hours)

        total_row = await self.session.execute(
            select(func.coalesce(func.sum(AiSpendEvent.est_cost_micro_mnt), 0)).where(
                AiSpendEvent.created_at >= cutoff
            )
        )
        total = int(total_row.scalar_one())

        by_model_rows = await self.session.execute(
            select(
                AiSpendEvent.model,
                func.coalesce(func.sum(AiSpendEvent.prompt_tokens), 0),
                func.coalesce(func.sum(AiSpendEvent.completion_tokens), 0),
                func.coalesce(func.sum(AiSpendEvent.audio_seconds), 0),
                func.coalesce(func.sum(AiSpendEvent.est_cost_micro_mnt), 0),
            )
            .where(AiSpendEvent.created_at >= cutoff)
            .group_by(AiSpendEvent.model)
            .order_by(desc(func.sum(AiSpendEvent.est_cost_micro_mnt)))
        )
        by_model = [
            SpendByModelOut(
                model=row[0],
                prompt_tokens=int(row[1]),
                completion_tokens=int(row[2]),
                audio_seconds=int(row[3]),
                micro_mnt=int(row[4]),
            )
            for row in by_model_rows.all()
        ]

        top_user_rows = await self.session.execute(
            select(
                AiSpendEvent.user_id,
                func.count(),
                func.coalesce(func.sum(AiSpendEvent.est_cost_micro_mnt), 0),
            )
            .where(AiSpendEvent.created_at >= cutoff)
            .group_by(AiSpendEvent.user_id)
            .order_by(desc(func.sum(AiSpendEvent.est_cost_micro_mnt)))
            .limit(_TOP_USERS_LIMIT)
        )
        top_users = [
            SpendByUserOut(user_id=row[0], requests=int(row[1]), micro_mnt=int(row[2]))
            for row in top_user_rows.all()
        ]

        return SpendReportOut(
            window_hours=window_hours,
            total_micro_mnt=total,
            by_model=by_model,
            top_users=top_users,
        )
