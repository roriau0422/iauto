"""ORM models for the identity context."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    LargeBinary,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.platform.base import Base, Timestamped, UuidPrimaryKey
from app.platform.crypto import get_cipher, get_search_index


class UserRole(StrEnum):
    driver = "driver"
    business = "business"
    admin = "admin"


class DevicePlatform(StrEnum):
    ios = "ios"
    android = "android"
    web = "web"
    unknown = "unknown"


class User(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "users"

    # Encrypted phone storage.
    #
    # `phone_cipher` is a non-deterministic Fernet envelope of the
    # normalized phone; `phone_search` is an HMAC-SHA256 blind index of the
    # same normalized value, used for equality lookups and dedup.
    #
    # Reads/writes go through the `phone` Python property so call sites stay
    # shaped like `User(phone="+97688110921")` / `user.phone`. SA 2.0's
    # default `__init__` routes constructor kwargs through Python property
    # setters, so no custom `__init__` is required here.
    phone_cipher: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    phone_search: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role", native_enum=True),
        nullable=False,
        default=UserRole.driver,
    )
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    phone_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    devices: Mapped[list[Device]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    @property
    def phone(self) -> str:
        """Decrypted phone in E.164 form (`+976XXXXXXXX`)."""
        return get_cipher().decrypt(self.phone_cipher)

    @phone.setter
    def phone(self, value: str) -> None:
        # Normalize defensively so that `User(phone="88110921")` and
        # `User(phone="+97688110921")` both hash to the same search index
        # and dedup correctly.
        from app.identity.schemas import normalize_phone

        normalized = normalize_phone(value)
        self.phone_cipher = get_cipher().encrypt(normalized)
        self.phone_search = get_search_index().compute(normalized)


class Device(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "devices"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    platform: Mapped[DevicePlatform] = mapped_column(
        SAEnum(DevicePlatform, name="device_platform", native_enum=True),
        nullable=False,
        default=DevicePlatform.unknown,
    )
    push_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="devices")
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
    )


class RefreshToken(UuidPrimaryKey, Timestamped, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )

    user: Mapped[User] = relationship(back_populates="refresh_tokens")
    device: Mapped[Device] = relationship(back_populates="refresh_tokens")
