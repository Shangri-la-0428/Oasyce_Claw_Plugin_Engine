"""Tests for AHRP persistence layer — agents, escrows survive restart."""

import pytest

from oasyce.ahrp import AgentIdentity, AnnouncePayload, Capability
from oasyce.ahrp.persistence import AHRPStore
from oasyce.ahrp.executor import AHRPExecutor, EscrowRecord
from oasyce.config import NetworkMode


def _make_agent(agent_id="agent-1", stake=200.0):
    return AgentIdentity(
        agent_id=agent_id,
        public_key="pub_" + agent_id,
        reputation=50.0,
        stake=stake,
        metadata={"name": "test-agent"},
    )


def _make_caps():
    return [
        Capability(
            capability_id="cap-1",
            tags=["nlp", "translation"],
            description="Translate text",
            price_floor=0.5,
        ),
    ]


class TestAHRPStore:
    def test_save_and_load_agent(self):
        store = AHRPStore(":memory:")
        agent = _make_agent()
        store.save_agent(agent, ["http://localhost:8080"], announce_count=3)

        agents = store.load_agents()
        assert "agent-1" in agents
        identity, endpoints, count = agents["agent-1"]
        assert identity.agent_id == "agent-1"
        assert identity.stake == 200.0
        assert endpoints == ["http://localhost:8080"]
        assert count == 3

    def test_save_and_load_capabilities(self):
        store = AHRPStore(":memory:")
        caps = _make_caps()
        store.save_capabilities("agent-1", caps)

        loaded = store.load_capabilities()
        assert "agent-1" in loaded
        assert len(loaded["agent-1"]) == 1
        assert loaded["agent-1"][0].capability_id == "cap-1"
        assert loaded["agent-1"][0].tags == ["nlp", "translation"]
        assert loaded["agent-1"][0].price_floor == 0.5

    def test_save_and_load_escrow(self):
        store = AHRPStore(":memory:")
        store.save_escrow(
            tx_id="tx-001", buyer="alice", seller="bob",
            amount_oas=10.0, locked_at=1000, released=False,
            chain_escrow_id="chain-abc",
        )

        escrows = store.load_escrows()
        assert len(escrows) == 1
        assert escrows[0]["tx_id"] == "tx-001"
        assert escrows[0]["amount_oas"] == 10.0
        assert escrows[0]["released"] is False

    def test_update_escrow_released(self):
        store = AHRPStore(":memory:")
        store.save_escrow("tx-001", "a", "b", 5.0, 1000)
        store.update_escrow_released("tx-001", True)

        escrows = store.load_escrows()
        assert escrows[0]["released"] is True

    def test_save_and_load_auction(self):
        store = AHRPStore(":memory:")
        store.save_auction(
            request_id="req-1", requester_id="alice",
            budget_oas=50.0, deadline=9999,
            bids=[{"provider": "bob", "price": 30.0}],
            closed=False,
        )

        auctions = store.load_auctions()
        assert len(auctions) == 1
        assert auctions[0]["request_id"] == "req-1"
        assert auctions[0]["bids"][0]["provider"] == "bob"
        assert auctions[0]["closed"] is False

    def test_delete_agent_cascades_capabilities(self):
        store = AHRPStore(":memory:")
        agent = _make_agent()
        store.save_agent(agent, [])
        store.save_capabilities("agent-1", _make_caps())

        store.delete_agent("agent-1")
        assert "agent-1" not in store.load_agents()
        assert "agent-1" not in store.load_capabilities()

    def test_stats(self):
        store = AHRPStore(":memory:")
        store.save_agent(_make_agent(), [])
        store.save_escrow("tx-1", "a", "b", 5.0, 1000)

        s = store.stats()
        assert s["agents"] == 1
        assert s["escrows"] == 1
        assert s["transactions"] == 0
        assert s["auctions"] == 0


class TestExecutorPersistence:
    def test_announce_persists_agent(self):
        """Agents registered via handle_announce survive executor recreation."""
        executor = AHRPExecutor(
            require_signature=False,
            network_mode=NetworkMode.LOCAL,
            db_path=":memory:",
        )
        payload = AnnouncePayload(
            identity=_make_agent(stake=200.0),
            capabilities=_make_caps(),
            endpoints=["http://localhost:9000"],
        )
        executor.handle_announce(payload)

        # Verify persisted in store
        agents = executor._store.load_agents()
        assert "agent-1" in agents
        caps = executor._store.load_capabilities()
        assert "agent-1" in caps

    def test_no_persistence_without_db_path(self):
        """Default executor (no db_path) has no store."""
        executor = AHRPExecutor(
            require_signature=False,
            network_mode=NetworkMode.LOCAL,
        )
        assert executor._store is None

    def test_escrow_persists_on_accept(self):
        """Escrow created in handle_accept is written to store."""
        from oasyce.ahrp import OfferPayload

        executor = AHRPExecutor(
            require_signature=False,
            network_mode=NetworkMode.LOCAL,
            db_path=":memory:",
        )
        # Register agents first
        for aid in ["buyer-1", "seller-1"]:
            executor.agents[aid] = _make_agent(aid, stake=200.0)

        offer = OfferPayload(
            request_id="req-1",
            capability_id="cap-1",
            price_oas=5.0,
        )
        tx = executor.handle_accept("buyer-1", "seller-1", offer)

        escrows = executor._store.load_escrows()
        assert len(escrows) == 1
        assert escrows[0]["buyer"] == "buyer-1"
        assert escrows[0]["amount_oas"] == 5.0
