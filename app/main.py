"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from app import __version__
from app.api.errors import register_error_handlers
from app.api.routes import health_router, router
from app.config import Settings, load_settings
from app.correlation import CorrelationMiddleware
from app.db import make_engine, make_session_factory
from app.logging_config import configure_logging
from app.services.documents.store import LocalDocumentStore
from app.services.integrations.review_queue import OutboxReviewQueue
from app.services.rules.engine import build_rules_engine
from app.services.scoring.factory import build_scorer


def create_app(settings: Settings | None = None) -> FastAPI:
    active = settings if settings is not None else load_settings()
    configure_logging(active.log_level)
    application = FastAPI(
        title="InsuranceClaims Prior Authorization",
        version=__version__,
        description=(
            "Three-tier prior authorization: business rules, a pluggable medical "
            "necessity score, and human triage."
        ),
    )
    application.state.settings = active
    engine = make_engine(active.database_url)
    application.state.engine = engine
    application.state.session_factory = make_session_factory(engine)
    application.state.scorer = build_scorer(active)
    application.state.rules_engine = build_rules_engine(active)
    application.state.document_store = LocalDocumentStore(active.storage_path)
    application.state.review_queue = OutboxReviewQueue()
    register_error_handlers(application)
    application.add_middleware(CorrelationMiddleware)
    application.include_router(health_router)
    application.include_router(router)
    return application


app = create_app()
