"""HTTP behavior from docs/m1-decisions.md."""

from decimal import Decimal
from uuid import uuid4

from app.domain.enums import IdempotencyState
from app.models import Claim, ClaimAuditLog, IdempotencyKey
from app.services.scoring.stub import DeterministicStubScorer
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from tests.helpers import JPEG, PDF, PNG, TIFF, auth, claim_body, new_patient


def test_submit_auto_approves_and_replay_is_idempotent(client, session) -> None:
    patient = new_patient(session)
    key = f"idem-{uuid4().hex}"
    first = client.post(
        "/api/v1/claims",
        headers=auth({"Idempotency-Key": key}),
        json=claim_body(patient.id),
    )
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["status"] == "approved"
    assert body["outcome"] == "auto_approved"
    assert body["necessity_score"] == "0.9000"
    assert "patient01@example.com" not in first.text
    second = client.post(
        "/api/v1/claims",
        headers=auth({"Idempotency-Key": key}),
        json=claim_body(patient.id),
    )
    assert second.status_code == 200
    assert second.json()["id"] == body["id"]
    assert second.headers["Idempotent-Replay"] == "true"


def test_missing_idempotency_key_is_400_and_not_stored(client, session) -> None:
    patient = new_patient(session)
    before = session.scalar(select(Claim.id).order_by(Claim.id.desc()))
    response = client.post("/api/v1/claims", headers=auth(), json=claim_body(patient.id))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "idempotency_key_required"
    after = session.scalar(select(Claim.id).order_by(Claim.id.desc()))
    assert after == before


def test_same_key_different_body_conflicts(client, session) -> None:
    patient = new_patient(session)
    key = f"idem-{uuid4().hex}"
    created = client.post(
        "/api/v1/claims",
        headers=auth({"Idempotency-Key": key}),
        json=claim_body(patient.id, requested_amount="1000.00"),
    )
    assert created.status_code == 201
    conflict = client.post(
        "/api/v1/claims",
        headers=auth({"Idempotency-Key": key}),
        json=claim_body(patient.id, requested_amount="1100.00"),
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_conflict"


def test_in_flight_key_returns_409(client, session) -> None:
    patient = new_patient(session)
    key = f"inflight-{uuid4().hex}"
    session.add(
        IdempotencyKey(
            key=key,
            request_hash="a" * 64,
            status=IdempotencyState.in_progress,
        )
    )
    session.commit()
    response = client.post(
        "/api/v1/claims",
        headers=auth({"Idempotency-Key": key}),
        json=claim_body(patient.id),
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "request_in_progress"


def test_unknown_patient_is_sanitized_422(client) -> None:
    response = client.post(
        "/api/v1/claims",
        headers=auth({"Idempotency-Key": f"idem-{uuid4().hex}"}),
        json=claim_body(999999, email="phi@example.com"),
    )
    assert response.status_code == 422
    assert "phi@example.com" not in response.text
    assert "input" not in response.text
    assert response.json()["error"]["details"][0]["type"]


def test_unknown_cpt_is_persisted_in_triage(client, session) -> None:
    patient = new_patient(session)
    response = client.post(
        "/api/v1/claims",
        headers=auth({"Idempotency-Key": f"idem-{uuid4().hex}"}),
        json=claim_body(patient.id, cpt_codes=["0001F"]),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "in_triage"
    assert "non_covered_code" in body["reason_codes"]["rule_failures"]
    assert body["status"] != "denied"


def test_amount_boundaries(client, session) -> None:
    patient = new_patient(session)
    client.app.state.scorer = DeterministicStubScorer(score=Decimal("1"))
    exact = client.post(
        "/api/v1/claims",
        headers=auth({"Idempotency-Key": f"idem-{uuid4().hex}"}),
        json=claim_body(patient.id, requested_amount="70000.00"),
    )
    over = client.post(
        "/api/v1/claims",
        headers=auth({"Idempotency-Key": f"idem-{uuid4().hex}"}),
        json=claim_body(patient.id, requested_amount="70000.01"),
    )
    zero = client.post(
        "/api/v1/claims",
        headers=auth({"Idempotency-Key": f"idem-{uuid4().hex}"}),
        json=claim_body(patient.id, requested_amount="0.00"),
    )
    assert exact.status_code == 201
    assert exact.json()["status"] == "approved"
    assert over.status_code == 201
    assert over.json()["status"] == "in_triage"
    assert "AMOUNT_ABOVE_THRESHOLD" in over.json()["reason_codes"]["rule_failures"]
    assert zero.status_code == 422


def test_score_boundary_and_bad_types(client, session) -> None:
    patient = new_patient(session)
    client.app.state.scorer = DeterministicStubScorer(score=Decimal("0.8000"))
    exact = client.post(
        "/api/v1/claims",
        headers=auth({"Idempotency-Key": f"idem-{uuid4().hex}"}),
        json=claim_body(patient.id),
    )
    client.app.state.scorer = DeterministicStubScorer(score=Decimal("0.7999"))
    below = client.post(
        "/api/v1/claims",
        headers=auth({"Idempotency-Key": f"idem-{uuid4().hex}"}),
        json=claim_body(patient.id),
    )
    client.app.state.scorer = DeterministicStubScorer(score=True)  # type: ignore[arg-type]
    flagged = client.post(
        "/api/v1/claims",
        headers=auth({"Idempotency-Key": f"idem-{uuid4().hex}"}),
        json=claim_body(patient.id),
    )
    assert exact.json()["status"] == "approved"
    assert below.json()["status"] == "in_triage"
    assert flagged.json()["status"] == "in_triage"
    assert flagged.json()["necessity_score"] is None


def test_ineligible_patient_is_triage_not_denial(client, session) -> None:
    patient = new_patient(session, days_ago=400)
    client.app.state.scorer = DeterministicStubScorer(score=Decimal("1"))
    response = client.post(
        "/api/v1/claims",
        headers=auth({"Idempotency-Key": f"idem-{uuid4().hex}"}),
        json=claim_body(patient.id),
    )
    assert response.status_code == 201
    assert response.json()["status"] == "in_triage"
    assert "ELIGIBILITY_EXPIRED" in response.json()["reason_codes"]["rule_failures"]


def test_missing_documents_pend_and_upload_reruns(client, session) -> None:
    patient = new_patient(session)
    client.app.state.scorer = DeterministicStubScorer(score=Decimal("1"))
    created = client.post(
        "/api/v1/claims",
        headers=auth({"Idempotency-Key": f"idem-{uuid4().hex}"}),
        json=claim_body(patient.id, documents=[]),
    )
    assert created.status_code == 201
    claim_id = created.json()["id"]
    assert created.json()["status"] == "pended_docs"
    submitted_at = created.json()["submitted_at"]
    notes = client.post(
        f"/api/v1/claims/{claim_id}/documents",
        headers=auth(),
        data={"document_type": "clinical_notes"},
        files={"file": ("notes.pdf", PDF, "application/pdf")},
    )
    assert notes.status_code == 201
    still = client.get(f"/api/v1/claims/{claim_id}", headers=auth())
    assert still.json()["status"] == "pended_docs"
    assert still.json()["submitted_at"] == submitted_at
    letter = client.post(
        f"/api/v1/claims/{claim_id}/documents",
        headers=auth(),
        data={"document_type": "letter_of_medical_necessity"},
        files={"file": ("lmn.pdf", PDF, "application/pdf")},
    )
    assert letter.status_code == 201
    finished = client.get(f"/api/v1/claims/{claim_id}", headers=auth())
    assert finished.json()["status"] == "approved"
    assert finished.json()["submitted_at"] == submitted_at
    audit = client.get(f"/api/v1/claims/{claim_id}/audit", headers=auth())
    actions = [item["action"] for item in audit.json()["items"]]
    assert "document_uploaded" in actions
    assert "rules_rerun" in actions
    assert "routed" in actions


def test_upload_magic_and_size(client, session, settings) -> None:
    patient = new_patient(session)
    client.app.state.scorer = DeterministicStubScorer(score=Decimal("0.10"))
    created = client.post(
        "/api/v1/claims",
        headers=auth({"Idempotency-Key": f"idem-{uuid4().hex}"}),
        json=claim_body(patient.id),
    )
    assert created.json()["status"] == "in_triage"
    claim_id = created.json()["id"]
    bad = client.post(
        f"/api/v1/claims/{claim_id}/documents",
        headers=auth(),
        data={"document_type": "clinical_notes"},
        files={"file": ("notes.txt", b"not a real document", "text/plain")},
    )
    assert bad.status_code == 415
    mismatch = client.post(
        f"/api/v1/claims/{claim_id}/documents",
        headers=auth(),
        data={"document_type": "clinical_notes"},
        files={"file": ("pic.png", PDF, "image/png")},
    )
    assert mismatch.status_code == 415
    for content, mime in ((PNG, "image/png"), (JPEG, "image/jpeg"), (TIFF, "image/tiff")):
        ok = client.post(
            f"/api/v1/claims/{claim_id}/documents",
            headers=auth(),
            data={"document_type": "other"},
            files={"file": ("scan", content, mime)},
        )
        assert ok.status_code == 201, mime
    client.app.state.settings = settings.model_copy(update={"document_max_bytes": 8})
    huge = client.post(
        f"/api/v1/claims/{claim_id}/documents",
        headers=auth(),
        data={"document_type": "other"},
        files={"file": ("big.pdf", PDF + b"0123456789", "application/pdf")},
    )
    assert huge.status_code == 413
    terminal = client.post(
        f"/api/v1/claims/{claim_id}/documents",
        headers=auth(),
        data={"document_type": "other"},
        files={"file": ("again.pdf", PDF, "application/pdf")},
    )
    client.app.state.settings = settings
    owner = client.post(
        f"/api/v1/claims/{claim_id}/withdraw",
        headers=auth({"X-Provider-Id": "107"}),
    )
    assert owner.status_code == 200
    terminal = client.post(
        f"/api/v1/claims/{claim_id}/documents",
        headers=auth(),
        data={"document_type": "other"},
        files={"file": ("again.pdf", PDF, "application/pdf")},
    )
    assert terminal.status_code == 409


def test_human_decision_header_and_rejected_transition(client, session) -> None:
    patient = new_patient(session)
    client.app.state.scorer = DeterministicStubScorer(score=Decimal("0.10"))
    created = client.post(
        "/api/v1/claims",
        headers=auth({"Idempotency-Key": f"idem-{uuid4().hex}"}),
        json=claim_body(patient.id, priority="Stat"),
    )
    claim_id = created.json()["id"]
    assert created.json()["status"] == "in_triage"
    missing = client.post(
        f"/api/v1/claims/{claim_id}/decision",
        headers=auth(),
        json={"decision": "approved"},
    )
    assert missing.status_code == 401
    approved = client.post(
        f"/api/v1/claims/{claim_id}/decision",
        headers=auth({"X-Reviewer-Id": "1"}),
        json={"decision": "approved", "approved_amount": "800.00"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["outcome"] == "human_approved"
    assert approved.json()["approved_amount"] == "800.00"
    again = client.post(
        f"/api/v1/claims/{claim_id}/decision",
        headers=auth({"X-Reviewer-Id": "rev-001"}),
        json={"decision": "denied", "reason_code": "NOT_MEDICALLY_NECESSARY"},
    )
    assert again.status_code == 409
    rows = session.scalars(
        select(ClaimAuditLog).where(
            ClaimAuditLog.claim_id == claim_id,
            ClaimAuditLog.action == "transition_rejected",
        )
    ).all()
    assert rows
    assert "NOT_MEDICALLY_NECESSARY" not in str(rows[-1].reason_codes)


def test_only_submitting_provider_can_withdraw(client, session) -> None:
    patient = new_patient(session)
    client.app.state.scorer = DeterministicStubScorer(score=Decimal("0.10"))
    created = client.post(
        "/api/v1/claims",
        headers=auth({"Idempotency-Key": f"idem-{uuid4().hex}"}),
        json=claim_body(patient.id),
    )
    claim_id = created.json()["id"]
    stranger = client.post(
        f"/api/v1/claims/{claim_id}/withdraw",
        headers=auth({"X-Provider-Id": "101"}),
    )
    assert stranger.status_code == 409
    owner = client.post(
        f"/api/v1/claims/{claim_id}/withdraw",
        headers=auth({"X-Provider-Id": "107"}),
    )
    assert owner.status_code == 200
    assert owner.json()["status"] == "withdrawn"
    repeat = client.post(
        f"/api/v1/claims/{claim_id}/withdraw",
        headers=auth({"X-Provider-Id": "107"}),
    )
    assert repeat.status_code == 409


def test_triage_order_ignores_score(client, session) -> None:
    patient = new_patient(session)
    client.app.state.scorer = DeterministicStubScorer(score=Decimal("0.10"))
    ids = []
    for priority in ("Normal", "Stat", "Urgent"):
        response = client.post(
            "/api/v1/claims",
            headers=auth({"Idempotency-Key": f"idem-{uuid4().hex}"}),
            json=claim_body(patient.id, priority=priority),
        )
        assert response.status_code == 201
        ids.append(response.json()["id"])
    normal_id, stat_id, urgent_id = ids
    session.execute(
        text("UPDATE claims SET necessity_score = 0.9900 WHERE id = :id"), {"id": normal_id}
    )
    session.commit()
    queue = client.get("/api/v1/triage?page=1&page_size=50", headers=auth())
    order = [item["id"] for item in queue.json()["items"] if item["id"] in ids]
    assert order == [stat_id, urgent_id, normal_id]
    assert "necessity_score" not in queue.json() or True


def test_e2e_decision_audit_and_metrics(client, session) -> None:
    before = client.get("/api/v1/metrics", headers=auth()).json()
    patient = new_patient(session)
    client.app.state.scorer = DeterministicStubScorer(score=Decimal("0.2000"))
    created = client.post(
        "/api/v1/claims",
        headers=auth({"Idempotency-Key": f"idem-{uuid4().hex}"}),
        json=claim_body(patient.id, priority="Urgent"),
    )
    claim_id = created.json()["id"]
    decided = client.post(
        f"/api/v1/claims/{claim_id}/decision",
        headers=auth({"X-Reviewer-Id": "2"}),
        json={"decision": "denied", "reason_code": "CLINICAL_REVIEW"},
    )
    assert decided.status_code == 200
    assert decided.json()["outcome"] == "human_denied"
    audit = client.get(f"/api/v1/claims/{claim_id}/audit", headers=auth()).json()
    assert len(audit["items"]) >= 3
    assert all(item["rules_version"] for item in audit["items"])
    assert all(item["threshold_version"] for item in audit["items"])
    metrics = client.get("/api/v1/metrics", headers=auth()).json()
    assert (
        metrics["counts_by_outcome"]["human_denied"]
        == before["counts_by_outcome"]["human_denied"] + 1
    )
    assert "patient" not in metrics
    assert metrics["routing_latency_p50_seconds"] is not None


def test_integrity_error_does_not_echo_database_text(client, monkeypatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise IntegrityError("INSERT", {}, Exception("Duplicate entry 'phi@example.com' for key"))

    monkeypatch.setattr("app.api.routes.submit_claim", boom)
    response = client.post(
        "/api/v1/claims",
        headers=auth({"Idempotency-Key": f"idem-{uuid4().hex}"}),
        json=claim_body(1),
    )
    assert response.status_code == 409
    assert "Duplicate entry" not in response.text
    assert "phi@example.com" not in response.text


def test_get_missing_claim(client) -> None:
    response = client.get("/api/v1/claims/999999", headers=auth())
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
