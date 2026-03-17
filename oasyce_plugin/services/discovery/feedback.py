"""Feedback loop for skill discovery — tracks execution outcomes."""
from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class ExecutionRecord:
    """A single skill execution outcome."""
    skill_id: str
    success: bool
    latency_ms: int
    caller_rating: float  # 0.0-5.0
    timestamp: int = 0

    def __post_init__(self):
        if self.timestamp == 0:
            self.timestamp = int(time.time())


class FeedbackStore:
    """In-memory feedback store with time-decayed trust scoring."""

    DECAY_HALF_LIFE_DAYS: int = 30
    MAX_RECORDS_PER_SKILL: int = 200

    def __init__(self) -> None:
        self._records: Dict[str, List[ExecutionRecord]] = defaultdict(list)

    def record(self, rec: ExecutionRecord) -> None:
        """Record an execution outcome."""
        records = self._records[rec.skill_id]
        records.append(rec)
        # Evict oldest if over limit
        if len(records) > self.MAX_RECORDS_PER_SKILL:
            self._records[rec.skill_id] = records[-self.MAX_RECORDS_PER_SKILL:]

    def learned_trust(self, skill_id: str) -> Optional[float]:
        """Compute time-decayed trust score for a skill.

        Score per record: 0.6 * success(0/1) + 0.4 * (rating/5)
        Weighted by exponential decay based on age.
        """
        records = self._records.get(skill_id)
        if not records:
            return None

        now = int(time.time())
        half_life_seconds = self.DECAY_HALF_LIFE_DAYS * 86400
        ln2 = math.log(2)

        total_weight = 0.0
        weighted_score = 0.0

        for rec in records:
            age = max(now - rec.timestamp, 0)
            weight = math.exp(-ln2 * age / half_life_seconds)
            score = 0.6 * (1.0 if rec.success else 0.0) + 0.4 * (rec.caller_rating / 5.0)
            weighted_score += weight * score
            total_weight += weight

        if total_weight == 0.0:
            return None

        return weighted_score / total_weight

    def stats(self, skill_id: str) -> Dict:
        """Return summary statistics for a skill."""
        records = self._records.get(skill_id, [])
        if not records:
            return {
                "total": 0,
                "successes": 0,
                "failures": 0,
                "avg_latency_ms": 0,
                "avg_rating": 0.0,
            }

        successes = sum(1 for r in records if r.success)
        return {
            "total": len(records),
            "successes": successes,
            "failures": len(records) - successes,
            "avg_latency_ms": sum(r.latency_ms for r in records) // len(records),
            "avg_rating": sum(r.caller_rating for r in records) / len(records),
        }
