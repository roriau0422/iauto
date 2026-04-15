"""Marketplace service — RFQ submission and cancellation (session 4 slice)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.marketplace.events import PartSearchCancelled, PartSearchSubmitted
from app.marketplace.models import PartSearchRequest, PartSearchStatus
from app.marketplace.repository import PartSearchRepository
from app.marketplace.schemas import PartSearchCreateIn
from app.platform.errors import ConflictError, NotFoundError
from app.platform.logging import get_logger
from app.platform.outbox import write_outbox_event
from app.vehicles.repository import OwnershipRepository, VehicleRepository

logger = get_logger("app.marketplace.service")


@dataclass(slots=True)
class ListResult:
    items: list[PartSearchRequest]
    total: int


class MarketplaceService:
    def __init__(self, *, session: AsyncSession) -> None:
        self.session = session
        self.searches = PartSearchRepository(session)
        self.vehicles = VehicleRepository(session)
        self.ownerships = OwnershipRepository(session)

    async def submit_search(
        self,
        *,
        driver_id: uuid.UUID,
        payload: PartSearchCreateIn,
    ) -> PartSearchRequest:
        # Ownership + existence checks collapsed into a single opaque 404
        # to avoid leaking whether a vehicle_id exists outside the caller's
        # scope. The same pattern is used in vehicles.unregister.
        vehicle = await self.vehicles.get_by_id(payload.vehicle_id)
        if vehicle is None or not await self.ownerships.exists(driver_id, vehicle.id):
            raise NotFoundError("Vehicle not found")

        request = await self.searches.create(
            driver_id=driver_id,
            vehicle_id=vehicle.id,
            description=payload.description,
            media_urls=payload.media_urls,
        )
        write_outbox_event(
            self.session,
            PartSearchSubmitted(
                aggregate_id=request.id,
                driver_id=driver_id,
                vehicle_id=vehicle.id,
                vehicle_brand_id=vehicle.vehicle_brand_id,
                vehicle_model_id=vehicle.vehicle_model_id,
                description=payload.description,
                media_urls=list(payload.media_urls),
            ),
        )
        logger.info(
            "part_search_submitted",
            search_id=str(request.id),
            driver_id=str(driver_id),
            vehicle_id=str(vehicle.id),
        )
        return request

    async def get_for_driver(
        self, *, driver_id: uuid.UUID, search_id: uuid.UUID
    ) -> PartSearchRequest:
        request = await self.searches.get_by_id(search_id)
        # Opaque 404 when the search is missing or owned by someone else —
        # never hint at cross-tenant existence.
        if request is None or request.driver_id != driver_id:
            raise NotFoundError("Search not found")
        return request

    async def list_for_driver(
        self,
        *,
        driver_id: uuid.UUID,
        status: PartSearchStatus | None,
        limit: int,
        offset: int,
    ) -> ListResult:
        items, total = await self.searches.list_for_driver(
            driver_id=driver_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return ListResult(items=items, total=total)

    async def cancel(
        self, *, driver_id: uuid.UUID, search_id: uuid.UUID
    ) -> PartSearchRequest:
        request = await self.get_for_driver(driver_id=driver_id, search_id=search_id)
        if request.status != PartSearchStatus.open:
            raise ConflictError(
                f"Cannot cancel a search in status '{request.status.value}'"
            )
        request.status = PartSearchStatus.cancelled
        await self.session.flush()
        write_outbox_event(
            self.session,
            PartSearchCancelled(
                aggregate_id=request.id,
                driver_id=driver_id,
            ),
        )
        logger.info("part_search_cancelled", search_id=str(request.id))
        return request
