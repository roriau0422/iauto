"""JWT and refresh-token primitives.

Access tokens are short-lived (minutes) HS256 JWTs. Refresh tokens are
high-entropy random strings; the server stores only a SHA-256 hash, so a DB
leak does not expose the raw token. Refresh tokens rotate on every use.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from app.identity.models import User, UserRole
from app.platform.config import Settings
from app.platform.errors import AuthError


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    sub: uuid.UUID
    sid: uuid.UUID
    role: UserRole
    iat: datetime
    exp: datetime
    iss: str


def issue_access_token(
    user: User, device_id: uuid.UUID, settings: Settings
) -> tuple[str, int]:
    now = datetime.now(UTC)
    exp = now + timedelta(minutes=settings.jwt_access_ttl_minutes)
    payload = {
        "sub": str(user.id),
        "sid": str(device_id),
        "role": user.role.value,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "iss": settings.jwt_issuer,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, settings.jwt_access_ttl_minutes * 60


def decode_access_token(token: str, settings: Settings) -> AccessTokenClaims:
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "sid", "role", "iss"]},
        )
    except jwt.ExpiredSignatureError as e:
        raise AuthError("Access token expired") from e
    except jwt.InvalidTokenError as e:
        raise AuthError("Invalid access token") from e

    try:
        return AccessTokenClaims(
            sub=uuid.UUID(payload["sub"]),
            sid=uuid.UUID(payload["sid"]),
            role=UserRole(payload["role"]),
            iat=datetime.fromtimestamp(payload["iat"], tz=UTC),
            exp=datetime.fromtimestamp(payload["exp"], tz=UTC),
            iss=payload["iss"],
        )
    except (KeyError, ValueError) as e:
        raise AuthError("Malformed access token claims") from e


def generate_refresh_token() -> str:
    """256-bit URL-safe random token."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """SHA-256 of the plaintext refresh token, hex-encoded.

    Refresh tokens are long random strings, so a fast hash is sufficient —
    no password hashing needed.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
