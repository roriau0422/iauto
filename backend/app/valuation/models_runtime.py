"""Runtime model: protocol + heuristic + CatBoost.

The heuristic ships as the cold-start fallback (no `sales` data yet)
AND as the test stub. `CatBoostValuationModel` is loaded from a MinIO
artifact when the trainer cron has produced one.

Pricing surface:
  predict(features) -> (predicted_mnt, low_mnt, high_mnt)

Confidence band is held +/- 15% of the point estimate for the
heuristic; the trained CatBoost reports a band derived from the
holdout MAE.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

# Median 2010–2025 used-car prices in MNT, calibrated against the spec
# §14 sample data. Refined per-brand once we ship real ingestion.
_BASE_PRICE_MNT = 30_000_000
# Yearly depreciation factor for cars older than the median sample year.
_DEPRECIATION_PER_YEAR = 0.92
# Mileage hit at ~50_000_000 km.
_MILEAGE_HIT_PER_KM = 80


@dataclass(slots=True)
class ValuationPrediction:
    predicted_mnt: int
    low_mnt: int
    high_mnt: int


class ValuationRuntime(Protocol):
    """Surface every concrete runtime implements."""

    version: str

    def predict(self, *, features: dict[str, Any]) -> ValuationPrediction: ...


class HeuristicValuationModel:
    """Cold-start + test fallback. No external state — deterministic."""

    version = "heuristic-v1"

    def predict(self, *, features: dict[str, Any]) -> ValuationPrediction:
        build_year = int(features.get("build_year") or datetime.now(UTC).year)
        years_old = max(0, datetime.now(UTC).year - build_year)
        depreciated = _BASE_PRICE_MNT * (_DEPRECIATION_PER_YEAR**years_old)

        mileage_km = features.get("mileage_km")
        mileage_hit = 0
        if isinstance(mileage_km, int):
            mileage_hit = mileage_km * _MILEAGE_HIT_PER_KM

        condition = features.get("condition")
        condition_factor = {
            "new": 1.10,
            "imported": 1.00,
            "used": 0.85,
        }.get(str(condition or "").lower(), 1.00)

        point = max(2_000_000, int((depreciated - mileage_hit) * condition_factor))
        # ±15% band keeps the heuristic honest about its imprecision.
        return ValuationPrediction(
            predicted_mnt=point,
            low_mnt=int(point * 0.85),
            high_mnt=int(point * 1.15),
        )


class CatBoostValuationModel:
    """Wraps a trained CatBoost regressor loaded from a binary artifact.

    Loaded lazily — `load_from_bytes` is called by the dependency
    builder once an active row + artifact exist. Until then, the
    heuristic is served.
    """

    version: str

    def __init__(
        self,
        *,
        version: str,
        feature_columns: list[str],
        mae_mnt: int | None,
        booster: object,
    ) -> None:
        self.version = version
        self._feature_columns = feature_columns
        self._mae_mnt = mae_mnt or 4_000_000
        self._booster = booster

    @classmethod
    def load_from_bytes(
        cls,
        *,
        version: str,
        feature_columns: list[str],
        mae_mnt: int | None,
        artifact: bytes,
    ) -> CatBoostValuationModel:
        # Lazy imports — catboost is heavy and only the live runtime
        # needs it; the heuristic + tests don't.
        import tempfile

        from catboost import CatBoostRegressor

        booster = CatBoostRegressor()
        # CatBoost's load_model wants a path; write the bytes to a
        # tempfile to avoid forking a serializer.
        with tempfile.NamedTemporaryFile(suffix=".cbm", delete=False) as fh:
            fh.write(artifact)
            artifact_path = fh.name
        booster.load_model(artifact_path)
        return cls(
            version=version,
            feature_columns=feature_columns,
            mae_mnt=mae_mnt,
            booster=booster,
        )

    def predict(self, *, features: dict[str, Any]) -> ValuationPrediction:
        # Build a feature row in the column order the model was trained on.
        row: list[Any] = []
        for col in self._feature_columns:
            value = features.get(col)
            row.append(value if value is not None else 0)
        # CatBoost accepts a single-row 2D list.
        prediction = float(self._booster.predict([row])[0])  # type: ignore[attr-defined]
        point = max(2_000_000, int(prediction))
        # Confidence band derived from the holdout MAE — wider than the
        # heuristic's flat 15% so we don't oversell the model's precision.
        delta = max(self._mae_mnt, int(point * 0.10))
        return ValuationPrediction(
            predicted_mnt=point,
            low_mnt=max(2_000_000, point - delta),
            high_mnt=point + delta,
        )
