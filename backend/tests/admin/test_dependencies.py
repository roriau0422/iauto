"""Admin auth-gating tests."""

from __future__ import annotations

import pytest

from app.admin.dependencies import require_admin
from app.identity.models import User, UserRole
from app.platform.errors import ForbiddenError


def test_require_admin_allows_admin_user() -> None:
    user = User(phone="+97688119991", role=UserRole.admin)
    assert require_admin(user) is user


def test_require_admin_rejects_driver() -> None:
    user = User(phone="+97688119992", role=UserRole.driver)
    with pytest.raises(ForbiddenError) as ei:
        require_admin(user)
    assert "Admin" in ei.value.detail


def test_require_admin_rejects_business() -> None:
    user = User(phone="+97688119993", role=UserRole.business)
    with pytest.raises(ForbiddenError):
        require_admin(user)
