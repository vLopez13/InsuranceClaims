"""MySQL constraints the application relies on."""

import pytest
from app.models import Claim, ClaimAuditLog
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError


def _npi_valid(npi: str) -> bool:
    digits = [int(character) for character in "80840" + npi]
    total = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def test_engine_charset_and_restrict(session) -> None:
    tables = session.execute(
        text(
            "SELECT ENGINE, TABLE_COLLATION FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE' "
            "AND TABLE_NAME != 'alembic_version'"
        )
    ).all()
    assert tables
    assert {row[0] for row in tables} == {"InnoDB"}
    assert {row[1] for row in tables} == {"utf8mb4_unicode_ci"}
    rules = session.execute(
        text(
            "SELECT DELETE_RULE, UPDATE_RULE FROM information_schema.REFERENTIAL_CONSTRAINTS "
            "WHERE CONSTRAINT_SCHEMA = DATABASE()"
        )
    ).all()
    assert rules
    assert {row[0] for row in rules} == {"RESTRICT"}
    assert {row[1] for row in rules} == {"RESTRICT"}


def test_seed_identifiers_are_not_valid_npis(session) -> None:
    rows = session.execute(text("SELECT npi, tax_id, practice_name FROM providers")).all()
    assert rows
    for npi, tax_id, name in rows:
        assert not _npi_valid(npi)
        assert tax_id.startswith("00-")
        assert "Kaiser" not in name
        assert "Sutter" not in name
    emails = session.execute(text("SELECT email_address FROM patients")).scalars().all()
    assert emails
    assert all(email.endswith("@example.com") for email in emails)


def test_code_checks_and_score_and_audit(session) -> None:
    session.execute(
        text(
            "INSERT INTO icd10_codes (code, description, billable) "
            "VALUES ('U07.1', 'Synthetic U code', 1)"
        )
    )
    session.commit()
    with pytest.raises(OperationalError):
        session.execute(
            text(
                "INSERT INTO icd10_codes (code, description, billable) VALUES ('M17X11', 'bad', 1)"
            )
        )
        session.commit()
    session.rollback()
    with pytest.raises(OperationalError):
        session.execute(
            text(
                "INSERT INTO cpt_codes (code, description, active, covered) VALUES ('1234A', 'bad', 1, 1)"
            )
        )
        session.commit()
    session.rollback()
    with pytest.raises(OperationalError):
        session.execute(text("UPDATE claims SET necessity_score = 1.5 WHERE id = 1"))
        session.commit()
    session.rollback()
    with pytest.raises(OperationalError):
        session.execute(text("UPDATE claim_audit_log SET action = 'tamper'"))
        session.commit()
    session.rollback()
    with pytest.raises(IntegrityError):
        session.execute(text("DELETE FROM providers WHERE id = 101"))
        session.commit()
    session.rollback()
    assert session.get(Claim, 1) is not None
    assert session.get(ClaimAuditLog, 1) is not None
