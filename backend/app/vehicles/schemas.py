"""HTTP request/response Pydantic schemas for the vehicles endpoints."""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.vehicles.models import VerificationSource

# ---------------------------------------------------------------------------
# Plate normalization
# ---------------------------------------------------------------------------

# Mongolian Cyrillic uppercase alphabet — includes the standard Russian block
# plus Ё, Ө, and Ү. Enough to accept every valid civilian plate.
# Sample plate: "9987УБӨ" (4 digits + 3 Cyrillic letters, UB = Ulaanbaatar).
_PLATE_RE = re.compile(
    r"^\d{4}[АБВГДЕЁЖЗИЙКЛМНОӨПРСТУҮФХЦЧШЩЪЫЬЭЮЯ]{3}$"
)


def normalize_plate(raw: str) -> str:
    """Normalize a Mongolian civilian plate to the canonical `NNNNLLL` form.

    Accepts: `9987УБӨ`, `9987 УБ Ө`, ` 9987УБӨ `, lowercase variants.
    Rejects anything that doesn't collapse to 4 digits + 3 Mongolian-Cyrillic
    uppercase letters.
    """
    if not isinstance(raw, str):
        raise ValueError("plate must be a string")
    normalized = unicodedata.normalize("NFC", raw)
    stripped = re.sub(r"\s+", "", normalized)
    upper = stripped.upper()
    if not _PLATE_RE.match(upper):
        raise ValueError(f"not a valid Mongolian plate: {raw!r}")
    return upper


def mask_plate(plate: str) -> str:
    """Mask digits, keep the 3 region/series letters for operator forensics.

    `9987УБӨ` → `****УБӨ`.
    """
    if len(plate) < 3:
        return "***"
    return "****" + plate[-3:]


# ---------------------------------------------------------------------------
# Lookup plan (client instructions)
# ---------------------------------------------------------------------------


class LookupPlanEndpointOut(BaseModel):
    method: str
    url: str
    headers: dict[str, str]
    body_template: dict[str, Any]
    slots: dict[str, Any]


class LookupPlanOut(BaseModel):
    plan_version: str
    service_code: str
    endpoint: LookupPlanEndpointOut
    expected: dict[str, Any]
    ttl_seconds: int


# ---------------------------------------------------------------------------
# Lookup failure report
# ---------------------------------------------------------------------------


class LookupReportIn(BaseModel):
    plate: str
    status_code: int = Field(..., ge=100, le=599)
    error_snippet: str | None = Field(default=None, max_length=1000)
    plan_version: str | None = None

    @field_validator("plate")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return normalize_plate(v)


class LookupReportOut(BaseModel):
    received: Literal[True] = True
    alert_fired: bool
    window_count: int  # number of failures already in the current bucket
    operator_notified: bool


# ---------------------------------------------------------------------------
# Vehicle registration + listing
# ---------------------------------------------------------------------------


class XypPayloadIn(BaseModel):
    """Raw XYP response the client captured on a successful on-device lookup.

    The client MUST pass this through untouched so we can store it verbatim
    in `vehicles.raw_xyp` for later auditing. Individual fields below are
    parsed from this payload during registration.

    Field names match smartcar.mn's real wire format — camelCase upstream,
    which is why each line ignores `N815` (non-lowercase variable names).
    """

    markName: str | None = None  # noqa: N815
    modelName: str | None = None  # noqa: N815
    buildYear: int | str | None = None  # noqa: N815 — upstream flip-flops int/str
    cabinNumber: str | None = None  # noqa: N815 — XYP term for VIN
    motorNumber: str | None = None  # noqa: N815
    colorName: str | None = None  # noqa: N815
    capacity: int | float | str | None = None

    model_config = ConfigDict(extra="allow")


class VehicleRegisterIn(BaseModel):
    plate: str
    xyp: XypPayloadIn

    @field_validator("plate")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return normalize_plate(v)


class VehicleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vin: str | None
    plate: str
    make: str | None
    model: str | None
    build_year: int | None
    color: str | None
    engine_number: str | None
    capacity_cc: int | None
    verification_source: VerificationSource
    first_seen_at: datetime
    last_seen_at: datetime


class VehicleListOut(BaseModel):
    items: list[VehicleOut]


class VehicleRegisterOut(BaseModel):
    vehicle: VehicleOut
    was_new_vehicle: bool
    already_owned: bool


class VehicleDeleteOut(BaseModel):
    ok: Literal[True] = True
