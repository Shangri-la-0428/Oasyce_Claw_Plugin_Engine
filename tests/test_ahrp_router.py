"""Tests for AHRP Router — capability search and request routing."""

from __future__ import annotations
import time
import pytest
from oasyce.ahrp import (
    AgentIdentity,
    AnnouncePayload,
    Capability,
    Need,
    RequestPayload,
)
from oasyce.ahrp.router import Router


def _make_announce(agent_id, tags, price=0.0, origin="human", rep=50.0, access=None):
    return AnnouncePayload(
        identity=AgentIdentity(agent_id=agent_id, public_key=f"pk-{agent_id}", reputation=rep),
        capabilities=[
            Capability(
                capability_id=f"cap-{agent_id}",
                tags=tags,
                price_floor=price,
                origin_type=origin,
                access_levels=access or ["L0", "L1"],
            )
        ],
        endpoints=[f"https://{agent_id}.example.com"],
    )


@pytest.fixture
def router():
    r = Router()
    r.announce(_make_announce("alice", ["NLP", "sentiment"], price=1.0, origin="curated", rep=70.0))
    r.announce(
        _make_announce("bob", ["finance", "SEC", "quarterly"], price=2.0, origin="human", rep=80.0)
    )
    r.announce(_make_announce("carol", ["finance", "crypto"], price=0.5, origin="sensor", rep=40.0))
    r.announce(
        _make_announce(
            "dave",
            ["medical", "genomics"],
            price=5.0,
            origin="human",
            rep=90.0,
            access=["L0", "L1", "L2"],
        )
    )
    r.announce(
        _make_announce("eve", ["NLP", "translation"], price=0.1, origin="synthetic", rep=20.0)
    )
    return r


class TestAnnounce:
    def test_register(self, router):
        assert router.stats()["total_agents"] == 5

    def test_refresh(self, router):
        router.announce(_make_announce("alice", ["NLP", "sentiment", "new-tag"], rep=75.0))
        record = router._agents["alice"]
        assert record.announce_count == 2
        assert "new-tag" in record.capabilities[0].tags
        assert record.identity.reputation == 75.0

    def test_remove(self, router):
        assert router.remove("eve")
        assert router.stats()["total_agents"] == 4
        assert not router.remove("nonexistent")


class TestSearch:
    def test_search_by_tag(self, router):
        results = router.search(tags=["finance"])
        assert len(results) == 2  # bob + carol
        assert results[0]["agent_id"] == "bob"  # higher rep

    def test_search_by_origin(self, router):
        results = router.search(origin_type="human")
        assert all(r["origin_type"] == "human" for r in results)
        assert len(results) == 2  # bob + dave

    def test_search_by_price(self, router):
        results = router.search(max_price=1.0)
        assert all(r["price_floor"] <= 1.0 for r in results)

    def test_search_by_reputation(self, router):
        results = router.search(min_reputation=60.0)
        assert all(r["reputation"] >= 60.0 for r in results)

    def test_search_combined_filters(self, router):
        results = router.search(tags=["finance"], origin_type="human", min_reputation=50.0)
        assert len(results) == 1
        assert results[0]["agent_id"] == "bob"

    def test_search_top_k(self, router):
        results = router.search(top_k=2)
        assert len(results) == 2

    def test_unique_tags(self, router):
        stats = router.stats()
        assert (
            stats["unique_tags"] >= 8
        )  # NLP, sentiment, finance, SEC, quarterly, crypto, medical, genomics, translation


class TestRoute:
    def test_route_basic(self, router):
        req = RequestPayload(
            need=Need(description="financial analysis", tags=["finance"]),
            budget_oas=10.0,
            request_id="req-001",
        )
        matches = router.route(req, requester_id="alice")
        assert len(matches) >= 1
        # bob should rank higher (more tag overlap + higher rep)
        agent_ids = [m["agent_id"] for m in matches]
        assert "bob" in agent_ids

    def test_route_stores_request(self, router):
        req = RequestPayload(
            need=Need(description="NLP", tags=["NLP"]),
            budget_oas=5.0,
            request_id="req-002",
        )
        router.route(req, requester_id="bob")
        assert "req-002" in router._requests
        assert router.stats()["pending_requests"] == 1

    def test_route_excludes_self(self, router):
        req = RequestPayload(
            need=Need(description="NLP", tags=["NLP"]),
            budget_oas=5.0,
            request_id="req-003",
        )
        matches = router.route(req, requester_id="alice")
        assert all(m["agent_id"] != "alice" for m in matches)

    def test_route_reputation_filter(self, router):
        req = RequestPayload(
            need=Need(description="finance", tags=["finance"], min_reputation=70.0),
            budget_oas=10.0,
            request_id="req-004",
        )
        matches = router.route(req, requester_id="alice")
        assert all(router._agents[m["agent_id"]].identity.reputation >= 70.0 for m in matches)


class TestReverseMatch:
    def test_new_announce_matches_pending(self, router):
        # Alice posts a request for medical data
        req = RequestPayload(
            need=Need(description="medical", tags=["medical", "imaging"]),
            budget_oas=20.0,
            request_id="req-reverse",
        )
        router.route(req, requester_id="alice")

        # New agent Frank announces with medical imaging capability
        router.announce(
            _make_announce("frank", ["medical", "imaging", "radiology"], price=3.0, rep=85.0)
        )
        pending = router.check_pending_requests("frank")
        assert len(pending) >= 1
        assert pending[0][0] == "req-reverse"
        assert pending[0][1] > 0.0


class TestGC:
    def test_gc_expired_agents(self):
        r = Router()
        # Announce with very short heartbeat
        payload = AnnouncePayload(
            identity=AgentIdentity(agent_id="temp", public_key="pk"),
            capabilities=[Capability(capability_id="c1", tags=["test"])],
            endpoints=[],
            heartbeat_interval=1,  # 1 second
        )
        r.announce(payload)
        # Manually set last_seen to the past
        r._agents["temp"].last_seen = int(time.time()) - 10
        assert not r._agents["temp"].is_alive
        removed = r.gc()
        assert removed == 1
        assert "temp" not in r._agents

    def test_gc_expired_requests(self):
        r = Router()
        r.announce(_make_announce("bob", ["finance"]))
        req = RequestPayload(
            need=Need(description="x", tags=["finance"]),
            budget_oas=1.0,
            request_id="req-expire",
            deadline=int(time.time()) - 10,  # already expired
        )
        r.route(req, requester_id="alice")  # alice not registered but that's ok for routing
        removed = r.gc()
        assert removed >= 1
        assert "req-expire" not in r._requests
