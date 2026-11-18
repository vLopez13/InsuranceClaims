"""Prior-authorization HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import (
    get_db,
    get_settings,
    require_api_key,
    require_idempotency_key,
    require_provider_header,
    require_reviewer_header,
)
from app.config import Settings
from app.correlation import current_correlation_id
from app.domain.enums import DocumentType
from app.models import Claim, ClaimAuditLog, ClaimDocument
from app.schemas.api import (
    AuditEntry,
    AuditPage,
    ClaimCreate,
    ClaimPage,
    ClaimResponse,
    DecisionCreate,
    DocumentResponse,
    HealthResponse,
    MetricsResponse,
    OutcomeCounts,
    ReasonCodes,
)
from app.services.claims.service import (
    HumanDecision,
    IncomingDocument,
    NewClaim,
    add_document,
    get_claim,
    list_audit,
    list_triage,
    record_human_decision,
    request_fingerprint,
    resubmit_claim,
    submit_claim,
    withdraw_claim,
)
from app.services.metrics.compute import compute_metrics

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])
health_router = APIRouter()


def _claim_response(claim: Claim) -> ClaimResponse:
    return ClaimResponse(
        id=claim.id,
        patient_id=claim.patient_id,
        provider_id=claim.provider_id,
        payer_id=claim.payer_id,
        status=claim.status,
        outcome=claim.outcome,
        priority=claim.priority,
        requested_amount=claim.requested_amount,
        approved_amount=claim.approved_amount,
        rejection_code=claim.rejection_code,
        automation_flag=claim.automation_flag,
        necessity_score=claim.necessity_score,
        model_version=claim.model_version,
        rules_version=claim.rules_version,
        threshold_version=claim.threshold_version,
        reason_codes=ReasonCodes.model_validate(claim.reason_codes),
        reviewer_id=claim.reviewer_id,
        submitted_at=claim.submitted_at,
        routed_at=claim.routed_at,
        decided_at=claim.decided_at,
        version=claim.version,
        cpt_codes=[
            row.cpt_code for row in sorted(claim.procedures, key=lambda item: item.sequence)
        ],
        icd10_codes=[
            row.icd10_code for row in sorted(claim.diagnoses, key=lambda item: item.sequence)
        ],
        correlation_id=claim.correlation_id,
        notes=claim.decision_notes,
    )


def _audit_entry(row: ClaimAuditLog) -> AuditEntry:
    return AuditEntry(
        id=row.id,
        claim_id=row.claim_id,
        actor=row.actor,
        action=row.action,
        from_status=row.from_status,
        to_status=row.to_status,
        rules_version=row.rules_version,
        model_version=row.model_version,
        threshold_version=row.threshold_version,
        reason_codes=ReasonCodes.model_validate(row.reason_codes),
        correlation_id=row.correlation_id,
        created_at=row.created_at,
    )


def _document_response(row: ClaimDocument) -> DocumentResponse:
    return DocumentResponse(
        id=row.id,
        claim_id=row.claim_id,
        document_type=row.document_type,
        file_reference=row.file_reference,
        content_sha256=row.content_sha256,
        mime_type=row.mime_type,
        byte_size=row.byte_size,
        created_at=row.created_at,
    )


@router.post("/claims", response_model=ClaimResponse, status_code=201)
def create_claim(
    payload: ClaimCreate,
    response: Response,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    idempotency_key: str = Depends(require_idempotency_key),
) -> ClaimResponse:
    draft = NewClaim(
        patient_id=payload.patient_id,
        provider_id=payload.provider_id,
        payer_id=payload.payer_id,
        priority=payload.priority,
        requested_amount=payload.requested_amount,
        cpt_codes=list(payload.cpt_codes),
        icd10_codes=list(payload.icd10_codes),
        documents=[
            IncomingDocument(
                document_type=document.document_type,
                mime_type=document.mime_type,
                content_base64=document.content_base64,
            )
            for document in payload.documents
        ],
        idempotency_key=idempotency_key,
        request_hash=request_fingerprint(payload.model_dump(mode="json")),
    )
    claim, created = submit_claim(
        session,
        draft,
        settings=settings,
        scorer=request.app.state.scorer,
        rules_engine=request.app.state.rules_engine,
        document_store=request.app.state.document_store,
        review_queue=request.app.state.review_queue,
        correlation_id=current_correlation_id(),
    )
    if not created:
        response.status_code = 200
        response.headers["Idempotent-Replay"] = "true"
    return _claim_response(claim)


@router.get("/claims/{claim_id}", response_model=ClaimResponse)
def read_claim(claim_id: int, session: Session = Depends(get_db)) -> ClaimResponse:
    return _claim_response(get_claim(session, claim_id))


@router.get("/triage", response_model=ClaimPage)
def triage_queue(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db),
) -> ClaimPage:
    items, total = list_triage(session, page=page, page_size=page_size)
    return ClaimPage(
        items=[_claim_response(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("/claims/{claim_id}/documents", response_model=DocumentResponse, status_code=201)
async def upload_document(
    claim_id: int,
    request: Request,
    document_type: DocumentType = Form(...),
    file: UploadFile = File(...),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DocumentResponse:
    content = await file.read()
    document = add_document(
        session,
        claim_id,
        document_type=document_type,
        mime_type=file.content_type or "",
        content=content,
        document_store=request.app.state.document_store,
        settings=settings,
        scorer=request.app.state.scorer,
        rules_engine=request.app.state.rules_engine,
        review_queue=request.app.state.review_queue,
        correlation_id=current_correlation_id(),
    )
    return _document_response(document)


@router.post("/claims/{claim_id}/decision", response_model=ClaimResponse)
def decide_claim(
    claim_id: int,
    payload: DecisionCreate,
    reviewer_token: str = Depends(require_reviewer_header),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ClaimResponse:
    claim = record_human_decision(
        session,
        claim_id,
        HumanDecision(
            decision=payload.decision,
            reviewer_token=reviewer_token,
            reason_code=payload.reason_code,
            approved_amount=payload.approved_amount,
            notes=payload.notes,
            expected_version=payload.expected_version,
        ),
        settings=settings,
        correlation_id=current_correlation_id(),
    )
    return _claim_response(claim)


@router.post("/claims/{claim_id}/withdraw", response_model=ClaimResponse)
def withdraw(
    claim_id: int,
    provider_id: int = Depends(require_provider_header),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ClaimResponse:
    claim = withdraw_claim(
        session,
        claim_id,
        provider_id=provider_id,
        settings=settings,
        correlation_id=current_correlation_id(),
    )
    return _claim_response(claim)


@router.post("/claims/{claim_id}/resubmit", response_model=ClaimResponse)
def resubmit(
    claim_id: int,
    request: Request,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ClaimResponse:
    claim = resubmit_claim(
        session,
        claim_id,
        settings=settings,
        scorer=request.app.state.scorer,
        rules_engine=request.app.state.rules_engine,
        review_queue=request.app.state.review_queue,
        correlation_id=current_correlation_id(),
    )
    return _claim_response(claim)


@router.get("/claims/{claim_id}/audit", response_model=AuditPage)
def claim_audit(
    claim_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    session: Session = Depends(get_db),
) -> AuditPage:
    items, total = list_audit(session, claim_id, page=page, page_size=page_size)
    return AuditPage(
        items=[_audit_entry(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/metrics", response_model=MetricsResponse)
def metrics(session: Session = Depends(get_db)) -> MetricsResponse:
    snapshot = compute_metrics(session)
    return MetricsResponse(
        counts_by_outcome=OutcomeCounts.model_validate(snapshot.counts_by_outcome),
        straight_through_rate=snapshot.straight_through_rate,
        automation_rate=snapshot.automation_rate,
        decided_count=snapshot.decided_count,
        average_turnaround_seconds=snapshot.average_turnaround_seconds,
        latency_p50_seconds=snapshot.latency_p50_seconds,
        latency_p95_seconds=snapshot.latency_p95_seconds,
        average_routing_seconds=snapshot.average_routing_seconds,
        routing_latency_p50_seconds=snapshot.routing_latency_p50_seconds,
        routing_latency_p95_seconds=snapshot.routing_latency_p95_seconds,
        target_turnaround_seconds=snapshot.target_turnaround_seconds,
    )


@health_router.get("/health")
def health(request: Request) -> JSONResponse:
    session = request.app.state.session_factory()
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    finally:
        session.close()
    return JSONResponse(content=HealthResponse(status="ok").model_dump())
