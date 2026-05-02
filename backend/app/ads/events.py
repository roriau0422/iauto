"""Domain events emitted by the ads context."""

from __future__ import annotations

import uuid
from typing import Literal

from app.platform.events import DomainEvent


class AdCampaignCreated(DomainEvent):
    event_type: Literal["ads.campaign_created"] = "ads.campaign_created"
    aggregate_type: Literal["ad_campaign"] = "ad_campaign"
    payment_intent_id: uuid.UUID | None
    budget_mnt: int


class AdCampaignActivated(DomainEvent):
    event_type: Literal["ads.campaign_activated"] = "ads.campaign_activated"
    aggregate_type: Literal["ad_campaign"] = "ad_campaign"


class AdImpressionRecorded(DomainEvent):
    event_type: Literal["ads.impression_recorded"] = "ads.impression_recorded"
    aggregate_type: Literal["ad_campaign"] = "ad_campaign"
    viewer_user_id: uuid.UUID | None
    spent_mnt: int


class AdClickRecorded(DomainEvent):
    event_type: Literal["ads.click_recorded"] = "ads.click_recorded"
    aggregate_type: Literal["ad_campaign"] = "ad_campaign"
    viewer_user_id: uuid.UUID | None


class AdCampaignExhausted(DomainEvent):
    event_type: Literal["ads.campaign_exhausted"] = "ads.campaign_exhausted"
    aggregate_type: Literal["ad_campaign"] = "ad_campaign"
    spent_mnt: int
    budget_mnt: int
