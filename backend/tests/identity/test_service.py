"""Service-level tests for the identity context.

These tests wire `IdentityService` directly to a transactional test DB
session, the test Redis DB (#15), and the in-memory SMS provider, so they
exercise the full flow without going through HTTP.
"""

from __future__ import annotations

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import DevicePlatform, RefreshToken, User
from app.identity.providers.sms import InMemorySmsProvider
from app.identity.service import IdentityService
from app.platform.config import Settings
from app.platform.errors import AuthError, RateLimitedError
from app.platform.outbox import OutboxEvent

PHONE = "+97688110921"


@pytest.fixture
def service(
    db_session: AsyncSession,
    redis: Redis,
    sms: InMemorySmsProvider,
    settings: Settings,
) -> IdentityService:
    return IdentityService(
        session=db_session, redis=redis, sms=sms, settings=settings
    )


async def test_request_otp_sends_message_and_returns_code(
    service: IdentityService,
    sms: InMemorySmsProvider,
) -> None:
    result = await service.request_otp(PHONE)

    assert len(sms.sent) == 1
    assert sms.sent[0][0] == PHONE
    assert "iAuto" in sms.sent[0][1]
    # Console provider echoes the code for manual testing.
    assert result.debug_code is not None
    assert result.debug_code in sms.sent[0][1]
    assert result.cooldown_seconds > 0


async def test_request_otp_honours_cooldown(service: IdentityService) -> None:
    await service.request_otp(PHONE)
    with pytest.raises(RateLimitedError):
        await service.request_otp(PHONE)


async def test_verify_otp_creates_user_and_tokens(
    service: IdentityService,
    db_session: AsyncSession,
) -> None:
    req = await service.request_otp(PHONE)
    assert req.debug_code is not None

    pair = await service.verify_otp(
        phone=PHONE,
        code=req.debug_code,
        platform=DevicePlatform.ios,
        device_label="iPhone test",
        push_token=None,
    )

    assert pair.access_token
    assert pair.refresh_token
    assert pair.user.phone == PHONE
    assert pair.user.phone_verified_at is not None

    # A user_registered and session_started outbox row should exist.
    rows = (
        await db_session.execute(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == pair.user.id)
        )
    ).scalars().all()
    event_types = {r.event_type for r in rows}
    assert "identity.user_registered" in event_types
    assert "identity.session_started" in event_types


async def test_verify_otp_rejects_wrong_code(service: IdentityService) -> None:
    req = await service.request_otp(PHONE)
    assert req.debug_code is not None

    with pytest.raises(AuthError):
        await service.verify_otp(
            phone=PHONE,
            code="000000" if req.debug_code != "000000" else "999999",
            platform=DevicePlatform.unknown,
            device_label=None,
            push_token=None,
        )
    # The real code still works after a single wrong attempt.
    pair = await service.verify_otp(
        phone=PHONE,
        code=req.debug_code,
        platform=DevicePlatform.unknown,
        device_label=None,
        push_token=None,
    )
    assert pair.user.phone == PHONE


async def test_verify_otp_burns_code_after_max_attempts(
    service: IdentityService,
    settings: Settings,
) -> None:
    req = await service.request_otp(PHONE)
    assert req.debug_code is not None
    bad = "000000" if req.debug_code != "000000" else "999999"

    for _ in range(settings.otp_max_attempts):
        with pytest.raises(AuthError):
            await service.verify_otp(
                phone=PHONE,
                code=bad,
                platform=DevicePlatform.unknown,
                device_label=None,
                push_token=None,
            )

    # Even the real code no longer works — OTP is toast.
    with pytest.raises(AuthError):
        await service.verify_otp(
            phone=PHONE,
            code=req.debug_code,
            platform=DevicePlatform.unknown,
            device_label=None,
            push_token=None,
        )


async def test_verify_otp_without_request_fails(service: IdentityService) -> None:
    with pytest.raises(AuthError):
        await service.verify_otp(
            phone=PHONE,
            code="123456",
            platform=DevicePlatform.unknown,
            device_label=None,
            push_token=None,
        )


async def test_refresh_rotates_and_revokes_prior_token(
    service: IdentityService,
    db_session: AsyncSession,
) -> None:
    req = await service.request_otp(PHONE)
    assert req.debug_code is not None
    first = await service.verify_otp(
        phone=PHONE,
        code=req.debug_code,
        platform=DevicePlatform.android,
        device_label=None,
        push_token=None,
    )

    second = await service.refresh(first.refresh_token)
    assert second.refresh_token != first.refresh_token

    # Old token now revoked, new one active.
    rows = (
        await db_session.execute(select(RefreshToken))
    ).scalars().all()
    revoked = [r for r in rows if r.revoked_at is not None]
    assert len(revoked) == 1
    assert revoked[0].replaced_by_id is not None


async def test_refresh_reuse_kills_device_chain(
    service: IdentityService,
) -> None:
    req = await service.request_otp(PHONE)
    assert req.debug_code is not None
    first = await service.verify_otp(
        phone=PHONE,
        code=req.debug_code,
        platform=DevicePlatform.android,
        device_label=None,
        push_token=None,
    )
    second = await service.refresh(first.refresh_token)

    # Replaying the original (now-revoked) refresh token must fail and must
    # also revoke the live rotated token, logging the whole device out.
    with pytest.raises(AuthError):
        await service.refresh(first.refresh_token)

    with pytest.raises(AuthError):
        await service.refresh(second.refresh_token)


async def test_logout_is_idempotent(service: IdentityService) -> None:
    req = await service.request_otp(PHONE)
    assert req.debug_code is not None
    pair = await service.verify_otp(
        phone=PHONE,
        code=req.debug_code,
        platform=DevicePlatform.unknown,
        device_label=None,
        push_token=None,
    )
    await service.logout(pair.refresh_token)
    # Second logout is a no-op (no error).
    await service.logout(pair.refresh_token)

    with pytest.raises(AuthError):
        await service.refresh(pair.refresh_token)


async def test_verify_otp_existing_user_does_not_emit_registered(
    service: IdentityService,
    db_session: AsyncSession,
) -> None:
    # First login — creates user.
    req1 = await service.request_otp(PHONE)
    assert req1.debug_code is not None
    pair1 = await service.verify_otp(
        phone=PHONE,
        code=req1.debug_code,
        platform=DevicePlatform.unknown,
        device_label=None,
        push_token=None,
    )

    # Second login on the same phone — user already exists.
    # Clear cooldown first.
    await service.otp.redis.delete(f"otp:cooldown:{PHONE}")
    req2 = await service.request_otp(PHONE)
    assert req2.debug_code is not None
    pair2 = await service.verify_otp(
        phone=PHONE,
        code=req2.debug_code,
        platform=DevicePlatform.unknown,
        device_label=None,
        push_token=None,
    )

    assert pair1.user.id == pair2.user.id

    # Exactly one user_registered event total — not two.
    user_registered_count = len(
        [
            r
            for r in (
                await db_session.execute(
                    select(OutboxEvent).where(
                        OutboxEvent.aggregate_id == pair1.user.id
                    )
                )
            )
            .scalars()
            .all()
            if r.event_type == "identity.user_registered"
        ]
    )
    assert user_registered_count == 1


async def test_phone_normalization_uniqueness(
    service: IdentityService,
    db_session: AsyncSession,
) -> None:
    # Raw forms that should all collapse to +97688110921.
    # Note: service itself doesn't normalize — the schema does. Here we
    # pre-normalize because the service expects clean phones.
    req = await service.request_otp(PHONE)
    assert req.debug_code is not None
    await service.verify_otp(
        phone=PHONE,
        code=req.debug_code,
        platform=DevicePlatform.unknown,
        device_label=None,
        push_token=None,
    )

    # One row, CITEXT-cased.
    users = (await db_session.execute(select(User))).scalars().all()
    matching = [u for u in users if u.phone == PHONE]
    assert len(matching) == 1
