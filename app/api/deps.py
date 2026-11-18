"""Request dependencies."""

from __future__ import annotations

import hmac
import re
from collections.abc import Generator

from fastapi import Depends, Request
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings
from app.domain.errors import DomainValidation, IdempotencyKeyRequired, MissingActor

_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9_:-]{8,80}$")


def get_db(request: Request) -> Generator[Session, None, None]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def require_api_key(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    provided = request.headers.get("X-API-Key", "")
    expected = settings.api_key.get_secret_value()
    if not provided or not hmac.compare_digest(provided.encode(), expected.encode()):
        raise StarletteHTTPException(status_code=401)


def require_idempotency_key(request: Request) -> str:
    raw = request.headers.get("Idempotency-Key", "")
    if raw.strip() == "":
        raise IdempotencyKeyRequired()
    if not _IDEMPOTENCY.fullmatch(raw):
        raise DomainValidation("Idempotency-Key", "invalid_idempotency_key")
    return raw


def require_reviewer_header(request: Request) -> str:
    raw = request.headers.get("X-Reviewer-Id", "").strip()
    if not raw:
        raise MissingActor()
    return raw


def require_provider_header(request: Request) -> int:
    raw = request.headers.get("X-Provider-Id", "").strip()
    if not raw.isdigit():
        raise MissingActor()
    return int(raw)
