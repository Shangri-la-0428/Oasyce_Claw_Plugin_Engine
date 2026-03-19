"""Consumer Rating System for capability invocations.

After a settled invocation, the consumer can rate the provider (1-5).
Rating weight = rater_reputation × rater_stake, so high-rep raters
count more.  Each invocation can only be rated once.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class RatingRecord:
    """A single consumer rating for a completed invocation."""

    invocation_id: str
    capability_id: str
    consumer_id: str
    provider_id: str
    score: int  # 1-5
    weight: float  # rater_reputation × rater_stake
    created_at: int = field(default_factory=lambda: int(time.time()))


@dataclass
class RatingStats:
    """Aggregated rating statistics for a capability or provider."""

    count: int
    weighted_sum: float
    weight_total: float
    weighted_average: float
    raw_average: float


class RatingError(Exception):
    """Raised on invalid rating operations."""


class RatingEngine:
    """Manages consumer ratings for capability invocations.

    Parameters
    ----------
    get_invocation : callable
        Returns invocation record by ID (must have .consumer_id,
        .capability_id, .provider_id, .state attributes).
    get_reputation : callable
        (agent_id) → float reputation score.
    get_stake : callable
        (agent_id) → float staked amount.
    """

    def __init__(
        self,
        get_invocation: Callable[[str], Any],
        get_reputation: Callable[[str], float],
        get_stake: Callable[[str], float],
    ) -> None:
        self._get_invocation = get_invocation
        self._get_reputation = get_reputation
        self._get_stake = get_stake
        # invocation_id → RatingRecord
        self._ratings: Dict[str, RatingRecord] = {}
        # capability_id → [RatingRecord]
        self._by_capability: Dict[str, List[RatingRecord]] = {}
        # provider_id → [RatingRecord]
        self._by_provider: Dict[str, List[RatingRecord]] = {}

    def submit_rating(
        self,
        invocation_id: str,
        consumer_id: str,
        score: int,
    ) -> RatingRecord:
        """Rate a completed invocation.

        Validates:
            - Score in 1-5
            - Invocation exists and is completed (settled)
            - Consumer matches the invocation's consumer
            - Not already rated

        Returns:
            RatingRecord with computed weight.
        """
        # Validate score range
        if not isinstance(score, int) or score < 1 or score > 5:
            raise RatingError("score must be an integer between 1 and 5")

        # Check already rated
        if invocation_id in self._ratings:
            raise RatingError(f"invocation {invocation_id} has already been rated")

        # Look up invocation
        inv = self._get_invocation(invocation_id)
        if inv is None:
            raise RatingError(f"invocation not found: {invocation_id}")

        # Must be completed (settled)
        state = inv.state if hasattr(inv, "state") else None
        state_val = state.value if hasattr(state, "value") else str(state)
        if state_val != "completed":
            raise RatingError(f"can only rate completed invocations, got {state_val}")

        # Only the consumer of that invocation can rate
        if inv.consumer_id != consumer_id:
            raise RatingError("only the consumer of this invocation can rate")

        # Compute weight = reputation × stake (min 1.0 to avoid zero weight)
        rep = max(self._get_reputation(consumer_id), 1.0)
        stake = max(self._get_stake(consumer_id), 1.0)
        weight = rep * stake

        record = RatingRecord(
            invocation_id=invocation_id,
            capability_id=inv.capability_id,
            consumer_id=consumer_id,
            provider_id=inv.provider_id,
            score=score,
            weight=weight,
        )

        self._ratings[invocation_id] = record
        self._by_capability.setdefault(inv.capability_id, []).append(record)
        self._by_provider.setdefault(inv.provider_id, []).append(record)

        return record

    def get_ratings(self, capability_id: str) -> List[RatingRecord]:
        """Return all ratings for a capability."""
        return list(self._by_capability.get(capability_id, []))

    def get_capability_stats(self, capability_id: str) -> Optional[RatingStats]:
        """Return aggregated stats for a capability, or None if no ratings."""
        ratings = self._by_capability.get(capability_id, [])
        if not ratings:
            return None
        return self._compute_stats(ratings)

    def get_provider_score(self, provider_id: str) -> Optional[RatingStats]:
        """Return weighted average across all capabilities for a provider."""
        ratings = self._by_provider.get(provider_id, [])
        if not ratings:
            return None
        return self._compute_stats(ratings)

    @staticmethod
    def _compute_stats(ratings: List[RatingRecord]) -> RatingStats:
        count = len(ratings)
        weighted_sum = sum(r.score * r.weight for r in ratings)
        weight_total = sum(r.weight for r in ratings)
        weighted_average = weighted_sum / weight_total if weight_total > 0 else 0.0
        raw_average = sum(r.score for r in ratings) / count if count > 0 else 0.0
        return RatingStats(
            count=count,
            weighted_sum=weighted_sum,
            weight_total=weight_total,
            weighted_average=weighted_average,
            raw_average=raw_average,
        )
