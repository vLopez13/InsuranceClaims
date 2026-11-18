"""Explicit claim lifecycle.

System routing may move a new claim from submitted to pended_docs, in_triage,
or approved. It never sets denied. Only a human decision may set denied, and
only from in_triage. A requested transition into the status the claim already
has is rejected. Re-checking documents may leave a claim in pended_docs; that
path passes ``allow_same`` and is not a rejected transition.
"""

from __future__ import annotations

from app.domain.enums import ClaimStatus
from app.domain.errors import IllegalTransition

_ALLOWED: dict[ClaimStatus, frozenset[ClaimStatus]] = {
    ClaimStatus.submitted: frozenset(
        {
            ClaimStatus.pended_docs,
            ClaimStatus.in_triage,
            ClaimStatus.approved,
            ClaimStatus.withdrawn,
        }
    ),
    ClaimStatus.pended_docs: frozenset(
        {
            ClaimStatus.in_triage,
            ClaimStatus.approved,
            ClaimStatus.withdrawn,
        }
    ),
    ClaimStatus.in_triage: frozenset(
        {
            ClaimStatus.approved,
            ClaimStatus.denied,
            ClaimStatus.pended_docs,
            ClaimStatus.withdrawn,
        }
    ),
    ClaimStatus.approved: frozenset(),
    ClaimStatus.denied: frozenset(),
    ClaimStatus.withdrawn: frozenset(),
}


def assert_transition(
    current: ClaimStatus,
    target: ClaimStatus,
    *,
    allow_same: bool = False,
) -> None:
    if current == target:
        if allow_same:
            return
        raise IllegalTransition(current.value, target.value)
    if target not in _ALLOWED[current]:
        raise IllegalTransition(current.value, target.value)
