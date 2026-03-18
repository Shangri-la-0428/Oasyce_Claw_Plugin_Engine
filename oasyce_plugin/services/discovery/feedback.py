"""Feedback loop for skill discovery — tracks execution outcomes."""
from __future__ import annotations

import math
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class ExecutionRecord:
    """A single skill execution outcome."""
    skill_id: str
    success: bool
    latency_ms: int
    caller_rating: float  # 0.0-5.0
    timestamp: int = 0
    invocation_id: Optional[str] = None
    verified: bool = True  # set by FeedbackStore.record()

    def __post_init__(self):
        if self.timestamp == 0:
            self.timestamp = int(time.time())


class FeedbackStore:
    """In-memory feedback store with time-decayed trust scoring."""

    DECAY_HALF_LIFE_DAYS: int = 30
    MAX_RECORDS_PER_SKILL: int = 200

    # Weight multipliers for verified vs unverified feedback
    VERIFIED_WEIGHT: float = 1.0
    UNVERIFIED_WEIGHT: float = 0.1

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._records: Dict[str, List[ExecutionRecord]] = defaultdict(list)
        self._db: Optional[sqlite3.Connection] = None
        self._valid_invocation_ids: Set[str] = set()

        if db_path is not None:
            self._db = sqlite3.connect(db_path, check_same_thread=False)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS feedback_records ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "skill_id TEXT, "
                "success INTEGER, "
                "latency_ms INTEGER, "
                "caller_rating REAL, "
                "timestamp INTEGER, "
                "invocation_id TEXT, "
                "verified INTEGER NOT NULL DEFAULT 1)"
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_feedback_skill_id "
                "ON feedback_records (skill_id)"
            )
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS valid_invocation_ids ("
                "invocation_id TEXT PRIMARY KEY)"
            )
            self._db.commit()
            # Load valid invocation IDs
            cursor = self._db.execute(
                "SELECT invocation_id FROM valid_invocation_ids"
            )
            for row in cursor:
                self._valid_invocation_ids.add(row[0])
            # Load existing records into memory
            cursor = self._db.execute(
                "SELECT skill_id, success, latency_ms, caller_rating, timestamp, "
                "invocation_id, verified "
                "FROM feedback_records ORDER BY id"
            )
            for row in cursor:
                rec = ExecutionRecord(
                    skill_id=row[0],
                    success=bool(row[1]),
                    latency_ms=row[2],
                    caller_rating=row[3],
                    timestamp=row[4],
                    invocation_id=row[5],
                    verified=bool(row[6]),
                )
                self._records[rec.skill_id].append(rec)

    def register_invocation(self, invocation_id: str) -> None:
        """Register a valid invocation ID from the settlement protocol.

        Called after a successful invocation so that subsequent feedback
        referencing this ID can be marked as verified.
        """
        self._valid_invocation_ids.add(invocation_id)
        if self._db is not None:
            self._db.execute(
                "INSERT OR IGNORE INTO valid_invocation_ids (invocation_id) VALUES (?)",
                (invocation_id,),
            )
            self._db.commit()

    def record(self, rec: ExecutionRecord) -> None:
        """Record an execution outcome.

        If the record has an invocation_id that exists in the valid set,
        it is marked as verified.  Otherwise it is marked as unverified
        (lower weight in trust calculation).

        caller_rating is clamped to the 0.0-5.0 range.
        """
        # Clamp caller_rating to 0.0-5.0
        rec.caller_rating = max(0.0, min(5.0, rec.caller_rating))

        # Verify invocation_id
        if rec.invocation_id and rec.invocation_id in self._valid_invocation_ids:
            rec.verified = True
        elif rec.invocation_id is None:
            # No invocation_id provided — mark as unverified
            rec.verified = False
        else:
            # invocation_id provided but not in valid set — unverified
            rec.verified = False

        records = self._records[rec.skill_id]
        records.append(rec)

        if self._db is not None:
            self._db.execute(
                "INSERT INTO feedback_records "
                "(skill_id, success, latency_ms, caller_rating, timestamp, "
                "invocation_id, verified) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rec.skill_id, int(rec.success), rec.latency_ms,
                 rec.caller_rating, rec.timestamp, rec.invocation_id,
                 int(rec.verified)),
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
        Verified feedback is weighted at 1.0x, unverified at 0.1x.
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
            decay = math.exp(-ln2 * age / half_life_seconds)
            verification_mult = (
                self.VERIFIED_WEIGHT if rec.verified else self.UNVERIFIED_WEIGHT
            )
            weight = decay * verification_mult
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
