"""Enforce rules, then scorer, then router. Nothing else may reorder these calls."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.services.decision.router import Decision, DecisionRouter
from app.services.rules.engine import RuleContext, RulesEngine, RulesEvaluation
from app.services.scoring.base import MedicalNecessityScorer, ScoreResult, ScoringFeatures
from app.services.scoring.guard import score_guarded


@dataclass(frozen=True)
class PipelineResult:
    rules: RulesEvaluation
    score: ScoreResult
    decision: Decision


def run_pipeline(
    *,
    rules_engine: RulesEngine,
    scorer: MedicalNecessityScorer,
    router: DecisionRouter,
    rule_context: RuleContext,
    features: ScoringFeatures,
    requested_amount: Decimal,
    approve_t: Decimal,
    scorer_timeout_seconds: float,
) -> PipelineResult:
    rules_evaluation = rules_engine.evaluate(rule_context)
    score_result = score_guarded(scorer, features, scorer_timeout_seconds)
    decision = router.decide(
        rules=rules_evaluation,
        score=score_result,
        requested_amount=requested_amount,
        approve_t=approve_t,
    )
    return PipelineResult(rules=rules_evaluation, score=score_result, decision=decision)
