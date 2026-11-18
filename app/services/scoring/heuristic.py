"""Transparent point model. A trained model can replace this class behind the protocol."""

from __future__ import annotations

from decimal import Decimal

from app.domain.enums import DocumentType
from app.services.scoring.base import ScoreResult, ScoringFeatures

MODEL_VERSION = "heuristic-v1"

# Specialty tokens match the seed vocabulary, including the legacy "Orthopedic" spelling.
_CPT_SPECIALTY: dict[str, str] = {
    "27447": "Orthopedic",
    "27130": "Orthopedic",
    "29881": "Orthopedic",
    "63030": "Neurosurgery",
    "33533": "Cardiology",
    "43239": "Gastroenterology",
    "45378": "Gastroenterology",
    "66984": "Ophthalmology",
    "47562": "General Surgery",
    "19120": "Oncology",
}


def specialty_matches(features: ScoringFeatures) -> bool:
    specialty = features.provider_specialty.strip().casefold()
    for code in features.cpt_codes:
        expected = _CPT_SPECIALTY.get(code)
        if expected is not None and expected.casefold() == specialty:
            return True
    return False


class HeuristicScorer:
    """Deterministic score in ``[0, 1]``.

    Start at 0.40.
    +0.20 when both required document types are present.
    +0.10 when eligibility is current.
    +0.05 when the provider is in network.
    +0.15 when a CPT maps to the provider specialty.
    A complete matching request scores 0.90. The same request without a
    specialty match scores 0.75, which is below the default APPROVE_T of 0.80.
    Amount is not part of the score. HIGH_AMOUNT_T is enforced by the rules.
    """

    model_version = MODEL_VERSION

    def score(self, features: ScoringFeatures) -> ScoreResult:
        score = Decimal("0.40")
        explanations = ["BASE_PRIOR"]
        documents = set(features.document_types)
        required = {
            DocumentType.letter_of_medical_necessity.value,
            DocumentType.clinical_notes.value,
        }
        if required.issubset(documents):
            score += Decimal("0.20")
            explanations.append("DOCS_COMPLETE")
        if features.eligibility_current:
            score += Decimal("0.10")
            explanations.append("ELIGIBILITY_CURRENT")
        if features.provider_in_network:
            score += Decimal("0.05")
            explanations.append("IN_NETWORK")
        if specialty_matches(features):
            score += Decimal("0.15")
            explanations.append("SPECIALTY_MATCH")
        if score < 0:
            score = Decimal("0")
        if score > 1:
            score = Decimal("1")
        return ScoreResult(
            score=score.quantize(Decimal("0.0001")),
            model_version=self.model_version,
            explanations=tuple(explanations),
            error=None,
        )
