"""
AHRP — Agent Handshake & Routing Protocol

The minimum viable protocol for two stranger agents to discover each other,
negotiate terms, and complete a data transaction on the Oasyce network.

Design principles:
  1. Six messages to complete a transaction (ANNOUNCE → REQUEST → OFFER → ACCEPT → DELIVER → CONFIRM)
  2. Protocol is transport-agnostic (works over HTTP, WebSocket, P2P, carrier pigeon)
  3. Settlement delegated to Oasyce core (bond, escrow, fee split)
  4. Capability discovery is semantic (vector-based matching, not rigid categories)
  5. Every message is signed — identity is cryptographic, not social
"""

from __future__ import annotations

import enum
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Protocol Version ─────────────────────────────────────────────────
PROTOCOL_VERSION = "ahrp/0.1"


# ── Message Types ────────────────────────────────────────────────────
class MessageType(str, enum.Enum):
    """The six AHRP primitives + four capability extensions."""

    ANNOUNCE = "announce"  # "I exist, here's what I can do"
    REQUEST = "request"  # "I need X, willing to pay Y"
    OFFER = "offer"  # "I can provide X for Y"
    ACCEPT = "accept"  # "Deal. Lock escrow."
    DELIVER = "deliver"  # "Here's the result"
    CONFIRM = "confirm"  # "Received. Release payment."

    # Phase 2 — Capability invocation extensions
    CAPABILITY_QUERY = "capability_query"  # Consumer → Network: discover
    CAPABILITY_INVOKE = "capability_invoke"  # Consumer → Provider: invoke
    CAPABILITY_RESULT = "capability_result"  # Provider → Consumer: result
    CAPABILITY_FAIL = "capability_fail"  # Provider → Consumer: failure


# ── Agent Identity ───────────────────────────────────────────────────
@dataclass
class AgentIdentity:
    """Cryptographic identity of an agent on the network.

    agent_id:   Deterministic hash of public key (not human-chosen)
    public_key: Ed25519 public key (hex)
    reputation: Current R score on Oasyce network [0, 100]
    stake:      OAS staked (anti-sybil, min 100 OAS to create identity)
    """

    agent_id: str
    public_key: str
    reputation: float = 10.0
    stake: float = 0.0
    metadata: Dict[str, str] = field(default_factory=dict)  # name, version, etc.

    @classmethod
    def from_keypair(
        cls,
        private_key_hex: str,
        public_key_hex: str,
        **kwargs: Any,
    ) -> "AgentIdentity":
        """Create an identity with agent_id = sha256(public_key_hex)[:16]."""
        agent_id = hashlib.sha256(public_key_hex.encode()).hexdigest()[:16]
        return cls(agent_id=agent_id, public_key=public_key_hex, **kwargs)


# ── Capability Descriptor ────────────────────────────────────────────
@dataclass
class Capability:
    """What an agent can provide.

    Instead of rigid categories ("finance", "code", "translation"),
    capabilities are described as semantic vectors + free-text tags.
    Matching is cosine-similarity based — agents don't need to agree
    on a taxonomy, they just need to be close in embedding space.

    Example:
        tags: ["financial-analysis", "SEC-filings", "quarterly-reports"]
        semantic_vector: [0.12, -0.34, ...]  (embedding of capability description)
        access_levels: ["L0", "L1"]  (what tiers of data access this agent provides)
        price_floor: 0.5  (minimum OAS per request)
    """

    capability_id: str
    tags: List[str] = field(default_factory=list)
    description: str = ""
    semantic_vector: Optional[List[float]] = None
    access_levels: List[str] = field(default_factory=lambda: ["L0"])
    price_floor: float = 0.0
    origin_type: str = "human"  # human/sensor/curated/synthetic — affects pricing weight


# ── Need Descriptor ──────────────────────────────────────────────────
@dataclass
class Need:
    """What an agent is looking for.

    Mirror structure of Capability, so matching is symmetric:
    match_score = cosine_similarity(need.semantic_vector, capability.semantic_vector)
    """

    description: str
    tags: List[str] = field(default_factory=list)
    semantic_vector: Optional[List[float]] = None
    min_reputation: float = 0.0  # "I only want agents with R >= X"
    max_price: float = float("inf")  # budget cap
    required_access_level: str = "L0"
    preferred_origin_type: Optional[str] = None  # prefer human data? sensor?


# ── Protocol Messages ────────────────────────────────────────────────
@dataclass
class ProtocolMessage:
    """Base envelope for all AHRP messages.

    Every message is:
      1. Versioned (protocol_version)
      2. Signed (signature over payload)
      3. Timestamped (unix seconds)
      4. Traceable (message_id, references previous via in_reply_to)
    """

    protocol_version: str = PROTOCOL_VERSION
    message_type: str = ""
    message_id: str = ""
    sender: str = ""  # agent_id
    recipient: str = ""  # agent_id or "*" for broadcast
    timestamp: int = field(default_factory=lambda: int(time.time()))
    signature: str = ""  # Ed25519 signature of payload
    in_reply_to: str = ""  # chain messages into a transaction
    payload: Dict[str, Any] = field(default_factory=dict)
    ttl: int = 300  # seconds until message expires

    def _signing_bytes(self) -> bytes:
        """Canonical bytes used for signing/verification."""
        payload_json = json.dumps(self.payload, sort_keys=True)
        canonical = (
            f"{self.protocol_version}|{self.message_type}|"
            f"{self.sender}|{self.recipient}|"
            f"{self.timestamp}|{payload_json}"
        )
        return canonical.encode("utf-8")

    def sign_message(self, private_key_hex: str) -> None:
        """Sign this message in-place using Ed25519."""
        from oasyce.crypto.keys import sign

        self.signature = sign(self._signing_bytes(), private_key_hex)

    def verify_signature(self, public_key_hex: str) -> bool:
        """Verify the Ed25519 signature against the given public key."""
        from oasyce.crypto.keys import verify

        if not self.signature:
            return False
        return verify(self._signing_bytes(), self.signature, public_key_hex)

    @classmethod
    def create_signed(
        cls,
        message_type: str,
        sender: str,
        recipient: str,
        payload_dict: Dict[str, Any],
        private_key_hex: str,
        **kwargs: Any,
    ) -> "ProtocolMessage":
        """Build and sign a message in one step."""
        msg = cls(
            message_type=message_type,
            sender=sender,
            recipient=recipient,
            payload=payload_dict,
            **kwargs,
        )
        msg.sign_message(private_key_hex)
        return msg


# ── Announce ─────────────────────────────────────────────────────────
@dataclass
class AnnouncePayload:
    """Broadcast: 'I exist, here's what I can do.'

    Sent periodically or on network join. Routers index these
    for capability-based discovery.
    """

    identity: AgentIdentity = field(default_factory=AgentIdentity)
    capabilities: List[Capability] = field(default_factory=list)
    endpoints: List[str] = field(default_factory=list)  # how to reach me
    heartbeat_interval: int = 600  # seconds between re-announcements


# ── Request ──────────────────────────────────────────────────────────
@dataclass
class RequestPayload:
    """'I need X, willing to pay up to Y OAS.'

    Can be broadcast (recipient="*") for open matching,
    or directed to a specific agent.
    """

    need: Need = field(default_factory=Need)
    budget_oas: float = 0.0
    deadline: int = 0  # unix timestamp, 0 = no deadline
    request_id: str = ""


# ── Offer ────────────────────────────────────────────────────────────
@dataclass
class OfferPayload:
    """'I can fulfill your request. Here are my terms.'

    Always in_reply_to a REQUEST message.
    """

    request_id: str = ""
    capability_id: str = ""
    price_oas: float = 0.0
    access_level: str = "L0"
    estimated_delivery_seconds: int = 60
    terms: Dict[str, Any] = field(default_factory=dict)  # custom terms
    offer_id: str = ""
    valid_until: int = 0  # expiry timestamp


# ── Accept ───────────────────────────────────────────────────────────
@dataclass
class AcceptPayload:
    """'Deal. I accept your offer. Lock escrow now.'

    Triggers Oasyce settlement: bond calculation, escrow lock.
    """

    offer_id: str = ""
    escrow_tx_id: str = ""  # Oasyce transaction ID for the escrow


# ── Deliver ──────────────────────────────────────────────────────────
@dataclass
class DeliverPayload:
    """'Here's the result / data.'

    For L0-L2: contains query results, samples, or compute outputs.
    For L3: contains data delivery proof + encrypted payload reference.
    """

    offer_id: str = ""
    access_level: str = "L0"
    content_hash: str = ""  # SHA-256 of delivered content
    content_ref: str = ""  # URI / IPFS CID / inline (for small payloads)
    content_size_bytes: int = 0
    watermark_id: str = ""  # for leakage tracking


# ── Confirm ──────────────────────────────────────────────────────────
@dataclass
class ConfirmPayload:
    """'Received and verified. Release payment.'

    Triggers Oasyce settlement: release escrow, distribute fees,
    update reputation for both parties.
    """

    offer_id: str = ""
    content_hash_verified: bool = False
    settlement_tx_id: str = ""  # Oasyce settlement transaction
    rating: Optional[int] = None  # 1-5 star rating (optional, feeds reputation)


# ── Matching Engine ──────────────────────────────────────────────────
import math


def match_score(need: Need, capability: Capability) -> float:
    """Calculate match score between a need and a capability.

    Score ∈ [0, 1]. Components:
      1. Semantic similarity (60% weight) — cosine of embedding vectors
      2. Tag overlap (20% weight) — Jaccard index of tag sets
      3. Price fit (10% weight) — 1.0 if within budget, decays above
      4. Access level fit (10% weight) — 1.0 if capability meets requirement

    Returns 0.0 if hard constraints fail (reputation, access level).
    """
    # Hard constraints — instant rejection
    if capability.price_floor > need.max_price:
        return 0.0

    # 1. Semantic similarity
    sem_score = 0.0
    a, b = need.semantic_vector, capability.semantic_vector
    if a and b and len(a) == len(b):
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a > 0 and norm_b > 0:
            sem_score = max(0.0, dot / (norm_a * norm_b))

    # 2. Tag overlap (Jaccard)
    tag_score = 0.0
    if need.tags or capability.tags:
        s1, s2 = set(need.tags), set(capability.tags)
        union = s1 | s2
        if union:
            tag_score = len(s1 & s2) / len(union)

    # 3. Price fit
    price_score = 1.0
    if need.max_price < float("inf") and capability.price_floor > 0:
        ratio = capability.price_floor / need.max_price
        price_score = max(0.0, 1.0 - max(0.0, ratio - 1.0))

    # 4. Access level fit
    level_order = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
    required = level_order.get(need.required_access_level, 0)
    provided = (
        max(level_order.get(lvl, 0) for lvl in capability.access_levels)
        if capability.access_levels
        else 0
    )
    access_score = 1.0 if provided >= required else 0.0

    # 5. Origin type preference
    origin_bonus = 0.0
    if need.preferred_origin_type and capability.origin_type == need.preferred_origin_type:
        origin_bonus = 0.05  # small bonus for matching preference

    return min(
        1.0,
        (
            0.60 * sem_score
            + 0.20 * tag_score
            + 0.10 * price_score
            + 0.10 * access_score
            + origin_bonus
        ),
    )


# ── Transaction State Machine ────────────────────────────────────────
class TxState(str, enum.Enum):
    """Transaction lifecycle states."""

    OPEN = "open"  # REQUEST sent, waiting for OFFERs
    OFFERED = "offered"  # OFFER received, buyer deciding
    ACCEPTED = "accepted"  # ACCEPT sent, escrow locked
    ESCROWED = "escrowed"  # Funds locked in escrow (capability flow)
    DELIVERED = "delivered"  # DELIVER received, buyer verifying
    CONFIRMED = "confirmed"  # CONFIRM sent, settled
    EXPIRED = "expired"  # TTL exceeded at any stage
    DISPUTED = "disputed"  # Either party raised a dispute


@dataclass
class Transaction:
    """Full lifecycle of a single agent-to-agent data transaction."""

    tx_id: str
    buyer: str  # agent_id
    seller: str  # agent_id
    state: TxState = TxState.OPEN
    request: Optional[RequestPayload] = None
    offer: Optional[OfferPayload] = None
    accept: Optional[AcceptPayload] = None
    deliver: Optional[DeliverPayload] = None
    confirm: Optional[ConfirmPayload] = None
    created_at: int = field(default_factory=lambda: int(time.time()))
    settled_at: Optional[int] = None

    def advance(self, message_type: MessageType) -> None:
        """State machine transition."""
        transitions = {
            (TxState.OPEN, MessageType.OFFER): TxState.OFFERED,
            (TxState.OFFERED, MessageType.ACCEPT): TxState.ACCEPTED,
            (TxState.ACCEPTED, MessageType.DELIVER): TxState.DELIVERED,
            (TxState.DELIVERED, MessageType.CONFIRM): TxState.CONFIRMED,
            # Capability flow transitions
            (TxState.ACCEPTED, MessageType.CAPABILITY_INVOKE): TxState.ESCROWED,
            (TxState.ESCROWED, MessageType.CAPABILITY_RESULT): TxState.DELIVERED,
            (TxState.ESCROWED, MessageType.CAPABILITY_FAIL): TxState.EXPIRED,
        }
        key = (self.state, message_type)
        if key not in transitions:
            raise ValueError(f"Invalid transition: {self.state} + {message_type}")
        self.state = transitions[key]
        if self.state == TxState.CONFIRMED:
            self.settled_at = int(time.time())


# ── Capability Payload Dataclasses (Phase 2) ─────────────────────────


@dataclass
class CapabilityQueryPayload:
    """CAPABILITY_QUERY — Consumer searches for capabilities."""

    query_tags: List[str] = field(default_factory=list)
    query_text: str = ""
    semantic_vector: Optional[List[float]] = None
    max_price: float = float("inf")
    limit: int = 10


@dataclass
class CapabilityInvokePayload:
    """CAPABILITY_INVOKE — Consumer invokes a specific capability."""

    invocation_id: str = ""
    capability_id: str = ""
    input: Dict[str, Any] = field(default_factory=dict)
    max_price: float = 0.0
    escrow_tx_id: str = ""


@dataclass
class CapabilityResultPayload:
    """CAPABILITY_RESULT — Provider returns execution output."""

    invocation_id: str = ""
    output: Dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""
    execution_time_ms: int = 0


@dataclass
class CapabilityFailPayload:
    """CAPABILITY_FAIL — Provider reports execution failure."""

    invocation_id: str = ""
    error_code: str = ""  # timeout | invalid_input | internal_error | capacity_exceeded
    error_message: str = ""
