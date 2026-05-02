"""Marketplace service — sessions 4–6.

Driver-side RFQ (4), business-side feed + quotes (5), reservations + sales
+ reviews (6). The fulfillment loop closes here: a quote becomes a 24h
hold, the hold becomes a sale, both parties leave reviews.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.businesses.models import Business
from app.businesses.service import BusinessesService
from app.marketplace.events import (
    PartSearchCancelled,
    PartSearchSubmitted,
    QuoteSent,
    ReservationCancelled,
    ReservationStarted,
    ReviewSubmitted,
    SaleCompleted,
)
from app.marketplace.models import (
    PartSearchRequest,
    PartSearchStatus,
    Quote,
    Reservation,
    ReservationStatus,
    Review,
    ReviewDirection,
    Sale,
)
from app.marketplace.repository import (
    PartSearchRepository,
    QuoteRepository,
    ReservationRepository,
    ReviewRepository,
    SaleRepository,
)
from app.marketplace.schemas import (
    PartSearchCreateIn,
    QuoteCreateIn,
    ReviewCreateIn,
)
from app.media.models import MediaAssetPurpose
from app.media.service import MediaService
from app.platform.errors import ConflictError, ForbiddenError, NotFoundError
from app.platform.logging import get_logger
from app.platform.outbox import write_outbox_event
from app.vehicles.service import VehiclesService

logger = get_logger("app.marketplace.service")

# 24-hour reservation hold per spec §6. Long enough for the driver to
# arrange pickup / payment, short enough that other businesses don't get
# stuck waiting on a stale hold.
RESERVATION_TTL = timedelta(hours=24)


@dataclass(slots=True)
class ListResult:
    items: list[PartSearchRequest]
    total: int


@dataclass(slots=True)
class QuoteListResult:
    items: list[Quote]
    total: int


@dataclass(slots=True)
class ReservationListResult:
    items: list[Reservation]
    total: int


@dataclass(slots=True)
class SaleListResult:
    items: list[Sale]
    total: int


class MarketplaceService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        vehicles_svc: VehiclesService,
        businesses_svc: BusinessesService,
        media_svc: MediaService,
    ) -> None:
        self.session = session
        self.searches = PartSearchRepository(session)
        self.quotes = QuoteRepository(session)
        self.reservations = ReservationRepository(session)
        self.sales = SaleRepository(session)
        self.reviews = ReviewRepository(session)
        self.vehicles_svc = vehicles_svc
        self.businesses_svc = businesses_svc
        self.media_svc = media_svc

    # ---- driver-side (session 4) ------------------------------------------

    async def submit_search(
        self,
        *,
        driver_id: uuid.UUID,
        payload: PartSearchCreateIn,
    ) -> PartSearchRequest:
        # Ownership + existence collapsed into a single opaque 404 to avoid
        # leaking whether a vehicle_id exists outside the caller's scope.
        vehicle = await self.vehicles_svc.check_ownership(
            user_id=driver_id, vehicle_id=payload.vehicle_id
        )

        # Reject any media id that isn't a confirmed `part_search` asset
        # owned by this driver. 422 with the offending ids — easier to debug
        # than the alternative of silently dropping them.
        await self.media_svc.validate_asset_ids(
            owner_id=driver_id,
            asset_ids=payload.media_asset_ids,
            purpose=MediaAssetPurpose.part_search,
        )

        request = await self.searches.create(
            driver_id=driver_id,
            vehicle_id=vehicle.id,
            description=payload.description,
            media_asset_ids=payload.media_asset_ids,
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
                media_asset_ids=[str(i) for i in payload.media_asset_ids],
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

    async def cancel(self, *, driver_id: uuid.UUID, search_id: uuid.UUID) -> PartSearchRequest:
        request = await self.get_for_driver(driver_id=driver_id, search_id=search_id)
        if request.status != PartSearchStatus.open:
            raise ConflictError(f"Cannot cancel a search in status '{request.status.value}'")
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

    async def list_quotes_for_search(
        self,
        *,
        driver_id: uuid.UUID,
        search_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> QuoteListResult:
        """Driver views every quote submitted on their own search."""
        request = await self.get_for_driver(driver_id=driver_id, search_id=search_id)
        items, total = await self.quotes.list_for_search(
            part_search_id=request.id, limit=limit, offset=offset
        )
        return QuoteListResult(items=items, total=total)

    # ---- business-side (session 5) ----------------------------------------

    async def list_incoming(
        self,
        *,
        business_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> ListResult:
        """Paginated feed of open searches matching the business's coverage."""
        coverage = await self.businesses_svc.get_coverage_filters(business_id)
        if not coverage:
            return ListResult(items=[], total=0)
        items, total = await self.searches.list_incoming(
            coverage=coverage, limit=limit, offset=offset
        )
        return ListResult(items=items, total=total)

    async def submit_quote(
        self,
        *,
        business_id: uuid.UUID,
        search_id: uuid.UUID,
        owner_user_id: uuid.UUID,
        payload: QuoteCreateIn,
    ) -> Quote:
        """Business submits a price quote for a driver's open search.

        Checks, in order: search exists (404), search is open (409),
        business coverage matches this vehicle (403), no duplicate
        quote from this business (409), media assets owned + confirmed (422).
        Emits `marketplace.quote_sent` on success.
        """
        request = await self.searches.get_by_id(search_id)
        if request is None:
            raise NotFoundError("Search not found")
        if request.status != PartSearchStatus.open:
            raise ConflictError(f"Cannot quote on a search in status '{request.status.value}'")

        coverage = await self.businesses_svc.get_coverage_filters(business_id)
        # `search_matches_coverage` returns False on empty coverage so
        # the explicit guard here is defensive clarity only.
        matches = await self.searches.search_matches_coverage(
            search_id=search_id, coverage=coverage
        )
        if not matches:
            raise ForbiddenError("This search is outside your vehicle brand coverage")

        existing = await self.quotes.get_by_search_and_business(
            part_search_id=search_id, business_id=business_id
        )
        if existing is not None:
            raise ConflictError("You have already submitted a quote for this search")

        # Media assets are owned by the business **owner** (User) — businesses
        # don't have a user-id of their own. The caller layer threads in the
        # owner's user id; we validate against that.
        await self.media_svc.validate_asset_ids(
            owner_id=owner_user_id,
            asset_ids=payload.media_asset_ids,
            purpose=MediaAssetPurpose.quote,
        )

        quote = await self.quotes.create(
            part_search_id=search_id,
            business_id=business_id,
            price_mnt=payload.price_mnt,
            condition=payload.condition,
            notes=payload.notes,
            media_asset_ids=payload.media_asset_ids,
        )
        write_outbox_event(
            self.session,
            QuoteSent(
                aggregate_id=quote.id,
                tenant_id=business_id,
                part_search_id=search_id,
                driver_id=request.driver_id,
                price_mnt=payload.price_mnt,
                condition=payload.condition.value,
            ),
        )
        logger.info(
            "quote_sent",
            quote_id=str(quote.id),
            search_id=str(search_id),
            business_id=str(business_id),
        )
        return quote

    async def list_my_quotes(
        self,
        *,
        business_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> QuoteListResult:
        items, total = await self.quotes.list_for_business(
            business_id=business_id, limit=limit, offset=offset
        )
        return QuoteListResult(items=items, total=total)

    # ---- reservations (session 6) -----------------------------------------

    async def reserve(self, *, driver_id: uuid.UUID, quote_id: uuid.UUID) -> Reservation:
        """Driver places a 24h hold on a quote.

        Gates: quote exists, search is `open`, the calling driver owns the
        underlying search, no `active` reservation already exists on this
        search, no reservation already exists on this quote (DB unique).
        """
        quote = await self.quotes.get_by_id(quote_id)
        if quote is None:
            raise NotFoundError("Quote not found")

        search = await self.searches.get_by_id(quote.part_search_id)
        # The driver-ownership check uses the same opaque 404 convention
        # as the rest of the codebase.
        if search is None or search.driver_id != driver_id:
            raise NotFoundError("Quote not found")
        if search.status != PartSearchStatus.open:
            raise ConflictError(
                f"Cannot reserve a quote on a search in status '{search.status.value}'"
            )

        # If the quote itself is already reserved, the unique constraint
        # would catch it — but the explicit pre-check produces a friendlier
        # 409 instead of a generic IntegrityError.
        existing_quote_res = await self.reservations.get_by_quote_id(quote_id)
        if existing_quote_res is not None:
            raise ConflictError("This quote already has a reservation")

        # Some other quote on the same search might be actively reserved —
        # the driver can only run one hold at a time per search.
        active = await self.reservations.find_active_for_search(part_search_id=search.id)
        if active is not None:
            raise ConflictError("Another active reservation exists on this search")

        expires_at = datetime.now(UTC) + RESERVATION_TTL
        reservation = await self.reservations.create(
            quote_id=quote.id,
            part_search_id=search.id,
            driver_id=driver_id,
            tenant_id=quote.tenant_id,
            expires_at=expires_at,
        )
        write_outbox_event(
            self.session,
            ReservationStarted(
                aggregate_id=reservation.id,
                tenant_id=quote.tenant_id,
                quote_id=quote.id,
                part_search_id=search.id,
                driver_id=driver_id,
                expires_at=expires_at,
                price_mnt=quote.price_mnt,
            ),
        )
        logger.info(
            "reservation_started",
            reservation_id=str(reservation.id),
            quote_id=str(quote.id),
            driver_id=str(driver_id),
        )
        return reservation

    async def cancel_reservation(
        self, *, driver_id: uuid.UUID, reservation_id: uuid.UUID
    ) -> Reservation:
        reservation = await self.reservations.get_by_id(reservation_id)
        if reservation is None or reservation.driver_id != driver_id:
            raise NotFoundError("Reservation not found")
        if reservation.status != ReservationStatus.active:
            raise ConflictError(
                f"Cannot cancel a reservation in status '{reservation.status.value}'"
            )
        reservation.status = ReservationStatus.cancelled
        await self.session.flush()
        write_outbox_event(
            self.session,
            ReservationCancelled(
                aggregate_id=reservation.id,
                tenant_id=reservation.tenant_id,
                quote_id=reservation.quote_id,
                part_search_id=reservation.part_search_id,
                driver_id=driver_id,
            ),
        )
        logger.info(
            "reservation_cancelled",
            reservation_id=str(reservation.id),
            driver_id=str(driver_id),
        )
        return reservation

    async def list_reservations_for_driver(
        self,
        *,
        driver_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> ReservationListResult:
        items, total = await self.reservations.list_for_driver(
            driver_id=driver_id, limit=limit, offset=offset
        )
        return ReservationListResult(items=items, total=total)

    async def list_reservations_for_business(
        self,
        *,
        business_id: uuid.UUID,
        status: ReservationStatus | None,
        limit: int,
        offset: int,
    ) -> ReservationListResult:
        items, total = await self.reservations.list_for_business(
            business_id=business_id, status=status, limit=limit, offset=offset
        )
        return ReservationListResult(items=items, total=total)

    # ---- sales (session 6) ------------------------------------------------

    async def complete_reservation(
        self,
        *,
        business_id: uuid.UUID,
        reservation_id: uuid.UUID,
    ) -> Sale:
        """Business marks a reservation delivered.

        Creates a `sales` row with the price frozen from the quote, flips
        the reservation to `completed`, and flips the underlying part
        search to `fulfilled`. All three writes are inside the same
        transaction along with the outbox event.
        """
        reservation = await self.reservations.get_by_id(reservation_id)
        # Opaque 404: hide existence from a stranger business.
        if reservation is None or reservation.tenant_id != business_id:
            raise NotFoundError("Reservation not found")
        if reservation.status != ReservationStatus.active:
            raise ConflictError(
                f"Cannot complete a reservation in status '{reservation.status.value}'"
            )

        quote = await self.quotes.get_by_id(reservation.quote_id)
        if quote is None:
            # Shouldn't happen — FK is RESTRICT — but the type checker
            # doesn't know that.
            raise NotFoundError("Quote not found")
        search = await self.searches.get_by_id(reservation.part_search_id)
        if search is None:
            raise NotFoundError("Search not found")

        sale = await self.sales.create(reservation=reservation, price_mnt=quote.price_mnt)
        reservation.status = ReservationStatus.completed
        search.status = PartSearchStatus.fulfilled
        await self.session.flush()

        write_outbox_event(
            self.session,
            SaleCompleted(
                aggregate_id=sale.id,
                tenant_id=business_id,
                reservation_id=reservation.id,
                quote_id=quote.id,
                part_search_id=search.id,
                driver_id=reservation.driver_id,
                price_mnt=quote.price_mnt,
            ),
        )
        logger.info(
            "sale_completed",
            sale_id=str(sale.id),
            reservation_id=str(reservation.id),
            tenant_id=str(business_id),
        )
        return sale

    async def get_sale_for_party(
        self,
        *,
        sale_id: uuid.UUID,
        user_id: uuid.UUID,
        business_id: uuid.UUID | None,
    ) -> Sale:
        """Either the buyer (driver) or the selling business may read a sale."""
        sale = await self.sales.get_by_id(sale_id)
        if sale is None:
            raise NotFoundError("Sale not found")
        if sale.driver_id == user_id:
            return sale
        if business_id is not None and sale.tenant_id == business_id:
            return sale
        raise NotFoundError("Sale not found")

    async def list_sales_for_driver(
        self,
        *,
        driver_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> SaleListResult:
        items, total = await self.sales.list_for_driver(
            driver_id=driver_id, limit=limit, offset=offset
        )
        return SaleListResult(items=items, total=total)

    async def list_sales_for_business(
        self,
        *,
        business_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> SaleListResult:
        items, total = await self.sales.list_for_business(
            business_id=business_id, limit=limit, offset=offset
        )
        return SaleListResult(items=items, total=total)

    # ---- reviews (session 6) ----------------------------------------------

    async def submit_review_as_driver(
        self,
        *,
        driver_id: uuid.UUID,
        sale_id: uuid.UUID,
        payload: ReviewCreateIn,
    ) -> Review:
        sale = await self.sales.get_by_id(sale_id)
        if sale is None or sale.driver_id != driver_id:
            raise NotFoundError("Sale not found")
        return await self._submit_review(
            sale=sale,
            direction=ReviewDirection.buyer_to_seller,
            author_user_id=driver_id,
            subject_business_id=sale.tenant_id,
            subject_user_id=None,
            payload=payload,
        )

    async def submit_review_as_business(
        self,
        *,
        business: Business,
        sale_id: uuid.UUID,
        payload: ReviewCreateIn,
    ) -> Review:
        sale = await self.sales.get_by_id(sale_id)
        if sale is None or sale.tenant_id != business.id:
            raise NotFoundError("Sale not found")
        return await self._submit_review(
            sale=sale,
            direction=ReviewDirection.seller_to_buyer,
            author_user_id=business.owner_id,
            subject_business_id=None,
            subject_user_id=sale.driver_id,
            payload=payload,
        )

    async def list_reviews_for_sale(
        self, *, sale_id: uuid.UUID, user_id: uuid.UUID, business_id: uuid.UUID | None
    ) -> list[Review]:
        # Reuse the party check so reviews follow the same access shape as the sale.
        await self.get_sale_for_party(sale_id=sale_id, user_id=user_id, business_id=business_id)
        return await self.reviews.list_for_sale(sale_id=sale_id)

    async def _submit_review(
        self,
        *,
        sale: Sale,
        direction: ReviewDirection,
        author_user_id: uuid.UUID,
        subject_business_id: uuid.UUID | None,
        subject_user_id: uuid.UUID | None,
        payload: ReviewCreateIn,
    ) -> Review:
        existing = await self.reviews.get_by_sale_and_direction(
            sale_id=sale.id, direction=direction
        )
        if existing is not None:
            raise ConflictError(f"A {direction.value} review already exists for this sale")
        review = await self.reviews.create(
            sale_id=sale.id,
            direction=direction,
            author_user_id=author_user_id,
            subject_business_id=subject_business_id,
            subject_user_id=subject_user_id,
            rating=payload.rating,
            body=payload.body,
        )
        write_outbox_event(
            self.session,
            ReviewSubmitted(
                aggregate_id=review.id,
                tenant_id=sale.tenant_id,
                sale_id=sale.id,
                direction=direction.value,
                author_user_id=author_user_id,
                rating=payload.rating,
            ),
        )
        logger.info(
            "review_submitted",
            review_id=str(review.id),
            sale_id=str(sale.id),
            direction=direction.value,
        )
        return review
