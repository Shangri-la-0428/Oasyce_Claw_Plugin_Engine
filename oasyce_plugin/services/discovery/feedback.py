"""Feedback loop for skill discovery — tracks execution outcomes."""
from __future__ import annotations

import math
import sqlite3
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

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._records: Dict[str, List[ExecutionRecord]] = defaultdict(list)
        self._db: Optional[sqlite3.Connection] = None

        if db_path is not None:
            self._db = sqlite3.connect(db_path, check_same_thread=False)
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS feedback_records ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "skill_id TEXT, "
                "success INTEGER, "
                "latency_ms INTEGER, "
                "caller_rating REAL, "
                "timestamp INTEGER)"
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_feedback_skill_id "
                "ON feedback_records (skill_id)"
            )
            self._db.commit()
            # Load existing records into memory
            cursor = self._db.execute(
                "SELECT skill_id, success, latency_ms, caller_rating, timestamp "
                "FROM feedback_records ORDER BY id"
            )
            for row in cursor:
                rec = ExecutionRecord(
                    skill_id=row[0],
                    success=bool(row[1]),
                    latency_ms=row[2],
                    caller_rating=row[3],
                    timestamp=row[4],
                )
                self._records[rec.skill_id].append(rec)

    def record(self, rec: ExecutionRecord) -> None:
        """Record an execution outcome."""
        records = self._records[rec.skill_id]
        records.append(rec)

        if self._db is not None:
            self._db.execute(
                "INSERT INTO feedback_records (skill_id, success, latency_ms, caller_rating, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (rec.skill_id, int(rec.success), rec.latency_ms, rec.caller_rating, rec.timestamp),
            )
            self._db.commit()

        # Evict oldest if over limit
        if len(records) > self.MAX_RECORDS_PER_SKILL:
            evicted = records[: len(records) - self.MAX_RECORDS_PER_SKILL]
            self._records[rec.skill_id] = records[-self.MAX_RECORDS_PER_SKILL:]
            if self._db is not None:
                # Delete the oldest rows for this skill_id that match evicted timestamps
                self._db.execute(
                    "DELETE FROM feedback_records WHERE id IN ("
                    "  SELECT id FROM feedback_records WHERE skill_id = ? "
                    "  ORDER BY id LIMIT ?"
                    ")",
                    (rec.skill_id, len(evicted)),
                )
                self._db.commit()

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
