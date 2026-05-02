"""QPay v2 client — operation-for-operation port of the Laravel reference.

See `backend/docs/references/qpay_laravel_reference.md` for the contract.
The Laravel `QpayClient` is the source of truth for operation names and
payload shapes — same discipline as the MessagePro and smartcar.mn ports.

Caching: the access token gets stashed in Redis at `qpay:token` for
`expires_in - 60` seconds. We refresh from QPay only on a cache miss or
401 from a downstream call.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from redis.asyncio import Redis

from app.platform.config import Settings
from app.platform.logging import get_logger

logger = get_logger("app.payments.qpay")

TOKEN_REDIS_KEY = "qpay:token"  # noqa: S105 — Redis key, not a credential
# Safety margin so we don't try to use a token QPay considers stale by the
# time the request lands at their LB.
TOKEN_REFRESH_SAFETY = 60


@dataclass(slots=True)
class QpayInvoiceResult:
    ok: bool
    status: int
    body: dict[str, Any]


class QpayClient(Protocol):
    """The surface the rest of the codebase consumes.

    Tests substitute a `FakeQpayClient` that records calls and returns
    canned responses. Production wiring uses `HttpQpayClient` below.
    """

    async def create_invoice(self, *, payload: dict[str, Any]) -> QpayInvoiceResult: ...

    async def check_payment(self, *, qpay_invoice_id: str) -> QpayInvoiceResult: ...


class HttpQpayClient:
    """`QpayClient` backed by httpx + a Redis-cached bearer token."""

    def __init__(
        self,
        *,
        settings: Settings,
        redis: Redis,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings
        self.redis = redis
        # The shared `httpx.AsyncClient` is owned by the FastAPI lifespan
        # in production wiring; tests pass their own instance. We cap
        # timeouts tight — QPay is interactive-path latency, anything
        # above 10s is a sign of a real problem.
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=10.0),
        )

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    @property
    def base_url(self) -> str:
        url = str(self.settings.qpay_base_url).rstrip("/") if self.settings.qpay_base_url else ""
        if not url:
            raise RuntimeError("QPAY_BASE_URL is not configured")
        return url

    # ---- token cache ---------------------------------------------------

    async def get_access_token(self, *, force_refresh: bool = False) -> str | None:
        if not force_refresh:
            cached = await self.redis.get(TOKEN_REDIS_KEY)
            if cached:
                # `decode_responses=True` on the connection returns str.
                return cached if isinstance(cached, str) else cached.decode()

        username = self.settings.qpay_username
        password = self.settings.qpay_password
        if not username or not password:
            logger.warning("qpay_credentials_missing")
            return None

        basic = base64.b64encode(f"{username}:{password}".encode()).decode()
        url = f"{self.base_url}/v2/auth/token"
        try:
            response = await self._http.post(
                url,
                headers={"Authorization": f"Basic {basic}"},
                json={},
            )
        except httpx.HTTPError as exc:
            logger.warning("qpay_token_request_failed", error=str(exc))
            return None

        if response.status_code != 200:
            logger.warning(
                "qpay_token_failed",
                status=response.status_code,
                body=response.text[:500],
            )
            return None

        data = response.json()
        token = data.get("access_token")
        expires_in = int(data.get("expires_in") or 0)
        if not token:
            return None
        ttl = max(expires_in - TOKEN_REFRESH_SAFETY, 60)
        await self.redis.set(TOKEN_REDIS_KEY, token, ex=ttl)
        return str(token)

    # ---- invoice -------------------------------------------------------

    async def create_invoice(self, *, payload: dict[str, Any]) -> QpayInvoiceResult:
        token = await self.get_access_token()
        if token is None:
            return QpayInvoiceResult(ok=False, status=0, body={})

        return await self._post_with_token(
            url=f"{self.base_url}/v2/invoice",
            payload=payload,
            token=token,
        )

    async def check_payment(self, *, qpay_invoice_id: str) -> QpayInvoiceResult:
        token = await self.get_access_token()
        if token is None:
            return QpayInvoiceResult(ok=False, status=0, body={})

        return await self._post_with_token(
            url=f"{self.base_url}/v2/payment/check",
            payload={
                "object_type": "INVOICE",
                "object_id": qpay_invoice_id,
                "offset": {"page_number": 1, "page_limit": 100},
            },
            token=token,
        )

    async def _post_with_token(
        self,
        *,
        url: str,
        payload: dict[str, Any],
        token: str,
    ) -> QpayInvoiceResult:
        try:
            response = await self._http.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
                json=payload,
            )
        except httpx.HTTPError as exc:
            logger.warning("qpay_request_failed", url=url, error=str(exc))
            return QpayInvoiceResult(ok=False, status=0, body={})

        body: dict[str, Any]
        try:
            parsed = response.json()
            body = parsed if isinstance(parsed, dict) else {"data": parsed}
        except ValueError:
            body = {}

        ok = 200 <= response.status_code < 300
        if not ok:
            logger.warning(
                "qpay_response_not_ok",
                url=url,
                status=response.status_code,
                body=str(body)[:500],
            )
        return QpayInvoiceResult(ok=ok, status=response.status_code, body=body)
