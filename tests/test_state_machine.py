"""The D17 transition table."""

import pytest
from app.domain.enums import ClaimStatus
from app.domain.errors import IllegalTransition
from app.services.decision.state_machine import assert_transition


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ClaimStatus.submitted, ClaimStatus.pended_docs),
        (ClaimStatus.submitted, ClaimStatus.in_triage),
        (ClaimStatus.submitted, ClaimStatus.approved),
        (ClaimStatus.submitted, ClaimStatus.withdrawn),
        (ClaimStatus.pended_docs, ClaimStatus.in_triage),
        (ClaimStatus.pended_docs, ClaimStatus.approved),
        (ClaimStatus.pended_docs, ClaimStatus.withdrawn),
        (ClaimStatus.in_triage, ClaimStatus.approved),
        (ClaimStatus.in_triage, ClaimStatus.denied),
        (ClaimStatus.in_triage, ClaimStatus.pended_docs),
        (ClaimStatus.in_triage, ClaimStatus.withdrawn),
    ],
)
def test_legal(current: ClaimStatus, target: ClaimStatus) -> None:
    assert_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ClaimStatus.submitted, ClaimStatus.denied),
        (ClaimStatus.submitted, ClaimStatus.submitted),
        (ClaimStatus.pended_docs, ClaimStatus.denied),
        (ClaimStatus.approved, ClaimStatus.denied),
        (ClaimStatus.approved, ClaimStatus.approved),
        (ClaimStatus.denied, ClaimStatus.approved),
        (ClaimStatus.withdrawn, ClaimStatus.approved),
        (ClaimStatus.in_triage, ClaimStatus.in_triage),
    ],
)
def test_illegal_including_same_status(current: ClaimStatus, target: ClaimStatus) -> None:
    with pytest.raises(IllegalTransition):
        assert_transition(current, target)
