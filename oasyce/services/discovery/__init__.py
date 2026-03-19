"""
Skill Discovery Engine — Recall → Rank pipeline.

Phase 1: Recall   — broad, low-threshold candidate retrieval (intent OR semantic OR tag)
Phase 2: Rank     — trust filtering, feedback-adjusted scoring, economic optimization

Also provides skill affinity caching and feedback loop integration.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .feedback import ExecutionRecord, FeedbackStore


# ── Data types ────────────────────────────────────────────────────


@dataclass
class RecallCandidate:
    """A candidate from the recall phase."""

    capability_id: str
    cap: Dict[str, Any]
    recall_score: float = 0.0


@dataclass
class DiscoveryCandidate:
    """A scored candidate from the discovery pipeline."""

    capability_id: str
    name: str
    provider: str
    tags: List[str]
    # Per-layer scores (0-1 each)
    intent_score: float = 0.0
    semantic_score: float = 0.0
    trust_score: float = 0.0
    economic_score: float = 0.0
    # Composite
    final_score: float = 0.0
    # Metadata for display
    base_price: float = 0.0
    success_rate: float = 0.0
    call_count: int = 0
    rating: float = 0.0


@dataclass
class SkillAffinity:
    """Cached preference: agent remembers successful skill pairings."""

    task_key: str
    capability_id: str
    success_count: int = 0
    fail_count: int = 0
    last_used: int = 0

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 0.0


# ── Discovery weights ────────────────────────────────────────────


@dataclass(frozen=True)
class DiscoveryWeights:
    """Weights for the discovery layers."""

    intent: float = 0.40
    semantic: float = 0.30
    trust: float = 0.20
    economic: float = 0.10

    # Trust filter thresholds
    min_trust_score: float = 0.3
    min_success_rate: float = 0.5


# ── Discovery Engine ─────────────────────────────────────────────


class SkillDiscoveryEngine:
    """Recall → Rank skill discovery with feedback loop integration.

    Parameters
    ----------
    get_capabilities : callable
        () → list of capability dicts with at least:
        {capability_id, name, provider, tags, semantic_vector,
         base_price, intents}
    get_reputation : callable or None
        (provider_id) → float reputation score (0-100)
    get_rating : callable or None
        (capability_id) → dict {weighted_average, count} or None
    get_call_stats : callable or None
        (capability_id) → dict {call_count, success_count, fail_count}
    feedback_store : FeedbackStore or None
        Shared feedback store for learned trust scores.
    """

    # Recall threshold — intentionally low for broad retrieval
    RECALL_THRESHOLD: float = 0.05

    def __init__(
        self,
        get_capabilities: Callable[[], List[Dict[str, Any]]],
        get_reputation: Optional[Callable[[str], float]] = None,
        get_rating: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
        get_call_stats: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
        weights: Optional[DiscoveryWeights] = None,
        feedback_store: Optional[FeedbackStore] = None,
    ) -> None:
        self._get_capabilities = get_capabilities
        self._get_reputation = get_reputation
        self._get_rating = get_rating
        self._get_call_stats = get_call_stats
        self.weights = weights or DiscoveryWeights()
        self.feedback_store = feedback_store or FeedbackStore()
        # Agent skill affinities: agent_id → {task_key → SkillAffinity}
        self._affinities: Dict[str, Dict[str, SkillAffinity]] = {}

    # ── Public API (unchanged signature) ──────────────────────────

    def discover(
        self,
        intents: Optional[List[str]] = None,
        query_tags: Optional[List[str]] = None,
        semantic_vector: Optional[List[float]] = None,
        agent_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[DiscoveryCandidate]:
        """Run Recall → Rank discovery pipeline.

        Args:
            intents: structured intent strings (e.g. ["generate_quest"])
            query_tags: tag-based filter
            semantic_vector: embedding vector for semantic similarity
            agent_id: if provided, boost skills with positive affinity
            limit: max results

        Returns:
            Sorted list of DiscoveryCandidate, best first.
        """
        recalled = self._recall(intents, query_tags, semantic_vector)
        if not recalled:
            return []
        return self._rank(recalled, agent_id, intents, limit)

    def discover_arbitrators(
        self,
        dispute_tags: Optional[List[str]] = None,
        limit: int = 5,
    ) -> List[DiscoveryCandidate]:
        """Find arbitrator capabilities for dispute resolution."""
        return self.discover(
            intents=["dispute_arbitrate"],
            query_tags=dispute_tags or ["arbitration", "dispute"],
            limit=limit,
        )

    def record_outcome(
        self,
        agent_id: str,
        capability_id: str,
        task_key: str,
        success: bool,
        latency_ms: int = 0,
        caller_rating: float = 3.0,
    ) -> None:
        """Record an execution outcome — writes to both FeedbackStore and SkillAffinity."""
        # FeedbackStore
        self.feedback_store.record(
            ExecutionRecord(
                skill_id=capability_id,
                success=success,
                latency_ms=latency_ms,
                caller_rating=caller_rating,
            )
        )
        # SkillAffinity
        self.record_affinity(agent_id, task_key, capability_id, success)

    # ── Recall phase ──────────────────────────────────────────────

    def _recall(
        self,
        intents: Optional[List[str]],
        query_tags: Optional[List[str]],
        semantic_vector: Optional[List[float]],
    ) -> List[RecallCandidate]:
        """Broad retrieval: low threshold, OR logic across signals."""
        capabilities = self._get_capabilities()
        if not capabilities:
            return []

        candidates: List[RecallCandidate] = []

        for cap in capabilities:
            cid = cap.get("capability_id", "")

            intent_score = self._intent_score(intents, cap)
            sem_score = self._semantic_score(semantic_vector, cap)
            tag_score = self._tag_overlap_score(query_tags, cap)

            # OR logic: pass if any signal exceeds threshold
            recall_score = max(intent_score, sem_score, tag_score)
            if recall_score < self.RECALL_THRESHOLD:
                continue

            candidates.append(
                RecallCandidate(
                    capability_id=cid,
                    cap=cap,
                    recall_score=recall_score,
                )
            )

        return candidates

    # ── Rank phase ────────────────────────────────────────────────

    def _rank(
        self,
        candidates: List[RecallCandidate],
        agent_id: Optional[str],
        intents: Optional[List[str]],
        limit: int,
    ) -> List[DiscoveryCandidate]:
        """Score, filter, and sort recalled candidates."""
        w = self.weights
        ranked: List[DiscoveryCandidate] = []

        for rc in candidates:
            cap = rc.cap
            cid = rc.capability_id

            # Trust scoring with feedback integration
            static_trust, success_rate, call_count, rating = self._trust_score(cap)

            # Blend static trust with learned trust from FeedbackStore
            learned = self.feedback_store.learned_trust(cid)
            if learned is not None:
                trust_score = 0.6 * static_trust + 0.4 * learned
            else:
                trust_score = static_trust

            # Trust filter
            if trust_score < w.min_trust_score:
                continue

            # Layer scores
            intent_score = self._intent_score(intents, cap)
            sem_score = self._semantic_score(None, cap)  # already captured in recall
            base_price = cap.get("base_price", 1.0)
            econ_score = self._economic_score(success_rate, trust_score, base_price)

            # Composite: fold recall_score into intent+semantic weight
            recall_weight = (w.intent + w.semantic) * rc.recall_score
            final = recall_weight + w.trust * trust_score + w.economic * econ_score

            # Affinity boost
            if agent_id and intents:
                affinity_boost = self._affinity_boost(agent_id, intents, cid)
                final = final * (1.0 + 0.2 * affinity_boost)

            ranked.append(
                DiscoveryCandidate(
                    capability_id=cid,
                    name=cap.get("name", ""),
                    provider=cap.get("provider", ""),
                    tags=cap.get("tags", []),
                    intent_score=round(intent_score, 4),
                    semantic_score=round(sem_score, 4),
                    trust_score=round(trust_score, 4),
                    economic_score=round(econ_score, 4),
                    final_score=round(final, 4),
                    base_price=round(base_price, 6),
                    success_rate=round(success_rate, 4),
                    call_count=call_count,
                    rating=round(rating, 2),
                )
            )

        ranked.sort(key=lambda c: c.final_score, reverse=True)
        return ranked[:limit]

    # ── Scoring helpers ───────────────────────────────────────────

    def _intent_score(
        self,
        query_intents: Optional[List[str]],
        cap: Dict[str, Any],
    ) -> float:
        """Intent matching via set overlap (Jaccard)."""
        if not query_intents:
            return 0.0
        cap_intents = set(cap.get("intents", []))
        if not cap_intents:
            cap_intents = set(cap.get("tags", []))
        if not cap_intents:
            return 0.0
        query_set = set(query_intents)
        intersection = query_set & cap_intents
        union = query_set | cap_intents
        return len(intersection) / len(union) if union else 0.0

    @staticmethod
    def _tag_overlap_score(
        query_tags: Optional[List[str]],
        cap: Dict[str, Any],
    ) -> float:
        """Tag overlap scoring (Jaccard)."""
        if not query_tags:
            return 0.0
        cap_tags = set(cap.get("tags", []))
        if not cap_tags:
            return 0.0
        query_set = set(query_tags)
        intersection = query_set & cap_tags
        union = query_set | cap_tags
        return len(intersection) / len(union) if union else 0.0

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return max(0.0, dot / (norm_a * norm_b))

    def _semantic_score(
        self,
        query_vector: Optional[List[float]],
        cap: Dict[str, Any],
    ) -> float:
        """Semantic similarity via cosine distance."""
        if not query_vector:
            return 0.0
        cap_vector = cap.get("semantic_vector")
        if not cap_vector:
            return 0.0
        return self._cosine_similarity(query_vector, cap_vector)

    def _trust_score(
        self,
        cap: Dict[str, Any],
    ) -> Tuple[float, float, int, float]:
        """Trust & quality scoring.

        Returns (trust_score, success_rate, call_count, rating).
        """
        provider = cap.get("provider", "")
        cid = cap.get("capability_id", "")

        # Reputation (0-100 → 0-1)
        rep = 0.5
        if self._get_reputation:
            rep = min(self._get_reputation(provider) / 100.0, 1.0)

        # Rating (1-5 → 0-1)
        rating = 3.0
        if self._get_rating:
            stats = self._get_rating(cid)
            if stats:
                rating = stats.get("weighted_average", 3.0)
        rating_norm = (rating - 1.0) / 4.0

        # Call stats
        success_rate = 0.5
        call_count = 0
        if self._get_call_stats:
            stats = self._get_call_stats(cid)
            if stats:
                call_count = stats.get("call_count", 0)
                sc = stats.get("success_count", 0)
                fc = stats.get("fail_count", 0)
                total = sc + fc
                success_rate = sc / total if total > 0 else 0.5

        trust = 0.4 * rep + 0.3 * rating_norm + 0.3 * success_rate
        return trust, success_rate, call_count, rating

    @staticmethod
    def _economic_score(
        success_rate: float,
        trust_score: float,
        base_price: float,
    ) -> float:
        """Economic optimization — value = quality / price."""
        if base_price <= 0:
            return 1.0
        value = (success_rate * trust_score) / base_price
        return min(value, 1.0)

    # ── Skill affinity ────────────────────────────────────────────

    def record_affinity(
        self,
        agent_id: str,
        task_key: str,
        capability_id: str,
        success: bool,
    ) -> None:
        """Record a skill usage outcome for affinity learning."""
        if agent_id not in self._affinities:
            self._affinities[agent_id] = {}
        key = f"{task_key}:{capability_id}"
        if key not in self._affinities[agent_id]:
            self._affinities[agent_id][key] = SkillAffinity(
                task_key=task_key,
                capability_id=capability_id,
            )
        aff = self._affinities[agent_id][key]
        if success:
            aff.success_count += 1
        else:
            aff.fail_count += 1
        aff.last_used = int(time.time())

    def _affinity_boost(
        self,
        agent_id: str,
        intents: List[str],
        capability_id: str,
    ) -> float:
        """Return affinity boost (0-1) for a skill based on past success."""
        if agent_id not in self._affinities:
            return 0.0
        best = 0.0
        for intent in intents:
            key = f"{intent}:{capability_id}"
            aff = self._affinities[agent_id].get(key)
            if aff and aff.success_rate > best:
                best = aff.success_rate
        return best

    def get_agent_affinities(self, agent_id: str) -> List[Dict[str, Any]]:
        """Return all skill affinities for an agent."""
        if agent_id not in self._affinities:
            return []
        return [
            {
                "task_key": a.task_key,
                "capability_id": a.capability_id,
                "success_rate": round(a.success_rate, 4),
                "success_count": a.success_count,
                "fail_count": a.fail_count,
                "last_used": a.last_used,
            }
            for a in self._affinities[agent_id].values()
        ]
