"""Unit tests for vehicle schema helpers — no I/O."""

from __future__ import annotations

import pytest

from app.vehicles.schemas import mask_plate, normalize_plate


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("9987УБӨ", "9987УБӨ"),
        ("9987 УБӨ", "9987УБӨ"),
        (" 9987 УБ Ө ", "9987УБӨ"),
        ("9987убө", "9987УБӨ"),  # lowercase accepted, uppercased
        ("1234АБВ", "1234АБВ"),
        ("5678ҮБЕ", "5678ҮБЕ"),   # Ү is allowed
    ],
)
def test_normalize_plate_accepts(raw: str, expected: str) -> None:
    assert normalize_plate(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "998УБӨ",          # only 3 digits
        "99987УБӨ",        # 5 digits
        "9987УБ",          # only 2 letters
        "9987УБӨА",        # 4 letters
        "9987ABC",         # Latin letters
        "ABCD9999",        # wrong layout
        "9987У3Ө",         # digit in letter slot
    ],
)
def test_normalize_plate_rejects(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_plate(raw)


def test_normalize_plate_rejects_non_string() -> None:
    with pytest.raises(ValueError):
        normalize_plate(9987)  # type: ignore[arg-type]


def test_mask_plate_hides_digits_keeps_letters() -> None:
    assert mask_plate("9987УБӨ") == "****УБӨ"


def test_mask_plate_short_input() -> None:
    assert mask_plate("AB") == "***"
