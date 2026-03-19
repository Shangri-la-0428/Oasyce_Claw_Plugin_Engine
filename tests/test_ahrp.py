"""Tests for AHRP — Agent Handshake & Routing Protocol."""

from __future__ import annotations
import pytest
from oasyce.ahrp import (
    AgentIdentity,
    Capability,
    Need,
    MessageType,
    TxState,
    Transaction,
    ProtocolMessage,
    AnnouncePayload,
    RequestPayload,
    OfferPayload,
    AcceptPayload,
    DeliverPayload,
    ConfirmPayload,
    match_score,
    PROTOCOL_VERSION,
)


class TestAgentIdentity:
    def test_create(self):
        agent = AgentIdentity(agent_id="A1", public_key="abc123")
        assert agent.reputation == 10.0
        assert agent.stake == 0.0

    def test_metadata(self):
        agent = AgentIdentity(agent_id="A1", public_key="abc", metadata={"name": "FinBot"})
        assert agent.metadata["name"] == "FinBot"


class TestCapability:
    def test_defaults(self):
        cap = Capability(capability_id="c1", tags=["finance"])
        assert cap.access_levels == ["L0"]
        assert cap.origin_type == "human"
        assert cap.price_floor == 0.0


class TestMatchScore:
    def test_perfect_tag_match(self):
        need = Need(description="finance", tags=["finance", "SEC"])
        cap = Capability(capability_id="c1", tags=["finance", "SEC"], access_levels=["L0"])
        score = match_score(need, cap)
        assert score > 0.15  # tag component = 0.20 * 1.0

    def test_price_rejection(self):
        need = Need(description="x", max_price=1.0)
        cap = Capability(capability_id="c1", price_floor=2.0)
        assert match_score(need, cap) == 0.0

    def test_semantic_similarity(self):
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [1.0, 0.0, 0.0]
        need = Need(description="x", semantic_vector=vec_a)
        cap = Capability(capability_id="c1", semantic_vector=vec_b, access_levels=["L0"])
        score = match_score(need, cap)
        assert score >= 0.6  # 60% weight * 1.0 similarity

    def test_orthogonal_vectors(self):
        need = Need(description="x", semantic_vector=[1.0, 0.0, 0.0])
        cap = Capability(capability_id="c1", semantic_vector=[0.0, 1.0, 0.0], access_levels=["L0"])
        score = match_score(need, cap)
        assert score < 0.25  # semantic=0, only access+price contribute

    def test_access_level_insufficient_reduces_score(self):
        need = Need(description="x", tags=["data"], required_access_level="L2")
        cap_low = Capability(capability_id="c1", tags=["data"], access_levels=["L0", "L1"])
        cap_high = Capability(capability_id="c2", tags=["data"], access_levels=["L0", "L1", "L2"])
        # Insufficient access level should score lower
        assert match_score(need, cap_low) < match_score(need, cap_high)

    def test_access_level_sufficient(self):
        need = Need(description="x", tags=["data"], required_access_level="L1")
        cap = Capability(capability_id="c1", tags=["data"], access_levels=["L0", "L1", "L2"])
        score = match_score(need, cap)
        assert score > 0.0

    def test_origin_type_bonus(self):
        need = Need(description="x", tags=["med"], preferred_origin_type="human")
        cap_h = Capability(
            capability_id="c1", tags=["med"], origin_type="human", access_levels=["L0"]
        )
        cap_s = Capability(
            capability_id="c2", tags=["med"], origin_type="synthetic", access_levels=["L0"]
        )
        assert match_score(need, cap_h) > match_score(need, cap_s)


class TestTransactionStateMachine:
    def _make_tx(self):
        return Transaction(tx_id="tx-001", buyer="A", seller="B")

    def test_initial_state(self):
        tx = self._make_tx()
        assert tx.state == TxState.OPEN

    def test_full_lifecycle(self):
        tx = self._make_tx()
        tx.advance(MessageType.OFFER)
        assert tx.state == TxState.OFFERED
        tx.advance(MessageType.ACCEPT)
        assert tx.state == TxState.ACCEPTED
        tx.advance(MessageType.DELIVER)
        assert tx.state == TxState.DELIVERED
        tx.advance(MessageType.CONFIRM)
        assert tx.state == TxState.CONFIRMED
        assert tx.settled_at is not None

    def test_invalid_transition(self):
        tx = self._make_tx()
        with pytest.raises(ValueError, match="Invalid transition"):
            tx.advance(MessageType.CONFIRM)  # can't confirm from OPEN

    def test_cannot_skip_steps(self):
        tx = self._make_tx()
        with pytest.raises(ValueError):
            tx.advance(MessageType.DELIVER)  # can't deliver from OPEN


class TestProtocolMessage:
    def test_envelope(self):
        msg = ProtocolMessage(
            message_type=MessageType.REQUEST.value,
            sender="agent-A",
            recipient="*",
        )
        assert msg.protocol_version == PROTOCOL_VERSION
        assert msg.ttl == 300

    def test_directed_message(self):
        msg = ProtocolMessage(
            message_type=MessageType.OFFER.value,
            sender="agent-B",
            recipient="agent-A",
            in_reply_to="req-001",
        )
        assert msg.recipient == "agent-A"


class TestPayloads:
    def test_announce(self):
        payload = AnnouncePayload(
            identity=AgentIdentity(agent_id="A", public_key="pk"),
            capabilities=[Capability(capability_id="c1", tags=["NLP"])],
            endpoints=["https://agent-a.example.com/ahrp"],
        )
        assert len(payload.capabilities) == 1
        assert payload.heartbeat_interval == 600

    def test_request(self):
        payload = RequestPayload(
            need=Need(description="financial analysis", tags=["finance"]),
            budget_oas=5.0,
            request_id="req-001",
        )
        assert payload.budget_oas == 5.0

    def test_offer(self):
        payload = OfferPayload(
            request_id="req-001",
            capability_id="c1",
            price_oas=3.0,
            offer_id="off-001",
        )
        assert payload.price_oas == 3.0

    def test_deliver(self):
        payload = DeliverPayload(
            offer_id="off-001",
            content_hash="sha256:abc123",
            content_ref="ipfs://QmXyz",
            content_size_bytes=1024,
        )
        assert payload.content_ref.startswith("ipfs://")

    def test_confirm_with_rating(self):
        payload = ConfirmPayload(
            offer_id="off-001",
            content_hash_verified=True,
            settlement_tx_id="stx-001",
            rating=5,
        )
        assert payload.rating == 5
