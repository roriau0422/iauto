"""ORM models for the ads context."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.base import Base, TenantScoped, Timestamped, UuidPrimaryKey


class AdPlacement(StrEnum):
    story_feed = "story_feed"
    search_results = "search_results"


class AdCampaignStatus(StrEnum):
    """Lifecycle of a paid ad campaign.

    - `draft`           — created, payment intent not yet issued (unused
                          today; flow goes straight from POST to
                          `pending_payment`).
    - `pending_payment` — QPay invoice issued; awaiting settlement.
    - `active`          — settled; serving impressions.
    - `paused`          — manually paused by the business.
    - `exhausted`       — `spent_mnt >= budget_mnt`; auto-flipped.
    - `cancelled`       — manual cancel; refunds tracked elsewhere.
    """

    draft = "draft"
    pending_payment = "pending_payment"
    active = "active"
    paused = "paused"
    exhausted = "exhausted"
    cancelled = "cancelled"


class AdCampaign(UuidPrimaryKey, Timestamped, TenantScoped, Base):
    __tablename__ = "ad_campaigns"

    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    media_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("media_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    placement: Mapped[AdPlacement] = mapped_column(
        SAEnum(AdPlacement, name="ad_placement", native_enum=True),
        nullable=False,
    )
    budget_mnt: Mapped[int] = mapped_column(Integer, nullable=False)
    cpm_mnt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[AdCampaignStatus] = mapped_column(
        SAEnum(AdCampaignStatus, name="ad_campaign_status", native_enum=True),
        nullable=False,
        default=AdCampaignStatus.pending_payment,
    )
    payment_intent_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("payment_intents.id", ondelete="SET NULL"),
        nullable=True,
    )
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    spent_mnt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (
        CheckConstraint("budget_mnt > 0", name="ck_ad_campaigns_budget_positive"),
        CheckConstraint("cpm_mnt > 0", name="ck_ad_campaigns_cpm_positive"),
    )


class AdImpression(UuidPrimaryKey, Base):
    __tablename__ = "ad_impressions"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("ad_campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    viewer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class AdClick(UuidPrimaryKey, Base):
    __tablename__ = "ad_clicks"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("ad_campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    viewer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
