"""Scorer contract. The router depends on this module and not on an implementation.

``score`` must not raise for an expected model failure. The guard still converts
unexpected exceptions and timeouts into a ``ScoreResult`` so callers never see them.
Features are de-identified: codes, specialty, document types, priority, amount, and
two booleans. Do not add names, addresses, contact details, member ids, or free text.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class ScoringFeatures:
    cpt_codes: tuple[str, ...]
    icd10_codes: tuple[str, ...]
    provider_specialty: str
    document_types: tuple[str, ...]
    priority: str
    requested_amount: Decimal
    eligibility_current: bool
    provider_in_network: bool


@dataclass(frozen=True)
class ScoreError:
    kind: str
    code: str


@dataclass(frozen=True)
class ScoreResult:
    score: Decimal | None
    model_version: str
    explanations: tuple[str, ...]
    error: ScoreError | None = None


class MedicalNecessityScorer(Protocol):
    model_version: str

    def score(self, features: ScoringFeatures) -> ScoreResult:
        """Return a typed result. Do not raise for model failure, NaN, or timeout."""
