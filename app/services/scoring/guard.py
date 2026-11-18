"""Turn scorer failures into typed results. This function does not raise."""

from __future__ import annotations

import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from app.domain import codes
from app.domain.money import quantize_score
from app.services.scoring.base import (
    MedicalNecessityScorer,
    ScoreError,
    ScoreResult,
    ScoringFeatures,
)

_EXPLANATION = re.compile(codes.REASON_CODE_PATTERN)
_VERSION = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def _version_of(scorer: object) -> str:
    version = getattr(scorer, "model_version", "unknown")
    if isinstance(version, str) and _VERSION.fullmatch(version):
        return version
    return "unknown"


def _safe_explanations(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(
        value for value in values if isinstance(value, str) and _EXPLANATION.fullmatch(value)
    )


def _failure(scorer: object, kind: str, code: str) -> ScoreResult:
    return ScoreResult(
        score=None,
        model_version=_version_of(scorer),
        explanations=(),
        error=ScoreError(kind=kind, code=code),
    )


def _normalize(result: ScoreResult, scorer: object) -> ScoreResult:
    version = (
        result.model_version
        if _VERSION.fullmatch(result.model_version or "")
        else _version_of(scorer)
    )
    explanations = _safe_explanations(result.explanations)
    if result.error is not None:
        return ScoreResult(
            score=None,
            model_version=version,
            explanations=explanations,
            error=result.error,
        )
    score = result.score
    if isinstance(score, bool) or score is None or isinstance(score, str):
        code = codes.SCORE_MISSING if score is None else codes.SCORE_INVALID
        kind = "missing" if score is None else "invalid"
        return _failure(scorer, kind, code)
    if isinstance(score, float):
        if math.isnan(score) or math.isinf(score):
            return _failure(scorer, "nan", codes.SCORE_NAN)
        try:
            score = Decimal(str(score))
        except Exception:
            return _failure(scorer, "invalid", codes.SCORE_INVALID)
    elif isinstance(score, int):
        score = Decimal(score)
    elif not isinstance(score, Decimal):
        return _failure(scorer, "invalid", codes.SCORE_INVALID)
    if score.is_nan():
        return _failure(scorer, "nan", codes.SCORE_NAN)
    if score.is_infinite():
        return _failure(scorer, "invalid", codes.SCORE_INVALID)
    try:
        quantized = quantize_score(score)
    except Exception:
        return _failure(scorer, "invalid", codes.SCORE_INVALID)
    if quantized < 0 or quantized > 1:
        return _failure(scorer, "invalid", codes.SCORE_INVALID)
    return ScoreResult(
        score=quantized,
        model_version=version,
        explanations=explanations,
        error=None,
    )


def _invoke(scorer: MedicalNecessityScorer, features: ScoringFeatures) -> ScoreResult:
    try:
        result = scorer.score(features)
    except Exception:
        return _failure(scorer, "exception", codes.SCORE_ERROR)
    try:
        return _normalize(result, scorer)
    except Exception:
        return _failure(scorer, "exception", codes.SCORE_ERROR)


def score_guarded(
    scorer: MedicalNecessityScorer,
    features: ScoringFeatures,
    timeout_seconds: float,
) -> ScoreResult:
    """Call ``scorer.score`` and convert timeout, NaN, and exceptions into ``ScoreResult``."""

    if (
        not isinstance(timeout_seconds, (int, float))
        or isinstance(timeout_seconds, bool)
        or math.isnan(timeout_seconds)
        or timeout_seconds <= 0
    ):
        return _failure(scorer, "timeout", codes.SCORE_TIMEOUT)

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="necessity-scorer")
    future = executor.submit(_invoke, scorer, features)
    timed_out = False
    try:
        return future.result(timeout=timeout_seconds)
    except TimeoutError:
        timed_out = True
        logging.getLogger(__name__).info(
            "scorer_result_discarded model_version=%s",
            _version_of(scorer),
        )
        return _failure(scorer, "timeout", codes.SCORE_TIMEOUT)
    except Exception:
        return _failure(scorer, "exception", codes.SCORE_ERROR)
    finally:
        executor.shutdown(wait=not timed_out, cancel_futures=True)
