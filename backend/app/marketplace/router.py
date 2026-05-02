"""HTTP routes for the marketplace context (sessions 4–6)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from app.businesses.dependencies import get_current_business
from app.businesses.models import Business
from app.identity.dependencies import get_current_user
from app.identity.models import User, UserRole
from app.marketplace.dependencies import get_marketplace_service
from app.marketplace.models import PartSearchStatus, ReservationStatus
from app.marketplace.schemas import (
    PartSearchCancelOut,
    PartSearchCreateIn,
    PartSearchListOut,
    PartSearchOut,
    QuoteCreateIn,
    QuoteListOut,
    QuoteOut,
    ReservationListOut,
    ReservationOut,
    ReviewCreateIn,
    ReviewListOut,
    ReviewOut,
    SaleListOut,
    SaleOut,
)
from app.marketplace.service import MarketplaceService

router = APIRouter(tags=["marketplace"])


# ---------------------------------------------------------------------------
# Driver-side part search (session 4)
# ---------------------------------------------------------------------------


@router.post(
    "/marketplace/searches",
    response_model=PartSearchOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a part search request against one of the driver's vehicles",
)
async def create_search(
    body: PartSearchCreateIn,
    service: Annotated[MarketplaceService, Depends(get_marketplace_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> PartSearchOut:
    request = await service.submit_search(driver_id=user.id, payload=body)
    return PartSearchOut.model_validate(request)


@router.get(
    "/marketplace/searches/mine",
    response_model=PartSearchListOut,
    summary="List the authenticated driver's part search requests",
)
async def list_my_searches(
    service: Annotated[MarketplaceService, Depends(get_marketplace_service)],
    user: Annotated[User, Depends(get_current_user)],
    status_filter: Annotated[
        Literal["open", "cancelled", "expired", "fulfilled", "all"],
        Query(alias="status"),
    ] = "all",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PartSearchListOut:
    status_enum = None if status_filter == "all" else PartSearchStatus(status_filter)
    result = await service.list_for_driver(
        driver_id=user.id,
        status=status_enum,
        limit=limit,
        offset=offset,
    )
    return PartSearchListOut(
        items=[PartSearchOut.model_validate(r) for r in result.items],
        total=result.total,
    )


# Business-facing feed — MUST be registered before `/{search_id}` so
# FastAPI doesn't mistake "incoming" for a path parameter value.
@router.get(
    "/marketplace/searches/incoming",
    response_model=PartSearchListOut,
    summary="Paginated feed of open searches matching the business's coverage",
)
async def list_incoming_searches(
    service: Annotated[MarketplaceService, Depends(get_marketplace_service)],
    business: Annotated[Business, Depends(get_current_business)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PartSearchListOut:
    result = await service.list_incoming(business_id=business.id, limit=limit, offset=offset)
    return PartSearchListOut(
        items=[PartSearchOut.model_validate(r) for r in result.items],
        total=result.total,
    )


# Business-facing "my quotes" feed — registered before `/{search_id}` so
# the "quotes" literal isn't eaten as a UUID.
@router.get(
    "/marketplace/quotes/mine",
    response_model=QuoteListOut,
    summary="List the authenticated business's submitted quotes",
)
async def list_my_quotes(
    service: Annotated[MarketplaceService, Depends(get_marketplace_service)],
    business: Annotated[Business, Depends(get_current_business)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> QuoteListOut:
    result = await service.list_my_quotes(business_id=business.id, limit=limit, offset=offset)
    return QuoteListOut(
        items=[QuoteOut.model_validate(q) for q in result.items],
        total=result.total,
    )


# ---------------------------------------------------------------------------
# Reservations (session 6)
# ---------------------------------------------------------------------------

# Static literal segments must be registered before parameterized siblings.


@router.post(
    "/marketplace/quotes/{quote_id}/reserve",
    response_model=ReservationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Driver places a 24-hour hold on a quote",
)
async def reserve_quote(
    quote_id: uuid.UUID,
    service: Annotated[MarketplaceService, Depends(get_marketplace_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> ReservationOut:
    if user.role != UserRole.driver:
        # Business / admin accounts can't be the buyer on a sale.
        from app.platform.errors import ForbiddenError

        raise ForbiddenError("Only drivers can reserve a quote")
    reservation = await service.reserve(driver_id=user.id, quote_id=quote_id)
    return ReservationOut.model_validate(reservation)


@router.get(
    "/marketplace/reservations/mine",
    response_model=ReservationListOut,
    summary="Driver's own reservations, newest first",
)
async def list_my_reservations(
    service: Annotated[MarketplaceService, Depends(get_marketplace_service)],
    user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ReservationListOut:
    result = await service.list_reservations_for_driver(
        driver_id=user.id, limit=limit, offset=offset
    )
    return ReservationListOut(
        items=[ReservationOut.model_validate(r) for r in result.items],
        total=result.total,
    )


@router.get(
    "/marketplace/reservations/incoming",
    response_model=ReservationListOut,
    summary="Business's incoming reservations, newest first",
)
async def list_incoming_reservations(
    service: Annotated[MarketplaceService, Depends(get_marketplace_service)],
    business: Annotated[Business, Depends(get_current_business)],
    status_filter: Annotated[
        Literal["active", "cancelled", "expired", "completed", "all"],
        Query(alias="status"),
    ] = "all",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ReservationListOut:
    status_enum = None if status_filter == "all" else ReservationStatus(status_filter)
    result = await service.list_reservations_for_business(
        business_id=business.id, status=status_enum, limit=limit, offset=offset
    )
    return ReservationListOut(
        items=[ReservationOut.model_validate(r) for r in result.items],
        total=result.total,
    )


@router.post(
    "/marketplace/reservations/{reservation_id}/cancel",
    response_model=ReservationOut,
    summary="Driver cancels their active reservation",
)
async def cancel_reservation(
    reservation_id: uuid.UUID,
    service: Annotated[MarketplaceService, Depends(get_marketplace_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> ReservationOut:
    reservation = await service.cancel_reservation(driver_id=user.id, reservation_id=reservation_id)
    return ReservationOut.model_validate(reservation)


@router.post(
    "/marketplace/reservations/{reservation_id}/complete",
    response_model=SaleOut,
    summary="Business marks a reservation delivered → creates a sale",
)
async def complete_reservation(
    reservation_id: uuid.UUID,
    service: Annotated[MarketplaceService, Depends(get_marketplace_service)],
    business: Annotated[Business, Depends(get_current_business)],
) -> SaleOut:
    sale = await service.complete_reservation(
        business_id=business.id, reservation_id=reservation_id
    )
    return SaleOut.model_validate(sale)


# ---------------------------------------------------------------------------
# Sales (session 6)
# ---------------------------------------------------------------------------


@router.get(
    "/marketplace/sales/mine",
    response_model=SaleListOut,
    summary="Driver's own purchases, newest first",
)
async def list_my_sales(
    service: Annotated[MarketplaceService, Depends(get_marketplace_service)],
    user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SaleListOut:
    result = await service.list_sales_for_driver(driver_id=user.id, limit=limit, offset=offset)
    return SaleListOut(
        items=[SaleOut.model_validate(s) for s in result.items],
        total=result.total,
    )


@router.get(
    "/marketplace/sales/outgoing",
    response_model=SaleListOut,
    summary="Business's sold items, newest first",
)
async def list_outgoing_sales(
    service: Annotated[MarketplaceService, Depends(get_marketplace_service)],
    business: Annotated[Business, Depends(get_current_business)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SaleListOut:
    result = await service.list_sales_for_business(
        business_id=business.id, limit=limit, offset=offset
    )
    return SaleListOut(
        items=[SaleOut.model_validate(s) for s in result.items],
        total=result.total,
    )


@router.get(
    "/marketplace/sales/{sale_id}",
    response_model=SaleOut,
    summary="Either party (driver or business) reads the sale",
)
async def get_sale(
    sale_id: uuid.UUID,
    service: Annotated[MarketplaceService, Depends(get_marketplace_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> SaleOut:
    business_id = await _resolve_optional_business_id(service, user)
    sale = await service.get_sale_for_party(
        sale_id=sale_id, user_id=user.id, business_id=business_id
    )
    return SaleOut.model_validate(sale)


@router.post(
    "/marketplace/sales/{sale_id}/reviews",
    response_model=ReviewOut,
    status_code=status.HTTP_201_CREATED,
    summary="Driver or business writes their review on a sale",
)
async def create_review(
    sale_id: uuid.UUID,
    body: ReviewCreateIn,
    service: Annotated[MarketplaceService, Depends(get_marketplace_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> ReviewOut:
    if user.role == UserRole.driver:
        review = await service.submit_review_as_driver(
            driver_id=user.id, sale_id=sale_id, payload=body
        )
    elif user.role == UserRole.business:
        # Resolve the caller's business in-line — `get_current_business`
        # would 403 a driver, but we want the role split inside the body.
        from app.businesses.dependencies import get_businesses_service

        businesses_svc = get_businesses_service(session=service.session)
        business = await businesses_svc.get_for_owner(user)
        review = await service.submit_review_as_business(
            business=business, sale_id=sale_id, payload=body
        )
    else:
        from app.platform.errors import ForbiddenError

        raise ForbiddenError("Only drivers and businesses can review a sale")
    return ReviewOut.model_validate(review)


@router.get(
    "/marketplace/sales/{sale_id}/reviews",
    response_model=ReviewListOut,
    summary="List both reviews on a sale (caller must be a party)",
)
async def list_sale_reviews(
    sale_id: uuid.UUID,
    service: Annotated[MarketplaceService, Depends(get_marketplace_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> ReviewListOut:
    business_id = await _resolve_optional_business_id(service, user)
    rows = await service.list_reviews_for_sale(
        sale_id=sale_id, user_id=user.id, business_id=business_id
    )
    return ReviewListOut(items=[ReviewOut.model_validate(r) for r in rows], total=len(rows))


# ---------------------------------------------------------------------------
# Generic search lookups (must be registered after all literal routes)
# ---------------------------------------------------------------------------


@router.get(
    "/marketplace/searches/{search_id}",
    response_model=PartSearchOut,
    summary="Return the authenticated driver's part search by id",
)
async def get_search(
    search_id: uuid.UUID,
    service: Annotated[MarketplaceService, Depends(get_marketplace_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> PartSearchOut:
    request = await service.get_for_driver(driver_id=user.id, search_id=search_id)
    return PartSearchOut.model_validate(request)


@router.get(
    "/marketplace/searches/{search_id}/quotes",
    response_model=QuoteListOut,
    summary="Driver views quotes submitted on their own search",
)
async def list_search_quotes(
    search_id: uuid.UUID,
    service: Annotated[MarketplaceService, Depends(get_marketplace_service)],
    user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> QuoteListOut:
    result = await service.list_quotes_for_search(
        driver_id=user.id, search_id=search_id, limit=limit, offset=offset
    )
    return QuoteListOut(
        items=[QuoteOut.model_validate(q) for q in result.items],
        total=result.total,
    )


@router.post(
    "/marketplace/searches/{search_id}/quotes",
    response_model=QuoteOut,
    status_code=status.HTTP_201_CREATED,
    summary="Business submits a price quote on a part search",
)
async def create_quote(
    search_id: uuid.UUID,
    body: QuoteCreateIn,
    service: Annotated[MarketplaceService, Depends(get_marketplace_service)],
    business: Annotated[Business, Depends(get_current_business)],
) -> QuoteOut:
    quote = await service.submit_quote(
        business_id=business.id,
        owner_user_id=business.owner_id,
        search_id=search_id,
        payload=body,
    )
    return QuoteOut.model_validate(quote)


@router.post(
    "/marketplace/searches/{search_id}/cancel",
    response_model=PartSearchCancelOut,
    summary="Cancel an open part search",
)
async def cancel_search(
    search_id: uuid.UUID,
    service: Annotated[MarketplaceService, Depends(get_marketplace_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> PartSearchCancelOut:
    request = await service.cancel(driver_id=user.id, search_id=search_id)
    return PartSearchCancelOut(status=request.status)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_optional_business_id(
    service: MarketplaceService, user: User
) -> uuid.UUID | None:
    """Return the business_id for a business user, else None.

    Used by sale/review reads where either party can call. We could also
    expose this via FastAPI dependency stacking, but that hides the
    role-conditional intent — the inline lookup makes it obvious.
    """
    if user.role != UserRole.business:
        return None
    from app.businesses.dependencies import get_businesses_service

    biz_svc = get_businesses_service(session=service.session)
    business = await biz_svc.businesses.get_by_owner(user.id)
    return business.id if business is not None else None
