"""Select a scorer from configuration. The decision router does not import this."""

from __future__ import annotations

from app.config import Settings
from app.services.scoring.base import MedicalNecessityScorer
from app.services.scoring.heuristic import HeuristicScorer
from app.services.scoring.stub import DeterministicStubScorer


def build_scorer(settings: Settings) -> MedicalNecessityScorer:
    if settings.scorer_impl == "stub":
        return DeterministicStubScorer(score=settings.stub_score)
    if settings.scorer_impl == "heuristic":
        return HeuristicScorer()
    raise RuntimeError("unknown scorer")
