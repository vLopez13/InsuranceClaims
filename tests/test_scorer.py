"""Score rounding, typed failures, and discarded timeouts."""

import time
from decimal import Decimal

from app.services.scoring.base import ScoreResult, ScoringFeatures
from app.services.scoring.guard import score_guarded
from app.services.scoring.heuristic import HeuristicScorer


def features() -> ScoringFeatures:
    return ScoringFeatures(
        cpt_codes=("27447",),
        icd10_codes=("M17.11",),
        provider_specialty="Orthopedic",
        document_types=("clinical_notes", "letter_of_medical_necessity"),
        priority="Normal",
        requested_amount=Decimal("1000.00"),
        eligibility_current=True,
        provider_in_network=True,
    )


class _Fixed:
    model_version = "fixed-v1"

    def __init__(self, value: object) -> None:
        self._value = value

    def score(self, _features: ScoringFeatures) -> ScoreResult:
        return ScoreResult(
            score=self._value,  # type: ignore[arg-type]
            model_version=self.model_version,
            explanations=("STUB",),
        )


class _Slow:
    model_version = "slow-v1"

    def score(self, _features: ScoringFeatures) -> ScoreResult:
        time.sleep(0.4)
        return ScoreResult(score=Decimal("1"), model_version=self.model_version, explanations=())


def test_rounds_half_up_before_the_boundary() -> None:
    high = score_guarded(_Fixed(Decimal("0.79996")), features(), 1)
    low = score_guarded(_Fixed(Decimal("0.79994")), features(), 1)
    assert high.score == Decimal("0.8000")
    assert low.score == Decimal("0.7999")


def test_accepts_float_and_int_and_rejects_other_types() -> None:
    assert score_guarded(_Fixed(0.8), features(), 1).score == Decimal("0.8000")
    assert score_guarded(_Fixed(1), features(), 1).score == Decimal("1.0000")
    assert score_guarded(_Fixed(True), features(), 1).error is not None
    assert score_guarded(_Fixed("0.80"), features(), 1).error is not None
    assert score_guarded(_Fixed(None), features(), 1).error is not None
    assert score_guarded(_Fixed(Decimal("NaN")), features(), 1).error is not None
    assert score_guarded(_Fixed(Decimal("1.0001")), features(), 1).error is not None


def test_timeout_discards_the_late_score() -> None:
    result = score_guarded(_Slow(), features(), 0.05)
    time.sleep(0.5)
    assert result.score is None
    assert result.error is not None
    assert result.error.code == "SCORE_TIMEOUT"


def test_heuristic_matches_specialty_above_default_threshold() -> None:
    matched = HeuristicScorer().score(features())
    other = HeuristicScorer().score(
        ScoringFeatures(
            cpt_codes=("27447",),
            icd10_codes=("M17.11",),
            provider_specialty="Cardiology",
            document_types=("clinical_notes", "letter_of_medical_necessity"),
            priority="Normal",
            requested_amount=Decimal("1000"),
            eligibility_current=True,
            provider_in_network=True,
        )
    )
    assert matched.score == Decimal("0.9000")
    assert other.score == Decimal("0.7500")
    names = set(ScoringFeatures.__dataclass_fields__)
    assert "email" not in names
    assert "address" not in names
