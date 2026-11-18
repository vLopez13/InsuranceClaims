"""SQLAlchemy engine and session factory. Timestamps are written as UTC."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}


def mysql_table_args() -> dict[str, str]:
    """A fresh dict per table. SQLAlchemy may mutate table args."""

    return {
        "mysql_engine": "InnoDB",
        "mysql_charset": "utf8mb4",
        "mysql_collate": "utf8mb4_unicode_ci",
    }


def utcnow() -> datetime:
    """Naive UTC timestamp. MySQL DATETIME does not store a zone; the session is UTC."""

    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def make_engine(url: str) -> Engine:
    engine = create_engine(
        url,
        pool_pre_ping=True,
        future=True,
        connect_args={"charset": "utf8mb4"},
    )

    @event.listens_for(engine, "connect")
    def _set_utc(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("SET time_zone = '+00:00'")
        finally:
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
