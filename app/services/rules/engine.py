"""Pure rules. They see a de-identified context, not ORM rows or documents."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from app.config import Settings
from app.domain import codes
from app.domain.enums import DocumentType

_CPT = re.compile(codes.CPT_PATTERN)
_ICD = re.compile(codes.ICD10_PATTERN)


@dataclass(frozen=True)
class CptFact:
    code: str
    active: bool
    covered: bool


@dataclass(frozen=True)
class IcdFact:
    code: str
    billable: bool


@dataclass(frozen=True)
class RuleContext:
    """Inputs a rule is allowed to see. No names, addresses, emails, or document bytes."""

    eligibility_verified_date: date | None
    as_of: date
    eligibility_max_age_days: int
    provider_active: bool
    provider_in_network: bool
    document_types: frozenset[str]
    cpt_codes: tuple[CptFact, ...]
    icd10_codes: tuple[IcdFact, ...]
    requested_amount: Decimal
    high_amount_t: Decimal


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    passed: bool
    severity: str
    pass_code: str
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class RulesEvaluation:
    results: tuple[RuleResult, ...]
    version: str

    @property
    def triage_codes(self) -> tuple[str, ...]:
        return _failed(self.results, "triage")

    @property
    def pend_docs_codes(self) -> tuple[str, ...]:
        return _failed(self.results, "pend_docs")

    @property
    def pass_codes(self) -> tuple[str, ...]:
        return tuple(result.pass_code for result in self.results if result.passed)


def _failed(results: tuple[RuleResult, ...], severity: str) -> tuple[str, ...]:
    found: list[str] = []
    for result in results:
        if result.passed or result.severity != severity:
            continue
        for code in result.reason_codes:
            if code not in found:
                found.append(code)
    return tuple(found)


class Rule(Protocol):
    rule_id: str
    severity: str

    def evaluate(self, context: RuleContext) -> RuleResult: ...


def _result(
    *,
    rule_id: str,
    severity: str,
    pass_code: str,
    failures: list[str],
) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        passed=not failures,
        severity=severity,
        pass_code=pass_code,
        reason_codes=tuple(failures),
    )


class EligibilityRule:
    """Triage when coverage was never verified or the verification is stale."""

    rule_id = "eligibility"
    severity = "triage"

    def evaluate(self, context: RuleContext) -> RuleResult:
        verified = context.eligibility_verified_date
        failures: list[str] = []
        if verified is None or verified > context.as_of:
            failures.append(codes.ELIGIBILITY_NOT_VERIFIED)
        elif (context.as_of - verified).days > context.eligibility_max_age_days:
            failures.append(codes.ELIGIBILITY_EXPIRED)
        return _result(
            rule_id=self.rule_id,
            severity=self.severity,
            pass_code=codes.ELIGIBILITY_CURRENT,
            failures=failures,
        )


class ProviderNetworkRule:
    """Triage when the rendering provider is inactive or out of network for the payer."""

    rule_id = "provider_network"
    severity = "triage"

    def evaluate(self, context: RuleContext) -> RuleResult:
        failures: list[str] = []
        if not context.provider_active:
            failures.append(codes.PROVIDER_INACTIVE)
        if not context.provider_in_network:
            failures.append(codes.PROVIDER_NOT_IN_NETWORK)
        return _result(
            rule_id=self.rule_id,
            severity=self.severity,
            pass_code=codes.PROVIDER_IN_NETWORK,
            failures=failures,
        )


class RequiredDocumentsRule:
    """Pend, rather than deny, when a letter of necessity or clinical notes are absent.

    A later OCR milestone can read the stored files. This rule only checks presence.
    """

    rule_id = "required_documents"
    severity = "pend_docs"

    def evaluate(self, context: RuleContext) -> RuleResult:
        failures: list[str] = []
        if DocumentType.letter_of_medical_necessity.value not in context.document_types:
            failures.append(codes.DOCUMENT_LMN_MISSING)
        if DocumentType.clinical_notes.value not in context.document_types:
            failures.append(codes.DOCUMENT_CLINICAL_NOTES_MISSING)
        return _result(
            rule_id=self.rule_id,
            severity=self.severity,
            pass_code=codes.DOCUMENTS_PRESENT,
            failures=failures,
        )


class CodeSanityRule:
    """Triage when a procedure is not covered or a diagnosis is not billable."""

    rule_id = "code_sanity"
    severity = "triage"

    def evaluate(self, context: RuleContext) -> RuleResult:
        failures: list[str] = []
        if not context.cpt_codes:
            failures.append(codes.CPT_MISSING)
        else:
            invalid_cpt = False
            not_covered = False
            for fact in context.cpt_codes:
                if not _CPT.fullmatch(fact.code):
                    invalid_cpt = True
                elif not fact.active or not fact.covered:
                    not_covered = True
            if invalid_cpt:
                failures.append(codes.CPT_INVALID)
            if not_covered:
                failures.append(codes.NON_COVERED_CODE)
        if not context.icd10_codes:
            failures.append(codes.ICD10_MISSING)
        else:
            invalid_icd = False
            not_billable = False
            for fact in context.icd10_codes:
                if not _ICD.fullmatch(fact.code):
                    invalid_icd = True
                elif not fact.billable:
                    not_billable = True
            if invalid_icd:
                failures.append(codes.ICD10_INVALID)
            if not_billable:
                failures.append(codes.ICD10_NOT_BILLABLE)
        return _result(
            rule_id=self.rule_id,
            severity=self.severity,
            pass_code=codes.CODES_VALID,
            failures=failures,
        )


class AmountRule:
    """Triage when the requested amount is above HIGH_AMOUNT_T. The boundary is inclusive."""

    rule_id = "amount"
    severity = "triage"

    def evaluate(self, context: RuleContext) -> RuleResult:
        failures: list[str] = []
        if context.requested_amount <= 0:
            failures.append(codes.AMOUNT_INVALID)
        elif context.requested_amount > context.high_amount_t:
            failures.append(codes.AMOUNT_ABOVE_THRESHOLD)
        return _result(
            rule_id=self.rule_id,
            severity=self.severity,
            pass_code=codes.AMOUNT_WITHIN_LIMIT,
            failures=failures,
        )


class RulesEngine:
    def __init__(self, rules: tuple[Rule, ...] | list[Rule], version: str) -> None:
        self._rules = tuple(rules)
        self.version = version

    def evaluate(self, context: RuleContext) -> RulesEvaluation:
        return RulesEvaluation(
            results=tuple(rule.evaluate(context) for rule in self._rules),
            version=self.version,
        )


def build_rules_engine(settings: Settings) -> RulesEngine:
    """The production rule set. Tests can construct an engine with a subset."""

    return RulesEngine(
        rules=(
            EligibilityRule(),
            ProviderNetworkRule(),
            RequiredDocumentsRule(),
            CodeSanityRule(),
            AmountRule(),
        ),
        version=settings.rules_version,
    )
