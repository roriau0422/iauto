"""Database access for the marketplace context."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.schemas import CoverageFilter
from app.marketplace.models import PartSearchRequest, PartSearchStatus, Quote, QuoteCondition
from app.vehicles.models import Vehicle


def _build_coverage_where(coverage: list[CoverageFilter]) -> ColumnElement[bool]:
    """Translate a business's coverage set into a SQLAlchemy WHERE clause.

    Each entry becomes `(brand = :b AND [year_start_ok] AND [year_end_ok]
    AND [steering_ok])`; the set is OR'd together. A NULL slot on the
    coverage side drops the predicate entirely — no bound means no
    constraint, so the `and_()` just gets one less clause instead of a
    tautology.

    Vehicle-side NULLs: if coverage constrains year or steering but the
    vehicle row has `build_year IS NULL` or `steering_side IS NULL`, the
    comparison is SQL-NULL which Postgres treats as false. Net effect:
    non-enriched vehicles never survive a restrictive coverage filter.

    Shared between the incoming feed (`list_incoming`) and the
    per-search coverage probe (`search_matches_coverage`) so the two
    paths can't drift.
    """
    clauses: list[ColumnElement[bool]] = []
    for entry in coverage:
        parts: list[ColumnElement[bool]] = [Vehicle.vehicle_brand_id == entry.brand_id]
        if entry.year_start is not None:
            parts.append(Vehicle.build_year >= entry.year_start)
        if entry.year_end is not None:
            parts.append(Vehicle.build_year <= entry.year_end)
        if entry.steering_side is not None:
            parts.append(Vehicle.steering_side == entry.steering_side)
        clauses.append(and_(*parts))
    return or_(*clauses)


class PartSearchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, search_id: uuid.UUID) -> PartSearchRequest | None:
        return await self.session.get(PartSearchRequest, search_id)

    async def create(
        self,
        *,
        driver_id: uuid.UUID,
        vehicle_id: uuid.UUID,
        description: str,
        media_urls: list[str],
    ) -> PartSearchRequest:
        row = PartSearchRequest(
            driver_id=driver_id,
            vehicle_id=vehicle_id,
            description=description,
            media_urls=list(media_urls),
            status=PartSearchStatus.open,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_for_driver(
        self,
        *,
        driver_id: uuid.UUID,
        status: PartSearchStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[list[PartSearchRequest], int]:
        base = select(PartSearchRequest).where(PartSearchRequest.driver_id == driver_id)
        count_base = select(func.count(PartSearchRequest.id)).where(
            PartSearchRequest.driver_id == driver_id
        )
        if status is not None:
            base = base.where(PartSearchRequest.status == status)
            count_base = count_base.where(PartSearchRequest.status == status)
        stmt = base.order_by(PartSearchRequest.created_at.desc()).limit(limit).offset(offset)
        rows_result = await self.session.execute(stmt)
        total_result = await self.session.execute(count_base)
        rows = list(rows_result.scalars())
        total = int(total_result.scalar_one())
        return rows, total

    async def list_incoming(
        self,
        *,
        coverage: list[CoverageFilter],
        limit: int,
        offset: int,
    ) -> tuple[list[PartSearchRequest], int]:
        """Paginated feed of open searches whose vehicle matches the coverage.

        Joined against vehicles so the WHERE can filter on brand, year
        and steering side. Only `status=open` searches participate —
        cancelled/expired/fulfilled rows stay out of the feed.
        """
        if not coverage:
            return [], 0

        where_clause = and_(
            PartSearchRequest.status == PartSearchStatus.open,
            Vehicle.vehicle_brand_id.is_not(None),
            _build_coverage_where(coverage),
        )

        stmt = (
            select(PartSearchRequest)
            .join(Vehicle, Vehicle.id == PartSearchRequest.vehicle_id)
            .where(where_clause)
            .order_by(PartSearchRequest.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        count_stmt = (
            select(func.count(PartSearchRequest.id))
            .join(Vehicle, Vehicle.id == PartSearchRequest.vehicle_id)
            .where(where_clause)
        )
        rows_result = await self.session.execute(stmt)
        total_result = await self.session.execute(count_stmt)
        return list(rows_result.scalars()), int(total_result.scalar_one())

    async def search_matches_coverage(
        self,
        *,
        search_id: uuid.UUID,
        coverage: list[CoverageFilter],
    ) -> bool:
        """Return True iff this search's vehicle is inside the coverage set.

        Reuses the same WHERE builder as `list_incoming` so the feed
        and the quote-submission gate can't disagree. A search that
        isn't `open` still participates here — the "is search open?"
        check is the caller's concern, we only answer the coverage
        question.
        """
        if not coverage:
            return False
        stmt = (
            select(PartSearchRequest.id)
            .join(Vehicle, Vehicle.id == PartSearchRequest.vehicle_id)
            .where(
                PartSearchRequest.id == search_id,
                Vehicle.vehicle_brand_id.is_not(None),
                _build_coverage_where(coverage),
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None


class QuoteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, quote_id: uuid.UUID) -> Quote | None:
        return await self.session.get(Quote, quote_id)

    async def get_by_search_and_business(
        self,
        *,
        part_search_id: uuid.UUID,
        business_id: uuid.UUID,
    ) -> Quote | None:
        stmt = select(Quote).where(
            Quote.part_search_id == part_search_id,
            Quote.tenant_id == business_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        part_search_id: uuid.UUID,
        business_id: uuid.UUID,
        price_mnt: int,
        condition: QuoteCondition,
        notes: str | None,
        media_urls: list[Any],
    ) -> Quote:
        quote = Quote(
            part_search_id=part_search_id,
            tenant_id=business_id,
            price_mnt=price_mnt,
            condition=condition,
            notes=notes,
            media_urls=list(media_urls),
        )
        self.session.add(quote)
        await self.session.flush()
        return quote

    async def list_for_business(
        self,
        *,
        business_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[Quote], int]:
        base = select(Quote).where(Quote.tenant_id == business_id)
        stmt = base.order_by(Quote.created_at.desc()).limit(limit).offset(offset)
        count_stmt = select(func.count(Quote.id)).where(Quote.tenant_id == business_id)
        rows_result = await self.session.execute(stmt)
        total_result = await self.session.execute(count_stmt)
        return list(rows_result.scalars()), int(total_result.scalar_one())

    async def list_for_search(
        self,
        *,
        part_search_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[Quote], int]:
        base = select(Quote).where(Quote.part_search_id == part_search_id)
        stmt = base.order_by(Quote.created_at.desc()).limit(limit).offset(offset)
        count_stmt = select(func.count(Quote.id)).where(Quote.part_search_id == part_search_id)
        rows_result = await self.session.execute(stmt)
        total_result = await self.session.execute(count_stmt)
        return list(rows_result.scalars()), int(total_result.scalar_one())
