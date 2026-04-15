"""Redis-backed OTP storage.

OTPs live only in Redis — not Postgres. They're ephemeral, have strict TTLs,
and we don't want an audit record of the codes themselves. On verify the key
is deleted to prevent replay.

Layout:
    otp:{phone}           JSON {code, attempts}   TTL = OTP_TTL_SECONDS
    otp:cooldown:{phone}  "1"                      TTL = OTP_RESEND_COOLDOWN_SECONDS
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from redis.asyncio import Redis

from app.platform.config import Settings


def _otp_key(phone: str) -> str:
    return f"otp:{phone}"


def _cooldown_key(phone: str) -> str:
    return f"otp:cooldown:{phone}"


@dataclass(slots=True)
class StoredOtp:
    code: str
    attempts: int


class OtpStore:
    def __init__(self, redis: Redis, settings: Settings) -> None:
        self.redis = redis
        self.settings = settings

    async def cooldown_remaining(self, phone: str) -> int:
        ttl: int = await self.redis.ttl(_cooldown_key(phone))
        return max(ttl, 0)

    async def put(self, phone: str, code: str) -> None:
        payload = json.dumps({"code": code, "attempts": 0})
        await self.redis.set(_otp_key(phone), payload, ex=self.settings.otp_ttl_seconds)
        await self.redis.set(
            _cooldown_key(phone),
            "1",
            ex=self.settings.otp_resend_cooldown_seconds,
        )

    async def get(self, phone: str) -> StoredOtp | None:
        raw = await self.redis.get(_otp_key(phone))
        if raw is None:
            return None
        data = json.loads(raw)
        return StoredOtp(code=data["code"], attempts=int(data["attempts"]))

    async def increment_attempts(self, phone: str, current: StoredOtp) -> int:
        remaining_ttl = await self.redis.ttl(_otp_key(phone))
        if remaining_ttl <= 0:
            return current.attempts
        new_attempts = current.attempts + 1
        payload = json.dumps({"code": current.code, "attempts": new_attempts})
        await self.redis.set(_otp_key(phone), payload, ex=remaining_ttl)
        return new_attempts

    async def delete(self, phone: str) -> None:
        await self.redis.delete(_otp_key(phone))
