"""Aggregate prior-authorization metrics. The result has no claim or patient ids.

straight_through_rate
    auto_approved / persisted claims that reached routing.
    Schema failures return 422 and are not stored, so they are already excluded.
    Every stored claim has been routed.

Decision latency is decided_at - submitted_at for claims with a final decision
(approved, denied, or withdrawn). Routing latency is routed_at - submitted_at.
Percentiles use the nearest-rank method.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import ClaimOutcome, ClaimStatus
from app.models import Claim

TARGET_TURNAROUND_SECONDS = 7200


@dataclass(frozen=True)
class MetricsSnapshot:
    counts_by_outcome: dict[str, int]
    straight_through_rate: Decimal
    automation_rate: Decimal
    decided_count: int
    average_turnaround_seconds: Decimal | None
    latency_p50_seconds: Decimal | None
    latency_p95_seconds: Decimal | None
    average_routing_seconds: Decimal | None
    routing_latency_p50_seconds: Decimal | None
    routing_latency_p95_seconds: Decimal | None
    target_turnaround_seconds: int = TARGET_TURNAROUND_SECONDS


def compute_metrics(session: Session) -> MetricsSnapshot:
    claims = list(session.scalars(select(Claim)))
    counts = {outcome.value: 0 for outcome in ClaimOutcome}
    decision_latencies: list[Decimal] = []
    routing_latencies: list[Decimal] = []
    for claim in claims:
        counts[claim.outcome.value] += 1
        if claim.routed_at is not None:
            routing_latencies.append(_seconds(claim.submitted_at, claim.routed_at))
        if claim.decided_at is not None:
            decision_latencies.append(_seconds(claim.submitted_at, claim.decided_at))
    decision_latencies = [value for value in decision_latencies if value >= 0]
    routing_latencies = [value for value in routing_latencies if value >= 0]
    decision_latencies.sort()
    routing_latencies.sort()
    withdrawn = sum(1 for claim in claims if claim.status == ClaimStatus.withdrawn)
    denominator = len(claims) - withdrawn
    auto_approved = counts[ClaimOutcome.auto_approved.value]
    return MetricsSnapshot(
        counts_by_outcome=counts,
        straight_through_rate=_rate(auto_approved, denominator),
        automation_rate=_rate(auto_approved, denominator),
        decided_count=len(decision_latencies),
        average_turnaround_seconds=_average(decision_latencies),
        latency_p50_seconds=_percentile(decision_latencies, 50),
        latency_p95_seconds=_percentile(decision_latencies, 95),
        average_routing_seconds=_average(routing_latencies),
        routing_latency_p50_seconds=_percentile(routing_latencies, 50),
        routing_latency_p95_seconds=_percentile(routing_latencies, 95),
    )


def _seconds(start: datetime, end: datetime) -> Decimal:
    delta = end - start
    return Decimal(delta.days * 86400 + delta.seconds) + (
        Decimal(delta.microseconds) / Decimal(1_000_000)
    )


def _rate(numerator: int, denominator: int) -> Decimal:
    if denominator == 0:
        return Decimal("0.0000")
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.0001"),
        rounding=ROUND_HALF_UP,
    )


def _average(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, Decimal("0")) / Decimal(len(values))).quantize(
        Decimal("0.001"),
        rounding=ROUND_HALF_UP,
    )


def _percentile(values: list[Decimal], pct: int) -> Decimal | None:
    if not values:
        return None
    rank = math.ceil(pct / 100 * len(values))
    index = min(len(values), max(rank, 1)) - 1
    return values[index].quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
