"""structlog bootstrap.

Console renderer in dev, JSON renderer elsewhere. A PII redaction processor
masks phone numbers, VINs, license plates, and authorization headers on the
way out. Log site code doesn't need to opt in — it's global.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any, cast

import structlog
from structlog.stdlib import BoundLogger

from app.platform.config import LogFormat, Settings, get_settings

# Values we never want to see in logs. Add to this list as new PII columns
# enter the system.
_PII_KEYS = {
    "phone",
    "phone_number",
    "msisdn",
    "vin",
    "license_plate",
    "plate",
    "authorization",
    "cookie",
    "set-cookie",
    "otp",
    "otp_code",
    "access_token",
    "refresh_token",
    "password",
    "jwt",
    "api_key",
}

_PHONE_RE = re.compile(r"\+?\d{7,15}")
_VIN_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")


def _redact_value(key: str, value: object) -> object:
    if isinstance(value, str):
        if key.lower() in _PII_KEYS:
            return "***"
        # Defensive: even for other keys, scrub phone-looking substrings that
        # might have slipped into a free-form message.
        if _PHONE_RE.search(value) or _VIN_RE.search(value):
            return _PHONE_RE.sub("***", _VIN_RE.sub("***", value))
    return value


def _redact_processor(
    _logger: object,
    _method: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    return {k: _redact_value(k, v) for k, v in event_dict.items()}


def configure_logging(settings: Settings | None = None) -> None:
    s = settings or get_settings()

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=s.app_log_level,
    )

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact_processor,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: Any
    if s.app_log_format == LogFormat.json:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(s.app_log_level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> BoundLogger:
    return cast(BoundLogger, structlog.get_logger(name))
