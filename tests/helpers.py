"""Shared builders for API tests."""

from __future__ import annotations

import base64
from datetime import date, timedelta
from uuid import uuid4

from app.models import Patient
from sqlalchemy.orm import Session

PDF = b"%PDF-1.4\n%synthetic\n"
PNG = b"\x89PNG\r\n\x1a\n"
JPEG = b"\xff\xd8\xff\xe0"
TIFF = b"II*\x00"


def auth(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"X-API-Key": "test-api-key"}
    if extra:
        headers.update(extra)
    return headers


def b64(content: bytes) -> str:
    return base64.b64encode(content).decode()


def documents() -> list[dict[str, str]]:
    return [
        {
            "document_type": "letter_of_medical_necessity",
            "mime_type": "application/pdf",
            "content_base64": b64(PDF),
        },
        {
            "document_type": "clinical_notes",
            "mime_type": "application/pdf",
            "content_base64": b64(PDF),
        },
    ]


def new_patient(session: Session, *, days_ago: int = 1, pcp_id: int = 107) -> Patient:
    patient = Patient(
        address="100 Example Street, Fictional City, FS 00000",
        email_address=f"synthetic-{uuid4().hex[:8]}@example.com",
        eligibility_verified_date=date.today() - timedelta(days=days_ago),
        primary_care_physician_id=pcp_id,
    )
    session.add(patient)
    session.commit()
    return patient


def claim_body(patient_id: int, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "patient_id": patient_id,
        "provider_id": 107,
        "payer_id": 1,
        "priority": "Normal",
        "requested_amount": "1000.00",
        "cpt_codes": ["27447"],
        "icd10_codes": ["M17.11"],
        "documents": documents(),
    }
    body.update(overrides)
    return body
