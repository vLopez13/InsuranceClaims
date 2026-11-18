"""MySQL-backed fixtures. Each test rolls back its writes."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "mysql+pymysql://claims:devpassword@127.0.0.1:3306/insurance_claims_test?charset=utf8mb4",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["API_KEY"] = os.environ.get("TEST_API_KEY", "test-api-key")
os.environ["APPROVE_T"] = "0.80"
os.environ["HIGH_AMOUNT_T"] = "70000.00"
os.environ["SCORER_TIMEOUT_SECONDS"] = "5"
os.environ.setdefault(
    "MYSQL_ADMIN_URL",
    "mysql+pymysql://claims:devpassword@127.0.0.1:3306/mysql?charset=utf8mb4",
)

from app.api.deps import get_db  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import make_engine  # noqa: E402
from app.main import create_app  # noqa: E402


def _recreate_database(name: str) -> None:
    admin = create_engine(os.environ["MYSQL_ADMIN_URL"], isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f"DROP DATABASE IF EXISTS `{name}`"))
        connection.execute(
            text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        )
    admin.dispose()


@pytest.fixture(scope="session")
def engine():
    _recreate_database("insurance_claims_test")
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    built = make_engine(TEST_DATABASE_URL)
    yield built
    built.dispose()


@pytest.fixture
def connection(engine):
    conn = engine.connect()
    transaction = conn.begin()
    yield conn
    transaction.rollback()
    conn.close()


@pytest.fixture
def session(connection) -> Generator[Session, None, None]:
    bound = Session(
        bind=connection,
        autoflush=False,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    yield bound
    bound.close()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url=TEST_DATABASE_URL,
        api_key="test-api-key",
        approve_t="0.80",
        high_amount_t="70000.00",
        scorer_timeout_seconds=5,
        storage_path=str(tmp_path),
    )


@pytest.fixture
def client(session: Session, settings: Settings) -> Generator[TestClient, None, None]:
    application = create_app(settings)

    def _override() -> Generator[Session, None, None]:
        yield session

    application.dependency_overrides[get_db] = _override
    with TestClient(application) as test_client:
        yield test_client
    application.state.engine.dispose()
