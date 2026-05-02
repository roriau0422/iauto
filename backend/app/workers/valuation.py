"""Daily CatBoost retrain cron.

Runs at 02:00 UTC. Pulls every `sales` row joined with vehicle facts,
fits a CatBoost regressor, evaluates MAE on a 20% holdout, uploads the
binary artifact to MinIO, and promotes the new model row to `active`.

Skips the run when there are fewer than `MIN_SAMPLES_FOR_TRAIN` sales
— the heuristic stays the served path until we have real signal.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.marketplace.models import PartSearchRequest, Sale
from app.media.client import S3MediaClient
from app.platform.config import get_settings
from app.platform.logging import get_logger
from app.valuation.repository import ValuationModelRepository
from app.vehicles.models import Vehicle

logger = get_logger("app.workers.valuation")

MIN_SAMPLES_FOR_TRAIN = 50
HOLDOUT_FRACTION = 0.2
MODEL_BUCKET_KEY_PREFIX = "valuation-models"

FEATURE_COLUMNS: list[str] = [
    "build_year",
    "vehicle_brand_id",
    "vehicle_model_id",
    "fuel_type",
    "steering_side",
    "capacity_cc",
]
# Indexes within FEATURE_COLUMNS that CatBoost should treat as categoricals.
_CAT_FEATURE_INDEXES: list[int] = [1, 2, 3, 4]


def _row_to_features(vehicle: Vehicle) -> list[Any]:
    return [
        vehicle.build_year or 0,
        str(vehicle.vehicle_brand_id) if vehicle.vehicle_brand_id else "",
        str(vehicle.vehicle_model_id) if vehicle.vehicle_model_id else "",
        vehicle.fuel_type or "",
        vehicle.steering_side.value if vehicle.steering_side else "",
        vehicle.capacity_cc or 0,
    ]


def _train_and_serialize(
    rows: list[tuple[Vehicle, int]],
) -> tuple[bytes, int]:
    """CPU-bound. Fit a CatBoost regressor and return (artifact_bytes, mae_mnt).

    Pulled out as a sync helper so we can hand it to `asyncio.to_thread`
    and keep the cron's outer `run_once` non-blocking.
    """
    from catboost import CatBoostRegressor

    x: list[list[Any]] = [_row_to_features(v) for v, _ in rows]
    y: list[float] = [float(price) for _, price in rows]

    split_at = max(1, int(len(rows) * (1 - HOLDOUT_FRACTION)))
    x_train, x_test = x[:split_at], x[split_at:]
    y_train, y_test = y[:split_at], y[split_at:]

    booster = CatBoostRegressor(
        iterations=200,
        depth=6,
        learning_rate=0.07,
        cat_features=_CAT_FEATURE_INDEXES,
        verbose=False,
    )
    booster.fit(x_train, y_train)

    # MAE on holdout (or train if holdout was empty).
    eval_x = x_test or x_train
    eval_y = y_test or y_train
    preds = booster.predict(eval_x)
    mae = int(sum(abs(p - a) for p, a in zip(preds, eval_y, strict=True)) / len(eval_y))

    with tempfile.NamedTemporaryFile(suffix=".cbm", delete=False) as fh:
        booster.save_model(fh.name)
        artifact_path = fh.name
    with open(artifact_path, "rb") as fh:
        artifact = fh.read()

    return artifact, mae


async def run_once(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """One retrain pass. Returns 1 if a new model was promoted, else 0."""
    async with session_factory() as session, session.begin():
        rows = await _gather_training_rows(session)
        if len(rows) < MIN_SAMPLES_FOR_TRAIN:
            logger.info(
                "valuation_retrain_skipped",
                reason="not_enough_samples",
                sample_count=len(rows),
            )
            return 0

        artifact, mae = await asyncio.to_thread(_train_and_serialize, rows)

        version = f"catboost-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
        settings = get_settings()
        client = S3MediaClient(settings)
        object_key = f"{MODEL_BUCKET_KEY_PREFIX}/{version}.cbm"
        # boto3 is sync; let it run on a worker thread so we don't stall
        # the event loop on a multi-MB upload to MinIO.
        await asyncio.to_thread(
            client._client.put_object,
            Bucket=settings.s3_bucket_media,
            Key=object_key,
            Body=artifact,
        )

        repo = ValuationModelRepository(session)
        row = await repo.create(
            version=version,
            sample_count=len(rows),
            mae_mnt=mae,
            artifact_object_key=object_key,
            feature_columns=FEATURE_COLUMNS,
        )
        await repo.promote(model_id=row.id)
        logger.info(
            "valuation_retrain_complete",
            model_id=str(row.id),
            version=version,
            sample_count=len(rows),
            mae_mnt=mae,
        )
        return 1


async def _gather_training_rows(session: AsyncSession) -> list[tuple[Vehicle, int]]:
    """Pull every sale joined with the underlying vehicle.

    `sales.price_mnt` is the regression target. `Vehicle` carries the
    categorical + numeric features. The join goes through
    `part_search_requests` because that's where the vehicle FK lives.
    """
    stmt = (
        select(Vehicle, Sale.price_mnt)
        .join(PartSearchRequest, PartSearchRequest.id == Sale.part_search_id)
        .join(Vehicle, Vehicle.id == PartSearchRequest.vehicle_id)
        .order_by(Sale.created_at)
    )
    result = await session.execute(stmt)
    return [(vehicle, int(price)) for vehicle, price in result.all()]


async def tick(ctx: dict[str, Any]) -> int:
    factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    return await run_once(factory)
