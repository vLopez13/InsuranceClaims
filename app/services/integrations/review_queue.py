"""Handoff for human utilization review.

The Salesforce milestone should drain ``integration_outbox`` and create a Case.
This write happens in the same transaction as the move to ``in_review``, so a
crash cannot approve a claim and forget the queue. The payload is ids and codes.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.orm import Session

from app.domain.enums import OutboxStatus
from app.models import IntegrationOutbox


class UtilizationReviewQueue(Protocol):
    def enqueue(
        self,
        session: Session,
        *,
        claim_id: int,
        priority: str,
        reason_codes: dict[str, list[str]],
        correlation_id: str,
    ) -> None: ...


class OutboxReviewQueue:
    def enqueue(
        self,
        session: Session,
        *,
        claim_id: int,
        priority: str,
        reason_codes: dict[str, list[str]],
        correlation_id: str,
    ) -> None:
        session.add(
            IntegrationOutbox(
                claim_id=claim_id,
                event_type="human_review_required",
                payload={
                    "claim_id": claim_id,
                    "priority": priority,
                    "reason_codes": reason_codes,
                    "correlation_id": correlation_id,
                },
                status=OutboxStatus.pending,
            )
        )
