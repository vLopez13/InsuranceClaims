"""Error responses. Bodies never echo request values."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.correlation import current_correlation_id
from app.domain.errors import (
    ClaimNotFound,
    DomainValidation,
    FinalizedClaim,
    IdempotencyConflict,
    IdempotencyKeyRequired,
    IllegalTransition,
    InvalidReference,
    MissingActor,
    PayloadTooLarge,
    RequestInProgress,
    UnsupportedMedia,
    VersionConflict,
)

logger = logging.getLogger(__name__)

_HTTP_CODES = {
    401: ("unauthorized", "Authentication required"),
    404: ("not_found", "Resource not found"),
    405: ("method_not_allowed", "Method not allowed"),
    409: ("conflict", "Request conflicts with the current resource state"),
    422: ("validation_error", "Request validation failed"),
}


def error_body(
    code: str, message: str, details: list[dict[str, object]] | None = None
) -> dict[str, object]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or [],
        }
    }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(IdempotencyKeyRequired)
    async def _key_required(_request: Request, _exc: IdempotencyKeyRequired) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=error_body("idempotency_key_required", "Idempotency-Key is required"),
        )

    @app.exception_handler(MissingActor)
    async def _actor(_request: Request, _exc: MissingActor) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            content=error_body("unauthorized", "Authentication required"),
        )

    @app.exception_handler(RequestInProgress)
    async def _in_progress(_request: Request, _exc: RequestInProgress) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content=error_body(
                "request_in_progress",
                "A request with this idempotency key is already in progress",
            ),
        )

    @app.exception_handler(PayloadTooLarge)
    async def _too_large(_request: Request, _exc: PayloadTooLarge) -> JSONResponse:
        return JSONResponse(
            status_code=413,
            content=error_body("payload_too_large", "Document exceeds the size limit"),
        )

    @app.exception_handler(UnsupportedMedia)
    async def _media(_request: Request, _exc: UnsupportedMedia) -> JSONResponse:
        return JSONResponse(
            status_code=415,
            content=error_body("unsupported_media_type", "Document type is not allowed"),
        )

    @app.exception_handler(ClaimNotFound)
    async def _missing(_request: Request, _exc: ClaimNotFound) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=error_body("not_found", "Resource not found"),
        )

    @app.exception_handler(IdempotencyConflict)
    async def _idempotency(_request: Request, _exc: IdempotencyConflict) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content=error_body(
                "idempotency_conflict",
                "This idempotency key was already used with a different request",
            ),
        )

    @app.exception_handler(FinalizedClaim)
    async def _finalized(_request: Request, _exc: FinalizedClaim) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content=error_body("finalized", "The claim can no longer accept documents"),
        )

    @app.exception_handler(VersionConflict)
    async def _version(_request: Request, _exc: VersionConflict) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content=error_body("version_conflict", "The claim was updated by someone else"),
        )

    @app.exception_handler(IllegalTransition)
    async def _transition(_request: Request, _exc: IllegalTransition) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content=error_body(
                "illegal_transition",
                "The claim status does not allow this action",
                [{"loc": ["body", "outcome"], "type": "illegal_transition"}],
            ),
        )

    @app.exception_handler(InvalidReference)
    async def _reference(_request: Request, exc: InvalidReference) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_body(
                "validation_error",
                "Request validation failed",
                [{"loc": ["body", exc.field], "type": "unknown_reference"}],
            ),
        )

    @app.exception_handler(DomainValidation)
    async def _domain(_request: Request, exc: DomainValidation) -> JSONResponse:
        loc = ["header", exc.field] if exc.field == "Idempotency-Key" else ["body", exc.field]
        return JSONResponse(
            status_code=422,
            content=error_body(
                "validation_error",
                "Request validation failed",
                [{"loc": loc, "type": exc.error_type}],
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError) -> JSONResponse:
        details = []
        for error in exc.errors():
            loc = [str(part) for part in error.get("loc", ())]
            error_type = str(error.get("type", "invalid"))
            details.append({"loc": loc, "type": error_type})
        logger.info(
            "validation_failed correlation_id=%s error_count=%s",
            current_correlation_id(),
            len(details),
        )
        return JSONResponse(
            status_code=422,
            content=error_body("validation_error", "Request validation failed", details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, message = _HTTP_CODES.get(exc.status_code, ("error", "Request failed"))
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, message),
        )

    @app.exception_handler(IntegrityError)
    async def _integrity(_request: Request, _exc: IntegrityError) -> JSONResponse:
        # MySQL texts such as "Duplicate entry ..." are not returned.
        logger.error(
            "constraint_failed correlation_id=%s error_type=%s",
            current_correlation_id(),
            "IntegrityError",
        )
        return JSONResponse(
            status_code=409,
            content=error_body("conflict", "Request conflicts with the current resource state"),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "request_failed correlation_id=%s error_type=%s",
            current_correlation_id(),
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content=error_body("internal_error", "The request could not be completed"),
        )
