"""ORM models for the businesses context."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, LargeBinary, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.identity.models import User
from app.platform.base import Base, Timestamped, UuidPrimaryKey
from app.platform.crypto import get_cipher, get_search_index


class Business(UuidPrimaryKey, Timestamped, Base):
    """A business profile owned by exactly one `User` with role=business.

    `businesses.id` is the tenant identifier every tenant-scoped row in the
    marketplace / warehouse / stories / ads contexts will carry. The 1:1
    invariant against `owner_id` is enforced by a partial unique index so
    future multi-staff (`business_members` pivot) can add more users under
    the same business without schema gymnastics.

    `contact_phone` is an optional override for the phone shown to
    counterparties in quotes + chat headers. When null, callers fall back
    to the owning user's phone. The column is encrypted with the same
    envelope pattern as `users.phone` — Fernet ciphertext + HMAC blind
    index for equality lookups if we ever need to dedup contact phones.
    """

    __tablename__ = "businesses"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_phone_cipher: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    contact_phone_search: Mapped[str | None] = mapped_column(Text, nullable=True)

    owner: Mapped[User] = relationship()

    @property
    def contact_phone(self) -> str | None:
        if self.contact_phone_cipher is None:
            return None
        return get_cipher().decrypt(self.contact_phone_cipher)

    @contact_phone.setter
    def contact_phone(self, value: str | None) -> None:
        if value is None or not value.strip():
            self.contact_phone_cipher = None
            self.contact_phone_search = None
            return
        from app.identity.schemas import normalize_phone

        normalized = normalize_phone(value)
        self.contact_phone_cipher = get_cipher().encrypt(normalized)
        self.contact_phone_search = get_search_index().compute(normalized)
