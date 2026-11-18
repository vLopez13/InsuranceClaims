"""Per-request correlation id. Invalid header values are replaced, not echoed."""

from __future__ import annotations

import re
from contextvars import ContextVar
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_CORRELATION = re.compile(r"^[A-Za-z0-9-]{8,64}$")
_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


def current_correlation_id() -> str:
    value = _correlation_id.get()
    if value:
        return value
    generated = str(uuid4())
    _correlation_id.set(generated)
    return generated


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        raw = request.headers.get("X-Correlation-ID", "")
        correlation_id = raw if _CORRELATION.fullmatch(raw) else str(uuid4())
        token = _correlation_id.set(correlation_id)
        try:
            response = await call_next(request)
        finally:
            _correlation_id.reset(token)
        response.headers["X-Correlation-ID"] = correlation_id
        return response
