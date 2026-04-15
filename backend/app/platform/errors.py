"""Domain error hierarchy + FastAPI exception handlers.

Services raise `DomainError` subclasses. The HTTP layer maps them to
problem+json responses (RFC 7807) via registered exception handlers. Internal
stack traces are never exposed to clients — only `title` + `detail` + a
request-scoped `request_id` the caller can include in a bug report.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from app.platform.logging import get_logger

logger = get_logger(__name__)


class DomainError(Exception):
    """Base class for business-rule and validation failures raised by services.

    Subclass this for anything that should surface to the client with a known
    HTTP status. Unhandled exceptions become 500s.
    """

    status_code: int = 400
    error_code: str = "domain_error"
    title: str = "Domain error"

    def __init__(self, detail: str, extra: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extra = extra or {}


class NotFoundError(DomainError):
    status_code = 404
    error_code = "not_found"
    title = "Resource not found"


class ConflictError(DomainError):
    status_code = 409
    error_code = "conflict"
    title = "Conflict"


class ValidationError(DomainError):
    status_code = 422
    error_code = "validation_error"
    title = "Validation error"


class AuthError(DomainError):
    status_code = 401
    error_code = "unauthorized"
    title = "Unauthorized"


class ForbiddenError(DomainError):
    status_code = 403
    error_code = "forbidden"
    title = "Forbidden"


class RateLimitedError(DomainError):
    status_code = 429
    error_code = "rate_limited"
    title = "Too many requests"


def _problem_response(
    request: Request,
    status: int,
    error_code: str,
    title: str,
    detail: str,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"about:blank#{error_code}",
        "title": title,
        "status": status,
        "detail": detail,
        "error_code": error_code,
        "request_id": getattr(request.state, "request_id", None),
    }
    if extra:
        body["extra"] = extra
    return JSONResponse(
        status_code=status,
        content=body,
        media_type="application/problem+json",
    )


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    logger.info(
        "domain_error",
        error_code=exc.error_code,
        status=exc.status_code,
        detail=exc.detail,
        path=request.url.path,
    )
    return _problem_response(
        request,
        exc.status_code,
        exc.error_code,
        exc.title,
        exc.detail,
        exc.extra or None,
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "unhandled_exception",
        path=request.url.path,
        exc_type=type(exc).__name__,
    )
    return _problem_response(
        request,
        500,
        "internal_error",
        "Internal server error",
        "An unexpected error occurred. The team has been notified.",
    )
