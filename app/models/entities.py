"""Relational model for prior authorization.

Every foreign key is explicit ``ON DELETE RESTRICT`` / ``ON UPDATE RESTRICT``.
Nothing cascades. The audit table is append-only via database triggers created
in the migration, and it stores identifiers and reason codes only.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, mysql_table_args, utcnow
from app.domain.enums import (
    ClaimOutcome,
    ClaimPriority,
    ClaimStatus,
    DocumentType,
    IdempotencyState,
    OutboxStatus,
)

# MySQL CHECK literals. Backslashes are doubled so the regex engine sees a literal dot.
_ICD10_CHECK = "code REGEXP '^[A-Z][0-9][0-9A-Z](\\\\.[0-9A-Z]{1,4})?$'"
_CPT_CHECK = "code REGEXP '^[0-9]{4}[0-9FT]$'"
_REJECTION_CHECK = "rejection_code IS NULL OR rejection_code REGEXP '^(CO|PR|OA|PI|CR)-[0-9]{1,3}$'"


def _enum(enum_cls: type, name: str) -> Enum:
    return Enum(
        enum_cls,
        name=name,
        native_enum=True,
        values_callable=lambda obj: [member.value for member in obj],
        validate_strings=True,
    )


def _fk(target: str) -> ForeignKey:
    return ForeignKey(target, ondelete="RESTRICT", onupdate="RESTRICT")


class Payer(Base):
    __tablename__ = "payers"
    __table_args__ = (mysql_table_args(),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class Provider(Base):
    __tablename__ = "providers"
    __table_args__ = (
        CheckConstraint("npi REGEXP '^[0-9]{10}$'", name="ck_providers_npi_format"),
        CheckConstraint(
            "tax_id REGEXP '^[0-9]{2}-[0-9]{7}$'",
            name="ck_providers_tax_id_format",
        ),
        Index("ix_providers_created_at", "created_at"),
        mysql_table_args(),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    npi: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    practice_name: Mapped[str] = mapped_column(String(255), nullable=False)
    specialty: Mapped[str] = mapped_column(String(100), nullable=False)
    tax_id: Mapped[str] = mapped_column(String(15), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class ProviderNetwork(Base):
    """Payer-specific network participation. In-network is not a provider attribute."""

    __tablename__ = "provider_networks"
    __table_args__ = (
        UniqueConstraint(
            "provider_id",
            "payer_id",
            name="uq_provider_networks_provider_payer",
        ),
        mysql_table_args(),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[int] = mapped_column(_fk("providers.id"), nullable=False, index=True)
    payer_id: Mapped[int] = mapped_column(_fk("payers.id"), nullable=False, index=True)
    in_network: Mapped[bool] = mapped_column(Boolean, nullable=False)


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (
        Index("ix_patients_created_at", "created_at"),
        mysql_table_args(),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    email_address: Mapped[str] = mapped_column(String(255), nullable=False)
    eligibility_verified_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    primary_care_physician_id: Mapped[int] = mapped_column(
        _fk("providers.id"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class Reviewer(Base):
    """Internal reviewer identity. No names or emails are stored."""

    __tablename__ = "reviewers"
    __table_args__ = (mysql_table_args(),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class CptCode(Base):
    __tablename__ = "cpt_codes"
    __table_args__ = (
        CheckConstraint(_CPT_CHECK, name="ck_cpt_codes_format"),
        mysql_table_args(),
    )

    code: Mapped[str] = mapped_column(String(5), primary_key=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    covered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Icd10Code(Base):
    __tablename__ = "icd10_codes"
    __table_args__ = (
        CheckConstraint(_ICD10_CHECK, name="ck_icd10_codes_format"),
        mysql_table_args(),
    )

    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    billable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Claim(Base):
    __tablename__ = "claims"
    __table_args__ = (
        CheckConstraint(
            "necessity_score IS NULL OR (necessity_score >= 0 AND necessity_score <= 1)",
            name="ck_claims_necessity_score_range",
        ),
        CheckConstraint(
            "requested_amount >= 0",
            name="ck_claims_requested_amount_nonneg",
        ),
        CheckConstraint(
            "approved_amount >= 0",
            name="ck_claims_approved_amount_nonneg",
        ),
        CheckConstraint(
            "approved_amount <= requested_amount",
            name="ck_claims_approved_lte_requested",
        ),
        CheckConstraint(_REJECTION_CHECK, name="ck_claims_rejection_code_format"),
        Index("ix_claims_status", "status"),
        Index("ix_claims_created_at", "created_at"),
        Index("ix_claims_submitted_at", "submitted_at"),
        Index("ix_claims_correlation_id", "correlation_id"),
        Index(
            "ix_claims_triage",
            "status",
            "priority",
            "submitted_at",
        ),
        mysql_table_args(),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    patient_id: Mapped[int] = mapped_column(_fk("patients.id"), nullable=False, index=True)
    provider_id: Mapped[int] = mapped_column(_fk("providers.id"), nullable=False, index=True)
    payer_id: Mapped[int] = mapped_column(_fk("payers.id"), nullable=False, index=True)
    reviewer_id: Mapped[int | None] = mapped_column(
        _fk("reviewers.id"),
        nullable=True,
        index=True,
    )
    status: Mapped[ClaimStatus] = mapped_column(_enum(ClaimStatus, "claim_status"), nullable=False)
    outcome: Mapped[ClaimOutcome] = mapped_column(
        _enum(ClaimOutcome, "claim_outcome"),
        nullable=False,
    )
    priority: Mapped[ClaimPriority] = mapped_column(
        _enum(ClaimPriority, "claim_priority"),
        nullable=False,
    )
    requested_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    approved_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00"),
    )
    rejection_code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    automation_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    necessity_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rules_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    threshold_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason_codes: Mapped[dict[str, list[str]]] = mapped_column(JSON, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_notes: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    routed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    procedures: Mapped[list[ClaimProcedure]] = relationship(
        back_populates="claim",
        cascade="save-update, merge",
        passive_deletes=True,
        order_by="ClaimProcedure.sequence",
    )
    diagnoses: Mapped[list[ClaimDiagnosis]] = relationship(
        back_populates="claim",
        cascade="save-update, merge",
        passive_deletes=True,
        order_by="ClaimDiagnosis.sequence",
    )
    documents: Mapped[list[ClaimDocument]] = relationship(
        back_populates="claim",
        cascade="save-update, merge",
        passive_deletes=True,
    )


class ClaimProcedure(Base):
    """CPT values are stored even when they are absent from the reference table.

    An unknown but well-formed code is a business result (``non_covered_code``),
    so this column is intentionally not a foreign key.
    """

    __tablename__ = "claim_procedures"
    __table_args__ = (
        UniqueConstraint("claim_id", "cpt_code", name="uq_claim_procedures_claim_cpt"),
        UniqueConstraint("claim_id", "sequence", name="uq_claim_procedures_claim_sequence"),
        CheckConstraint(
            "cpt_code REGEXP '^[0-9]{4}[0-9FT]$'",
            name="ck_claim_procedures_cpt_format",
        ),
        mysql_table_args(),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[int] = mapped_column(_fk("claims.id"), nullable=False, index=True)
    cpt_code: Mapped[str] = mapped_column(String(5), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    claim: Mapped[Claim] = relationship(back_populates="procedures")


class ClaimDiagnosis(Base):
    __tablename__ = "claim_diagnoses"
    __table_args__ = (
        UniqueConstraint("claim_id", "icd10_code", name="uq_claim_diagnoses_claim_icd"),
        UniqueConstraint("claim_id", "sequence", name="uq_claim_diagnoses_claim_sequence"),
        mysql_table_args(),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[int] = mapped_column(_fk("claims.id"), nullable=False, index=True)
    icd10_code: Mapped[str] = mapped_column(_fk("icd10_codes.code"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    claim: Mapped[Claim] = relationship(back_populates="diagnoses")


class ClaimDocument(Base):
    """Document metadata. File bytes live in the document store, never in this table."""

    __tablename__ = "claim_documents"
    __table_args__ = (
        CheckConstraint(
            "content_sha256 REGEXP '^[0-9a-f]{64}$'",
            name="ck_claim_documents_sha256",
        ),
        CheckConstraint("byte_size > 0", name="ck_claim_documents_byte_size"),
        CheckConstraint("file_reference <> ''", name="ck_claim_documents_reference"),
        Index("ix_claim_documents_created_at", "created_at"),
        mysql_table_args(),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[int] = mapped_column(_fk("claims.id"), nullable=False, index=True)
    document_type: Mapped[DocumentType] = mapped_column(
        _enum(DocumentType, "document_type"),
        nullable=False,
    )
    file_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(127), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    claim: Mapped[Claim] = relationship(back_populates="documents")


class ClaimAuditLog(Base):
    """Append-only decision log. Triggers reject UPDATE and DELETE.

    ``from_status`` is null only for the row that records creation. Every other
    row has both statuses. Reason codes and versions are identifiers, not narrative.
    """

    __tablename__ = "claim_audit_log"
    __table_args__ = (
        Index("ix_claim_audit_log_created_at", "created_at"),
        Index("ix_claim_audit_log_correlation_id", "correlation_id"),
        mysql_table_args(),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[int] = mapped_column(_fk("claims.id"), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    from_status: Mapped[ClaimStatus | None] = mapped_column(
        _enum(ClaimStatus, "claim_status"),
        nullable=True,
    )
    to_status: Mapped[ClaimStatus] = mapped_column(
        _enum(ClaimStatus, "claim_status"),
        nullable=False,
    )
    rules_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    threshold_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason_codes: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    claim: Mapped[Claim] = relationship()


class IntegrationOutbox(Base):
    """Durable handoff for a later Salesforce case sync. Payload is ids and codes."""

    __tablename__ = "integration_outbox"
    __table_args__ = (
        Index("ix_integration_outbox_status_created", "status", "created_at"),
        mysql_table_args(),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[int] = mapped_column(_fk("claims.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    status: Mapped[OutboxStatus] = mapped_column(
        _enum(OutboxStatus, "outbox_status"),
        nullable=False,
        default=OutboxStatus.pending,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class IdempotencyKey(Base):
    """Claimed before routing so a duplicate in-flight request can be rejected."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (mysql_table_args(),)

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[IdempotencyState] = mapped_column(
        _enum(IdempotencyState, "idempotency_state"),
        nullable=False,
    )
    claim_id: Mapped[int | None] = mapped_column(_fk("claims.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
