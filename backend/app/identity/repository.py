"""Database access for the identity context.

Pure data access: no business rules, no outbox, no SMS. Thin wrappers over
SQLAlchemy so the service layer stays readable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import Device, DevicePlatform, RefreshToken, User, UserRole


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_phone(self, phone: str) -> User | None:
        result = await self.session.execute(select(User).where(User.phone == phone))
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        phone: str,
        role: UserRole = UserRole.driver,
        display_name: str | None = None,
    ) -> User:
        user = User(
            phone=phone,
            role=role,
            display_name=display_name,
            phone_verified_at=datetime.now(UTC),
        )
        self.session.add(user)
        await self.session.flush()
        return user


class DeviceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, device_id: uuid.UUID) -> Device | None:
        return await self.session.get(Device, device_id)

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        platform: DevicePlatform,
        label: str | None,
        push_token: str | None,
    ) -> Device:
        device = Device(
            user_id=user_id,
            platform=platform,
            label=label,
            push_token=push_token,
            last_seen_at=datetime.now(UTC),
        )
        self.session.add(device)
        await self.session.flush()
        return device

    async def touch(self, device: Device) -> None:
        device.last_seen_at = datetime.now(UTC)
        await self.session.flush()


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        device_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> RefreshToken:
        row = RefreshToken(
            user_id=user_id,
            device_id=device_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        result = await self.session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def revoke(self, row: RefreshToken, replaced_by: uuid.UUID | None) -> None:
        row.revoked_at = datetime.now(UTC)
        row.replaced_by_id = replaced_by
        await self.session.flush()

    async def revoke_all_for_device(self, device_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(RefreshToken).where(
                RefreshToken.device_id == device_id,
                RefreshToken.revoked_at.is_(None),
            )
        )
        rows = list(result.scalars())
        now = datetime.now(UTC)
        for row in rows:
            row.revoked_at = now
        await self.session.flush()
        return len(rows)
