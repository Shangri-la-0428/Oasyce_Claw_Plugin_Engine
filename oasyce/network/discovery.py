"""Peer discovery via gossip protocol.

Nodes maintain a set of known peers and periodically exchange peer lists
with each other to grow their view of the network.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from oasyce.network.config import NetworkConfig

if TYPE_CHECKING:
    from oasyce.network.scoring import PeerScoring

logger = logging.getLogger(__name__)


@dataclass
class PeerInfo:
    """Metadata about a known peer."""

    address: str  # host:port
    node_id: str = ""
    last_seen: float = field(default_factory=time.time)


class PeerDiscovery:
    """Manages the set of known peers and runs discovery loops."""

    def __init__(self, config: NetworkConfig, own_address: str) -> None:
        self._config = config
        self._own_address = own_address
        # address -> PeerInfo
        self._peers: dict[str, PeerInfo] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Peer management
    # ------------------------------------------------------------------

    async def add_peer(self, address: str, node_id: str = "") -> bool:
        """Add a peer if not already known and under the limit.

        Returns True if the peer was newly added.
        """
        if address == self._own_address:
            return False
        async with self._lock:
            if address in self._peers:
                self._peers[address].last_seen = time.time()
                if node_id:
                    self._peers[address].node_id = node_id
                return False
            if len(self._peers) >= self._config.max_peers:
                return False
            self._peers[address] = PeerInfo(address=address, node_id=node_id, last_seen=time.time())
            logger.info("Discovered peer %s", address)
            return True

    async def remove_peer(self, address: str) -> None:
        async with self._lock:
            self._peers.pop(address, None)

    async def mark_seen(self, address: str) -> None:
        async with self._lock:
            if address in self._peers:
                self._peers[address].last_seen = time.time()

    async def get_peers(self) -> list[PeerInfo]:
        async with self._lock:
            return list(self._peers.values())

    async def get_peer_addresses(self) -> list[str]:
        async with self._lock:
            return list(self._peers.keys())

    async def peer_count(self) -> int:
        async with self._lock:
            return len(self._peers)

    # ------------------------------------------------------------------
    # Seed bootstrap
    # ------------------------------------------------------------------

    async def bootstrap(self) -> None:
        """Add configured seed nodes to the peer set."""
        for addr in self._config.seed_nodes:
            await self.add_peer(addr)
        logger.info(
            "Bootstrap complete – %d seed peers added",
            await self.peer_count(),
        )

    # ------------------------------------------------------------------
    # Merge peers received from a PEER_EXCHANGE message
    # ------------------------------------------------------------------

    async def merge_peers(self, addresses: list[str]) -> int:
        """Merge a list of peer addresses (from gossip). Returns count of new peers."""
        added = 0
        for addr in addresses:
            if await self.add_peer(addr):
                added += 1
        return added

    # ------------------------------------------------------------------
    # Eviction of stale peers
    # ------------------------------------------------------------------

    async def evict_low_score(self, scoring: PeerScoring, min_score: float = 10.0) -> int:
        """Remove peers whose score is below *min_score*. Returns count removed."""
        to_remove: list[str] = []
        async with self._lock:
            for addr in self._peers:
                if scoring.get_score(addr) < min_score:
                    to_remove.append(addr)
            for addr in to_remove:
                del self._peers[addr]
        if to_remove:
            logger.info("Evicted %d low-score peers", len(to_remove))
        return len(to_remove)

    async def evict_stale(self, max_age_seconds: float = 120.0) -> int:
        """Remove peers not seen within *max_age_seconds*. Returns count removed."""
        now = time.time()
        to_remove: list[str] = []
        async with self._lock:
            for addr, info in self._peers.items():
                if now - info.last_seen > max_age_seconds:
                    to_remove.append(addr)
            for addr in to_remove:
                del self._peers[addr]
        if to_remove:
            logger.info("Evicted %d stale peers", len(to_remove))
        return len(to_remove)
