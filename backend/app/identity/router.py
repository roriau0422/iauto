"""HTTP routes for the identity context."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.identity.dependencies import get_current_user, get_identity_service
from app.identity.models import User
from app.identity.schemas import (
    EmptyOut,
    LogoutIn,
    OtpRequestIn,
    OtpRequestOut,
    OtpVerifyIn,
    RefreshIn,
    TokenPairOut,
    UserOut,
)
from app.identity.service import IdentityService, TokenPair

router = APIRouter(tags=["identity"])


def _to_token_pair_out(pair: TokenPair) -> TokenPairOut:
    return TokenPairOut(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.access_expires_in,
        user=UserOut.model_validate(pair.user),
    )


@router.post(
    "/auth/otp/request",
    response_model=OtpRequestOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request an OTP for a phone number",
)
async def request_otp(
    body: OtpRequestIn,
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> OtpRequestOut:
    result = await service.request_otp(body.phone)
    return OtpRequestOut(
        sent=True,
        cooldown_seconds=result.cooldown_seconds,
        debug_code=result.debug_code,
    )


@router.post(
    "/auth/otp/verify",
    response_model=TokenPairOut,
    summary="Verify an OTP and receive a token pair",
)
async def verify_otp(
    body: OtpVerifyIn,
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> TokenPairOut:
    pair = await service.verify_otp(
        phone=body.phone,
        code=body.code,
        platform=body.device.platform,
        device_label=body.device.label,
        push_token=body.device.push_token,
        requested_role=body.role,
    )
    return _to_token_pair_out(pair)


@router.post(
    "/auth/refresh",
    response_model=TokenPairOut,
    summary="Rotate a refresh token",
)
async def refresh(
    body: RefreshIn,
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> TokenPairOut:
    pair = await service.refresh(body.refresh_token)
    return _to_token_pair_out(pair)


@router.post(
    "/auth/logout",
    response_model=EmptyOut,
    summary="Revoke a refresh token",
)
async def logout(
    body: LogoutIn,
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> EmptyOut:
    await service.logout(body.refresh_token)
    return EmptyOut()


@router.get(
    "/me",
    response_model=UserOut,
    summary="Return the currently authenticated user",
)
async def me(
    user: Annotated[User, Depends(get_current_user)],
) -> UserOut:
    return UserOut.model_validate(user)
