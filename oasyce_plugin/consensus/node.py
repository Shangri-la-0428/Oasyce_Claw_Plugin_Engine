"""
Consensus node — new node join flow and lifecycle management.

Handles the process of a new node joining the network:
  1. Connect to bootstrap peers
  2. Query network height
  3. Compare local height, decide if sync needed
  4. If needed, run block sync protocol
  5. Enter normal block production mode

Usage:
    node = ConsensusNode(engine, bootstrap_peers)
    result = await node.join_network()
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from oasyce_plugin.consensus.network.sync_protocol import (
    SyncResult,
    SyncStatus,
    make_genesis_block,
)
from oasyce_plugin.consensus.network.block_sync import PeerTransport
from oasyce_plugin.consensus.network.sync import BlockSyncProtocol
from oasyce_plugin.consensus.network.protocol import SyncState, SyncInfo

if TYPE_CHECKING:
    from oasyce_plugin.consensus import ConsensusEngine


class NodeState(str, Enum):
    """Lifecycle state of a consensus node."""
    INITIALIZING = "initializing"
    SYNCING = "syncing"
    SYNCED = "synced"
    PRODUCING = "producing"   # actively producing blocks
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class JoinResult:
    """Result of a node join attempt."""
    success: bool
    state: NodeState
    local_height: int = -1
    network_height: int = -1
    blocks_synced: int = 0
    peers_connected: int = 0
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "state": self.state.value,
            "local_height": self.local_height,
            "network_height": self.network_height,
            "blocks_synced": self.blocks_synced,
            "peers_connected": self.peers_connected,
            "error": self.error,
        }


class ConsensusNode:
    """Manages the lifecycle of a consensus node.

    Handles joining the network, syncing blocks, and transitioning
    to block production mode.
    """

    def __init__(self, engine: ConsensusEngine,
                 bootstrap_peers: Optional[List[PeerTransport]] = None,
                 local_height: int = -1,
                 verify_signatures: bool = False):
        self.engine = engine
        self.bootstrap_peers: List[PeerTransport] = list(bootstrap_peers or [])
        self.local_height = local_height
        self.verify_signatures = verify_signatures
        self.state = NodeState.INITIALIZING
        self._sync_protocol: Optional[BlockSyncProtocol] = None

    @property
    def genesis_hash(self) -> str:
        return self.engine.get_genesis_hash()

    @property
    def chain_id(self) -> str:
        return self.engine.chain_id

    def add_peer(self, peer: PeerTransport) -> None:
        """Add a bootstrap peer."""
        self.bootstrap_peers.append(peer)

    async def join_network(self) -> JoinResult:
        """Execute the full node join flow.

        Steps:
          1. Connect to bootstrap peers
          2. Query network height
          3. Compare with local height
          4. If behind, sync blocks
          5. Transition to synced/producing state

        Returns:
            JoinResult with status and statistics.
        """
        self.state = NodeState.INITIALIZING

        # 1. Check peers
        if not self.bootstrap_peers:
            return JoinResult(
                success=False,
                state=NodeState.ERROR,
                local_height=self.local_height,
                error="no bootstrap peers configured",
            )

        # 2. Query network height
        network_height, reachable_peers = await self._query_network_height()

        if reachable_peers == 0:
            return JoinResult(
                success=False,
                state=NodeState.ERROR,
                local_height=self.local_height,
                error="all bootstrap peers unreachable",
            )

        # 3. Check if sync is needed
        if self.local_height >= network_height:
            self.state = NodeState.SYNCED
            return JoinResult(
                success=True,
                state=NodeState.SYNCED,
                local_height=self.local_height,
                network_height=network_height,
                peers_connected=reachable_peers,
            )

        # 4. Sync blocks
        self.state = NodeState.SYNCING
        self._sync_protocol = BlockSyncProtocol(
            engine=self.engine,
            peers=self.bootstrap_peers,
            local_height=self.local_height,
            verify_signatures=self.verify_signatures,
        )

        sync_result = await self._sync_protocol.sync_from_network()

        # 5. Evaluate result
        if sync_result.ok:
            self.local_height = sync_result.to_height
            self.state = NodeState.SYNCED
            return JoinResult(
                success=True,
                state=NodeState.SYNCED,
                local_height=self.local_height,
                network_height=network_height,
                blocks_synced=sync_result.blocks_synced,
                peers_connected=reachable_peers,
            )
        elif sync_result.status == SyncStatus.PARTIAL:
            self.local_height = sync_result.to_height
            self.state = NodeState.SYNCING
            return JoinResult(
                success=False,
                state=NodeState.SYNCING,
                local_height=self.local_height,
                network_height=network_height,
                blocks_synced=sync_result.blocks_synced,
                peers_connected=reachable_peers,
                error=sync_result.error,
            )
        else:
            self.state = NodeState.ERROR
            return JoinResult(
                success=False,
                state=NodeState.ERROR,
                local_height=self.local_height,
                network_height=network_height,
                peers_connected=reachable_peers,
                error=sync_result.error,
            )

    async def check_sync_needed(self) -> bool:
        """Quick check if this node needs to sync."""
        if self._sync_protocol is None:
            self._sync_protocol = BlockSyncProtocol(
                engine=self.engine,
                peers=self.bootstrap_peers,
                local_height=self.local_height,
                verify_signatures=self.verify_signatures,
            )
        return await self._sync_protocol.needs_sync()

    async def incremental_sync(self) -> SyncResult:
        """Perform an incremental sync (catch up on new blocks).

        Used after initial join to stay in sync with the network.
        """
        if self._sync_protocol is None:
            self._sync_protocol = BlockSyncProtocol(
                engine=self.engine,
                peers=self.bootstrap_peers,
                local_height=self.local_height,
                verify_signatures=self.verify_signatures,
            )
        else:
            self._sync_protocol.local_height = self.local_height

        result = await self._sync_protocol.sync_from_network()
        if result.ok:
            self.local_height = result.to_height
        return result

    def enter_producing_mode(self) -> None:
        """Transition to block production mode (called after sync completes)."""
        if self.state == NodeState.SYNCED:
            self.state = NodeState.PRODUCING

    def stop(self) -> None:
        """Stop the node."""
        self.state = NodeState.STOPPED

    def get_status(self) -> Dict[str, Any]:
        """Get current node status."""
        return {
            "state": self.state.value,
            "chain_id": self.chain_id,
            "local_height": self.local_height,
            "genesis_hash": self.genesis_hash,
            "peers": len(self.bootstrap_peers),
            "is_syncing": self.state == NodeState.SYNCING,
        }

    # ── Internal ─────────────────────────────────────────────────

    async def _query_network_height(self) -> tuple:
        """Query all bootstrap peers for the network height.

        Returns:
            (max_height, reachable_peer_count)
        """
        def _query():
            max_height = -1
            reachable = 0
            genesis_hash = self.genesis_hash
            for peer in self.bootstrap_peers:
                try:
                    info = peer.get_peer_info()
                    # Only count peers with matching genesis
                    if info.genesis_hash == genesis_hash:
                        reachable += 1
                        if info.height > max_height:
                            max_height = info.height
                except Exception:
                    continue
            return max_height, reachable

        return await asyncio.get_event_loop().run_in_executor(None, _query)
