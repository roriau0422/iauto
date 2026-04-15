"""HTTP request/response Pydantic schemas for the identity endpoints."""

from __future__ import annotations

import re
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.identity.models import DevicePlatform, UserRole

# Mongolia's country code. We default to +976 when the caller sends a plain
# 8-digit national number.
MN_COUNTRY_CODE = "976"
_DIGITS_ONLY = re.compile(r"\D+")


def normalize_phone(raw: str) -> str:
    """Normalize a Mongolian phone number to E.164 (`+976XXXXXXXX`).

    Accepts: `+97688110921`, `976 88110921`, `88110921`, `8811-0921`, etc.
    Rejects anything that doesn't resolve to 8 national digits.
    """
    digits = _DIGITS_ONLY.sub("", raw)
    if digits.startswith(MN_COUNTRY_CODE) and len(digits) == 11:
        national = digits[3:]
    elif len(digits) == 8:
        national = digits
    else:
        raise ValueError(f"not a valid Mongolian phone number: {raw!r}")
    if not national.isdigit():
        raise ValueError(f"not a valid Mongolian phone number: {raw!r}")
    return f"+{MN_COUNTRY_CODE}{national}"


def mask_phone(phone: str) -> str:
    """Mask the middle of a phone number for logs and events."""
    if len(phone) < 6:
        return "***"
    return phone[:4] + "***" + phone[-4:]


# ---- request models --------------------------------------------------------


class OtpRequestIn(BaseModel):
    phone: str = Field(..., examples=["+97688110921", "88110921"])

    @field_validator("phone")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return normalize_phone(v)


class DeviceInfoIn(BaseModel):
    platform: DevicePlatform = DevicePlatform.unknown
    label: str | None = None
    push_token: str | None = None


class OtpVerifyIn(BaseModel):
    phone: str
    code: str = Field(..., min_length=4, max_length=8, pattern=r"^\d+$")
    device: DeviceInfoIn = Field(default_factory=DeviceInfoIn)

    @field_validator("phone")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return normalize_phone(v)


class RefreshIn(BaseModel):
    refresh_token: str


class LogoutIn(BaseModel):
    refresh_token: str


# ---- response models -------------------------------------------------------


class OtpRequestOut(BaseModel):
    sent: bool = True
    cooldown_seconds: int
    # In dev (console provider) we echo the code back to simplify manual
    # testing. Always empty in prod.
    debug_code: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    phone: str
    role: UserRole
    display_name: str | None
    avatar_url: str | None


class TokenPairOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["Bearer"] = "Bearer"  # noqa: S105
    expires_in: int  # seconds until access token expires
    user: UserOut


class EmptyOut(BaseModel):
    ok: bool = True
