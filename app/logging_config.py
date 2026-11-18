"""Logging setup that never records exception text.

SQLAlchemy and validation errors can embed request values. Callers log an error
type and a correlation id, not ``str(exc)`` and not ``exc_info``.
"""

from __future__ import annotations

import logging


def configure_logging(level: str) -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
