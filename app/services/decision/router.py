"""Route a claim after rules and scoring. This module does not call either tier.

The router never auto-denies. A triage-severity rule failure, a score below
APPROVE_T, or a scorer failure all go to human triage. Missing documents pend.
A requested amount above HIGH_AMOUNT_T is a triage-severity rule, so it cannot
auto-approve. An amount equal to HIGH_AMOUNT_T does not trip that rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domain import codes
from app.domain.enums import ClaimOutcome, ClaimStatus
from app.domain.money import MONEY
from app.services.rules.engine import RulesEvaluation
from app.services.scoring.base import ScoreResult


@dataclass(frozen=True)
class Decision:
    status: ClaimStatus
    outcome: ClaimOutcome
    automation_flag: bool
    reason_codes: dict[str, list[str]]
    rejection_code: str | None
    approved_amount: Decimal
    action: str


def _threshold_ok(value: Decimal) -> bool:
    return (
        isinstance(value, Decimal)
        and not isinstance(value, bool)
        and not value.is_nan()
        and not value.is_infinite()
        and Decimal("0") <= value <= Decimal("1")
    )


def _bad_score(score: Decimal) -> bool:
    return (
        isinstance(score, bool) or score.is_nan() or score.is_infinite() or score < 0 or score > 1
    )


class DecisionRouter:
    def decide(
        self,
        *,
        rules: RulesEvaluation,
        score: ScoreResult,
        requested_amount: Decimal,
        approve_t: Decimal,
    ) -> Decision:
        scorer_codes = _scorer_codes(score, approve_t)
        if rules.triage_codes:
            return _triage(
                rules.triage_codes, rules.pend_docs_codes, scorer_codes, rules.pass_codes
            )
        if rules.pend_docs_codes:
            return Decision(
                status=ClaimStatus.pended_docs,
                outcome=ClaimOutcome.pending,
                automation_flag=False,
                reason_codes=codes.bundle_reason_codes(
                    rule_failures=rules.pend_docs_codes,
                    rule_passes=rules.pass_codes,
                    scorer=scorer_codes,
                    router=[codes.ROUTE_PEND_DOCS],
                ),
                rejection_code=None,
                approved_amount=Decimal("0.00"),
                action="pended_docs",
            )
        if not _threshold_ok(approve_t) or score.error is not None or score.score is None:
            return _triage([], [], scorer_codes or [codes.SCORE_MISSING], rules.pass_codes)
        if _bad_score(score.score):
            return _triage([], [], scorer_codes or [codes.SCORE_INVALID], rules.pass_codes)
        if score.score >= approve_t:
            return Decision(
                status=ClaimStatus.approved,
                outcome=ClaimOutcome.auto_approved,
                automation_flag=True,
                reason_codes=codes.bundle_reason_codes(
                    rule_failures=[],
                    rule_passes=rules.pass_codes,
                    scorer=scorer_codes,
                    router=[codes.ROUTE_AUTO_APPROVE],
                ),
                rejection_code=None,
                approved_amount=requested_amount.quantize(MONEY),
                action="auto_approved",
            )
        return _triage([], [], scorer_codes, rules.pass_codes)


def _scorer_codes(score: ScoreResult, threshold: Decimal) -> list[str]:
    if score.error is not None:
        return [score.error.code]
    if score.score is None or isinstance(score.score, bool):
        return [codes.SCORE_MISSING if score.score is None else codes.SCORE_INVALID]
    if score.score.is_nan():
        return [codes.SCORE_NAN]
    if _bad_score(score.score):
        return [codes.SCORE_INVALID]
    explanations = [item for item in score.explanations if item]
    if not _threshold_ok(threshold):
        return explanations
    marker = (
        codes.SCORE_MEETS_THRESHOLD if score.score >= threshold else codes.SCORE_BELOW_THRESHOLD
    )
    return [*explanations, marker]


def _triage(
    triage_failures: tuple[str, ...] | list[str],
    doc_failures: tuple[str, ...] | list[str],
    scorer_codes: list[str],
    pass_codes: tuple[str, ...],
) -> Decision:
    failures = list(triage_failures)
    for code in doc_failures:
        if code not in failures:
            failures.append(code)
    return Decision(
        status=ClaimStatus.in_triage,
        outcome=ClaimOutcome.pending,
        automation_flag=False,
        reason_codes=codes.bundle_reason_codes(
            rule_failures=failures,
            rule_passes=pass_codes,
            scorer=scorer_codes,
            router=[codes.ROUTE_TRIAGE],
        ),
        rejection_code=None,
        approved_amount=Decimal("0.00"),
        action="route_triage",
    )
