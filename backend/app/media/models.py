"""ORM models for the media context."""

from __future__ import annotations

import uuid
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Enum as SAEnum,
    ForeignKey,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.base import Base, Timestamped, UuidPrimaryKey


class MediaAssetStatus(StrEnum):
    """Lifecycle of a media asset row.

    - `pending` — row exists, presigned PUT issued, bytes not yet confirmed.
    - `active`  — confirmed via HEAD; safe to reference from domain rows.
    - `deleted` — soft-deleted; underlying object scheduled for removal.
    """

    pending = "pending"
    active = "active"
    deleted = "deleted"


class MediaAssetPurpose(StrEnum):
    """What the asset is for. Drives object key prefix + access scopes."""

    part_search = "part_search"
    quote = "quote"
    review = "review"


class MediaAsset(UuidPrimaryKey, Timestamped, Base):
    """A single uploaded blob managed by the media platform.

    `object_key` is unique because it embeds the UUID PK. We keep the
    column unique anyway to make accidental collisions a 23505 instead
    of a silent overwrite. `byte_size` is filled at confirm time from
    the HEAD response — null while pending.
    """

    __tablename__ = "media_assets"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    bucket: Mapped[str] = mapped_column(Text, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    purpose: Mapped[MediaAssetPurpose] = mapped_column(
        SAEnum(MediaAssetPurpose, name="media_asset_purpose", native_enum=True),
        nullable=False,
    )
    status: Mapped[MediaAssetStatus] = mapped_column(
        SAEnum(MediaAssetStatus, name="media_asset_status", native_enum=True),
        nullable=False,
        default=MediaAssetStatus.pending,
    )
