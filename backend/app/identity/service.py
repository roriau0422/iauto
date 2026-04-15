"""Identity service — business logic for OTP auth, device registration,
refresh-token rotation, and session revocation.

The service owns the *rules*. The router hands it inputs; the session
dependency commits when the handler returns successfully. Outbox events are
written inline on the caller's session so they share the domain transaction.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.events import (
    SessionRefreshed,
    SessionRevoked,
    SessionStarted,
    UserRegistered,
)
from app.identity.models import Device, DevicePlatform, RefreshToken, User, UserRole
from app.identity.otp_store import OtpStore
from app.identity.providers.sms import SmsProvider
from app.identity.repository import (
    DeviceRepository,
    RefreshTokenRepository,
    UserRepository,
)
from app.identity.schemas import mask_phone
from app.identity.security import (
    generate_refresh_token,
    hash_refresh_token,
    issue_access_token,
)
from app.platform.config import Settings, SmsProviderKind
from app.platform.errors import AuthError, RateLimitedError
from app.platform.logging import get_logger
from app.platform.outbox import write_outbox_event

logger = get_logger("app.identity.service")


@dataclass(slots=True)
class RequestOtpResult:
    cooldown_seconds: int
    # Exposed only when running with the console SMS provider so that local
    # manual testing works without reading logs. Never returned in prod.
    debug_code: str | None


@dataclass(slots=True)
class TokenPair:
    access_token: str
    access_expires_in: int
    refresh_token: str
    user: User
    device: Device


class IdentityService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        redis: Redis,
        sms: SmsProvider,
        settings: Settings,
    ) -> None:
        self.session = session
        self.settings = settings
        self.sms = sms
        self.otp = OtpStore(redis, settings)
        self.users = UserRepository(session)
        self.devices = DeviceRepository(session)
        self.refresh_tokens = RefreshTokenRepository(session)

    # ---- OTP lifecycle -----------------------------------------------------

    async def request_otp(self, phone: str) -> RequestOtpResult:
        cooldown = await self.otp.cooldown_remaining(phone)
        if cooldown > 0:
            raise RateLimitedError(
                f"Please wait {cooldown}s before requesting another code",
                extra={"cooldown_seconds": cooldown},
            )

        code = self._generate_code()
        await self.otp.put(phone, code)

        message = (
            f"iAuto: your verification code is {code}. "
            f"It expires in {self.settings.otp_ttl_seconds // 60} minutes."
        )
        await self.sms.send(phone, message)

        logger.info(
            "otp_requested",
            phone=mask_phone(phone),
            ttl=self.settings.otp_ttl_seconds,
        )

        return RequestOtpResult(
            cooldown_seconds=self.settings.otp_resend_cooldown_seconds,
            debug_code=code if self.settings.sms_provider == SmsProviderKind.console else None,
        )

    async def verify_otp(
        self,
        *,
        phone: str,
        code: str,
        platform: DevicePlatform,
        device_label: str | None,
        push_token: str | None,
        requested_role: UserRole = UserRole.driver,
    ) -> TokenPair:
        stored = await self.otp.get(phone)
        if stored is None:
            raise AuthError("Code expired or not requested")

        if stored.attempts >= self.settings.otp_max_attempts:
            await self.otp.delete(phone)
            raise AuthError("Too many attempts — request a new code")

        if not secrets.compare_digest(stored.code, code):
            new_attempts = await self.otp.increment_attempts(phone, stored)
            logger.info(
                "otp_mismatch",
                phone=mask_phone(phone),
                attempts=new_attempts,
            )
            raise AuthError("Invalid code")

        # Match — burn the OTP immediately to prevent replay.
        await self.otp.delete(phone)

        user, is_new = await self._get_or_create_user(phone, requested_role)
        device = await self.devices.create(
            user_id=user.id,
            platform=platform,
            label=device_label,
            push_token=push_token,
        )

        if is_new:
            write_outbox_event(
                self.session,
                UserRegistered(
                    aggregate_id=user.id,
                    phone_masked=mask_phone(phone),
                    role=user.role,
                ),
            )

        write_outbox_event(
            self.session,
            SessionStarted(
                aggregate_id=user.id,
                device_id=device.id,
                platform=platform.value,
            ),
        )

        pair = await self._issue_tokens(user, device)
        logger.info(
            "otp_verified",
            phone=mask_phone(phone),
            user_id=str(user.id),
            device_id=str(device.id),
            is_new=is_new,
        )
        return pair

    # ---- refresh rotation --------------------------------------------------

    async def refresh(self, refresh_token_plain: str) -> TokenPair:
        row = await self.refresh_tokens.get_by_hash(hash_refresh_token(refresh_token_plain))
        if row is None:
            raise AuthError("Invalid refresh token")
        now = datetime.now(UTC)
        if row.revoked_at is not None or row.expires_at <= now:
            # Reuse-detection style response: if a revoked token is
            # presented, invalidate the whole device chain to fail closed.
            if row.revoked_at is not None:
                await self.refresh_tokens.revoke_all_for_device(row.device_id)
            raise AuthError("Refresh token is no longer valid")

        user = await self.users.get_by_id(row.user_id)
        device = await self.devices.get(row.device_id)
        if user is None or device is None or not user.is_active:
            raise AuthError("Account unavailable")

        pair = await self._issue_tokens(user, device)
        new_row_hash = hash_refresh_token(pair.refresh_token)
        new_row = await self.refresh_tokens.get_by_hash(new_row_hash)
        assert new_row is not None  # just inserted
        await self.refresh_tokens.revoke(row, replaced_by=new_row.id)

        await self.devices.touch(device)

        write_outbox_event(
            self.session,
            SessionRefreshed(
                aggregate_id=user.id,
                device_id=device.id,
            ),
        )
        return pair

    # ---- logout ------------------------------------------------------------

    async def logout(self, refresh_token_plain: str) -> None:
        row = await self.refresh_tokens.get_by_hash(hash_refresh_token(refresh_token_plain))
        if row is None:
            # Idempotent: unknown token = no-op.
            return
        if row.revoked_at is None:
            await self.refresh_tokens.revoke(row, replaced_by=None)
            write_outbox_event(
                self.session,
                SessionRevoked(
                    aggregate_id=row.user_id,
                    device_id=row.device_id,
                    reason="logout",
                ),
            )

    # ---- helpers -----------------------------------------------------------

    def _generate_code(self) -> str:
        length = self.settings.otp_length
        upper = 10**length
        code = secrets.randbelow(upper)
        return str(code).zfill(length)

    async def _get_or_create_user(self, phone: str, requested_role: UserRole) -> tuple[User, bool]:
        existing = await self.users.get_by_phone(phone)
        if existing is not None:
            # Existing users keep the role they registered with. We ignore
            # `requested_role` silently — a returning driver who accidentally
            # toggled the "I'm a business" switch should not suddenly become
            # a business. Role changes are an admin-only operation.
            if not existing.phone_verified_at:
                existing.phone_verified_at = datetime.now(UTC)
                await self.session.flush()
            return existing, False
        user = await self.users.create(phone=phone, role=requested_role)
        return user, True

    async def _issue_tokens(self, user: User, device: Device) -> TokenPair:
        access_token, access_ttl = issue_access_token(user, device.id, self.settings)
        refresh_plain = generate_refresh_token()
        await self._create_refresh_row(user, device, refresh_plain)
        return TokenPair(
            access_token=access_token,
            access_expires_in=access_ttl,
            refresh_token=refresh_plain,
            user=user,
            device=device,
        )

    async def _create_refresh_row(self, user: User, device: Device, plain: str) -> RefreshToken:
        return await self.refresh_tokens.create(
            user_id=user.id,
            device_id=device.id,
            token_hash=hash_refresh_token(plain),
            expires_at=datetime.now(UTC) + timedelta(days=self.settings.jwt_refresh_ttl_days),
        )
