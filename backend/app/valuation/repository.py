"""Database access for the valuation context."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.valuation.models import (
    ValuationEstimate,
    ValuationModel,
    ValuationModelStatus,
)


class ValuationModelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active(self) -> ValuationModel | None:
        stmt = select(ValuationModel).where(ValuationModel.status == ValuationModelStatus.active)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(
        self,
        *,
        version: str,
        sample_count: int,
        mae_mnt: int | None,
        artifact_object_key: str | None,
        feature_columns: list[str],
    ) -> ValuationModel:
        from datetime import UTC, datetime

        row = ValuationModel(
            version=version,
            status=ValuationModelStatus.training,
            sample_count=sample_count,
            mae_mnt=mae_mnt,
            artifact_object_key=artifact_object_key,
            feature_columns=list(feature_columns),
            trained_at=datetime.now(UTC),
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def promote(self, *, model_id: uuid.UUID) -> ValuationModel:
        from sqlalchemy import update

        # Demote any existing active model first to satisfy the partial
        # unique index.
        await self.session.execute(
            update(ValuationModel)
            .where(ValuationModel.status == ValuationModelStatus.active)
            .values(status=ValuationModelStatus.retired)
        )
        await self.session.execute(
            update(ValuationModel)
            .where(ValuationModel.id == model_id)
            .values(status=ValuationModelStatus.active)
        )
        await self.session.flush()
        row = await self.session.get(ValuationModel, model_id)
        if row is None:
            raise RuntimeError("Promoted model row missing after update")
        return row


class ValuationEstimateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: uuid.UUID | None,
        model_id: uuid.UUID | None,
        features: dict[str, Any],
        predicted_mnt: int,
        low_mnt: int | None,
        high_mnt: int | None,
    ) -> ValuationEstimate:
        row = ValuationEstimate(
            user_id=user_id,
            model_id=model_id,
            features=features,
            predicted_mnt=predicted_mnt,
            low_mnt=low_mnt,
            high_mnt=high_mnt,
        )
        self.session.add(row)
        await self.session.flush()
        return row
