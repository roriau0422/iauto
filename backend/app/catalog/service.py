"""Catalog service — listings and brand/model resolution for XYP strings."""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import VehicleBrand, VehicleCountry, VehicleModel
from app.catalog.repository import CatalogRepository
from app.platform.logging import get_logger

logger = get_logger("app.catalog.service")


# Case-folding for slug matching: NFKD-normalize, strip diacritics, drop any
# character outside [a-z0-9], collapse whitespace. Idempotent.
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


def slugify(raw: str) -> str:
    """Deterministic slug for case-insensitive exact matching.

    `"Toyota"`, `"TOYOTA"`, `"toyota  "`, `"Toyota!"` all map to `"toyota"`.
    `"Mercedes-Benz"` → `"mercedesbenz"`. Matching is exact on the slug, so
    typos still miss — that's intentional. Unmatched strings are logged and
    curated weekly instead of being guessed at by fuzzy logic.
    """
    nfkd = unicodedata.normalize("NFKD", raw)
    ascii_only = nfkd.encode("ascii", "ignore").decode("ascii")
    return _SLUG_STRIP_RE.sub("", ascii_only.lower())


@dataclass(slots=True)
class ResolvedBrandModel:
    brand_id: uuid.UUID | None
    model_id: uuid.UUID | None


class CatalogService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CatalogRepository(session)

    # ---- listings ----------------------------------------------------------

    async def list_countries(self) -> list[VehicleCountry]:
        return await self.repo.list_countries()

    async def list_brands(self, *, country_id: uuid.UUID | None = None) -> list[VehicleBrand]:
        return await self.repo.list_brands(country_id=country_id)

    async def list_models(self, *, brand_id: uuid.UUID | None = None) -> list[VehicleModel]:
        return await self.repo.list_models(brand_id=brand_id)

    # ---- resolution (called during vehicle registration) ------------------

    async def resolve_brand_model(
        self, *, make: str | None, model: str | None
    ) -> ResolvedBrandModel:
        """Resolve free-text XYP make/model strings to catalog IDs.

        Matching is exact on the normalized slug. Misses are logged (with the
        original raw string, not the slug, so they're actionable) and the
        corresponding ID comes back as None — the vehicles table keeps the
        raw string columns for display until a curator adds the catalog row.
        """
        brand_id: uuid.UUID | None = None
        model_id: uuid.UUID | None = None

        if make:
            brand_slug = slugify(make)
            brand = await self.repo.get_brand_by_slug(brand_slug) if brand_slug else None
            if brand is None:
                logger.info(
                    "catalog_brand_unmatched",
                    make_raw=make,
                    slug_attempted=brand_slug,
                )
            else:
                brand_id = brand.id
                if model:
                    model_slug = slugify(model)
                    row = (
                        await self.repo.get_model_by_brand_slug(brand_id=brand.id, slug=model_slug)
                        if model_slug
                        else None
                    )
                    if row is None:
                        logger.info(
                            "catalog_model_unmatched",
                            brand_slug=brand_slug,
                            model_raw=model,
                            slug_attempted=model_slug,
                        )
                    else:
                        model_id = row.id

        return ResolvedBrandModel(brand_id=brand_id, model_id=model_id)
