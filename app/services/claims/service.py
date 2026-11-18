"""Submit, resubmit, and record human decisions.

Each status change and its audit row are flushed before the single commit.
A failure rolls the session back, so a claim cannot change state without an audit row.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.domain import codes
from app.domain.enums import (
    FINAL_STATUSES,
    ClaimOutcome,
    ClaimPriority,
    ClaimStatus,
    DocumentType,
    IdempotencyState,
)
from app.domain.errors import (
    ClaimNotFound,
    DomainValidation,
    FinalizedClaim,
    IdempotencyConflict,
    IllegalTransition,
    InvalidReference,
    PayloadTooLarge,
    RequestInProgress,
    UnsupportedMedia,
    VersionConflict,
)
from app.domain.money import MONEY
from app.models import (
    Claim,
    ClaimAuditLog,
    ClaimDiagnosis,
    ClaimDocument,
    ClaimProcedure,
    CptCode,
    Icd10Code,
    IdempotencyKey,
    Patient,
    Payer,
    Provider,
    ProviderNetwork,
    Reviewer,
)
from app.services.decision.pipeline import run_pipeline
from app.services.decision.router import Decision, DecisionRouter
from app.services.decision.state_machine import assert_transition
from app.services.documents.store import DocumentStore
from app.services.integrations.review_queue import UtilizationReviewQueue
from app.services.rules.engine import (
    CptFact,
    IcdFact,
    RuleContext,
    RulesEngine,
    build_rules_engine,
)
from app.services.scoring.base import MedicalNecessityScorer, ScoringFeatures

logger = logging.getLogger(__name__)

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
ALLOWED_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "image/tiff",
        "image/png",
        "image/jpeg",
    }
)


@dataclass(frozen=True)
class IncomingDocument:
    document_type: DocumentType
    mime_type: str
    content_base64: str


@dataclass(frozen=True)
class NewClaim:
    patient_id: int
    provider_id: int
    payer_id: int
    priority: ClaimPriority
    requested_amount: Decimal
    cpt_codes: list[str]
    icd10_codes: list[str]
    documents: list[IncomingDocument]
    idempotency_key: str
    request_hash: str


@dataclass(frozen=True)
class HumanDecision:
    decision: str
    reviewer_token: str
    reason_code: str | None
    approved_amount: Decimal | None
    notes: str | None
    expected_version: int | None = None


@dataclass(frozen=True)
class _DecodedDocument:
    document_type: DocumentType
    mime_type: str
    content: bytes


def request_fingerprint(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def submit_claim(
    session: Session,
    draft: NewClaim,
    *,
    settings: Settings,
    scorer: MedicalNecessityScorer,
    rules_engine: RulesEngine,
    document_store: DocumentStore,
    review_queue: UtilizationReviewQueue,
    correlation_id: str,
) -> tuple[Claim, bool]:
    replay = _idempotency_replay(session, draft.idempotency_key, draft.request_hash)
    if replay is not None:
        return replay, False

    decoded = _decode_documents(draft.documents, settings.document_max_bytes)
    patient = session.get(Patient, draft.patient_id)
    if patient is None:
        raise InvalidReference("patient_id")
    provider = session.get(Provider, draft.provider_id)
    if provider is None:
        raise InvalidReference("provider_id")
    payer = session.get(Payer, draft.payer_id)
    if payer is None:
        raise InvalidReference("payer_id")
    icds = _load_icds(session, draft.icd10_codes)
    raced = _claim_idempotency(session, draft.idempotency_key, draft.request_hash)
    if raced is not None:
        return raced, False

    try:
        now = _utcnow()
        claim = Claim(
            idempotency_key=draft.idempotency_key,
            request_hash=draft.request_hash,
            patient_id=patient.id,
            provider_id=provider.id,
            payer_id=payer.id,
            status=ClaimStatus.submitted,
            outcome=ClaimOutcome.pending,
            priority=draft.priority,
            requested_amount=draft.requested_amount,
            approved_amount=Decimal("0.00"),
            automation_flag=False,
            necessity_score=None,
            model_version=None,
            rules_version=settings.rules_version,
            threshold_version=settings.threshold_version,
            reason_codes=codes.bundle_reason_codes(
                rule_failures=[],
                rule_passes=[],
                scorer=[],
                router=[codes.CLAIM_SUBMITTED],
            ),
            correlation_id=correlation_id,
            submitted_at=now,
            routed_at=None,
            decided_at=None,
            version=1,
        )
        session.add(claim)
        session.flush()
        _attach_codes(claim, draft.cpt_codes, icds)
        _store_documents(session, document_store, claim, decoded)
        _audit(
            session,
            claim=claim,
            actor="system",
            action="claim_submitted",
            from_status=None,
            to_status=ClaimStatus.submitted,
            reason_codes=claim.reason_codes,
            settings=settings,
            model_version=getattr(scorer, "model_version", None),
            correlation_id=correlation_id,
        )
        session.flush()
        _route_from_submitted(
            session,
            claim,
            patient=patient,
            provider=provider,
            settings=settings,
            scorer=scorer,
            rules_engine=rules_engine,
            review_queue=review_queue,
            correlation_id=correlation_id,
        )
        key_row = session.get(IdempotencyKey, draft.idempotency_key)
        if key_row is not None:
            key_row.status = IdempotencyState.complete
            key_row.claim_id = claim.id
        session.commit()
    except Exception:
        session.rollback()
        _release_idempotency(session, draft.idempotency_key)
        raise
    logger.info(
        "claim_routed claim_id=%s status=%s outcome=%s correlation_id=%s",
        claim.id,
        claim.status.value,
        claim.outcome.value,
        correlation_id,
    )
    return claim, True


def resubmit_claim(
    session: Session,
    claim_id: int,
    *,
    settings: Settings,
    scorer: MedicalNecessityScorer,
    rules_engine: RulesEngine,
    review_queue: UtilizationReviewQueue,
    correlation_id: str,
) -> Claim:
    try:
        claim = session.get(Claim, claim_id, with_for_update=True)
        if claim is None:
            raise ClaimNotFound()
        if claim.status != ClaimStatus.pended_docs:
            _reject_transition(
                session,
                claim,
                claim.status,
                actor="system",
                settings=settings,
                correlation_id=correlation_id,
            )
            raise IllegalTransition(claim.status.value, claim.status.value)
        patient = session.get(Patient, claim.patient_id)
        provider = session.get(Provider, claim.provider_id)
        if patient is None:
            raise InvalidReference("patient_id")
        if provider is None:
            raise InvalidReference("provider_id")
        _route_from_submitted(
            session,
            claim,
            patient=patient,
            provider=provider,
            settings=settings,
            scorer=scorer,
            rules_engine=rules_engine,
            review_queue=review_queue,
            correlation_id=correlation_id,
            allow_same=True,
        )
        session.commit()
    except (ClaimNotFound, IllegalTransition, InvalidReference, DomainValidation):
        raise
    except Exception:
        session.rollback()
        raise
    logger.info(
        "claim_routed claim_id=%s status=%s outcome=%s correlation_id=%s",
        claim.id,
        claim.status.value,
        claim.outcome.value,
        correlation_id,
    )
    return claim


def record_human_decision(
    session: Session,
    claim_id: int,
    decision: HumanDecision,
    *,
    settings: Settings,
    correlation_id: str,
) -> Claim:
    try:
        claim = session.get(Claim, claim_id, with_for_update=True)
        if claim is None:
            raise ClaimNotFound()
        reviewer = _reviewer_from_token(session, decision.reviewer_token)
        target, outcome, action = _human_target(decision.decision)
        actor = f"reviewer:{reviewer.id}"
        if decision.expected_version is not None and claim.version != decision.expected_version:
            _reject_transition(
                session,
                claim,
                target,
                actor=actor,
                settings=settings,
                correlation_id=correlation_id,
            )
            raise VersionConflict()
        try:
            assert_transition(claim.status, target)
        except IllegalTransition:
            _reject_transition(
                session,
                claim,
                target,
                actor=actor,
                settings=settings,
                correlation_id=correlation_id,
            )
            raise
        approved_amount, rejection_code = _human_amounts(claim, decision)
        previous = claim.status
        claim.status = target
        claim.outcome = outcome
        claim.automation_flag = False
        claim.reviewer_id = reviewer.id
        claim.approved_amount = approved_amount
        claim.rejection_code = rejection_code
        claim.decided_at = None if target == ClaimStatus.pended_docs else _utcnow()
        claim.version += 1
        claim.decision_notes = decision.notes
        claim.reason_codes = codes.bundle_reason_codes(
            rule_failures=[],
            rule_passes=[],
            scorer=[],
            router=[decision.reason_code or "HUMAN_APPROVED"],
        )
        _audit(
            session,
            claim=claim,
            actor=actor,
            action=action,
            from_status=previous,
            to_status=target,
            reason_codes=claim.reason_codes,
            settings=settings,
            model_version=claim.model_version,
            correlation_id=correlation_id,
            rules_version=claim.rules_version or settings.rules_version,
            threshold_version=claim.threshold_version or settings.threshold_version,
        )
        session.commit()
    except (ClaimNotFound, IllegalTransition, InvalidReference, DomainValidation, VersionConflict):
        raise
    except Exception:
        session.rollback()
        raise
    logger.info(
        "claim_routed claim_id=%s status=%s outcome=%s correlation_id=%s",
        claim.id,
        claim.status.value,
        claim.outcome.value,
        correlation_id,
    )
    return claim


def add_document(
    session: Session,
    claim_id: int,
    *,
    document_type: DocumentType,
    mime_type: str,
    content: bytes,
    document_store: DocumentStore,
    settings: Settings,
    scorer: MedicalNecessityScorer,
    rules_engine: RulesEngine,
    review_queue: UtilizationReviewQueue,
    correlation_id: str,
) -> ClaimDocument:
    detected = _require_media(content, mime_type, settings.document_max_bytes)
    mime_type = detected
    try:
        claim = session.get(Claim, claim_id, with_for_update=True)
        if claim is None:
            raise ClaimNotFound()
        if claim.status in FINAL_STATUSES:
            raise FinalizedClaim()
        stored = document_store.save(claim_id=claim.id, content=content)
        document = ClaimDocument(
            claim_id=claim.id,
            document_type=document_type,
            file_reference=stored.file_reference,
            content_sha256=stored.content_sha256,
            mime_type=mime_type,
            byte_size=stored.byte_size,
        )
        session.add(document)
        session.flush()
        reason_codes: dict[str, object] = {
            "rule_failures": [],
            "rule_passes": [],
            "scorer": [],
            "router": ["document_uploaded"],
            "document_id": document.id,
        }
        _audit(
            session,
            claim=claim,
            actor="api_client",
            action="document_uploaded",
            from_status=claim.status,
            to_status=claim.status,
            reason_codes=reason_codes,
            settings=settings,
            model_version=claim.model_version,
            correlation_id=correlation_id,
            rules_version=claim.rules_version or settings.rules_version,
            threshold_version=claim.threshold_version or settings.threshold_version,
        )
        if claim.status == ClaimStatus.pended_docs:
            patient = session.get(Patient, claim.patient_id)
            provider = session.get(Provider, claim.provider_id)
            if patient is None or provider is None:
                raise InvalidReference("patient_id" if patient is None else "provider_id")
            _audit(
                session,
                claim=claim,
                actor="system",
                action="rules_rerun",
                from_status=claim.status,
                to_status=claim.status,
                reason_codes=codes.empty_reason_codes(),
                settings=settings,
                model_version=getattr(scorer, "model_version", None),
                correlation_id=correlation_id,
                rules_version=settings.rules_version,
                threshold_version=settings.threshold_version,
            )
            _route_from_submitted(
                session,
                claim,
                patient=patient,
                provider=provider,
                settings=settings,
                scorer=scorer,
                rules_engine=rules_engine,
                review_queue=review_queue,
                correlation_id=correlation_id,
                allow_same=True,
                action_override="routed",
            )
        session.commit()
    except (ClaimNotFound, DomainValidation, FinalizedClaim, InvalidReference):
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise
    return document


def get_claim(session: Session, claim_id: int) -> Claim:
    claim = session.get(Claim, claim_id)
    if claim is None:
        raise ClaimNotFound()
    return claim


def list_triage(
    session: Session,
    *,
    page: int,
    page_size: int,
) -> tuple[list[Claim], int]:
    priority_rank = case(
        (Claim.priority == ClaimPriority.stat, 0),
        (Claim.priority == ClaimPriority.urgent, 1),
        else_=2,
    )
    base = select(Claim).where(Claim.status == ClaimStatus.in_triage)
    total = (
        session.scalar(
            select(func.count()).select_from(Claim).where(Claim.status == ClaimStatus.in_triage)
        )
        or 0
    )
    rows = session.scalars(
        base.order_by(priority_rank, Claim.submitted_at.asc(), Claim.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows), int(total)


def list_audit(
    session: Session,
    claim_id: int,
    *,
    page: int,
    page_size: int,
) -> tuple[list[ClaimAuditLog], int]:
    if session.get(Claim, claim_id) is None:
        raise ClaimNotFound()
    base = select(ClaimAuditLog).where(ClaimAuditLog.claim_id == claim_id)
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = session.scalars(
        base.order_by(ClaimAuditLog.id.asc()).offset((page - 1) * page_size).limit(page_size)
    )
    return list(rows), int(total)


def _route_from_submitted(
    session: Session,
    claim: Claim,
    *,
    patient: Patient,
    provider: Provider,
    settings: Settings,
    scorer: MedicalNecessityScorer,
    rules_engine: RulesEngine,
    review_queue: UtilizationReviewQueue,
    correlation_id: str,
    allow_same: bool = False,
    action_override: str | None = None,
) -> None:
    documents = list(
        session.scalars(select(ClaimDocument).where(ClaimDocument.claim_id == claim.id))
    )
    procedures = list(
        session.scalars(
            select(ClaimProcedure)
            .where(ClaimProcedure.claim_id == claim.id)
            .order_by(ClaimProcedure.sequence)
        )
    )
    diagnoses = list(
        session.scalars(
            select(ClaimDiagnosis)
            .where(ClaimDiagnosis.claim_id == claim.id)
            .order_by(ClaimDiagnosis.sequence)
        )
    )
    cpt_facts = _cpt_facts(session, [row.cpt_code for row in procedures])
    icds = _load_icds(session, [row.icd10_code for row in diagnoses])
    in_network = _provider_in_network(session, claim.provider_id, claim.payer_id)
    as_of = datetime.now(UTC).date()
    rule_context = RuleContext(
        eligibility_verified_date=patient.eligibility_verified_date,
        as_of=as_of,
        eligibility_max_age_days=settings.eligibility_max_age_days,
        provider_active=provider.active,
        provider_in_network=in_network,
        document_types=frozenset(document.document_type.value for document in documents),
        cpt_codes=tuple(cpt_facts),
        icd10_codes=tuple(IcdFact(code=row.code, billable=row.billable) for row in icds),
        requested_amount=claim.requested_amount,
        high_amount_t=settings.high_amount_t,
    )
    features = ScoringFeatures(
        cpt_codes=tuple(fact.code for fact in cpt_facts),
        icd10_codes=tuple(row.code for row in icds),
        provider_specialty=provider.specialty,
        document_types=tuple(sorted(rule_context.document_types)),
        priority=claim.priority.value,
        requested_amount=claim.requested_amount,
        eligibility_current=_eligibility_current(
            patient.eligibility_verified_date,
            as_of,
            settings.eligibility_max_age_days,
        ),
        provider_in_network=in_network,
    )
    result = run_pipeline(
        rules_engine=rules_engine,
        scorer=scorer,
        router=DecisionRouter(),
        rule_context=rule_context,
        features=features,
        requested_amount=claim.requested_amount,
        approve_t=settings.approve_t,
        scorer_timeout_seconds=settings.scorer_timeout_seconds,
    )
    _apply_decision(
        session,
        claim,
        result.decision,
        score=result.score.score,
        model_version=result.score.model_version,
        settings=settings,
        review_queue=review_queue,
        correlation_id=correlation_id,
        allow_same=allow_same,
        action_override=action_override,
    )


def _apply_decision(
    session: Session,
    claim: Claim,
    decision: Decision,
    *,
    score: Decimal | None,
    model_version: str | None,
    settings: Settings,
    review_queue: UtilizationReviewQueue,
    correlation_id: str,
    allow_same: bool = False,
    action_override: str | None = None,
) -> None:
    assert_transition(claim.status, decision.status, allow_same=allow_same)
    previous = claim.status
    same_status = previous == decision.status
    now = _utcnow()
    claim.status = decision.status
    claim.outcome = decision.outcome
    claim.automation_flag = decision.automation_flag
    claim.necessity_score = score
    claim.model_version = model_version
    claim.rules_version = settings.rules_version
    claim.threshold_version = settings.threshold_version
    claim.reason_codes = decision.reason_codes
    claim.rejection_code = decision.rejection_code
    claim.approved_amount = decision.approved_amount
    claim.reviewer_id = None
    claim.version += 1
    if claim.routed_at is None:
        claim.routed_at = now
    if decision.status in FINAL_STATUSES:
        claim.decided_at = now
    else:
        claim.decided_at = None
    _audit(
        session,
        claim=claim,
        actor="system",
        action=action_override or ("rules_reevaluated" if same_status else decision.action),
        from_status=previous,
        to_status=decision.status,
        reason_codes=decision.reason_codes,
        settings=settings,
        model_version=model_version,
        correlation_id=correlation_id,
    )
    if decision.status == ClaimStatus.in_triage and not same_status:
        review_queue.enqueue(
            session,
            claim_id=claim.id,
            priority=claim.priority.value,
            reason_codes=decision.reason_codes,
            correlation_id=correlation_id,
        )
    session.flush()


def _audit(
    session: Session,
    *,
    claim: Claim,
    actor: str,
    action: str,
    from_status: ClaimStatus | None,
    to_status: ClaimStatus,
    reason_codes: dict[str, object],
    settings: Settings,
    model_version: str | None,
    correlation_id: str,
    rules_version: str | None = None,
    threshold_version: str | None = None,
) -> None:
    session.add(
        ClaimAuditLog(
            claim_id=claim.id,
            actor=actor,
            action=action,
            from_status=from_status,
            to_status=to_status,
            rules_version=rules_version or settings.rules_version,
            model_version=model_version,
            threshold_version=threshold_version or settings.threshold_version,
            reason_codes=reason_codes,
            correlation_id=correlation_id,
        )
    )


def _attach_codes(
    claim: Claim,
    cpt_codes: list[str],
    icds: list[Icd10Code],
) -> None:
    for index, code in enumerate(cpt_codes, start=1):
        claim.procedures.append(ClaimProcedure(claim_id=claim.id, cpt_code=code, sequence=index))
    for index, icd in enumerate(icds, start=1):
        claim.diagnoses.append(
            ClaimDiagnosis(
                claim_id=claim.id,
                icd10_code=icd.code,
                sequence=index,
                is_primary=index == 1,
            )
        )


def _store_documents(
    session: Session,
    document_store: DocumentStore,
    claim: Claim,
    documents: list[_DecodedDocument],
) -> None:
    for document in documents:
        stored = document_store.save(claim_id=claim.id, content=document.content)
        claim.documents.append(
            ClaimDocument(
                claim_id=claim.id,
                document_type=document.document_type,
                file_reference=stored.file_reference,
                content_sha256=stored.content_sha256,
                mime_type=document.mime_type,
                byte_size=stored.byte_size,
            )
        )


def _reject_transition(
    session: Session,
    claim: Claim,
    target: ClaimStatus,
    *,
    actor: str,
    settings: Settings,
    correlation_id: str,
) -> None:
    """Persist an ID-only audit row for a transition that will not be applied."""

    try:
        _audit(
            session,
            claim=claim,
            actor=actor,
            action="transition_rejected",
            from_status=claim.status,
            to_status=target,
            reason_codes=codes.empty_reason_codes(),
            settings=settings,
            model_version=claim.model_version,
            correlation_id=correlation_id,
            rules_version=claim.rules_version or settings.rules_version,
            threshold_version=claim.threshold_version or settings.threshold_version,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise


def _decode_documents(
    documents: list[IncomingDocument],
    max_bytes: int,
) -> list[_DecodedDocument]:
    decoded: list[_DecodedDocument] = []
    for document in documents:
        if document.mime_type not in ALLOWED_MIME_TYPES:
            raise DomainValidation("documents", "invalid_mime")
        try:
            content = base64.b64decode(document.content_base64, validate=True)
        except Exception as exc:
            raise DomainValidation("documents", "invalid_document") from exc
        detected = _require_media(content, document.mime_type, max_bytes)
        decoded.append(
            _DecodedDocument(
                document_type=document.document_type,
                mime_type=detected,
                content=content,
            )
        )
    return decoded


def _load_cpts(session: Session, requested: list[str]) -> list[CptCode]:
    if not requested:
        raise InvalidReference("cpt_codes")
    rows = list(session.scalars(select(CptCode).where(CptCode.code.in_(requested))))
    by_code = {row.code: row for row in rows}
    if any(code not in by_code for code in requested):
        raise InvalidReference("cpt_codes")
    return [by_code[code] for code in requested]


def _load_icds(session: Session, requested: list[str]) -> list[Icd10Code]:
    if not requested:
        raise InvalidReference("icd10_codes")
    rows = list(session.scalars(select(Icd10Code).where(Icd10Code.code.in_(requested))))
    by_code = {row.code: row for row in rows}
    if any(code not in by_code for code in requested):
        raise InvalidReference("icd10_codes")
    return [by_code[code] for code in requested]


def _provider_in_network(session: Session, provider_id: int, payer_id: int) -> bool:
    value = session.scalar(
        select(ProviderNetwork.in_network).where(
            ProviderNetwork.provider_id == provider_id,
            ProviderNetwork.payer_id == payer_id,
        )
    )
    return bool(value)


def _eligibility_current(verified: date | None, as_of: date, max_age_days: int) -> bool:
    if verified is None or verified > as_of:
        return False
    return (as_of - verified).days <= max_age_days


def _claim_by_key(session: Session, key: str) -> Claim | None:
    return session.scalar(select(Claim).where(Claim.idempotency_key == key))


def _human_target(decision: str) -> tuple[ClaimStatus, ClaimOutcome, str]:
    if decision == "approved":
        return ClaimStatus.approved, ClaimOutcome.human_approved, "human_approved"
    if decision == "denied":
        return ClaimStatus.denied, ClaimOutcome.human_denied, "human_denied"
    if decision == "pended_docs":
        return ClaimStatus.pended_docs, ClaimOutcome.pending, "human_pended_docs"
    raise DomainValidation("decision", "invalid_decision")


def _human_amounts(claim: Claim, decision: HumanDecision) -> tuple[Decimal, str | None]:
    if decision.decision == "approved":
        amount = (
            claim.requested_amount
            if decision.approved_amount is None
            else decision.approved_amount.quantize(MONEY)
        )
        if amount <= 0 or amount > claim.requested_amount:
            raise DomainValidation("approved_amount", "exceeds_requested_amount")
        return amount, None
    return Decimal("0.00"), None


def withdraw_claim(
    session: Session,
    claim_id: int,
    *,
    provider_id: int,
    settings: Settings,
    correlation_id: str,
) -> Claim:
    try:
        claim = session.get(Claim, claim_id, with_for_update=True)
        if claim is None:
            raise ClaimNotFound()
        actor = f"provider:{provider_id}"
        if provider_id != claim.provider_id:
            _reject_transition(
                session,
                claim,
                ClaimStatus.withdrawn,
                actor=actor,
                settings=settings,
                correlation_id=correlation_id,
            )
            raise IllegalTransition(claim.status.value, ClaimStatus.withdrawn.value)
        try:
            assert_transition(claim.status, ClaimStatus.withdrawn)
        except IllegalTransition:
            _reject_transition(
                session,
                claim,
                ClaimStatus.withdrawn,
                actor=actor,
                settings=settings,
                correlation_id=correlation_id,
            )
            raise
        previous = claim.status
        claim.status = ClaimStatus.withdrawn
        claim.outcome = ClaimOutcome.withdrawn
        claim.automation_flag = False
        claim.approved_amount = Decimal("0.00")
        claim.decided_at = _utcnow()
        claim.version += 1
        claim.reason_codes = codes.bundle_reason_codes(
            rule_failures=[],
            rule_passes=[],
            scorer=[],
            router=["WITHDRAWN"],
        )
        _audit(
            session,
            claim=claim,
            actor=actor,
            action="withdrawn",
            from_status=previous,
            to_status=ClaimStatus.withdrawn,
            reason_codes=claim.reason_codes,
            settings=settings,
            model_version=claim.model_version,
            correlation_id=correlation_id,
            rules_version=claim.rules_version or settings.rules_version,
            threshold_version=claim.threshold_version or settings.threshold_version,
        )
        session.commit()
    except (ClaimNotFound, IllegalTransition):
        raise
    except Exception:
        session.rollback()
        raise
    return claim


def _idempotency_replay(session: Session, key: str, digest: str) -> Claim | None:
    row = session.get(IdempotencyKey, key)
    if row is None:
        return None
    if row.status == IdempotencyState.in_progress:
        raise RequestInProgress()
    if row.request_hash != digest:
        raise IdempotencyConflict()
    claim = session.get(Claim, row.claim_id) if row.claim_id is not None else None
    if claim is None:
        raise RequestInProgress()
    return claim


def _claim_idempotency(session: Session, key: str, digest: str) -> Claim | None:
    session.add(
        IdempotencyKey(
            key=key,
            request_hash=digest,
            status=IdempotencyState.in_progress,
        )
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return _idempotency_replay(session, key, digest)
    return None


def _release_idempotency(session: Session, key: str) -> None:
    row = session.get(IdempotencyKey, key)
    if row is None or row.status != IdempotencyState.in_progress:
        return
    session.delete(row)
    session.commit()


def _cpt_facts(session: Session, requested: list[str]) -> list[CptFact]:
    rows = list(session.scalars(select(CptCode).where(CptCode.code.in_(requested))))
    by_code = {row.code: row for row in rows}
    facts: list[CptFact] = []
    for code in requested:
        row = by_code.get(code)
        covered = bool(row is not None and row.active and row.covered)
        facts.append(
            CptFact(
                code=code,
                active=bool(row.active) if row is not None else False,
                covered=covered,
            )
        )
    return facts


def _reviewer_from_token(session: Session, token: str) -> Reviewer:
    reviewer = session.get(Reviewer, int(token)) if token.isdigit() else None
    if reviewer is None:
        reviewer = session.scalar(select(Reviewer).where(Reviewer.external_id == token))
    if reviewer is None or not reviewer.active:
        raise InvalidReference("reviewer")
    return reviewer


def _require_media(content: bytes, declared: str, max_bytes: int) -> str:
    if not content or len(content) > max_bytes:
        raise PayloadTooLarge()
    detected = _sniff_media(content)
    if detected is None:
        raise UnsupportedMedia()
    if declared and declared not in {"application/octet-stream"} and declared != detected:
        raise UnsupportedMedia()
    return detected


def _sniff_media(content: bytes) -> str | None:
    if content.startswith(b"%PDF"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    return None


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


def default_engine(settings: Settings) -> RulesEngine:
    return build_rules_engine(settings)
