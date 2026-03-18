"""
BlockSyncProtocol — async block synchronization coordinator.

Wraps the lower-level sync functions into an async, stateful protocol
that tracks sync progress, selects peers, and supports header-first sync.

Usage:
    protocol = BlockSyncProtocol(engine, peers)
    result = await protocol.sync_from_network()
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from oasyce_plugin.consensus.network.sync_protocol import (
    Block,
    BlockHeader,
    GetBlocksRequest,
    GetBlocksResponse,
    SyncResult,
    SyncStatus,
    make_genesis_block,
)
from oasyce_plugin.consensus.network.block_sync import (
    InMemoryPeer,
    PeerTransport,
    verify_block,
    verify_block_chain,
    apply_synced_block,
    sync_from_peer,
    sync_from_network,
    sync_with_fork_detection,
)
from oasyce_plugin.consensus.network.protocol import (
    SyncState,
    SyncInfo,
    SyncStatusMessage,
)
from oasyce_plugin.consensus.core.fork_choice import (
    ChainInfo,
    choose_fork,
    should_sync,
    rank_peers,
)

if TYPE_CHECKING:
    from oasyce_plugin.consensus import ConsensusEngine


@dataclass
class BlockSyncProtocol:
    """Async block synchronization protocol.

    Coordinates peer selection, header verification, and block download
    for syncing a local chain to the network's canonical chain.
    """
    engine: ConsensusEngine
    peers: List[PeerTransport] = field(default_factory=list)
    local_height: int = -1
    verify_signatures: bool = False
    batch_size: int = 100
    on_progress: Optional[Callable[[int, int], None]] = None

    # Internal state
    _sync_info: SyncInfo = field(default_factory=SyncInfo)
    _syncing: bool = False

    def __post_init__(self):
        self._sync_info = SyncInfo(
            chain_id=self.engine.chain_id,
            local_height=self.local_height,
            genesis_hash=self.engine.get_genesis_hash(),
        )

    @property
    def sync_info(self) -> SyncInfo:
        return self._sync_info

    @property
    def is_syncing(self) -> bool:
        return self._syncing

    def get_sync_status(self) -> SyncStatusMessage:
        """Build a wire-level sync status for broadcasting to peers."""
        return SyncStatusMessage(
            current_height=self._sync_info.local_height,
            target_height=self._sync_info.best_known_height,
            is_syncing=self._syncing,
            chain_id=self.engine.chain_id,
            genesis_hash=self._sync_info.genesis_hash,
        )

    async def sync_from_peer(self, peer_id: str) -> SyncResult:
        """Sync blocks from a single named peer.

        Args:
            peer_id: The peer address to sync from.

        Returns:
            SyncResult with status and statistics.
        """
        peer = self._find_peer(peer_id)
        if peer is None:
            return SyncResult(
                status=SyncStatus.NO_PEERS,
                error=f"peer not found: {peer_id}",
            )

        self._syncing = True
        self._sync_info.state = SyncState.SYNCING
        self._sync_info.last_sync_peer = peer_id

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: sync_from_peer(
                    peer, self.engine,
                    self.local_height,
                    self._sync_info.genesis_hash,
                    batch_size=self.batch_size,
                    verify_signatures=self.verify_signatures,
                    on_progress=self._on_progress,
                ),
            )
            self._update_after_sync(result)
            return result
        except Exception as e:
            self._sync_info.state = SyncState.ERROR
            self._sync_info.last_sync_error = str(e)
            return SyncResult(
                status=SyncStatus.ERROR,
                peer=peer_id,
                error=str(e),
            )
        finally:
            self._syncing = False

    async def sync_from_network(self) -> SyncResult:
        """Sync from the best available peer on the network.

        Steps:
          1. Query all peers for chain info
          2. Use fork choice to select the best peer
          3. Sync blocks from it
          4. Update local sync state

        Returns:
            SyncResult.
        """
        if not self.peers:
            return SyncResult(status=SyncStatus.NO_PEERS, error="no peers configured")

        self._syncing = True
        self._sync_info.state = SyncState.SYNCING
        self._sync_info.peers_connected = len(self.peers)

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: sync_from_network(
                    self.peers, self.engine,
                    self.local_height,
                    self._sync_info.genesis_hash,
                    verify_signatures=self.verify_signatures,
                    on_progress=self._on_progress,
                ),
            )
            self._update_after_sync(result)
            return result
        except Exception as e:
            self._sync_info.state = SyncState.ERROR
            self._sync_info.last_sync_error = str(e)
            return SyncResult(
                status=SyncStatus.ERROR,
                error=str(e),
            )
        finally:
            self._syncing = False

    async def get_block_headers(self, peer_id: str,
                                from_height: int,
                                to_height: int) -> List[BlockHeader]:
        """Fetch block headers from a peer (lightweight chain scan).

        Requests full blocks from the peer but returns only headers.
        This is useful for validating chain linkage before downloading
        full block data.

        Args:
            peer_id: Peer address.
            from_height: Start height (inclusive).
            to_height: End height (inclusive).

        Returns:
            List of BlockHeader objects, sorted by block_number.
        """
        peer = self._find_peer(peer_id)
        if peer is None:
            return []

        def _fetch():
            resp = peer.get_blocks(GetBlocksRequest(
                from_height=from_height,
                to_height=to_height,
                limit=to_height - from_height + 1,
            ))
            headers = [b.to_header() for b in resp.blocks]
            headers.sort(key=lambda h: h.block_number)
            return headers

        return await asyncio.get_event_loop().run_in_executor(None, _fetch)

    async def get_block(self, peer_id: str, height: int) -> Optional[Block]:
        """Fetch a single block from a peer.

        Args:
            peer_id: Peer address.
            height: Block height to fetch.

        Returns:
            Block or None if not found / peer unavailable.
        """
        peer = self._find_peer(peer_id)
        if peer is None:
            return None

        def _fetch():
            resp = peer.get_blocks(GetBlocksRequest(
                from_height=height,
                to_height=height,
                limit=1,
            ))
            if resp.blocks:
                return resp.blocks[0]
            return None

        return await asyncio.get_event_loop().run_in_executor(None, _fetch)

    async def verify_chain(self, blocks: List[Block]) -> bool:
        """Verify that a list of blocks forms a valid chain.

        Checks hash linkage, merkle roots, timestamps, and optionally
        Ed25519 signatures.

        Args:
            blocks: Blocks to verify, sorted by block_number.

        Returns:
            True if the chain is valid.
        """
        def _verify():
            result = verify_block_chain(
                blocks,
                verify_signatures=self.verify_signatures,
            )
            return result.valid

        return await asyncio.get_event_loop().run_in_executor(None, _verify)

    async def get_peer_chains(self) -> List[ChainInfo]:
        """Query all peers for their chain metadata.

        Returns:
            List of ChainInfo, one per reachable peer.
        """
        def _query():
            chains = []
            for peer in self.peers:
                try:
                    info = peer.get_peer_info()
                    chains.append(ChainInfo(
                        chain_id=info.chain_id,
                        height=info.height,
                        genesis_hash=info.genesis_hash,
                        peer=peer.address,
                    ))
                except Exception:
                    continue
            return chains

        return await asyncio.get_event_loop().run_in_executor(None, _query)

    async def sync_with_reorg(self, local_blocks: Optional[List[Block]] = None
                              ) -> SyncResult:
        """Sync from the best peer with fork detection and reorg support.

        If a fork is detected and the remote chain is heavier, executes
        a chain reorganization before applying the new blocks.

        Args:
            local_blocks: Local chain blocks for fork detection.
                          If None, falls back to normal sync.

        Returns:
            SyncResult.
        """
        if not self.peers:
            return SyncResult(status=SyncStatus.NO_PEERS, error="no peers configured")

        self._syncing = True
        self._sync_info.state = SyncState.SYNCING
        self._sync_info.peers_connected = len(self.peers)

        try:
            # Pick the best peer
            chains = await self.get_peer_chains()
            if not chains:
                return SyncResult(status=SyncStatus.NO_PEERS, error="no peers reachable")

            best = choose_fork(chains, self._sync_info.genesis_hash)
            if best is None:
                return SyncResult(status=SyncStatus.GENESIS_MISMATCH,
                                  error="no compatible peers")

            if not should_sync(
                ChainInfo(chain_id=self.engine.chain_id,
                          height=self.local_height,
                          genesis_hash=self._sync_info.genesis_hash),
                best, self._sync_info.genesis_hash,
            ):
                return SyncResult(status=SyncStatus.ALREADY_SYNCED,
                                  from_height=self.local_height,
                                  to_height=self.local_height)

            peer = self._find_peer(best.peer)
            if peer is None:
                return SyncResult(status=SyncStatus.ERROR,
                                  error=f"best peer not found: {best.peer}")

            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: sync_with_fork_detection(
                    peer, self.engine,
                    self.local_height,
                    self._sync_info.genesis_hash,
                    local_blocks=local_blocks,
                    verify_signatures=self.verify_signatures,
                    on_progress=self._on_progress,
                ),
            )
            self._update_after_sync(result)
            return result
        except Exception as e:
            self._sync_info.state = SyncState.ERROR
            self._sync_info.last_sync_error = str(e)
            return SyncResult(status=SyncStatus.ERROR, error=str(e))
        finally:
            self._syncing = False

    async def needs_sync(self) -> bool:
        """Check if the local chain is behind the network.

        Queries peers and uses fork choice to determine if sync is needed.
        """
        chains = await self.get_peer_chains()
        if not chains:
            return False

        local = ChainInfo(
            chain_id=self.engine.chain_id,
            height=self.local_height,
            genesis_hash=self._sync_info.genesis_hash,
        )

        best = choose_fork(chains, self._sync_info.genesis_hash)
        if best is None:
            return False

        return should_sync(local, best, self._sync_info.genesis_hash)

    # ── Internal helpers ──────────────────────────────────────────

    def _find_peer(self, peer_id: str) -> Optional[PeerTransport]:
        """Find a peer by address."""
        for p in self.peers:
            if p.address == peer_id:
                return p
        return None

    def _on_progress(self, synced: int, total: int) -> None:
        """Internal progress callback — updates sync info and calls user callback."""
        self._sync_info.local_height = self.local_height + synced
        if total > 0:
            self._sync_info.best_known_height = self.local_height + total
        if self.on_progress:
            self.on_progress(synced, total)

    def _update_after_sync(self, result: SyncResult) -> None:
        """Update internal state after a sync completes."""
        self._sync_info.last_sync_time = int(time.time())
        self._sync_info.last_sync_peer = result.peer

        if result.ok:
            self.local_height = max(self.local_height, result.to_height)
            self._sync_info.local_height = self.local_height
            self._sync_info.state = SyncState.SYNCED
            self._sync_info.last_sync_error = ""
        elif result.status == SyncStatus.PARTIAL:
            self.local_height = result.to_height
            self._sync_info.local_height = self.local_height
            self._sync_info.state = SyncState.ERROR
            self._sync_info.last_sync_error = result.error
        else:
            self._sync_info.state = SyncState.ERROR
            self._sync_info.last_sync_error = result.error
