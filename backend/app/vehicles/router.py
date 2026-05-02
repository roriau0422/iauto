"""HTTP routes for the vehicles context."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import StreamingResponse

from app.identity.dependencies import get_current_user
from app.identity.models import User
from app.payments.dependencies import get_payments_service
from app.payments.service import PaymentsService
from app.vehicles.dependencies import get_vehicles_service
from app.vehicles.schemas import (
    LookupPlanEndpointOut,
    LookupPlanOut,
    LookupReportIn,
    LookupReportOut,
    MyCarListOut,
    VehicleDeleteOut,
    VehicleDueListOut,
    VehicleDueOut,
    VehicleDuePayOut,
    VehicleListOut,
    VehicleOut,
    VehicleRegisterIn,
    VehicleRegisterOut,
    VehicleServiceHistoryOut,
    VehicleServiceLogCreateIn,
    VehicleServiceLogDeleteOut,
    VehicleServiceLogOut,
)
from app.vehicles.service import VehiclesService

router = APIRouter(tags=["vehicles"])


@router.get(
    "/vehicles/lookup/plan",
    response_model=LookupPlanOut,
    summary="Current client-side XYP lookup plan",
)
async def get_lookup_plan(
    response: Response,
    service: Annotated[VehiclesService, Depends(get_vehicles_service)],
) -> LookupPlanOut:
    plan = await service.get_active_plan()
    # Cache-friendly — clients may keep the plan in memory for this long.
    response.headers["Cache-Control"] = f"public, max-age={plan.ttl_seconds}"
    return LookupPlanOut(
        plan_version=plan.plan_version,
        service_code=plan.service_code,
        endpoint=LookupPlanEndpointOut(
            method=plan.endpoint_method,
            url=plan.endpoint_url,
            headers=plan.headers,
            body_template=plan.body_template,
            slots=plan.slots,
        ),
        expected=plan.expected,
        ttl_seconds=plan.ttl_seconds,
    )


@router.post(
    "/vehicles/lookup/report",
    response_model=LookupReportOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Report a client-side XYP lookup failure",
)
async def report_lookup_failure(
    body: LookupReportIn,
    service: Annotated[VehiclesService, Depends(get_vehicles_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> LookupReportOut:
    result = await service.record_lookup_failure(
        user_id=user.id,
        plate=body.plate,
        status_code=body.status_code,
        error_snippet=body.error_snippet,
        plan_version=body.plan_version,
    )
    return LookupReportOut(
        alert_fired=result.alert.fired,
        window_count=result.alert.window_count,
        operator_notified=result.alert.operator_notified,
    )


@router.post(
    "/vehicles",
    response_model=VehicleRegisterOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a vehicle from a client-captured XYP payload",
)
async def register_vehicle(
    body: VehicleRegisterIn,
    service: Annotated[VehiclesService, Depends(get_vehicles_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> VehicleRegisterOut:
    result = await service.register_from_xyp(
        user_id=user.id,
        plate=body.plate,
        xyp=body.xyp,
    )
    return VehicleRegisterOut(
        vehicle=VehicleOut.model_validate(result.vehicle),
        was_new_vehicle=result.was_new_vehicle,
        already_owned=result.already_owned,
    )


@router.get(
    "/vehicles",
    response_model=VehicleListOut,
    summary="List the authenticated user's vehicles",
)
async def list_vehicles(
    service: Annotated[VehiclesService, Depends(get_vehicles_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> VehicleListOut:
    rows = await service.list_for_user(user.id)
    return VehicleListOut(items=[VehicleOut.model_validate(r) for r in rows])


@router.delete(
    "/vehicles/{vehicle_id}",
    response_model=VehicleDeleteOut,
    summary="Unregister a vehicle (owner-only, leaves the vehicle row intact)",
)
async def delete_vehicle(
    vehicle_id: uuid.UUID,
    service: Annotated[VehiclesService, Depends(get_vehicles_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> VehicleDeleteOut:
    await service.unregister(user_id=user.id, vehicle_id=vehicle_id)
    return VehicleDeleteOut()


# ---------------------------------------------------------------------------
# My Car (session 7 stubs)
# ---------------------------------------------------------------------------


@router.get(
    "/vehicles/{vehicle_id}/service-history",
    response_model=VehicleServiceHistoryOut,
    summary="List the vehicle's service-history entries (owner only)",
)
async def list_service_history(
    vehicle_id: uuid.UUID,
    service: Annotated[VehiclesService, Depends(get_vehicles_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> VehicleServiceHistoryOut:
    rows = await service.list_service_history(user_id=user.id, vehicle_id=vehicle_id)
    return VehicleServiceHistoryOut(items=[VehicleServiceLogOut.model_validate(r) for r in rows])


@router.post(
    "/vehicles/{vehicle_id}/service-history",
    response_model=VehicleServiceLogOut,
    status_code=status.HTTP_201_CREATED,
    summary="Append a service-history entry (owner only)",
)
async def add_service_log(
    vehicle_id: uuid.UUID,
    body: VehicleServiceLogCreateIn,
    service: Annotated[VehiclesService, Depends(get_vehicles_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> VehicleServiceLogOut:
    log = await service.add_service_log(user_id=user.id, vehicle_id=vehicle_id, payload=body)
    return VehicleServiceLogOut.model_validate(log)


@router.delete(
    "/vehicles/{vehicle_id}/service-history/{log_id}",
    response_model=VehicleServiceLogDeleteOut,
    summary="Delete a service-history entry (owner only)",
)
async def delete_service_log(
    vehicle_id: uuid.UUID,
    log_id: uuid.UUID,
    service: Annotated[VehiclesService, Depends(get_vehicles_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> VehicleServiceLogDeleteOut:
    await service.delete_service_log(user_id=user.id, vehicle_id=vehicle_id, log_id=log_id)
    return VehicleServiceLogDeleteOut()


@router.get(
    "/vehicles/{vehicle_id}/service-history.pdf",
    summary="Server-rendered PDF of the vehicle's service history (owner only)",
    include_in_schema=True,
)
async def service_history_pdf(
    vehicle_id: uuid.UUID,
    service: Annotated[VehiclesService, Depends(get_vehicles_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    from io import BytesIO

    from app.vehicles.pdf import render_service_history_pdf

    vehicle = await service.check_ownership(user_id=user.id, vehicle_id=vehicle_id)
    rows = await service.list_service_history(user_id=user.id, vehicle_id=vehicle_id)
    pdf_bytes = render_service_history_pdf(
        plate=vehicle.plate,
        make=vehicle.make,
        model=vehicle.model,
        logs=rows,
    )
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": (f'attachment; filename="service-history-{vehicle_id}.pdf"'),
            "Cache-Control": "private, no-store",
        },
    )


@router.get(
    "/vehicles/{vehicle_id}/tax",
    response_model=MyCarListOut,
    summary="Vehicle tax obligations placeholder (real data source TBD)",
)
async def list_vehicle_tax(
    vehicle_id: uuid.UUID,
    service: Annotated[VehiclesService, Depends(get_vehicles_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> MyCarListOut:
    await service.check_ownership(user_id=user.id, vehicle_id=vehicle_id)
    return MyCarListOut(vehicle_id=vehicle_id, items=[])


@router.get(
    "/vehicles/{vehicle_id}/insurance",
    response_model=MyCarListOut,
    summary="Vehicle insurance placeholder (real data source TBD)",
)
async def list_vehicle_insurance(
    vehicle_id: uuid.UUID,
    service: Annotated[VehiclesService, Depends(get_vehicles_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> MyCarListOut:
    await service.check_ownership(user_id=user.id, vehicle_id=vehicle_id)
    return MyCarListOut(vehicle_id=vehicle_id, items=[])


@router.get(
    "/vehicles/{vehicle_id}/fines",
    response_model=MyCarListOut,
    summary="Vehicle traffic-fines placeholder (real data source TBD)",
)
async def list_vehicle_fines(
    vehicle_id: uuid.UUID,
    service: Annotated[VehiclesService, Depends(get_vehicles_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> MyCarListOut:
    await service.check_ownership(user_id=user.id, vehicle_id=vehicle_id)
    return MyCarListOut(vehicle_id=vehicle_id, items=[])


# ---------------------------------------------------------------------------
# Vehicle dues — tax / insurance / fines (session 24)
# ---------------------------------------------------------------------------


@router.get(
    "/vehicles/{vehicle_id}/dues",
    response_model=VehicleDueListOut,
    summary="List a vehicle's payable obligations (owner only)",
)
async def list_vehicle_dues(
    vehicle_id: uuid.UUID,
    service: Annotated[VehiclesService, Depends(get_vehicles_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> VehicleDueListOut:
    rows = await service.list_dues(user_id=user.id, vehicle_id=vehicle_id)
    return VehicleDueListOut(
        vehicle_id=vehicle_id,
        items=[VehicleDueOut.model_validate(r) for r in rows],
    )


@router.post(
    "/vehicles/{vehicle_id}/dues/{due_id}/pay",
    response_model=VehicleDuePayOut,
    status_code=status.HTTP_201_CREATED,
    summary="Kick off a QPay invoice for a tax / insurance / fines due",
)
async def pay_vehicle_due(
    vehicle_id: uuid.UUID,
    due_id: uuid.UUID,
    service: Annotated[VehiclesService, Depends(get_vehicles_service)],
    payments: Annotated[PaymentsService, Depends(get_payments_service)],
    user: Annotated[User, Depends(get_current_user)],
) -> VehicleDuePayOut:
    """Mobile drives the QPay handoff with this endpoint.

    Idempotent per `due_id`: a second call returns the existing intent +
    a re-fetched QR is the mobile's job (the QPay invoice id is on the
    response). Once the due flips to `paid` the endpoint refuses further
    pay attempts.
    """
    from app.platform.errors import ConflictError
    from app.vehicles.models import VehicleDueStatus

    due = await service.get_due_for_payment(user_id=user.id, vehicle_id=vehicle_id, due_id=due_id)
    if due.status == VehicleDueStatus.paid:
        raise ConflictError("This due is already paid")

    invoice = await payments.create_intent_for_vehicle_due(driver_id=user.id, vehicle_due=due)
    service.attach_payment_intent(due=due, payment_intent_id=invoice.intent.id)

    return VehicleDuePayOut(
        due=VehicleDueOut.model_validate(due),
        payment_intent_id=invoice.intent.id,
        qr_text=invoice.qr_text,
        qr_image_base64=invoice.qr_image_base64,
        deeplink=invoice.deeplink,
        urls=invoice.urls,
    )
