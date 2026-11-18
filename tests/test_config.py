"""Startup validation for the confirmed thresholds."""

from decimal import Decimal

import pytest
from app.config import Settings, get_settings, load_settings
from pydantic import SecretStr, ValidationError


def test_confirmed_defaults(monkeypatch) -> None:
    monkeypatch.delenv("APPROVE_T", raising=False)
    monkeypatch.delenv("HIGH_AMOUNT_T", raising=False)
    monkeypatch.delenv("SCORER_TIMEOUT_SECONDS", raising=False)
    settings = Settings(
        database_url="mysql+pymysql://claims:dev@localhost/db", api_key="test-api-key"
    )
    assert settings.approve_t == Decimal("0.80")
    assert settings.high_amount_t == Decimal("70000.00")
    assert settings.scorer_timeout_seconds == 5
    assert settings.document_max_bytes == 20 * 1024 * 1024


@pytest.mark.parametrize("value", ["1.1", "-0.01", "NaN"])
def test_approve_t_must_be_a_unit_interval(value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(
            database_url="mysql+pymysql://claims:dev@localhost/db",
            api_key="test-api-key",
            approve_t=value,
        )


def test_load_settings_hides_secrets(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgres://claims:supersecret@localhost/db")
    monkeypatch.setenv("API_KEY", "short")
    with pytest.raises(SystemExit) as caught:
        load_settings()
    assert "supersecret" not in str(caught.value)
    assert "short" not in str(caught.value)
    get_settings.cache_clear()
    assert SecretStr
