"""Tests for Discovery refactor (Items 2-3): Recall/Rank + FeedbackStore."""
import time
import pytest
from oasyce_plugin.services.discovery import (
    SkillDiscoveryEngine,
    DiscoveryCandidate,
    RecallCandidate,
    DiscoveryWeights,
)
from oasyce_plugin.services.discovery.feedback import ExecutionRecord, FeedbackStore


# ── Fixtures ──────────────────────────────────────────────────────

def _make_capabilities():
    return [
        {
            "capability_id": "cap_a",
            "name": "Translator",
            "provider": "provider_1",
            "tags": ["nlp", "translate"],
            "intents": ["translate_text"],
            "base_price": 1.0,
            "semantic_vector": [1.0, 0.0, 0.0],
        },
        {
            "capability_id": "cap_b",
            "name": "Summarizer",
            "provider": "provider_2",
            "tags": ["nlp", "summarize"],
            "intents": ["summarize_text"],
            "base_price": 2.0,
            "semantic_vector": [0.0, 1.0, 0.0],
        },
        {
            "capability_id": "cap_c",
            "name": "Arbiter",
            "provider": "provider_3",
            "tags": ["arbitration", "dispute"],
            "intents": ["dispute_arbitrate"],
            "base_price": 0.5,
            "semantic_vector": [0.0, 0.0, 1.0],
        },
    ]


def _make_engine(caps=None, feedback_store=None):
    return SkillDiscoveryEngine(
        get_capabilities=lambda: caps or _make_capabilities(),
        feedback_store=feedback_store,
    )


# ── Recall tests ──────────────────────────────────────────────────

class TestRecall:
    def test_intent_recall(self):
        engine = _make_engine()
        results = engine._recall(intents=["translate_text"], query_tags=None, semantic_vector=None)
        ids = [r.capability_id for r in results]
        assert "cap_a" in ids

    def test_tag_recall(self):
        engine = _make_engine()
        results = engine._recall(intents=None, query_tags=["nlp"], semantic_vector=None)
        ids = [r.capability_id for r in results]
        assert "cap_a" in ids
        assert "cap_b" in ids

    def test_semantic_recall(self):
        engine = _make_engine()
        results = engine._recall(intents=None, query_tags=None, semantic_vector=[1.0, 0.0, 0.0])
        ids = [r.capability_id for r in results]
        assert "cap_a" in ids

    def test_low_score_filtered(self):
        engine = _make_engine()
        # No signals → nothing recalled
        results = engine._recall(intents=None, query_tags=None, semantic_vector=None)
        assert len(results) == 0

    def test_empty_corpus(self):
        engine = SkillDiscoveryEngine(get_capabilities=lambda: [])
        results = engine._recall(intents=["translate_text"], query_tags=None, semantic_vector=None)
        assert len(results) == 0


# ── Rank tests ────────────────────────────────────────────────────

class TestRank:
    def test_sorted_by_score(self):
        engine = _make_engine()
        results = engine.discover(intents=["translate_text"], query_tags=["nlp"])
        assert len(results) > 0
        scores = [r.final_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_trust_filter(self):
        """Candidates below min_trust_score should be filtered out."""
        def low_rep(provider_id):
            return 0.0  # very low reputation

        engine = SkillDiscoveryEngine(
            get_capabilities=_make_capabilities,
            get_reputation=low_rep,
            weights=DiscoveryWeights(min_trust_score=0.9),
        )
        results = engine.discover(intents=["translate_text"])
        assert len(results) == 0

    def test_affinity_boost(self):
        engine = _make_engine()
        # Record successful affinity
        engine.record_affinity("agent_1", "translate_text", "cap_a", success=True)
        engine.record_affinity("agent_1", "translate_text", "cap_a", success=True)

        with_affinity = engine.discover(intents=["translate_text"], agent_id="agent_1")
        without_affinity = engine.discover(intents=["translate_text"], agent_id=None)

        # cap_a should score higher with affinity
        score_with = next(c.final_score for c in with_affinity if c.capability_id == "cap_a")
        score_without = next(c.final_score for c in without_affinity if c.capability_id == "cap_a")
        assert score_with >= score_without

    def test_feedback_fusion(self):
        store = FeedbackStore()
        # Record great feedback for cap_a
        for _ in range(10):
            store.record(ExecutionRecord(
                skill_id="cap_a", success=True, latency_ms=100, caller_rating=5.0,
            ))
        engine = _make_engine(feedback_store=store)
        results = engine.discover(intents=["translate_text"])
        cap_a = next((c for c in results if c.capability_id == "cap_a"), None)
        assert cap_a is not None
        assert cap_a.trust_score > 0


# ── FeedbackStore tests ──────────────────────────────────────────

class TestFeedbackStore:
    def test_record_and_stats(self):
        store = FeedbackStore()
        store.record(ExecutionRecord("s1", success=True, latency_ms=100, caller_rating=4.0))
        store.record(ExecutionRecord("s1", success=False, latency_ms=200, caller_rating=2.0))
        stats = store.stats("s1")
        assert stats["total"] == 2
        assert stats["successes"] == 1
        assert stats["failures"] == 1

    def test_learned_trust_all_success(self):
        store = FeedbackStore()
        for _ in range(5):
            store.record(ExecutionRecord("s1", success=True, latency_ms=50, caller_rating=5.0))
        trust = store.learned_trust("s1")
        assert trust is not None
        # 0.6 * 1.0 + 0.4 * 1.0 = 1.0
        assert trust > 0.95

    def test_learned_trust_all_failure(self):
        store = FeedbackStore()
        for _ in range(5):
            store.record(ExecutionRecord("s1", success=False, latency_ms=50, caller_rating=0.0))
        trust = store.learned_trust("s1")
        assert trust is not None
        assert trust < 0.05

    def test_learned_trust_none_for_unknown(self):
        store = FeedbackStore()
        assert store.learned_trust("nonexistent") is None

    def test_decay_older_records_matter_less(self):
        store = FeedbackStore()
        now = int(time.time())
        # Old bad records
        for _ in range(5):
            store.record(ExecutionRecord(
                "s1", success=False, latency_ms=100, caller_rating=1.0,
                timestamp=now - 90 * 86400,  # 90 days ago
            ))
        # Recent good records
        for _ in range(5):
            store.record(ExecutionRecord(
                "s1", success=True, latency_ms=50, caller_rating=5.0,
                timestamp=now,
            ))
        trust = store.learned_trust("s1")
        assert trust is not None
        # Should be closer to good (recent) than bad (old)
        assert trust > 0.5

    def test_eviction_over_max(self):
        store = FeedbackStore()
        store.MAX_RECORDS_PER_SKILL = 10
        for i in range(20):
            store.record(ExecutionRecord("s1", success=True, latency_ms=50, caller_rating=4.0))
        stats = store.stats("s1")
        assert stats["total"] == 10

    def test_empty_stats(self):
        store = FeedbackStore()
        stats = store.stats("nonexistent")
        assert stats["total"] == 0


# ── discover() backward compatibility ─────────────────────────────

class TestDiscoverAPI:
    def test_signature_unchanged(self):
        engine = _make_engine()
        results = engine.discover(
            intents=["translate_text"],
            query_tags=["nlp"],
            semantic_vector=[1.0, 0.0, 0.0],
            agent_id="agent_1",
            limit=5,
        )
        assert isinstance(results, list)
        if results:
            assert isinstance(results[0], DiscoveryCandidate)

    def test_discover_arbitrators(self):
        engine = _make_engine()
        results = engine.discover_arbitrators()
        assert len(results) > 0
        ids = [c.capability_id for c in results]
        assert "cap_c" in ids

    def test_record_outcome(self):
        engine = _make_engine()
        engine.record_outcome(
            agent_id="agent_1",
            capability_id="cap_a",
            task_key="translate_text",
            success=True,
            latency_ms=100,
            caller_rating=5.0,
        )
        # Check both feedback store and affinity
        trust = engine.feedback_store.learned_trust("cap_a")
        assert trust is not None
        affinities = engine.get_agent_affinities("agent_1")
        assert len(affinities) == 1
