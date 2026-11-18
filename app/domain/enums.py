"""Constrained status, outcome, and document values."""

from __future__ import annotations

import enum


class ClaimStatus(enum.StrEnum):
    submitted = "submitted"
    pended_docs = "pended_docs"
    in_triage = "in_triage"
    approved = "approved"
    denied = "denied"
    withdrawn = "withdrawn"


class ClaimOutcome(enum.StrEnum):
    pending = "pending"
    auto_approved = "auto_approved"
    human_approved = "human_approved"
    human_denied = "human_denied"
    withdrawn = "withdrawn"


class ClaimPriority(enum.StrEnum):
    """Provider-supplied urgency. Stat is reviewed before Urgent, then Normal."""

    normal = "Normal"
    urgent = "Urgent"
    stat = "Stat"


class DocumentType(enum.StrEnum):
    letter_of_medical_necessity = "letter_of_medical_necessity"
    clinical_notes = "clinical_notes"
    other = "other"


class OutboxStatus(enum.StrEnum):
    pending = "pending"
    dispatched = "dispatched"


class IdempotencyState(enum.StrEnum):
    in_progress = "in_progress"
    complete = "complete"


FINAL_STATUSES = frozenset(
    {
        ClaimStatus.approved,
        ClaimStatus.denied,
        ClaimStatus.withdrawn,
    }
)
