"""
Block synchronization protocol — message types and Block dataclass.

Defines the wire-level data structures used by nodes to exchange
blocks and chain metadata during synchronization.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional

from oasyce_plugin.consensus.core.types import Operation, OperationType


# ── BlockHeader ───────────────────────────────────────────────────

@dataclass(frozen=True)
class BlockHeader:
    """Lightweight block header — everything except operations.

    Used for header-first sync: download headers, validate chain linkage,
    then request full blocks only for valid ranges.
    """
    chain_id: str
    block_number: int
    prev_hash: str
    merkle_root: str
    timestamp: int
    proposer: str = ""
    signature: str = ""

    @property
    def block_hash(self) -> str:
        """Same deterministic hash as the full Block."""
        data = f"{self.chain_id}{self.block_number}{self.prev_hash}{self.merkle_root}{self.timestamp}"
        return hashlib.sha256(data.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "block_number": self.block_number,
            "prev_hash": self.prev_hash,
            "merkle_root": self.merkle_root,
            "timestamp": self.timestamp,
            "proposer": self.proposer,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> BlockHeader:
        return cls(
            chain_id=d.get("chain_id", ""),
            block_number=d.get("block_number", 0),
            prev_hash=d.get("prev_hash", ""),
            merkle_root=d.get("merkle_root", ""),
            timestamp=d.get("timestamp", 0),
            proposer=d.get("proposer", ""),
            signature=d.get("signature", ""),
        )


# ── Block ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Block:
    """A finalized block in the Oasyce PoS chain.

    Immutable once created. The block_hash is computed deterministically
    from (chain_id, block_number, prev_hash, merkle_root, timestamp).
    """
    chain_id: str
    block_number: int
    prev_hash: str
    merkle_root: str
    timestamp: int
    operations: tuple = ()          # tuple of Operation (frozen)
    proposer: str = ""              # validator address / pubkey
    signature: str = ""             # proposer's Ed25519 signature

    @property
    def block_hash(self) -> str:
        """Deterministic block hash (same algo as execution.engine)."""
        data = f"{self.chain_id}{self.block_number}{self.prev_hash}{self.merkle_root}{self.timestamp}"
        return hashlib.sha256(data.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize block to a plain dict (for JSON transport)."""
        ops = []
        for op in self.operations:
            ops.append({
                "op_type": op.op_type.value if hasattr(op.op_type, "value") else str(op.op_type),
                "validator_id": op.validator_id,
                "amount": op.amount,
                "asset_type": op.asset_type,
                "from_addr": op.from_addr,
                "to_addr": op.to_addr,
                "reason": op.reason,
                "commission_rate": op.commission_rate,
                "signature": op.signature,
                "chain_id": op.chain_id,
                "sender": op.sender,
                "timestamp": op.timestamp,
            })
        return {
            "chain_id": self.chain_id,
            "block_number": self.block_number,
            "prev_hash": self.prev_hash,
            "merkle_root": self.merkle_root,
            "timestamp": self.timestamp,
            "operations": ops,
            "proposer": self.proposer,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Block:
        """Deserialize block from a plain dict."""
        ops = []
        for op_dict in d.get("operations", []):
            op_type_val = op_dict.get("op_type", "register")
            try:
                op_type = OperationType(op_type_val)
            except ValueError:
                op_type = OperationType.REGISTER
            ops.append(Operation(
                op_type=op_type,
                validator_id=op_dict.get("validator_id", ""),
                amount=op_dict.get("amount", 0),
                asset_type=op_dict.get("asset_type", "OAS"),
                from_addr=op_dict.get("from_addr", ""),
                to_addr=op_dict.get("to_addr", ""),
                reason=op_dict.get("reason", ""),
                commission_rate=op_dict.get("commission_rate", 1000),
                signature=op_dict.get("signature", ""),
                chain_id=op_dict.get("chain_id", ""),
                sender=op_dict.get("sender", ""),
                timestamp=op_dict.get("timestamp", 0),
            ))
        return cls(
            chain_id=d["chain_id"],
            block_number=d["block_number"],
            prev_hash=d["prev_hash"],
            merkle_root=d.get("merkle_root", ""),
            timestamp=d.get("timestamp", 0),
            operations=tuple(ops),
            proposer=d.get("proposer", ""),
            signature=d.get("signature", ""),
        )

    def to_header(self) -> BlockHeader:
        """Extract a lightweight header from this block."""
        return BlockHeader(
            chain_id=self.chain_id,
            block_number=self.block_number,
            prev_hash=self.prev_hash,
            merkle_root=self.merkle_root,
            timestamp=self.timestamp,
            proposer=self.proposer,
            signature=self.signature,
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, s: str) -> Block:
        return cls.from_dict(json.loads(s))


def compute_merkle_root(operations: tuple) -> str:
    """Compute a Merkle root from a tuple of Operations.

    Leaf hashes are SHA-256 of the canonical serialization of each op.
    Tree is built bottom-up, pairing adjacent hashes.
    Empty operations → zeroed hash.
    """
    if not operations:
        return "0" * 64

    from oasyce_plugin.consensus.core.signature import serialize_operation

    leaves = [hashlib.sha256(serialize_operation(op)).hexdigest() for op in operations]

    while len(leaves) > 1:
        next_level = []
        for i in range(0, len(leaves), 2):
            left = leaves[i]
            right = leaves[i + 1] if i + 1 < len(leaves) else left
            combined = hashlib.sha256((left + right).encode()).hexdigest()
            next_level.append(combined)
        leaves = next_level

    return leaves[0]


# ── Genesis ────────────────────────────────────────────────────────

GENESIS_PREV_HASH = "0" * 64


def make_genesis_block(chain_id: str, timestamp: int = 0) -> Block:
    """Create the genesis block (block_number=0, no operations)."""
    return Block(
        chain_id=chain_id,
        block_number=0,
        prev_hash=GENESIS_PREV_HASH,
        merkle_root="0" * 64,
        timestamp=timestamp,
        operations=(),
        proposer="genesis",
        signature="",
    )


# ── Sync messages ──────────────────────────────────────────────────

@dataclass
class GetBlocksRequest:
    """Request blocks in a height range."""
    from_height: int
    to_height: int
    limit: int = 100

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> GetBlocksRequest:
        return cls(
            from_height=d["from_height"],
            to_height=d["to_height"],
            limit=d.get("limit", 100),
        )


@dataclass
class GetBlocksResponse:
    """Response with requested blocks."""
    blocks: List[Block] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"blocks": [b.to_dict() for b in self.blocks]}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> GetBlocksResponse:
        return cls(blocks=[Block.from_dict(b) for b in d.get("blocks", [])])


@dataclass
class GetPeerInfoRequest:
    """Request peer's chain metadata."""
    pass

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "get_peer_info"}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> GetPeerInfoRequest:
        return cls()


@dataclass
class GetPeerInfoResponse:
    """Peer's chain metadata."""
    chain_id: str = ""
    height: int = 0
    genesis_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> GetPeerInfoResponse:
        return cls(
            chain_id=d.get("chain_id", ""),
            height=d.get("height", 0),
            genesis_hash=d.get("genesis_hash", ""),
        )


# ── Sync result ────────────────────────────────────────────────────

class SyncStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"           # synced some blocks but not all
    NO_PEERS = "no_peers"
    GENESIS_MISMATCH = "genesis_mismatch"
    INVALID_BLOCK = "invalid_block"
    ALREADY_SYNCED = "already_synced"
    ERROR = "error"


@dataclass
class SyncResult:
    """Result of a sync operation."""
    status: SyncStatus
    blocks_synced: int = 0
    from_height: int = 0
    to_height: int = 0
    peer: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status in (SyncStatus.SUCCESS, SyncStatus.ALREADY_SYNCED)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "blocks_synced": self.blocks_synced,
            "from_height": self.from_height,
            "to_height": self.to_height,
            "peer": self.peer,
            "error": self.error,
            "ok": self.ok,
        }
