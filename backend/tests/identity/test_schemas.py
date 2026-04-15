"""Unit tests for identity schema helpers (no I/O)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.identity.models import UserRole
from app.identity.schemas import OtpVerifyIn, mask_phone, normalize_phone


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+97688110921", "+97688110921"),
        ("97688110921", "+97688110921"),
        ("88110921", "+97688110921"),
        ("+976 8811 0921", "+97688110921"),
        ("976-8811-0921", "+97688110921"),
        (" 8811 0921 ", "+97688110921"),
    ],
)
def test_normalize_phone_accepts(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "881109",  # too short
        "123456789012345",  # too long
        "abcdefgh",  # not digits
        "+1 555 123 4567",  # not MN
        "",  # empty
    ],
)
def test_normalize_phone_rejects(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_phone(raw)


def test_mask_phone_preserves_prefix_and_suffix() -> None:
    masked = mask_phone("+97688110921")
    assert masked.startswith("+976")
    assert masked.endswith("0921")
    assert "***" in masked
    assert "8811" not in masked


def test_otp_verify_defaults_to_driver_role() -> None:
    v = OtpVerifyIn(phone="+97688110921", code="123456")
    assert v.role == UserRole.driver


@pytest.mark.parametrize("role", [UserRole.driver, UserRole.business])
def test_otp_verify_accepts_public_roles(role: UserRole) -> None:
    v = OtpVerifyIn(phone="+97688110921", code="123456", role=role)
    assert v.role == role


def test_otp_verify_rejects_admin_role() -> None:
    with pytest.raises(ValidationError):
        OtpVerifyIn(phone="+97688110921", code="123456", role=UserRole.admin)
