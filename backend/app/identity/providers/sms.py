"""SMS delivery providers.

`SmsProvider` is a Protocol so production (`MessageProSmsProvider`), dev
(`ConsoleSmsProvider`), and tests (`InMemorySmsProvider`) are
interchangeable. `make_sms_provider()` picks one based on the `SMS_PROVIDER`
setting.

The provider only handles transport — message content comes from the
identity service. Providers never see the OTP value directly (the service
composes the SMS body) so that logging decisions stay with the caller.
"""

from __future__ import annotations

from typing import Protocol

import httpx

from app.platform.config import Settings, SmsProviderKind
from app.platform.errors import DomainError
from app.platform.logging import get_logger

logger = get_logger("app.identity.sms")


class SmsSendError(DomainError):
    status_code = 502
    error_code = "sms_send_failed"
    title = "SMS delivery failed"


class SmsProvider(Protocol):
    async def send(self, to: str, text: str) -> None: ...


class ConsoleSmsProvider:
    """Logs to stdout. Default in dev so OTP codes are visible during local
    testing without burning MessagePro credits."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, to: str, text: str) -> None:
        logger.info("sms_console", to=to, text=text)
        self.sent.append((to, text))


class InMemorySmsProvider:
    """Test-only provider: records sent messages without logging, so tests
    can assert on content without parsing log output."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, to: str, text: str) -> None:
        self.sent.append((to, text))


class MessageProSmsProvider:
    """Real MessagePro (messagepro.mn) integration.

    Ported from the user's existing Laravel implementation: GET `/send` with
    `x-api-key` header and query params `from`, `to`, `text`.
    """

    def __init__(self, *, base_url: str, api_key: str, sender: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.sender = sender

    async def send(self, to: str, text: str) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.get(
                    f"{self.base_url}/send",
                    headers={"x-api-key": self.api_key},
                    params={"from": self.sender, "to": to, "text": text},
                )
            except httpx.HTTPError as exc:
                logger.warning(
                    "messagepro_request_failed",
                    error=str(exc),
                    to=to,
                )
                raise SmsSendError("Could not reach SMS provider") from exc

        if response.status_code >= 400:
            logger.warning(
                "messagepro_send_rejected",
                status=response.status_code,
                body=response.text[:500],
                to=to,
            )
            raise SmsSendError(
                f"SMS provider returned HTTP {response.status_code}"
            )
        logger.info("messagepro_send_ok", to=to, status=response.status_code)


def make_sms_provider(settings: Settings) -> SmsProvider:
    if settings.sms_provider == SmsProviderKind.messagepro:
        if not settings.messagepro_base_url or not settings.messagepro_api_key:
            raise RuntimeError(
                "SMS_PROVIDER=messagepro but MESSAGEPRO_BASE_URL or "
                "MESSAGEPRO_API_KEY are empty"
            )
        return MessageProSmsProvider(
            base_url=str(settings.messagepro_base_url),
            api_key=settings.messagepro_api_key,
            sender=settings.messagepro_sender,
        )
    return ConsoleSmsProvider()
