"""Router boundaries. The router never produces a denial."""

from decimal import Decimal

from app.domain.codes import NON_COVERED_CODE
from app.domain.enums import ClaimStatus
from app.services.decision.router import DecisionRouter
from app.services.rules.engine import RuleResult, RulesEvaluation
from app.services.scoring.base import ScoreError, ScoreResult


def evaluation(*results: RuleResult) -> RulesEvaluation:
    return RulesEvaluation(results=results, version="rules-v1")


def passed() -> RulesEvaluation:
    return evaluation(
        RuleResult("eligibility", True, "triage", "ELIGIBILITY_CURRENT", ()),
        RuleResult("provider_network", True, "triage", "PROVIDER_IN_NETWORK", ()),
        RuleResult("required_documents", True, "pend_docs", "DOCUMENTS_PRESENT", ()),
        RuleResult("code_sanity", True, "triage", "CODES_VALID", ()),
        RuleResult("amount", True, "triage", "AMOUNT_WITHIN_LIMIT", ()),
    )


def score(value: Decimal | None, error: ScoreError | None = None) -> ScoreResult:
    return ScoreResult(score=value, model_version="stub-v1", explanations=("STUB",), error=error)


def decide(rules: RulesEvaluation, value: Decimal | None, threshold: str = "0.80") -> object:
    return DecisionRouter().decide(
        rules=rules,
        score=score(value),
        requested_amount=Decimal("1000.00"),
        approve_t=Decimal(threshold),
    )


def test_exact_approve_threshold_approves() -> None:
    decision = decide(passed(), Decimal("0.8000"))
    assert decision.status == ClaimStatus.approved
    assert decision.outcome.value == "auto_approved"


def test_just_below_threshold_triages_and_does_not_deny() -> None:
    decision = decide(passed(), Decimal("0.7999"))
    assert decision.status == ClaimStatus.in_triage
    assert decision.status != ClaimStatus.denied


def test_score_failure_and_nan_triage() -> None:
    router = DecisionRouter()
    missing = router.decide(
        rules=passed(),
        score=score(None, ScoreError("missing", "SCORE_MISSING")),
        requested_amount=Decimal("1.00"),
        approve_t=Decimal("0.80"),
    )
    nan = router.decide(
        rules=passed(),
        score=ScoreResult(
            score=Decimal("NaN"),
            model_version="stub-v1",
            explanations=(),
            error=None,
        ),
        requested_amount=Decimal("1.00"),
        approve_t=Decimal("0.80"),
    )
    assert missing.status == ClaimStatus.in_triage
    assert nan.status == ClaimStatus.in_triage
    assert missing.status != ClaimStatus.denied


def test_non_document_failure_beats_a_perfect_score() -> None:
    rules = evaluation(
        RuleResult("code_sanity", False, "triage", "CODES_VALID", (NON_COVERED_CODE,)),
        RuleResult(
            "required_documents",
            False,
            "pend_docs",
            "DOCUMENTS_PRESENT",
            ("DOCUMENT_LMN_MISSING",),
        ),
    )
    decision = decide(rules, Decimal("1.0000"))
    assert decision.status == ClaimStatus.in_triage
    assert NON_COVERED_CODE in decision.reason_codes["rule_failures"]
    assert "DOCUMENT_LMN_MISSING" in decision.reason_codes["rule_failures"]


def test_missing_documents_alone_pend() -> None:
    rules = evaluation(
        RuleResult("eligibility", True, "triage", "ELIGIBILITY_CURRENT", ()),
        RuleResult(
            "required_documents",
            False,
            "pend_docs",
            "DOCUMENTS_PRESENT",
            ("DOCUMENT_LMN_MISSING",),
        ),
    )
    decision = decide(rules, Decimal("1"))
    assert decision.status == ClaimStatus.pended_docs


def test_router_has_no_auto_deny_status() -> None:
    low = decide(passed(), Decimal("0"))
    assert low.status != ClaimStatus.denied
    assert low.outcome.value != "auto_denied"
