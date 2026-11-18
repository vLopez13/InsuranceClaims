"""Seed synthetic reference data.

The patient rows and the original seven providers are the legacy SQL files
(patienttable.sql, queryproviders.sql), which inserted into tables that were
never created. Providers 100, 108, 111, and 121 were referenced as primary-care
physicians but were missing from queryproviders.sql; they are added here so the
foreign keys hold. Addresses and emails are the original synthetic samples.

Historical claims are illustrative records, not PHI and not recomputed scores.

Revision ID: d5a9e31c4b20
Revises: c41282e6b1c6
Create Date: 2026-11-18 01:30:00.000000

"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from decimal import Decimal
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5a9e31c4b20"
down_revision: Union[str, Sequence[str], None] = "c41282e6b1c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CREATED = datetime(2026, 1, 15, 12, 0, 0)
_AUDIT_INSERT = """
CREATE TRIGGER claim_audit_log_no_update
BEFORE UPDATE ON claim_audit_log
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'claim_audit_log is append-only';
END
"""
_AUDIT_DELETE = """
CREATE TRIGGER claim_audit_log_no_delete
BEFORE DELETE ON claim_audit_log
FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'claim_audit_log is append-only';
END
"""


def _digest(text: str) -> tuple[str, int]:
    raw = text.encode()
    return hashlib.sha256(raw).hexdigest(), len(raw)


def _reasons(
    failures: list[str],
    passes: list[str],
    scorer: list[str],
    router: list[str],
) -> dict[str, list[str]]:
    return {
        "rule_failures": failures,
        "rule_passes": passes,
        "scorer": scorer,
        "router": router,
    }


def upgrade() -> None:
    """Insert synthetic payers, providers, patients, codes, and sample claims."""

    payers = sa.table(
        "payers",
        sa.column("id", sa.Integer),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    op.bulk_insert(
        payers,
        [
            {"id": 1, "code": "PYR-NORTHWIND", "name": "Northwind Health Plan", "created_at": _CREATED},
            {"id": 2, "code": "PYR-CONTOSO", "name": "Contoso Insurance", "created_at": _CREATED},
            {"id": 3, "code": "PYR-FABRIKAM", "name": "Fabrikam Benefits", "created_at": _CREATED},
        ],
    )

    providers = sa.table(
        "providers",
        sa.column("id", sa.Integer),
        sa.column("npi", sa.String),
        sa.column("practice_name", sa.String),
        sa.column("specialty", sa.String),
        sa.column("tax_id", sa.String),
        sa.column("active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
    )
    # ids 101-107 are queryproviders.sql. 100, 108, 111, and 121 repair the patient file.
    op.bulk_insert(
        providers,
        [
            _provider(100, "0000000001", "Northwind Family Practice", "Internal Medicine", "00-0000100"),
            _provider(101, "0000000002", "Contoso Heart Clinic", "Cardiology", "00-0000101"),
            _provider(102, "0000000003", "Fabrikam Spine Group", "Neurosurgery", "00-0000102"),
            _provider(103, "0000000004", "Adventure Works Neurosurgery", "Neurosurgery", "00-0000103"),
            _provider(104, "0000000005", "Wide World Oncology", "Oncology", "00-0000104"),
            _provider(105, "0000000007", "Litware Oncology", "Oncology", "00-0000105"),
            _provider(106, "0000000008", "Alpine Cardiology", "Cardiology", "00-0000106"),
            _provider(107, "0000000009", "Woodgrove Orthopedics", "Orthopedic", "00-0000107"),
            _provider(108, "0000000010", "Coho Family Medicine", "Family Medicine", "00-0000108"),
            _provider(111, "0000000011", "Tailspin Internal Medicine", "Internal Medicine", "00-0000111"),
            _provider(121, "0000000012", "Graphic Design Primary Care", "Family Medicine", "00-0000121"),
        ],
    )

    reviewers = sa.table(
        "reviewers",
        sa.column("id", sa.Integer),
        sa.column("external_id", sa.String),
        sa.column("active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
    )
    op.bulk_insert(
        reviewers,
        [
            {"id": 1, "external_id": "rev-001", "active": True, "created_at": _CREATED},
            {"id": 2, "external_id": "rev-002", "active": True, "created_at": _CREATED},
        ],
    )

    cpt_codes = sa.table(
        "cpt_codes",
        sa.column("code", sa.String),
        sa.column("description", sa.String),
        sa.column("active", sa.Boolean),
        sa.column("covered", sa.Boolean),
    )
    op.bulk_insert(
        cpt_codes,
        [
            {"code": "27447", "description": "Total knee arthroplasty", "active": True, "covered": True},
            {"code": "27130", "description": "Total hip arthroplasty", "active": True, "covered": True},
            {"code": "29881", "description": "Knee arthroscopy with meniscectomy", "active": True, "covered": True},
            {"code": "63030", "description": "Lumbar laminotomy", "active": True, "covered": True},
            {"code": "33533", "description": "Coronary artery bypass, arterial", "active": True, "covered": True},
            {"code": "43239", "description": "Upper GI endoscopy with biopsy", "active": True, "covered": True},
            {"code": "45378", "description": "Diagnostic colonoscopy", "active": True, "covered": True},
            {"code": "66984", "description": "Cataract extraction with intraocular lens", "active": True, "covered": True},
            {"code": "47562", "description": "Laparoscopic cholecystectomy", "active": True, "covered": True},
            {"code": "19120", "description": "Excision of breast lesion", "active": True, "covered": True},
            {"code": "99999", "description": "Synthetic non-covered procedure", "active": True, "covered": False},
        ],
    )

    icd10_codes = sa.table(
        "icd10_codes",
        sa.column("code", sa.String),
        sa.column("description", sa.String),
        sa.column("billable", sa.Boolean),
    )
    op.bulk_insert(
        icd10_codes,
        [
            {"code": "M17.11", "description": "Unilateral primary osteoarthritis, right knee", "billable": True},
            {"code": "M16.11", "description": "Unilateral primary osteoarthritis, right hip", "billable": True},
            {"code": "M51.16", "description": "Intervertebral disc degeneration, lumbar region", "billable": True},
            {"code": "I25.10", "description": "Atherosclerotic heart disease of native coronary artery", "billable": True},
            {"code": "K21.0", "description": "Gastro-esophageal reflux disease with esophagitis", "billable": True},
            {"code": "K80.20", "description": "Calculus of gallbladder without cholecystitis", "billable": True},
            {"code": "H25.11", "description": "Age-related nuclear cataract, right eye", "billable": True},
            {"code": "C50.911", "description": "Malignant neoplasm of unspecified site of right female breast", "billable": True},
            {"code": "S72.001A", "description": "Fracture of unspecified part of neck of right femur, initial", "billable": True},
            {"code": "M1A.0710", "description": "Idiopathic chronic gout, right ankle and foot, without tophus", "billable": True},
            {"code": "Z99.89", "description": "Synthetic non-billable code", "billable": False},
        ],
    )

    networks = sa.table(
        "provider_networks",
        sa.column("provider_id", sa.Integer),
        sa.column("payer_id", sa.Integer),
        sa.column("in_network", sa.Boolean),
    )
    provider_ids = [100, 101, 102, 103, 104, 105, 106, 107, 108, 111, 121]
    op.bulk_insert(
        networks,
        [
            {"provider_id": provider_id, "payer_id": payer_id, "in_network": True}
            for provider_id in provider_ids
            for payer_id in (1, 2, 3)
        ],
    )

    patients = sa.table(
        "patients",
        sa.column("id", sa.Integer),
        sa.column("address", sa.String),
        sa.column("email_address", sa.String),
        sa.column("eligibility_verified_date", sa.Date),
        sa.column("primary_care_physician_id", sa.Integer),
        sa.column("created_at", sa.DateTime),
    )
    op.bulk_insert(
        patients,
        [
            _patient(1, "1 Example Street, Fictional City, FS 00001", "patient01@example.com", date(2024, 5, 21), 102),
            _patient(2, "2 Example Street, Fictional City, FS 00002", "patient02@example.com", date(2024, 1, 15), 101),
            _patient(3, "3 Example Street, Fictional City, FS 00003", "patient03@example.com", date(2023, 11, 1), 105),
            _patient(4, "4 Example Street, Fictional City, FS 00004", "patient04@example.com", date(2024, 6, 3), 108),
            _patient(5, "5 Example Street, Fictional City, FS 00005", "patient05@example.com", date(2024, 4, 10), 103),
            _patient(6, "6 Example Street, Fictional City, FS 00006", "patient06@example.com", date(2023, 10, 25), 107),
            _patient(7, "7 Example Street, Fictional City, FS 00007", "patient07@example.com", date(2024, 2, 29), 106),
            _patient(8, "8 Example Street, Fictional City, FS 00008", "patient08@example.com", date(2024, 5, 14), 100),
            _patient(9, "9 Example Street, Fictional City, FS 00009", "patient09@example.com", date(2023, 12, 5), 111),
            _patient(10, "10 Example Street, Fictional City, FS 00010", "patient10@example.com", date(2024, 3, 19), 121),
        ],
    )

    submitted_passes = [
        "ELIGIBILITY_CURRENT",
        "PROVIDER_IN_NETWORK",
        "DOCUMENTS_PRESENT",
        "CODES_VALID",
    ]
    claims = sa.table(
        "claims",
        sa.column("id", sa.Integer),
        sa.column("idempotency_key", sa.String),
        sa.column("request_hash", sa.String),
        sa.column("patient_id", sa.Integer),
        sa.column("provider_id", sa.Integer),
        sa.column("payer_id", sa.Integer),
        sa.column("reviewer_id", sa.Integer),
        sa.column("status", sa.String),
        sa.column("outcome", sa.String),
        sa.column("priority", sa.String),
        sa.column("requested_amount", sa.Numeric),
        sa.column("approved_amount", sa.Numeric),
        sa.column("rejection_code", sa.String),
        sa.column("automation_flag", sa.Boolean),
        sa.column("necessity_score", sa.Numeric),
        sa.column("model_version", sa.String),
        sa.column("rules_version", sa.String),
        sa.column("threshold_version", sa.String),
        sa.column("reason_codes", sa.JSON),
        sa.column("correlation_id", sa.String),
        sa.column("submitted_at", sa.DateTime),
        sa.column("routed_at", sa.DateTime),
        sa.column("decided_at", sa.DateTime),
        sa.column("version", sa.Integer),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    passes_with_amount = [*submitted_passes, "AMOUNT_WITHIN_LIMIT"]
    claim_rows = [
        _claim(
            1,
            patient_id=1,
            provider_id=107,
            payer_id=1,
            status="approved",
            outcome="auto_approved",
            priority="Normal",
            requested="18500.00",
            approved="18500.00",
            rejection=None,
            automated=True,
            score="0.9500",
            reasons=_reasons([], passes_with_amount, ["SPECIALTY_MATCH", "SCORE_MEETS_THRESHOLD"], ["ROUTE_AUTO_APPROVE"]),
            submitted=datetime(2026, 10, 1, 14, 0, 0),
            routed=datetime(2026, 10, 1, 14, 0, 2),
            decided=datetime(2026, 10, 1, 14, 12, 0),
        ),
        _claim(
            2,
            patient_id=2,
            provider_id=102,
            payer_id=1,
            status="in_triage",
            outcome="pending",
            priority="Urgent",
            requested="42000.00",
            approved="0.00",
            rejection=None,
            automated=False,
            score="0.6200",
            reasons=_reasons([], passes_with_amount, ["SCORE_BELOW_THRESHOLD"], ["ROUTE_TRIAGE"]),
            submitted=datetime(2026, 11, 1, 9, 0, 0),
            routed=datetime(2026, 11, 1, 9, 0, 1),
            decided=None,
        ),
        _claim(
            3,
            patient_id=3,
            provider_id=105,
            payer_id=2,
            status="in_triage",
            outcome="pending",
            priority="Stat",
            requested="15000.00",
            approved="0.00",
            rejection=None,
            automated=False,
            score="0.9000",
            reasons=_reasons(
                ["ELIGIBILITY_EXPIRED"],
                ["PROVIDER_IN_NETWORK", "DOCUMENTS_PRESENT", "CODES_VALID", "AMOUNT_WITHIN_LIMIT"],
                ["SCORE_MEETS_THRESHOLD"],
                ["ROUTE_TRIAGE"],
            ),
            submitted=datetime(2026, 9, 15, 8, 0, 0),
            routed=datetime(2026, 9, 15, 8, 0, 1),
            decided=None,
        ),
        _claim(
            4,
            patient_id=5,
            provider_id=103,
            payer_id=1,
            status="pended_docs",
            outcome="pending",
            priority="Normal",
            requested="9000.00",
            approved="0.00",
            rejection=None,
            automated=False,
            score="0.8000",
            reasons=_reasons(
                ["DOCUMENT_LMN_MISSING"],
                ["ELIGIBILITY_CURRENT", "PROVIDER_IN_NETWORK", "CODES_VALID", "AMOUNT_WITHIN_LIMIT"],
                ["SCORE_MEETS_THRESHOLD"],
                ["ROUTE_PEND_DOCS"],
            ),
            submitted=datetime(2026, 11, 10, 11, 0, 0),
            routed=datetime(2026, 11, 10, 11, 0, 1),
            decided=None,
        ),
    ]
    op.bulk_insert(claims, claim_rows)

    procedures = sa.table(
        "claim_procedures",
        sa.column("claim_id", sa.Integer),
        sa.column("cpt_code", sa.String),
        sa.column("sequence", sa.Integer),
    )
    op.bulk_insert(
        procedures,
        [
            {"claim_id": 1, "cpt_code": "27447", "sequence": 1},
            {"claim_id": 2, "cpt_code": "63030", "sequence": 1},
            {"claim_id": 3, "cpt_code": "19120", "sequence": 1},
            {"claim_id": 4, "cpt_code": "33533", "sequence": 1},
        ],
    )
    diagnoses = sa.table(
        "claim_diagnoses",
        sa.column("claim_id", sa.Integer),
        sa.column("icd10_code", sa.String),
        sa.column("sequence", sa.Integer),
        sa.column("is_primary", sa.Boolean),
    )
    op.bulk_insert(
        diagnoses,
        [
            {"claim_id": 1, "icd10_code": "M17.11", "sequence": 1, "is_primary": True},
            {"claim_id": 2, "icd10_code": "M51.16", "sequence": 1, "is_primary": True},
            {"claim_id": 3, "icd10_code": "C50.911", "sequence": 1, "is_primary": True},
            {"claim_id": 4, "icd10_code": "I25.10", "sequence": 1, "is_primary": True},
        ],
    )

    documents = sa.table(
        "claim_documents",
        sa.column("claim_id", sa.Integer),
        sa.column("document_type", sa.String),
        sa.column("file_reference", sa.String),
        sa.column("content_sha256", sa.String),
        sa.column("mime_type", sa.String),
        sa.column("byte_size", sa.Integer),
        sa.column("created_at", sa.DateTime),
    )
    document_rows = []
    specs = [
        (1, "letter_of_medical_necessity", "synthetic letter of medical necessity 1"),
        (1, "clinical_notes", "synthetic clinical notes 1"),
        (2, "letter_of_medical_necessity", "synthetic letter of medical necessity 2"),
        (2, "clinical_notes", "synthetic clinical notes 2"),
        (3, "letter_of_medical_necessity", "synthetic letter of medical necessity 3"),
        (3, "clinical_notes", "synthetic clinical notes 3"),
        (4, "clinical_notes", "synthetic clinical notes 4"),
    ]
    for claim_id, document_type, body in specs:
        digest, size = _digest(body)
        token = f"seed{claim_id}{document_type[:4]}"
        document_rows.append(
            {
                "claim_id": claim_id,
                "document_type": document_type,
                "file_reference": f"docstore://claims/{claim_id}/{token}",
                "content_sha256": digest,
                "mime_type": "text/plain",
                "byte_size": size,
                "created_at": _CREATED,
            }
        )
    op.bulk_insert(documents, document_rows)

    audit = sa.table(
        "claim_audit_log",
        sa.column("claim_id", sa.Integer),
        sa.column("actor", sa.String),
        sa.column("action", sa.String),
        sa.column("from_status", sa.String),
        sa.column("to_status", sa.String),
        sa.column("rules_version", sa.String),
        sa.column("model_version", sa.String),
        sa.column("threshold_version", sa.String),
        sa.column("reason_codes", sa.JSON),
        sa.column("correlation_id", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    audit_rows = []
    for row in claim_rows:
        submitted_at = row["submitted_at"]
        audit_rows.append(
            _audit(
                row["id"],
                "claim_submitted",
                None,
                "submitted",
                _reasons([], [], [], ["CLAIM_SUBMITTED"]),
                submitted_at,
                row["correlation_id"],
            )
        )
        audit_rows.append(
            _audit(
                row["id"],
                _action_for(str(row["status"])),
                "submitted",
                row["status"],
                row["reason_codes"],
                row["decided_at"] or submitted_at,
                row["correlation_id"],
            )
        )
    op.bulk_insert(audit, audit_rows)

    outbox = sa.table(
        "integration_outbox",
        sa.column("claim_id", sa.Integer),
        sa.column("event_type", sa.String),
        sa.column("payload", sa.JSON),
        sa.column("status", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    op.bulk_insert(
        outbox,
        [
            {
                "claim_id": 2,
                "event_type": "human_review_required",
                "payload": {
                    "claim_id": 2,
                    "priority": "urgent",
                    "reason_codes": claim_rows[1]["reason_codes"],
                    "correlation_id": "seed-claim-0002",
                },
                "status": "pending",
                "created_at": datetime(2026, 11, 1, 9, 0, 1),
            }
        ],
    )


def downgrade() -> None:
    """Remove seed rows. Triggers are dropped only long enough to delete the audit log."""

    op.execute("DROP TRIGGER IF EXISTS claim_audit_log_no_update")
    op.execute("DROP TRIGGER IF EXISTS claim_audit_log_no_delete")
    for table in (
        "integration_outbox",
        "claim_audit_log",
        "claim_documents",
        "claim_diagnoses",
        "claim_procedures",
        "claims",
        "patients",
        "provider_networks",
        "reviewers",
        "cpt_codes",
        "icd10_codes",
        "providers",
        "payers",
    ):
        op.execute(f"DELETE FROM {table}")
    op.execute(_AUDIT_INSERT)
    op.execute(_AUDIT_DELETE)


def _provider(
    provider_id: int,
    npi: str,
    practice_name: str,
    specialty: str,
    tax_id: str,
) -> dict[str, object]:
    return {
        "id": provider_id,
        "npi": npi,
        "practice_name": practice_name,
        "specialty": specialty,
        "tax_id": tax_id,
        "active": True,
        "created_at": _CREATED,
    }


def _patient(
    patient_id: int,
    address: str,
    email_address: str,
    eligibility: date,
    physician_id: int,
) -> dict[str, object]:
    return {
        "id": patient_id,
        "address": address,
        "email_address": email_address,
        "eligibility_verified_date": eligibility,
        "primary_care_physician_id": physician_id,
        "created_at": _CREATED,
    }


def _claim(
    claim_id: int,
    *,
    patient_id: int,
    provider_id: int,
    payer_id: int,
    status: str,
    outcome: str,
    priority: str,
    requested: str,
    approved: str,
    rejection: str | None,
    automated: bool,
    score: str,
    reasons: dict[str, list[str]],
    submitted: datetime,
    routed: datetime,
    decided: datetime | None,
) -> dict[str, object]:
    key = f"seed-claim-{claim_id:04d}"
    return {
        "id": claim_id,
        "idempotency_key": key,
        "request_hash": hashlib.sha256(key.encode()).hexdigest(),
        "patient_id": patient_id,
        "provider_id": provider_id,
        "payer_id": payer_id,
        "reviewer_id": None,
        "status": status,
        "outcome": outcome,
        "priority": priority,
        "requested_amount": Decimal(requested),
        "approved_amount": Decimal(approved),
        "rejection_code": rejection,
        "automation_flag": automated,
        "necessity_score": Decimal(score),
        "model_version": "heuristic-v1",
        "rules_version": "rules-v1",
        "threshold_version": "thresholds-v1",
        "reason_codes": reasons,
        "correlation_id": key,
        "submitted_at": submitted,
        "routed_at": routed,
        "decided_at": decided,
        "version": 2,
        "created_at": submitted,
        "updated_at": decided or routed,
    }


def _audit(
    claim_id: int,
    action: str,
    from_status: str | None,
    to_status: str,
    reasons: dict[str, list[str]],
    created_at: datetime,
    correlation_id: str,
) -> dict[str, object]:
    return {
        "claim_id": claim_id,
        "actor": "system",
        "action": action,
        "from_status": from_status,
        "to_status": to_status,
        "rules_version": "rules-v1",
        "model_version": "heuristic-v1",
        "threshold_version": "thresholds-v1",
        "reason_codes": reasons,
        "correlation_id": correlation_id,
        "created_at": created_at,
    }


def _action_for(status: str) -> str:
    return {
        "approved": "auto_approved",
        "in_triage": "route_triage",
        "pended_docs": "pended_docs",
    }[status]
