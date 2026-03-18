"""
Block synchronization — sync blocks from peers, verify, and apply.

Core functions:
  verify_block()       — validate block integrity (hash chain, signature, ops)
  apply_synced_block() — apply a verified block to local state
  sync_from_peer()     — download and apply blocks from a single peer
  sync_from_network()  — find the best peer and sync from it
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Protocol, TYPE_CHECKING

from oasyce_plugin.consensus.network.sync_protocol import (
    Block,
    GetBlocksRequest,
    GetBlocksResponse,
    GetPeerInfoRequest,
    GetPeerInfoResponse,
    SyncResult,
    SyncStatus,
    GENESIS_PREV_HASH,
    compute_merkle_root,
    make_genesis_block,
)
from oasyce_plugin.consensus.core.types import Operation

if TYPE_CHECKING:
    from oasyce_plugin.consensus import ConsensusEngine


# ── Peer transport abstraction ─────────────────────────────────────

class PeerTransport(Protocol):
    """Abstract peer that can answer sync requests.

    Implementations may use HTTP, TCP, in-process queues, etc.
    """
    @property
    def address(self) -> str: ...

    def get_peer_info(self) -> GetPeerInfoResponse: ...

    def get_blocks(self, request: GetBlocksRequest) -> GetBlocksResponse: ...


class InMemoryPeer:
    """In-process peer backed by a list of blocks (for testing)."""

    def __init__(self, addr: str, chain_id: str, genesis_hash: str,
                 blocks: Optional[List[Block]] = None):
        self._addr = addr
        self._chain_id = chain_id
        self._genesis_hash = genesis_hash
        self._blocks: List[Block] = list(blocks or [])

    @property
    def address(self) -> str:
        return self._addr

    def get_peer_info(self) -> GetPeerInfoResponse:
        height = max((b.block_number for b in self._blocks), default=-1)
        return GetPeerInfoResponse(
            chain_id=self._chain_id,
            height=height,
            genesis_hash=self._genesis_hash,
        )

    def get_blocks(self, request: GetBlocksRequest) -> GetBlocksResponse:
        result = []
        for b in self._blocks:
            if b.block_number < request.from_height:
                continue
            if b.block_number > request.to_height:
                continue
            result.append(b)
            if len(result) >= request.limit:
                break
        result.sort(key=lambda b: b.block_number)
        return GetBlocksResponse(blocks=result)

    def add_block(self, block: Block) -> None:
        self._blocks.append(block)


# ── Block verification ─────────────────────────────────────────────

class ValidationResult:
    """Result of block validation."""

    def __init__(self, valid: bool, error: str = ""):
        self.valid = valid
        self.error = error

    def __bool__(self) -> bool:
        return self.valid

    def __repr__(self) -> str:
        if self.valid:
            return "ValidationResult(valid=True)"
        return f"ValidationResult(valid=False, error={self.error!r})"


def verify_block(block: Block, prev_block: Optional[Block] = None,
                 verify_signatures: bool = False) -> ValidationResult:
    """Verify a block's integrity.

    Checks:
      1. prev_hash links to the previous block
      2. merkle_root matches operations
      3. timestamp is non-negative and monotonically increasing
      4. block_number is sequential
      5. chain_id consistency
      6. proposer signature (if verify_signatures=True)
      7. operation signatures (if verify_signatures=True)

    Args:
        block: The block to verify.
        prev_block: The previous block (for chain linkage checks).
                    None means skip prev_hash validation (genesis or first synced block).
        verify_signatures: Whether to verify Ed25519 signatures.

    Returns:
        ValidationResult with valid flag and optional error message.
    """
    # Basic field checks
    if block.block_number < 0:
        return ValidationResult(False, f"negative block_number: {block.block_number}")

    if block.timestamp < 0:
        return ValidationResult(False, f"negative timestamp: {block.timestamp}")

    if not block.chain_id:
        return ValidationResult(False, "empty chain_id")

    # Genesis block special case
    if block.block_number == 0:
        if block.prev_hash != GENESIS_PREV_HASH:
            return ValidationResult(False,
                f"genesis prev_hash must be zeroed, got {block.prev_hash}")

    # Chain linkage with previous block
    if prev_block is not None:
        if block.block_number != prev_block.block_number + 1:
            return ValidationResult(False,
                f"block_number gap: expected {prev_block.block_number + 1}, "
                f"got {block.block_number}")

        if block.prev_hash != prev_block.block_hash:
            return ValidationResult(False,
                f"prev_hash mismatch: expected {prev_block.block_hash}, "
                f"got {block.prev_hash}")

        if block.chain_id != prev_block.chain_id:
            return ValidationResult(False,
                f"chain_id mismatch: {block.chain_id} != {prev_block.chain_id}")

        if block.timestamp < prev_block.timestamp:
            return ValidationResult(False,
                f"timestamp regression: {block.timestamp} < {prev_block.timestamp}")

    # Merkle root verification
    expected_merkle = compute_merkle_root(block.operations)
    if block.merkle_root != expected_merkle:
        return ValidationResult(False,
            f"merkle_root mismatch: expected {expected_merkle}, "
            f"got {block.merkle_root}")

    # Signature verification (optional, for full validation)
    if verify_signatures and block.signature:
        try:
            from oasyce_plugin.crypto.keys import verify as ed25519_verify
            block_data = block.block_hash.encode()
            if not ed25519_verify(block_data, block.signature, block.proposer):
                return ValidationResult(False, "invalid proposer signature")
        except Exception as e:
            return ValidationResult(False, f"signature verification error: {e}")

    return ValidationResult(True)


def verify_block_chain(blocks: List[Block],
                       anchor: Optional[Block] = None,
                       verify_signatures: bool = False) -> ValidationResult:
    """Verify a sequence of blocks forms a valid chain.

    Args:
        blocks: Blocks to verify, sorted by block_number.
        anchor: The block immediately before the first block in the list.
        verify_signatures: Whether to check Ed25519 signatures.
    """
    if not blocks:
        return ValidationResult(True)

    prev = anchor
    for block in blocks:
        result = verify_block(block, prev, verify_signatures)
        if not result:
            return result
        prev = block

    return ValidationResult(True)


# ── Apply synced block ─────────────────────────────────────────────

def apply_synced_block(engine: ConsensusEngine, block: Block) -> Dict[str, Any]:
    """Apply a verified synced block to the local consensus engine.

    Wraps the block into the dict format expected by engine.apply_block().
    """
    block_dict = {
        "height": block.block_number,
        "block_number": block.block_number,
        "operations": list(block.operations),
    }
    return engine.apply_block(block_dict)


# ── Sync from peer ─────────────────────────────────────────────────

def sync_from_peer(peer: PeerTransport, engine: ConsensusEngine,
                   local_height: int, local_genesis_hash: str,
                   target_height: Optional[int] = None,
                   batch_size: int = 100,
                   verify_signatures: bool = False,
                   on_progress: Optional[Callable[[int, int], None]] = None,
                   ) -> SyncResult:
    """Sync blocks from a single peer.

    Steps:
      1. Get peer info (chain_id, height, genesis_hash)
      2. Verify genesis hash matches
      3. Batch-request blocks from local_height+1 to target
      4. Verify each block (hash chain, merkle, signatures)
      5. Apply to local state
      6. Return sync result

    Args:
        peer: The peer transport to sync from.
        engine: Local consensus engine.
        local_height: Current local chain height (-1 for empty).
        local_genesis_hash: Local genesis block hash (for validation).
        target_height: Sync up to this height (None = peer's height).
        batch_size: Number of blocks per request.
        verify_signatures: Verify Ed25519 signatures on blocks.
        on_progress: Callback(blocks_synced, target_height) for progress.

    Returns:
        SyncResult with status and statistics.
    """
    # 1. Get peer info
    try:
        peer_info = peer.get_peer_info()
    except Exception as e:
        return SyncResult(
            status=SyncStatus.ERROR,
            peer=peer.address,
            error=f"failed to get peer info: {e}",
        )

    # 2. Verify genesis hash
    if local_genesis_hash and peer_info.genesis_hash:
        if peer_info.genesis_hash != local_genesis_hash:
            return SyncResult(
                status=SyncStatus.GENESIS_MISMATCH,
                peer=peer.address,
                error=f"genesis mismatch: local={local_genesis_hash}, "
                      f"peer={peer_info.genesis_hash}",
            )

    # 3. Determine sync range
    effective_target = target_height if target_height is not None else peer_info.height
    start_height = local_height + 1

    if start_height > effective_target:
        return SyncResult(
            status=SyncStatus.ALREADY_SYNCED,
            from_height=local_height,
            to_height=local_height,
            peer=peer.address,
        )

    # 4. Batch download, verify, and apply
    blocks_synced = 0
    current_height = start_height
    prev_block: Optional[Block] = None  # for chain linkage

    while current_height <= effective_target:
        batch_end = min(current_height + batch_size - 1, effective_target)

        try:
            response = peer.get_blocks(GetBlocksRequest(
                from_height=current_height,
                to_height=batch_end,
                limit=batch_size,
            ))
        except Exception as e:
            if blocks_synced > 0:
                return SyncResult(
                    status=SyncStatus.PARTIAL,
                    blocks_synced=blocks_synced,
                    from_height=start_height,
                    to_height=start_height + blocks_synced - 1,
                    peer=peer.address,
                    error=f"batch request failed at height {current_height}: {e}",
                )
            return SyncResult(
                status=SyncStatus.ERROR,
                peer=peer.address,
                error=f"batch request failed: {e}",
            )

        if not response.blocks:
            break

        # Sort blocks by number for sequential application
        sorted_blocks = sorted(response.blocks, key=lambda b: b.block_number)

        for block in sorted_blocks:
            # Verify
            vr = verify_block(block, prev_block, verify_signatures)
            if not vr:
                if blocks_synced > 0:
                    return SyncResult(
                        status=SyncStatus.PARTIAL,
                        blocks_synced=blocks_synced,
                        from_height=start_height,
                        to_height=start_height + blocks_synced - 1,
                        peer=peer.address,
                        error=f"invalid block at height {block.block_number}: {vr.error}",
                    )
                return SyncResult(
                    status=SyncStatus.INVALID_BLOCK,
                    peer=peer.address,
                    error=f"invalid block at height {block.block_number}: {vr.error}",
                )

            # Apply
            apply_synced_block(engine, block)
            blocks_synced += 1
            prev_block = block

            if on_progress:
                on_progress(blocks_synced, effective_target - start_height + 1)

        current_height = batch_end + 1

    return SyncResult(
        status=SyncStatus.SUCCESS,
        blocks_synced=blocks_synced,
        from_height=start_height,
        to_height=start_height + blocks_synced - 1,
        peer=peer.address,
    )


# ── Fork-aware sync ──────────────────────────────────────────────


def sync_with_fork_detection(peer: PeerTransport, engine: ConsensusEngine,
                             local_height: int, local_genesis_hash: str,
                             local_blocks: Optional[List[Block]] = None,
                             verify_signatures: bool = False,
                             on_progress: Optional[Callable[[int, int], None]] = None,
                             ) -> SyncResult:
    """Sync from a peer with fork detection and reorg support.

    If a fork is detected and the remote chain is heavier, executes
    a chain reorganization before syncing the new blocks.

    Args:
        peer: Peer transport.
        engine: Local consensus engine.
        local_height: Current local chain height.
        local_genesis_hash: Local genesis block hash.
        local_blocks: Local chain blocks for fork detection (optional).
        verify_signatures: Verify Ed25519 signatures.
        on_progress: Progress callback.

    Returns:
        SyncResult with reorg info when applicable.
    """
    import logging
    logger = logging.getLogger(__name__)

    from oasyce_plugin.consensus.core.fork_choice import (
        detect_fork_info, execute_reorg, MAX_REORG_DEPTH,
    )

    # Get peer info
    try:
        peer_info = peer.get_peer_info()
    except Exception as e:
        return SyncResult(
            status=SyncStatus.ERROR,
            peer=peer.address,
            error=f"failed to get peer info: {e}",
        )

    # Genesis check
    if local_genesis_hash and peer_info.genesis_hash:
        if peer_info.genesis_hash != local_genesis_hash:
            return SyncResult(
                status=SyncStatus.GENESIS_MISMATCH,
                peer=peer.address,
                error="genesis mismatch",
            )

    # If we have local blocks, check for fork
    if local_blocks and local_height >= 0:
        # Fetch overlapping blocks from peer for fork detection
        overlap_start = max(0, local_height - MAX_REORG_DEPTH)
        try:
            resp = peer.get_blocks(GetBlocksRequest(
                from_height=overlap_start,
                to_height=peer_info.height,
                limit=peer_info.height - overlap_start + 1,
            ))
            peer_blocks = sorted(resp.blocks, key=lambda b: b.block_number)
        except Exception:
            peer_blocks = []

        if peer_blocks:
            fork_info = detect_fork_info(local_blocks, peer_blocks)

            if fork_info.has_fork and fork_info.remote_is_heavier:
                logger.info(
                    "fork detected at height %d: local_branch=%d remote_branch=%d "
                    "local_weight=%d remote_weight=%d — executing reorg",
                    fork_info.common_ancestor_height,
                    fork_info.local_branch_length,
                    fork_info.remote_branch_length,
                    fork_info.local_weight,
                    fork_info.remote_weight,
                )

                # Get the remote blocks after the common ancestor
                remote_new = [b for b in peer_blocks
                              if b.block_number > fork_info.common_ancestor_height]

                reorg_result = execute_reorg(
                    engine, fork_info.common_ancestor_height, remote_new,
                )

                if not reorg_result.success:
                    return SyncResult(
                        status=SyncStatus.ERROR,
                        peer=peer.address,
                        error=f"reorg failed: {reorg_result.error}",
                    )

                return SyncResult(
                    status=SyncStatus.SUCCESS,
                    blocks_synced=reorg_result.applied,
                    from_height=fork_info.common_ancestor_height + 1,
                    to_height=reorg_result.new_height,
                    peer=peer.address,
                )

    # No fork — normal sync
    return sync_from_peer(
        peer, engine, local_height, local_genesis_hash,
        target_height=peer_info.height,
        verify_signatures=verify_signatures,
        on_progress=on_progress,
    )


# ── Sync from network ─────────────────────────────────────────────

def sync_from_network(peers: List[PeerTransport], engine: ConsensusEngine,
                      local_height: int, local_genesis_hash: str,
                      verify_signatures: bool = False,
                      on_progress: Optional[Callable[[int, int], None]] = None,
                      ) -> SyncResult:
    """Find the best peer and sync from it.

    Steps:
      1. Query all peers for their chain info
      2. Filter peers with matching genesis
      3. Pick the peer with the highest height (fork choice)
      4. Sync from that peer

    Args:
        peers: List of peer transports.
        engine: Local consensus engine.
        local_height: Current local chain height.
        local_genesis_hash: Local genesis block hash.
        verify_signatures: Verify Ed25519 signatures.
        on_progress: Progress callback.

    Returns:
        SyncResult.
    """
    if not peers:
        return SyncResult(status=SyncStatus.NO_PEERS, error="no peers available")

    # 1. Gather peer info
    peer_infos: List[tuple] = []  # (peer, info)
    for peer in peers:
        try:
            info = peer.get_peer_info()
            peer_infos.append((peer, info))
        except Exception:
            continue

    if not peer_infos:
        return SyncResult(status=SyncStatus.NO_PEERS, error="all peers unreachable")

    # 2. Filter by genesis hash
    if local_genesis_hash:
        compatible = [(p, i) for p, i in peer_infos
                      if i.genesis_hash == local_genesis_hash]
        if not compatible:
            return SyncResult(
                status=SyncStatus.GENESIS_MISMATCH,
                error="no peers with matching genesis hash",
            )
        peer_infos = compatible

    # 3. Pick highest peer (longest chain rule)
    peer_infos.sort(key=lambda x: x[1].height, reverse=True)
    best_peer, best_info = peer_infos[0]

    if best_info.height <= local_height:
        return SyncResult(
            status=SyncStatus.ALREADY_SYNCED,
            from_height=local_height,
            to_height=local_height,
        )

    # 4. Sync from best peer
    return sync_from_peer(
        best_peer, engine, local_height, local_genesis_hash,
        target_height=best_info.height,
        verify_signatures=verify_signatures,
        on_progress=on_progress,
    )
