"""Request and response models. ``extra=forbid`` rejects unexpected fields."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from app.domain import codes
from app.domain.enums import (
    ClaimOutcome,
    ClaimPriority,
    ClaimStatus,
    DocumentType,
)
from app.domain.money import parse_money

_CPT = re.compile(codes.CPT_PATTERN)
_ICD = re.compile(codes.ICD10_PATTERN)


def _forbid_duplicate(values: list[str], code: str) -> list[str]:
    if len(set(values)) != len(values):
        raise PydanticCustomError(code, code)
    return values


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocumentInput(APIModel):
    document_type: DocumentType
    mime_type: str = Field(min_length=1, max_length=127)
    content_base64: str = Field(min_length=1, max_length=8_000_000)


class ClaimCreate(APIModel):
    patient_id: int = Field(gt=0)
    provider_id: int = Field(gt=0)
    payer_id: int = Field(gt=0)
    priority: ClaimPriority = ClaimPriority.normal
    requested_amount: Decimal
    cpt_codes: list[str] = Field(min_length=1, max_length=10)
    icd10_codes: list[str] = Field(min_length=1, max_length=10)
    documents: list[DocumentInput] = Field(default_factory=list, max_length=10)

    @field_validator("requested_amount", mode="before")
    @classmethod
    def _amount(cls, value: object) -> Decimal:
        try:
            return parse_money(value)
        except ValueError as exc:
            raise PydanticCustomError("invalid_amount", "invalid_amount") from exc

    @field_validator("cpt_codes")
    @classmethod
    def _cpt(cls, values: list[str]) -> list[str]:
        _forbid_duplicate(values, "duplicate_cpt")
        for value in values:
            if not _CPT.fullmatch(value):
                raise PydanticCustomError("invalid_cpt_format", "invalid_cpt_format")
        return values

    @field_validator("icd10_codes")
    @classmethod
    def _icd(cls, values: list[str]) -> list[str]:
        _forbid_duplicate(values, "duplicate_icd10")
        for value in values:
            if not _ICD.fullmatch(value):
                raise PydanticCustomError("invalid_icd10_format", "invalid_icd10_format")
        return values


class DecisionCreate(APIModel):
    decision: str
    reason_code: str | None = None
    approved_amount: Decimal | None = None
    notes: str | None = Field(default=None, max_length=4000)
    expected_version: int | None = Field(default=None, gt=0)

    @field_validator("decision")
    @classmethod
    def _decision(cls, value: str) -> str:
        if value not in {"approved", "denied", "pended_docs"}:
            raise PydanticCustomError("invalid_decision", "invalid_decision")
        return value

    @field_validator("reason_code")
    @classmethod
    def _reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not re.fullmatch(r"^[A-Z0-9_]{3,64}$", value):
            raise PydanticCustomError("invalid_reason_code", "invalid_reason_code")
        return value

    @field_validator("approved_amount", mode="before")
    @classmethod
    def _approved(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        try:
            return parse_money(value)
        except ValueError as exc:
            raise PydanticCustomError("invalid_amount", "invalid_amount") from exc

    @model_validator(mode="after")
    def _need_reason(self) -> DecisionCreate:
        if self.decision in {"denied", "pended_docs"} and not self.reason_code:
            raise PydanticCustomError("reason_code_required", "reason_code_required")
        return self


class ReasonCodes(APIModel):
    rule_failures: list[str] = Field(default_factory=list)
    rule_passes: list[str] = Field(default_factory=list)
    scorer: list[str] = Field(default_factory=list)
    router: list[str] = Field(default_factory=list)
    document_id: int | None = None


class ClaimResponse(APIModel):
    id: int
    patient_id: int
    provider_id: int
    payer_id: int
    status: ClaimStatus
    outcome: ClaimOutcome
    priority: ClaimPriority
    requested_amount: Decimal
    approved_amount: Decimal
    rejection_code: str | None
    automation_flag: bool
    necessity_score: Decimal | None
    model_version: str | None
    rules_version: str | None
    threshold_version: str | None
    reason_codes: ReasonCodes
    reviewer_id: int | None
    submitted_at: datetime
    routed_at: datetime | None
    decided_at: datetime | None
    version: int
    cpt_codes: list[str]
    icd10_codes: list[str]
    correlation_id: str
    notes: str | None = None

    @field_serializer("submitted_at", "routed_at", "decided_at")
    def _utc(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class DocumentResponse(APIModel):
    id: int
    claim_id: int
    document_type: DocumentType
    file_reference: str
    content_sha256: str
    mime_type: str
    byte_size: int
    created_at: datetime

    @field_serializer("created_at")
    def _utc(self, value: datetime) -> str:
        return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class AuditEntry(APIModel):
    id: int
    claim_id: int
    actor: str
    action: str
    from_status: ClaimStatus | None
    to_status: ClaimStatus
    rules_version: str | None
    model_version: str | None
    threshold_version: str | None
    reason_codes: ReasonCodes
    correlation_id: str
    created_at: datetime

    @field_serializer("created_at")
    def _utc(self, value: datetime) -> str:
        return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class ClaimPage(APIModel):
    items: list[ClaimResponse]
    page: int
    page_size: int
    total: int


class AuditPage(APIModel):
    items: list[AuditEntry]
    page: int
    page_size: int
    total: int


class OutcomeCounts(APIModel):
    pending: int
    auto_approved: int
    human_approved: int
    human_denied: int
    withdrawn: int


class MetricsResponse(APIModel):
    counts_by_outcome: OutcomeCounts
    straight_through_rate: Decimal
    automation_rate: Decimal
    decided_count: int
    average_turnaround_seconds: Decimal | None
    latency_p50_seconds: Decimal | None
    latency_p95_seconds: Decimal | None
    average_routing_seconds: Decimal | None
    routing_latency_p50_seconds: Decimal | None
    routing_latency_p95_seconds: Decimal | None
    target_turnaround_seconds: int


class HealthResponse(APIModel):
    status: str


class ErrorDetail(APIModel):
    loc: list[str]
    type: str


class ErrorBody(APIModel):
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorResponse(APIModel):
    error: ErrorBody
