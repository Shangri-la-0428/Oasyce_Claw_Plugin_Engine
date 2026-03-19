"""P2P message types for the Oasyce network.

Every message is JSON-serialisable and signed by its sender.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from oasyce.network.identity import NodeIdentity

MessageType = Literal[
    "ASSET_SUBMIT",
    "VOTE",
    "PEER_EXCHANGE",
    "HEARTBEAT",
    "CAPABILITY_QUERY",
    "CAPABILITY_INVOKE",
    "CAPABILITY_RESULT",
    "CAPABILITY_FAIL",
]


@dataclass
class NetworkMessage:
    """A signed message that travels over the Oasyce gossip network."""

    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    msg_type: MessageType = "HEARTBEAT"
    sender_id: str = ""  # node_id (public key hex) of the sender
    timestamp: float = field(default_factory=time.time)
    ttl: int = 5  # remaining hops
    payload: dict[str, Any] = field(default_factory=dict)
    signature: str = ""  # hex-encoded Ed25519 signature

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def signable_bytes(self) -> bytes:
        """Canonical byte representation used for signing.

        Excludes ``signature`` and ``ttl`` — TTL is a transport-layer field
        that relay nodes decrement, so it must not be part of the signed
        content.
        """
        obj = {
            "msg_id": self.msg_id,
            "msg_type": self.msg_type,
            "sender_id": self.sender_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }
        return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NetworkMessage:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_json(cls, raw: str) -> NetworkMessage:
        return cls.from_dict(json.loads(raw))

    # ------------------------------------------------------------------
    # Signing helpers
    # ------------------------------------------------------------------

    def sign(self, identity: NodeIdentity) -> None:
        """Sign this message in-place using *identity*."""
        self.sender_id = identity.node_id
        self.signature = identity.sign(self.signable_bytes())

    def verify_signature(self) -> bool:
        """Verify the message signature against sender_id."""
        return NodeIdentity.verify(self.sender_id, self.signable_bytes(), self.signature)

    # ------------------------------------------------------------------
    # Dedup hash
    # ------------------------------------------------------------------

    @property
    def msg_hash(self) -> str:
        """Deterministic hash for dedup (based on msg_id)."""
        return NodeIdentity.hash_message(self.msg_id.encode())


# ------------------------------------------------------------------
# Factory helpers
# ------------------------------------------------------------------


def make_asset_submit(
    identity: NodeIdentity,
    media_hash: str,
    creator: str,
    metadata: dict[str, str] | None = None,
    ttl: int = 5,
) -> NetworkMessage:
    """Create a signed ASSET_SUBMIT message."""
    msg = NetworkMessage(
        msg_type="ASSET_SUBMIT",
        ttl=ttl,
        payload={
            "media_hash": media_hash,
            "creator": creator,
            "metadata": metadata or {},
        },
    )
    msg.sign(identity)
    return msg


def make_vote(
    identity: NodeIdentity,
    asset_msg_id: str,
    accept: bool,
    reason: str = "",
    ttl: int = 5,
) -> NetworkMessage:
    """Create a signed VOTE message for a given asset submission."""
    msg = NetworkMessage(
        msg_type="VOTE",
        ttl=ttl,
        payload={
            "asset_msg_id": asset_msg_id,
            "accept": accept,
            "reason": reason,
        },
    )
    msg.sign(identity)
    return msg


def make_peer_exchange(
    identity: NodeIdentity,
    peers: list[str],
    ttl: int = 2,
    sender_address: str = "",
) -> NetworkMessage:
    """Create a signed PEER_EXCHANGE message listing known peers (host:port)."""
    payload: dict[str, Any] = {"peers": peers}
    if sender_address:
        payload["sender_address"] = sender_address
    msg = NetworkMessage(
        msg_type="PEER_EXCHANGE",
        ttl=ttl,
        payload=payload,
    )
    msg.sign(identity)
    return msg


def make_heartbeat(identity: NodeIdentity, ttl: int = 1) -> NetworkMessage:
    """Create a signed HEARTBEAT message."""
    msg = NetworkMessage(
        msg_type="HEARTBEAT",
        ttl=ttl,
        payload={},
    )
    msg.sign(identity)
    return msg
