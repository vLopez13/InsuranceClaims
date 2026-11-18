"""Stable reason-code tokens. These are identifiers, never free text."""

from __future__ import annotations

ELIGIBILITY_NOT_VERIFIED = "ELIGIBILITY_NOT_VERIFIED"
ELIGIBILITY_EXPIRED = "ELIGIBILITY_EXPIRED"
ELIGIBILITY_CURRENT = "ELIGIBILITY_CURRENT"

PROVIDER_INACTIVE = "PROVIDER_INACTIVE"
PROVIDER_NOT_IN_NETWORK = "PROVIDER_NOT_IN_NETWORK"
PROVIDER_IN_NETWORK = "PROVIDER_IN_NETWORK"

DOCUMENT_LMN_MISSING = "DOCUMENT_LMN_MISSING"
DOCUMENT_CLINICAL_NOTES_MISSING = "DOCUMENT_CLINICAL_NOTES_MISSING"
DOCUMENTS_PRESENT = "DOCUMENTS_PRESENT"

CPT_MISSING = "CPT_MISSING"
CPT_INVALID = "CPT_INVALID"
NON_COVERED_CODE = "non_covered_code"
ICD10_MISSING = "ICD10_MISSING"
ICD10_INVALID = "ICD10_INVALID"
ICD10_NOT_BILLABLE = "ICD10_NOT_BILLABLE"
AMOUNT_INVALID = "AMOUNT_INVALID"
AMOUNT_ABOVE_THRESHOLD = "AMOUNT_ABOVE_THRESHOLD"
AMOUNT_WITHIN_LIMIT = "AMOUNT_WITHIN_LIMIT"
CODES_VALID = "CODES_VALID"

SCORE_MEETS_THRESHOLD = "SCORE_MEETS_THRESHOLD"
SCORE_BELOW_THRESHOLD = "SCORE_BELOW_THRESHOLD"
SCORE_MISSING = "SCORE_MISSING"
SCORE_NAN = "SCORE_NAN"
SCORE_INVALID = "SCORE_INVALID"
SCORE_ERROR = "SCORE_ERROR"
SCORE_TIMEOUT = "SCORE_TIMEOUT"

ROUTE_AUTO_APPROVE = "ROUTE_AUTO_APPROVE"
ROUTE_PEND_DOCS = "ROUTE_PEND_DOCS"
ROUTE_TRIAGE = "ROUTE_TRIAGE"
ROUTE_THRESHOLD_INVALID = "ROUTE_THRESHOLD_INVALID"

CLAIM_SUBMITTED = "CLAIM_SUBMITTED"
RESUBMITTED = "RESUBMITTED"
DOCUMENT_ADDED = "DOCUMENT_ADDED"

CPT_PATTERN = r"^[0-9]{4}[0-9FT]$"
ICD10_PATTERN = r"^[A-Z][0-9][0-9A-Z](\.[0-9A-Z]{1,4})?$"
REJECTION_CODE_PATTERN = r"^(CO|PR|OA|PI|CR)-[0-9]{1,3}$"
REASON_CODE_PATTERN = r"^[A-Z0-9_]{1,64}$"


def rejection_code_for(reason_code: str) -> str:
    """Map a hard rule failure to a CARC-style code. The AI score has no mapping."""

    if reason_code.startswith("ELIGIBILITY"):
        return "CO-27"
    if reason_code.startswith("PROVIDER"):
        return "CO-242"
    return "CO-16"


def empty_reason_codes() -> dict[str, list[str]]:
    return {
        "rule_failures": [],
        "rule_passes": [],
        "scorer": [],
        "router": [],
    }


def bundle_reason_codes(
    *,
    rule_failures: list[str] | tuple[str, ...],
    rule_passes: list[str] | tuple[str, ...],
    scorer: list[str] | tuple[str, ...],
    router: list[str] | tuple[str, ...],
) -> dict[str, list[str]]:
    return {
        "rule_failures": list(rule_failures),
        "rule_passes": list(rule_passes),
        "scorer": list(scorer),
        "router": list(router),
    }
