"""Each business rule passes and fails on its own."""

from datetime import date, timedelta
from decimal import Decimal

from app.services.rules.engine import (
    AmountRule,
    CodeSanityRule,
    CptFact,
    EligibilityRule,
    IcdFact,
    ProviderNetworkRule,
    RequiredDocumentsRule,
    RuleContext,
)


def context(**overrides: object) -> RuleContext:
    values: dict[str, object] = {
        "eligibility_verified_date": date(2026, 11, 1),
        "as_of": date(2026, 11, 18),
        "eligibility_max_age_days": 365,
        "provider_active": True,
        "provider_in_network": True,
        "document_types": frozenset({"letter_of_medical_necessity", "clinical_notes"}),
        "cpt_codes": (CptFact("27447", True, True),),
        "icd10_codes": (IcdFact("M17.11", True),),
        "requested_amount": Decimal("70000.00"),
        "high_amount_t": Decimal("70000.00"),
    }
    values.update(overrides)
    return RuleContext(**values)  # type: ignore[arg-type]


def test_eligibility_pass_and_fail() -> None:
    assert EligibilityRule().evaluate(context()).passed
    expired = context(eligibility_verified_date=date(2026, 11, 18) - timedelta(days=366))
    missing = context(eligibility_verified_date=None)
    assert EligibilityRule().evaluate(expired).reason_codes == ("ELIGIBILITY_EXPIRED",)
    assert EligibilityRule().evaluate(missing).reason_codes == ("ELIGIBILITY_NOT_VERIFIED",)
    boundary = context(eligibility_verified_date=date(2026, 11, 18) - timedelta(days=365))
    assert EligibilityRule().evaluate(boundary).passed


def test_provider_pass_and_fail() -> None:
    assert ProviderNetworkRule().evaluate(context()).passed
    inactive = ProviderNetworkRule().evaluate(context(provider_active=False))
    offline = ProviderNetworkRule().evaluate(context(provider_in_network=False))
    assert "PROVIDER_INACTIVE" in inactive.reason_codes
    assert "PROVIDER_NOT_IN_NETWORK" in offline.reason_codes
    assert inactive.severity == "triage"


def test_documents_pass_and_fail() -> None:
    assert RequiredDocumentsRule().evaluate(context()).passed
    missing = RequiredDocumentsRule().evaluate(context(document_types=frozenset()))
    assert missing.severity == "pend_docs"
    assert "DOCUMENT_LMN_MISSING" in missing.reason_codes
    assert "DOCUMENT_CLINICAL_NOTES_MISSING" in missing.reason_codes


def test_code_and_amount_boundaries() -> None:
    assert CodeSanityRule().evaluate(context()).passed
    unknown = CodeSanityRule().evaluate(context(cpt_codes=(CptFact("0001F", False, False),)))
    assert unknown.reason_codes == ("non_covered_code",)
    assert AmountRule().evaluate(context(requested_amount=Decimal("70000.00"))).passed
    over = AmountRule().evaluate(context(requested_amount=Decimal("70000.01")))
    assert over.reason_codes == ("AMOUNT_ABOVE_THRESHOLD",)
    assert over.severity == "triage"
