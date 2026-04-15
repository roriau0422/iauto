"""XYP outage pager.

Coalesces client-reported XYP failures into at most one SMS per status
bucket per window. The first failure in a fresh window fires the SMS
immediately; subsequent failures in the same window only bump an INCR
counter so we know the real rate when the next window eventually fires.

**Character budget:** the MessagePro hard ceiling is 180 characters, but
the account auto-appends `" Navi market"` (a leading space plus the
11-char sender tag — 12 chars total) to every outbound body. We budget
168 for our own content so the final message stays under the limit.
Mongolian Cyrillic plus structured text eats bytes fast, so every field
below is tight.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis

from app.identity.providers.sms import SmsProvider
from app.platform.config import Settings
from app.platform.logging import get_logger

logger = get_logger("app.vehicles.alerts")

# MessagePro hard ceiling (provided by the operator).
SMS_HARD_CEILING = 180
# Trailing branding appended server-side by MessagePro to every outbound
# message. Discovered empirically on 2026-04-15 when the first real alert
# SMS landed with `... Navi market` tacked on.
MESSAGEPRO_SUFFIX = " Navi market"
SMS_BODY_MAX = SMS_HARD_CEILING - len(MESSAGEPRO_SUFFIX)


def _bucket(status_code: int) -> str:
    """Collapse similar statuses into one coalescing bucket.

    - 5xx → "5xx"    (outage / gateway error)
    - 4xx → exact code (401, 403, 404, 429 all behave differently)
    - 3xx → "3xx"    (unexpected redirects from the public gateway)
    """
    if 500 <= status_code < 600:
        return "5xx"
    if 300 <= status_code < 400:
        return "3xx"
    return str(status_code)


def _alert_key(bucket: str) -> str:
    return f"xyp:alert:{bucket}"


@dataclass(slots=True)
class AlertOutcome:
    fired: bool
    window_count: int
    operator_notified: bool


def _fmt_body(bucket: str, count: int, masked_plate: str, now: datetime) -> str:
    """Compose the SMS body, clamped to SMS_BODY_MAX."""
    iso = now.strftime("%Y-%m-%dT%H:%MZ")
    body = f"iAuto: XYP failing\nHTTP {bucket} x{count} in 15m\nlatest plate {masked_plate}\n{iso}"
    if len(body) > SMS_BODY_MAX:
        # Drop the trailing timestamp first (least useful), then truncate.
        body = (f"iAuto: XYP failing\nHTTP {bucket} x{count} in 15m\nlatest plate {masked_plate}")[
            :SMS_BODY_MAX
        ]
    return body


class XypAlerter:
    """Redis-coalesced SMS pager for client-reported XYP failures."""

    def __init__(self, *, redis: Redis, sms: SmsProvider, settings: Settings) -> None:
        self.redis = redis
        self.sms = sms
        self.settings = settings

    async def record_and_maybe_page(self, *, status_code: int, masked_plate: str) -> AlertOutcome:
        bucket = _bucket(status_code)
        key = _alert_key(bucket)
        window = self.settings.xyp_alert_window_seconds

        # INCR returns the new value; if this is the first increment we also
        # have to set the TTL (INCR does not imply EXPIRE).
        new_count = await self.redis.incr(key)
        if new_count == 1:
            await self.redis.expire(key, window)

        operator = self.settings.operator_phone
        if new_count > 1:
            logger.info(
                "xyp_alert_coalesced",
                bucket=bucket,
                count=new_count,
                masked_plate=masked_plate,
            )
            return AlertOutcome(
                fired=False,
                window_count=new_count,
                operator_notified=False,
            )

        if not operator:
            logger.warning(
                "xyp_alert_no_operator_configured",
                bucket=bucket,
                masked_plate=masked_plate,
            )
            return AlertOutcome(
                fired=True,
                window_count=new_count,
                operator_notified=False,
            )

        body = _fmt_body(bucket, new_count, masked_plate, datetime.now(UTC))
        try:
            await self.sms.send(operator, body)
        except Exception:
            logger.exception(
                "xyp_alert_sms_send_failed",
                bucket=bucket,
                masked_plate=masked_plate,
            )
            return AlertOutcome(
                fired=True,
                window_count=new_count,
                operator_notified=False,
            )

        logger.info(
            "xyp_alert_sent",
            bucket=bucket,
            masked_plate=masked_plate,
            body_len=len(body),
        )
        return AlertOutcome(
            fired=True,
            window_count=new_count,
            operator_notified=True,
        )
