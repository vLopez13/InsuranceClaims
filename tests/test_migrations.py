"""Migrations apply up and down from an empty database."""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]


def test_upgrade_and_downgrade(monkeypatch) -> None:
    admin = create_engine(os.environ["MYSQL_ADMIN_URL"], isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text("DROP DATABASE IF EXISTS insurance_claims_migrate"))
        connection.execute(
            text(
                "CREATE DATABASE insurance_claims_migrate "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )
    admin.dispose()
    url = (
        os.environ["MYSQL_ADMIN_URL"].rsplit("/", 1)[0]
        + "/insurance_claims_migrate?charset=utf8mb4"
    )
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM patients")).scalar() == 10
        assert connection.execute(text("SELECT COUNT(*) FROM providers")).scalar() == 11
    command.downgrade(config, "base")
    with engine.connect() as connection:
        names = (
            connection.execute(
                text(
                    "SELECT TABLE_NAME FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME != 'alembic_version'"
                )
            )
            .scalars()
            .all()
        )
        assert names == []
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM patients")).scalar() == 10
    engine.dispose()
