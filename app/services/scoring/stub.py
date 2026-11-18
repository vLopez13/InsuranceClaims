"""Deterministic scorer used by tests and by ``SCORER_IMPL=stub``."""

from __future__ import annotations

from decimal import Decimal

from app.services.scoring.base import ScoreError, ScoreResult, ScoringFeatures


class DeterministicStubScorer:
    model_version = "stub-v1"

    def __init__(
        self,
        score: Decimal | None = Decimal("0.50"),
        *,
        error: ScoreError | None = None,
        raise_exc: BaseException | None = None,
        sleep_seconds: float = 0,
    ) -> None:
        self._score = score
        self._error = error
        self._raise_exc = raise_exc
        self._sleep_seconds = sleep_seconds

    def score(self, features: ScoringFeatures) -> ScoreResult:
        if self._sleep_seconds:
            import time

            time.sleep(self._sleep_seconds)
        if self._raise_exc is not None:
            raise self._raise_exc
        if self._error is not None:
            return ScoreResult(
                score=None,
                model_version=self.model_version,
                explanations=(),
                error=self._error,
            )
        return ScoreResult(
            score=self._score,
            model_version=self.model_version,
            explanations=("STUB",),
            error=None,
        )
