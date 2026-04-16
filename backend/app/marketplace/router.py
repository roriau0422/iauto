"""HTTP routes for the marketplace context (sessions 4 + 5)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from app.businesses.dependencies import get_current_business
from app.businesses.models import Business
from app.identity.dependencies import get_current_user
from app.identity.models import User
from app.marketplace.dependencies import get_marketplace_service
from app.marketplace.models import PartSearchStatus
from app.marketplace.schemas import (
    PartSearchCancelOut,
    PartSearchCreateIn,
    PartSearchListOut,
    PartSearchOut,
    QuoteCreateIn,
    QuoteListOut,
    QuoteOut,
)
from app.marketplace.service import MarketplaceService

router = APIRouter(tags=["marketplace"])


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
    quote = await service.submit_quote(business_id=business.id, search_id=search_id, payload=body)
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
