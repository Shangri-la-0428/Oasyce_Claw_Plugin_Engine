"""Tests for Ed25519 signature verification in AHRP protocol messages."""

from __future__ import annotations

import hashlib
import json

import pytest

from oasyce.crypto.keys import generate_keypair, sign
from oasyce.ahrp import (
    AgentIdentity,
    AnnouncePayload,
    Capability,
    ConfirmPayload,
    DeliverPayload,
    MessageType,
    OfferPayload,
    ProtocolMessage,
    TxState,
)
from oasyce.ahrp.executor import AHRPExecutor


# ── Helpers ──────────────────────────────────────────────────────────


def _make_identity(priv: str, pub: str, **kwargs):
    return AgentIdentity.from_keypair(priv, pub, **kwargs)


def _make_announce_payload(identity: AgentIdentity):
    return AnnouncePayload(
        identity=identity,
        capabilities=[
            Capability(
                capability_id=f"cap-{identity.agent_id}",
                tags=["finance"],
                price_floor=1.0,
                access_levels=["L0", "L1"],
            ),
        ],
        endpoints=[f"https://{identity.agent_id}.example.com"],
    )


def _signed_announce(identity: AgentIdentity, priv: str):
    payload = _make_announce_payload(identity)
    msg = ProtocolMessage.create_signed(
        message_type=MessageType.ANNOUNCE,
        sender=identity.agent_id,
        recipient="*",
        payload_dict={"identity": identity.agent_id},
        private_key_hex=priv,
    )
    return payload, msg


# ── ProtocolMessage sign/verify ──────────────────────────────────────


class TestSignAndVerify:
    def test_sign_and_verify_roundtrip(self):
        priv, pub = generate_keypair()
        msg = ProtocolMessage.create_signed(
            message_type=MessageType.ANNOUNCE,
            sender="agent-1",
            recipient="*",
            payload_dict={"hello": "world"},
            private_key_hex=priv,
        )
        assert msg.signature != ""
        assert msg.verify_signature(pub)

    def test_tampered_payload_fails_verification(self):
        priv, pub = generate_keypair()
        msg = ProtocolMessage.create_signed(
            message_type=MessageType.ANNOUNCE,
            sender="agent-1",
            recipient="*",
            payload_dict={"data": "original"},
            private_key_hex=priv,
        )
        # Tamper with the payload after signing
        msg.payload["data"] = "tampered"
        assert not msg.verify_signature(pub)

    def test_wrong_key_fails_verification(self):
        priv1, pub1 = generate_keypair()
        _priv2, pub2 = generate_keypair()
        msg = ProtocolMessage.create_signed(
            message_type=MessageType.ANNOUNCE,
            sender="agent-1",
            recipient="*",
            payload_dict={"x": 1},
            private_key_hex=priv1,
        )
        # Signed with priv1 but verified with pub2
        assert not msg.verify_signature(pub2)
        # Correct key still works
        assert msg.verify_signature(pub1)

    def test_unsigned_message_fails_verification(self):
        _priv, pub = generate_keypair()
        msg = ProtocolMessage(
            message_type=MessageType.ANNOUNCE,
            sender="agent-1",
            recipient="*",
            payload={"x": 1},
        )
        assert msg.signature == ""
        assert not msg.verify_signature(pub)

    def test_signing_is_deterministic(self):
        """Same message content → same signature."""
        priv, pub = generate_keypair()
        kwargs = dict(
            message_type=MessageType.REQUEST,
            sender="a",
            recipient="b",
            payload_dict={"q": "test"},
            private_key_hex=priv,
            timestamp=1000,
        )
        msg1 = ProtocolMessage.create_signed(**kwargs)
        msg2 = ProtocolMessage.create_signed(**kwargs)
        assert msg1.signature == msg2.signature

    def test_payload_sort_keys(self):
        """Payload key order should not affect signature."""
        priv, pub = generate_keypair()
        msg1 = ProtocolMessage(
            message_type="test",
            sender="a",
            recipient="b",
            payload={"z": 1, "a": 2},
            timestamp=100,
        )
        msg1.sign_message(priv)

        msg2 = ProtocolMessage(
            message_type="test",
            sender="a",
            recipient="b",
            payload={"a": 2, "z": 1},
            timestamp=100,
        )
        msg2.sign_message(priv)
        assert msg1.signature == msg2.signature


# ── Executor signature enforcement ───────────────────────────────────


class TestExecutorRejectsUnsigned:
    def test_executor_rejects_unsigned_announce(self):
        ex = AHRPExecutor(require_signature=True)
        priv, pub = generate_keypair()
        identity = _make_identity(priv, pub, reputation=50.0, stake=1000.0)
        payload = _make_announce_payload(identity)
        with pytest.raises(ValueError, match="Signature required"):
            ex.handle_announce(payload)  # no signed_message

    def test_executor_rejects_bad_signature_announce(self):
        ex = AHRPExecutor(require_signature=True)
        priv, pub = generate_keypair()
        _priv2, _pub2 = generate_keypair()
        identity = _make_identity(priv, pub, reputation=50.0, stake=1000.0)
        payload = _make_announce_payload(identity)
        # Sign with wrong key
        msg = ProtocolMessage.create_signed(
            message_type=MessageType.ANNOUNCE,
            sender=identity.agent_id,
            recipient="*",
            payload_dict={"identity": identity.agent_id},
            private_key_hex=_priv2,
        )
        with pytest.raises(ValueError, match="Invalid signature"):
            ex.handle_announce(payload, signed_message=msg)


class TestExecutorAcceptsSigned:
    def test_executor_accepts_signed_announce(self):
        ex = AHRPExecutor(require_signature=True)
        priv, pub = generate_keypair()
        identity = _make_identity(priv, pub, reputation=50.0, stake=1000.0)
        payload, msg = _signed_announce(identity, priv)

        agent_id = ex.handle_announce(payload, signed_message=msg)
        assert agent_id == identity.agent_id
        assert agent_id in ex.agents


class TestExecutorBackwardCompat:
    def test_executor_backward_compat(self):
        """require_signature=False allows unsigned messages."""
        ex = AHRPExecutor(require_signature=False)
        identity = AgentIdentity(
            agent_id="legacy-agent",
            public_key="fake-key",
            reputation=50.0,
            stake=1000.0,
        )
        payload = _make_announce_payload(identity)
        # No signed_message — should work fine
        agent_id = ex.handle_announce(payload)
        assert agent_id == "legacy-agent"


# ── AgentIdentity.from_keypair ───────────────────────────────────────


class TestAgentIdentityFromKeypair:
    def test_agent_identity_from_keypair_deterministic(self):
        priv, pub = generate_keypair()
        id1 = AgentIdentity.from_keypair(priv, pub, reputation=10.0)
        id2 = AgentIdentity.from_keypair(priv, pub, reputation=20.0)
        # Same keys → same agent_id
        assert id1.agent_id == id2.agent_id
        expected = hashlib.sha256(pub.encode()).hexdigest()[:16]
        assert id1.agent_id == expected

    def test_different_keys_different_ids(self):
        priv1, pub1 = generate_keypair()
        priv2, pub2 = generate_keypair()
        id1 = AgentIdentity.from_keypair(priv1, pub1)
        id2 = AgentIdentity.from_keypair(priv2, pub2)
        assert id1.agent_id != id2.agent_id


# ── Full signed transaction flow ─────────────────────────────────────


class TestSignedTransactionFullFlow:
    def test_signed_transaction_full_flow(self):
        """announce → accept → deliver → confirm, all signed."""
        ex = AHRPExecutor(require_signature=True)

        # Generate keys for buyer and seller
        buyer_priv, buyer_pub = generate_keypair()
        seller_priv, seller_pub = generate_keypair()
        buyer = _make_identity(buyer_priv, buyer_pub, reputation=50.0, stake=1000.0)
        seller = _make_identity(seller_priv, seller_pub, reputation=60.0, stake=2000.0)

        # Seller has a capability
        seller_payload = AnnouncePayload(
            identity=seller,
            capabilities=[
                Capability(
                    capability_id="financial-data",
                    tags=["finance", "SEC"],
                    access_levels=["L0", "L1", "L2"],
                    price_floor=2.0,
                    origin_type="human",
                ),
            ],
            endpoints=["https://seller.example.com"],
        )

        # ANNOUNCE buyer
        buyer_payload, buyer_msg = _signed_announce(buyer, buyer_priv)
        ex.handle_announce(buyer_payload, signed_message=buyer_msg)

        # ANNOUNCE seller
        seller_announce_msg = ProtocolMessage.create_signed(
            message_type=MessageType.ANNOUNCE,
            sender=seller.agent_id,
            recipient="*",
            payload_dict={"identity": seller.agent_id},
            private_key_hex=seller_priv,
        )
        ex.handle_announce(seller_payload, signed_message=seller_announce_msg)

        assert buyer.agent_id in ex.agents
        assert seller.agent_id in ex.agents

        # ACCEPT — buyer accepts an offer
        offer = OfferPayload(
            request_id="req-001",
            capability_id="financial-data",
            price_oas=5.0,
            access_level="L1",
            offer_id="off-001",
        )
        accept_msg = ProtocolMessage.create_signed(
            message_type=MessageType.ACCEPT,
            sender=buyer.agent_id,
            recipient=seller.agent_id,
            payload_dict={"offer_id": "off-001"},
            private_key_hex=buyer_priv,
        )
        tx = ex.handle_accept(
            buyer_id=buyer.agent_id,
            seller_id=seller.agent_id,
            offer=offer,
            signed_message=accept_msg,
        )
        assert tx.state == TxState.ACCEPTED

        # DELIVER — seller delivers
        deliver_msg = ProtocolMessage.create_signed(
            message_type=MessageType.DELIVER,
            sender=seller.agent_id,
            recipient=buyer.agent_id,
            payload_dict={"offer_id": "off-001", "content_hash": "sha256:abc"},
            private_key_hex=seller_priv,
        )
        tx = ex.handle_deliver(
            tx_id=tx.tx_id,
            deliver=DeliverPayload(
                offer_id="off-001",
                content_hash="sha256:abc",
                content_ref="ipfs://QmData",
                content_size_bytes=4096,
            ),
            signed_message=deliver_msg,
        )
        assert tx.state == TxState.DELIVERED

        # CONFIRM — buyer confirms
        confirm_msg = ProtocolMessage.create_signed(
            message_type=MessageType.CONFIRM,
            sender=buyer.agent_id,
            recipient=seller.agent_id,
            payload_dict={"offer_id": "off-001", "verified": True},
            private_key_hex=buyer_priv,
        )
        tx = ex.handle_confirm(
            tx_id=tx.tx_id,
            confirm=ConfirmPayload(
                offer_id="off-001",
                content_hash_verified=True,
                rating=5,
            ),
            signed_message=confirm_msg,
        )
        assert tx.state == TxState.CONFIRMED
        assert tx.settled_at is not None
