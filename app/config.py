"""Runtime configuration. Secrets come from the environment, never from code.

``load_settings`` drops the Pydantic error on failure. That error string includes
the rejected values, which for ``DATABASE_URL`` would include the password.
"""

from __future__ import annotations

import math
import re
from decimal import Decimal
from functools import lru_cache

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_VERSION = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}


def _unit_interval(value: object) -> Decimal:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError("threshold must be a decimal between 0 and 1")
        value = Decimal(str(value))
    if isinstance(value, str):
        if value.strip().lower() in {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity"}:
            raise ValueError("threshold must be a decimal between 0 and 1")
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except Exception as exc:
        raise ValueError("threshold must be a decimal between 0 and 1") from exc
    if amount.is_nan() or amount.is_infinite() or amount < 0 or amount > 1:
        raise ValueError("threshold must be a decimal between 0 and 1")
    return amount


class DatabaseSettings(BaseSettings):
    """Subset used by Alembic so migrations do not require the API key."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    database_url: str = Field(min_length=1)

    @field_validator("database_url")
    @classmethod
    def _mysql_url(cls, value: str) -> str:
        if not value.startswith("mysql+pymysql://"):
            raise ValueError("DATABASE_URL must be a mysql+pymysql URL")
        return value


class Settings(DatabaseSettings):
    api_key: SecretStr = Field(min_length=8)
    approve_t: Decimal = Decimal("0.80")
    high_amount_t: Decimal = Decimal("70000.00")
    threshold_version: str = "thresholds-v1"
    rules_version: str = "rules-v1"
    scorer_impl: str = "heuristic"
    stub_score: Decimal = Decimal("0.50")
    scorer_timeout_seconds: float = 5.0
    eligibility_max_age_days: int = 365
    document_max_bytes: int = 20 * 1024 * 1024
    storage_path: str = "./var/documents"
    log_level: str = "INFO"

    @field_validator("approve_t", "stub_score", mode="before")
    @classmethod
    def _thresholds(cls, value: object) -> Decimal:
        return _unit_interval(value)

    @field_validator("high_amount_t", mode="before")
    @classmethod
    def _high_amount(cls, value: object) -> Decimal:
        if isinstance(value, bool) or isinstance(value, float):
            raise ValueError("HIGH_AMOUNT_T must be a decimal amount")
        try:
            amount = value if isinstance(value, Decimal) else Decimal(str(value))
        except Exception as exc:
            raise ValueError("HIGH_AMOUNT_T must be a decimal amount") from exc
        if amount.is_nan() or amount.is_infinite() or amount <= 0:
            raise ValueError("HIGH_AMOUNT_T must be a positive amount")
        return amount.quantize(Decimal("0.01"))

    @field_validator("scorer_timeout_seconds")
    @classmethod
    def _timeout(cls, value: float) -> float:
        if math.isnan(value) or math.isinf(value) or value <= 0 or value > 30:
            raise ValueError("scorer timeout must be a positive number of seconds")
        return value

    @field_validator("eligibility_max_age_days")
    @classmethod
    def _eligibility_window(cls, value: int) -> int:
        if value < 1 or value > 3650:
            raise ValueError("eligibility window is out of range")
        return value

    @field_validator("document_max_bytes")
    @classmethod
    def _document_max(cls, value: int) -> int:
        if value < 1 or value > 50 * 1024 * 1024:
            raise ValueError("document size limit is out of range")
        return value

    @field_validator("threshold_version", "rules_version")
    @classmethod
    def _version_token(cls, value: str) -> str:
        if not _VERSION.fullmatch(value):
            raise ValueError("version token is invalid")
        return value

    @field_validator("scorer_impl")
    @classmethod
    def _scorer_impl(cls, value: str) -> str:
        if value not in {"heuristic", "stub"}:
            raise ValueError("SCORER_IMPL must be heuristic or stub")
        return value

    @field_validator("api_key")
    @classmethod
    def _api_key(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if len(secret) < 8 or any(character.isspace() for character in secret):
            raise ValueError("API_KEY is invalid")
        return value

    @field_validator("log_level")
    @classmethod
    def _log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in _LOG_LEVELS:
            raise ValueError("LOG_LEVEL is invalid")
        return normalized

    @field_validator("storage_path")
    @classmethod
    def _storage_path(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("STORAGE_PATH is empty")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_settings() -> Settings:
    """Validate configuration at startup without echoing secret values."""

    try:
        return get_settings()
    except ValidationError as exc:
        fields = sorted({str(error.get("loc", ("unknown",))[0]) for error in exc.errors()})
        raise SystemExit(f"Invalid configuration for: {', '.join(fields)}") from None
