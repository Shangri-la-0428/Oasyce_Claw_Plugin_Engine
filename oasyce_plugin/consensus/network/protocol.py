"""
Extended network protocol messages for Oasyce PoS consensus.

Adds higher-level sync messages on top of the base sync_protocol types.
These support chain-height queries, block-range requests with pagination,
and sync status reporting.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional

from oasyce_plugin.consensus.network.sync_protocol import (
    Block,
    BlockHeader,
    GetBlocksRequest,
    GetBlocksResponse,
    GetPeerInfoRequest,
    GetPeerInfoResponse,
    SyncResult,
    SyncStatus,
)


# ── Height query ──────────────────────────────────────────────────

@dataclass
class GetHeight:
    """Request a peer's current chain height."""

    def to_dict(self) -> Dict[str, Any]:
        return {"type": "get_height"}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> GetHeight:
        return cls()


@dataclass
class HeightResponse:
    """Response with peer's chain height and best block hash."""
    height: int = -1
    best_hash: str = ""
    chain_id: str = ""
    timestamp: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> HeightResponse:
        return cls(
            height=d.get("height", -1),
            best_hash=d.get("best_hash", ""),
            chain_id=d.get("chain_id", ""),
            timestamp=d.get("timestamp", 0),
        )


# ── Block range request (superset of GetBlocksRequest) ───────────

@dataclass
class GetBlocks:
    """Request blocks in a height range with count limit.

    Extends GetBlocksRequest with explicit count field and
    serialization methods.
    """
    from_height: int = 0
    to_height: int = 0
    count: int = 100

    def to_request(self) -> GetBlocksRequest:
        """Convert to base sync_protocol request."""
        return GetBlocksRequest(
            from_height=self.from_height,
            to_height=self.to_height,
            limit=self.count,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "get_blocks",
            "from_height": self.from_height,
            "to_height": self.to_height,
            "count": self.count,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> GetBlocks:
        return cls(
            from_height=d.get("from_height", 0),
            to_height=d.get("to_height", 0),
            count=d.get("count", 100),
        )


@dataclass
class BlocksResponse:
    """Response containing requested blocks."""
    blocks: List[Block] = field(default_factory=list)
    has_more: bool = False
    next_height: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "blocks": [b.to_dict() for b in self.blocks],
            "has_more": self.has_more,
            "next_height": self.next_height,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> BlocksResponse:
        return cls(
            blocks=[Block.from_dict(b) for b in d.get("blocks", [])],
            has_more=d.get("has_more", False),
            next_height=d.get("next_height", 0),
        )


# ── Sync status ───────────────────────────────────────────────────

class SyncState(str, Enum):
    """Current sync state of a node."""
    IDLE = "idle"
    SYNCING = "syncing"
    SYNCED = "synced"
    FORKED = "forked"
    ERROR = "error"


@dataclass
class SyncInfo:
    """Snapshot of a node's sync status."""
    state: SyncState = SyncState.IDLE
    chain_id: str = ""
    local_height: int = -1
    best_known_height: int = -1
    genesis_hash: str = ""
    peers_connected: int = 0
    blocks_per_second: float = 0.0
    last_sync_time: int = 0
    last_sync_peer: str = ""
    last_sync_error: str = ""

    @property
    def sync_progress(self) -> float:
        """Sync progress as 0.0–1.0. Returns 1.0 if synced or no target."""
        if self.best_known_height <= 0:
            return 1.0
        if self.local_height < 0:
            return 0.0
        return min(1.0, (self.local_height + 1) / (self.best_known_height + 1))

    @property
    def blocks_behind(self) -> int:
        if self.best_known_height <= self.local_height:
            return 0
        return self.best_known_height - self.local_height

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "chain_id": self.chain_id,
            "local_height": self.local_height,
            "best_known_height": self.best_known_height,
            "genesis_hash": self.genesis_hash,
            "peers_connected": self.peers_connected,
            "blocks_per_second": self.blocks_per_second,
            "sync_progress": self.sync_progress,
            "blocks_behind": self.blocks_behind,
            "last_sync_time": self.last_sync_time,
            "last_sync_peer": self.last_sync_peer,
            "last_sync_error": self.last_sync_error,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> SyncInfo:
        state_val = d.get("state", "idle")
        try:
            state = SyncState(state_val)
        except ValueError:
            state = SyncState.IDLE
        return cls(
            state=state,
            chain_id=d.get("chain_id", ""),
            local_height=d.get("local_height", -1),
            best_known_height=d.get("best_known_height", -1),
            genesis_hash=d.get("genesis_hash", ""),
            peers_connected=d.get("peers_connected", 0),
            blocks_per_second=d.get("blocks_per_second", 0.0),
            last_sync_time=d.get("last_sync_time", 0),
            last_sync_peer=d.get("last_sync_peer", ""),
            last_sync_error=d.get("last_sync_error", ""),
        )


# ── Block header requests ────────────────────────────────────────

@dataclass
class GetBlockHeaders:
    """Request block headers in a height range (lightweight sync)."""
    from_height: int = 0
    to_height: int = 0
    limit: int = 500

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "get_block_headers",
            "from_height": self.from_height,
            "to_height": self.to_height,
            "limit": self.limit,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> GetBlockHeaders:
        return cls(
            from_height=d.get("from_height", 0),
            to_height=d.get("to_height", 0),
            limit=d.get("limit", 500),
        )


@dataclass
class BlockHeaders:
    """Response with block headers."""
    headers: List[BlockHeader] = field(default_factory=list)
    has_more: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "block_headers",
            "headers": [h.to_dict() for h in self.headers],
            "has_more": self.has_more,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> BlockHeaders:
        return cls(
            headers=[BlockHeader.from_dict(h) for h in d.get("headers", [])],
            has_more=d.get("has_more", False),
        )


# ── Sync status message (wire protocol) ─────────────────────────

@dataclass
class SyncStatusMessage:
    """Wire-level sync status broadcast to peers.

    Distinct from SyncInfo (local bookkeeping) — this is what a node
    sends to peers so they know whether it is still catching up.
    """
    current_height: int = -1
    target_height: int = -1
    is_syncing: bool = False
    chain_id: str = ""
    genesis_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "sync_status",
            "current_height": self.current_height,
            "target_height": self.target_height,
            "is_syncing": self.is_syncing,
            "chain_id": self.chain_id,
            "genesis_hash": self.genesis_hash,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> SyncStatusMessage:
        return cls(
            current_height=d.get("current_height", -1),
            target_height=d.get("target_height", -1),
            is_syncing=d.get("is_syncing", False),
            chain_id=d.get("chain_id", ""),
            genesis_hash=d.get("genesis_hash", ""),
        )


# ── Message router ────────────────────────────────────────────────

MESSAGE_TYPES = {
    "get_height": GetHeight,
    "height_response": HeightResponse,
    "get_blocks": GetBlocks,
    "blocks_response": BlocksResponse,
    "get_peer_info": GetPeerInfoRequest,
    "peer_info_response": GetPeerInfoResponse,
    "get_block_headers": GetBlockHeaders,
    "block_headers": BlockHeaders,
    "sync_status": SyncStatusMessage,
}


def parse_message(data: Dict[str, Any]) -> Any:
    """Parse a protocol message from a dict.

    Uses the 'type' field to determine the message class.
    Returns None if the type is unknown.
    """
    msg_type = data.get("type", "")
    cls = MESSAGE_TYPES.get(msg_type)
    if cls is None:
        return None
    return cls.from_dict(data)
