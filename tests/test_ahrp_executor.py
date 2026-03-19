"""Tests for AHRP Executor — full transaction lifecycle with settlement."""

from __future__ import annotations
import pytest
from oasyce.ahrp import (
    AgentIdentity,
    AnnouncePayload,
    Capability,
    ConfirmPayload,
    DeliverPayload,
    Need,
    OfferPayload,
    TxState,
)
from oasyce.ahrp.executor import AHRPExecutor


@pytest.fixture
def network():
    """Set up a two-agent network."""
    ex = AHRPExecutor(require_signature=False)

    # Agent A: buyer (data consumer)
    ex.handle_announce(
        AnnouncePayload(
            identity=AgentIdentity(
                agent_id="alice", public_key="pk-a", reputation=50.0, stake=1000.0
            ),
            capabilities=[
                Capability(
                    capability_id="nlp-analysis", tags=["NLP", "sentiment"], origin_type="curated"
                )
            ],
            endpoints=["https://alice.example.com"],
        )
    )

    # Agent B: seller (data provider)
    ex.handle_announce(
        AnnouncePayload(
            identity=AgentIdentity(
                agent_id="bob", public_key="pk-b", reputation=60.0, stake=2000.0
            ),
            capabilities=[
                Capability(
                    capability_id="financial-data",
                    tags=["finance", "SEC", "quarterly"],
                    access_levels=["L0", "L1", "L2"],
                    price_floor=2.0,
                    origin_type="human",
                ),
            ],
            endpoints=["https://bob.example.com"],
        )
    )
    return ex


class TestAgentRegistry:
    def test_announce_registers_agent(self, network):
        assert "alice" in network.agents
        assert "bob" in network.agents
        assert len(network.capabilities["bob"]) == 1

    def test_stats_after_announce(self, network):
        stats = network.stats()
        assert stats["registered_agents"] == 2
        assert stats["total_capabilities"] == 2


class TestMatchmaking:
    def test_find_matches_by_tags(self, network):
        need = Need(description="financial analysis", tags=["finance", "SEC"])
        matches = network.find_matches(need, requester_id="alice")
        assert len(matches) >= 1
        assert matches[0]["agent_id"] == "bob"

    def test_no_self_match(self, network):
        need = Need(description="NLP", tags=["NLP"])
        matches = network.find_matches(need, requester_id="alice")
        assert all(m["agent_id"] != "alice" for m in matches)

    def test_reputation_filter(self, network):
        need = Need(description="finance", tags=["finance"], min_reputation=99.0)
        matches = network.find_matches(need, requester_id="alice")
        assert len(matches) == 0  # bob has rep 60, below 99

    def test_origin_type_in_results(self, network):
        need = Need(description="finance", tags=["finance"])
        matches = network.find_matches(need, requester_id="alice")
        assert matches[0]["origin_type"] == "human"


class TestFullLifecycle:
    def test_accept_to_confirm(self, network):
        """Full 6-step transaction lifecycle."""
        # Step 1-2: ANNOUNCE already done in fixture
        # Step 3: Alice finds Bob
        need = Need(description="financial data", tags=["finance"])
        matches = network.find_matches(need, requester_id="alice")
        assert len(matches) >= 1

        # Step 4: Bob sends OFFER (simulated)
        offer = OfferPayload(
            request_id="req-001",
            capability_id="financial-data",
            price_oas=5.0,
            access_level="L1",
            offer_id="off-001",
        )

        # Step 5: Alice ACCEPTs → escrow locked
        tx = network.handle_accept(
            buyer_id="alice",
            seller_id="bob",
            offer=offer,
        )
        assert tx.state == TxState.ACCEPTED
        assert tx.tx_id in network.escrows
        assert not network.escrows[tx.tx_id].released

        # Step 6: Bob DELIVERs
        tx = network.handle_deliver(
            tx_id=tx.tx_id,
            deliver=DeliverPayload(
                offer_id="off-001",
                content_hash="sha256:abc123def",
                content_ref="ipfs://QmFinancialData",
                content_size_bytes=4096,
            ),
        )
        assert tx.state == TxState.DELIVERED

        # Step 7: Alice CONFIRMs → escrow released, reputation updated
        alice_rep_before = network.agents["alice"].reputation
        bob_rep_before = network.agents["bob"].reputation

        tx = network.handle_confirm(
            tx_id=tx.tx_id,
            confirm=ConfirmPayload(
                offer_id="off-001",
                content_hash_verified=True,
                rating=5,
            ),
        )
        assert tx.state == TxState.CONFIRMED
        assert tx.settled_at is not None
        assert network.escrows[tx.tx_id].released

        # Reputation increased for both parties
        assert network.agents["alice"].reputation > alice_rep_before
        assert network.agents["bob"].reputation > bob_rep_before

    def test_stats_after_transaction(self, network):
        offer = OfferPayload(
            request_id="req-002",
            capability_id="financial-data",
            price_oas=3.0,
            offer_id="off-002",
        )
        tx = network.handle_accept("alice", "bob", offer)
        network.handle_deliver(
            tx.tx_id,
            DeliverPayload(
                offer_id="off-002",
                content_hash="sha256:xyz",
            ),
        )
        network.handle_confirm(
            tx.tx_id,
            ConfirmPayload(
                offer_id="off-002",
                content_hash_verified=True,
            ),
        )

        stats = network.stats()
        assert stats["completed_transactions"] == 1
        assert stats["total_volume_oas"] == 3.0
        assert stats["active_transactions"] == 0

    def test_multiple_transactions(self, network):
        """Two sequential transactions between same agents."""
        for i in range(3):
            offer = OfferPayload(
                request_id=f"req-{i}",
                capability_id="financial-data",
                price_oas=1.0,
                offer_id=f"off-{i}",
            )
            tx = network.handle_accept("alice", "bob", offer)
            network.handle_deliver(
                tx.tx_id,
                DeliverPayload(
                    offer_id=f"off-{i}",
                    content_hash=f"hash-{i}",
                ),
            )
            network.handle_confirm(
                tx.tx_id,
                ConfirmPayload(
                    offer_id=f"off-{i}",
                    content_hash_verified=True,
                ),
            )

        stats = network.stats()
        assert stats["completed_transactions"] == 3


class TestErrorHandling:
    def test_deliver_unknown_tx(self, network):
        with pytest.raises(ValueError, match="not found"):
            network.handle_deliver("tx-nonexistent", DeliverPayload())

    def test_confirm_unknown_tx(self, network):
        with pytest.raises(ValueError, match="not found"):
            network.handle_confirm("tx-nonexistent", ConfirmPayload())

    def test_invalid_state_transition(self, network):
        """Can't confirm before deliver."""
        offer = OfferPayload(
            request_id="req-err",
            capability_id="financial-data",
            price_oas=1.0,
            offer_id="off-err",
        )
        tx = network.handle_accept("alice", "bob", offer)
        with pytest.raises(ValueError, match="Invalid transition"):
            network.handle_confirm(
                tx.tx_id,
                ConfirmPayload(
                    offer_id="off-err",
                    content_hash_verified=True,
                ),
            )
