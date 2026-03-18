"""
Fork choice rule for Oasyce PoS consensus.

Implements longest-chain rule with cumulative stake-weight as tiebreaker.
Includes fork detection, chain reorganization, and reorg depth limits.

Functions:
  choose_fork()        -- select the canonical chain from candidates
  choose_best_chain()  -- alias: select best chain (weight-first, height second)
  is_canonical_chain() -- check if a chain is the canonical chain
  should_sync()        -- decide whether to sync from a remote
  rank_peers()         -- rank peers by chain score
  get_chain_weight()   -- compute cumulative validator stake weight for blocks
  find_common_ancestor() -- find the common ancestor between two block lists
  detect_fork()        -- find the fork point between two block lists
  reorg_to()           -- rollback local chain and apply new chain
  execute_reorg()      -- reorg with depth limit and snapshot cleanup
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from oasyce_plugin.consensus.network.sync_protocol import Block

logger = logging.getLogger(__name__)

# Maximum reorg depth — refuse reorgs deeper than this to prevent
# long-range attacks and keep rollback cost bounded.
MAX_REORG_DEPTH = 100


@dataclass
class ChainInfo:
    """Metadata about a candidate chain (from a peer or local)."""
    chain_id: str
    height: int
    genesis_hash: str
    cumulative_weight: int = 0    # total stake-weighted block production
    peer: str = ""                # peer address (empty for local)
    last_block_hash: str = ""

    @property
    def score(self) -> tuple:
        """Comparison key: (cumulative_weight, height).

        Weight is primary (PoS: heavier chain wins), height is tiebreaker.
        """
        return (self.cumulative_weight, self.height)


@dataclass(frozen=True)
class ForkInfo:
    """Detailed information about a detected fork."""
    common_ancestor_height: int
    local_branch_length: int
    remote_branch_length: int
    local_weight: int
    remote_weight: int

    @property
    def has_fork(self) -> bool:
        return self.local_branch_length > 0

    @property
    def reorg_depth(self) -> int:
        return self.local_branch_length

    @property
    def remote_is_heavier(self) -> bool:
        if self.remote_weight != self.local_weight:
            return self.remote_weight > self.local_weight
        return self.remote_branch_length > self.local_branch_length


# ── Chain selection ──────────────────────────────────────────────


def choose_fork(chains: List[ChainInfo],
                local_genesis_hash: str) -> Optional[ChainInfo]:
    """Select the best chain from candidates.

    Algorithm:
      1. Filter out chains whose genesis_hash doesn't match local
      2. Select the chain with the highest score (weight, then height)
      3. Return None if no compatible chains

    Args:
        chains: List of candidate chain infos.
        local_genesis_hash: The expected genesis hash.

    Returns:
        The best ChainInfo, or None if no compatible chains exist.
    """
    if not chains:
        return None

    compatible = [c for c in chains if c.genesis_hash == local_genesis_hash]
    if not compatible:
        return None

    return max(compatible, key=lambda c: c.score)


def choose_best_chain(local_chain: ChainInfo,
                      remote_chains: List[ChainInfo]) -> ChainInfo:
    """Select the best chain from local + remotes (weight-first, height second).

    Always returns a chain — local_chain is included as a candidate.
    """
    all_chains = [local_chain] + list(remote_chains)
    compatible = [c for c in all_chains
                  if c.genesis_hash == local_chain.genesis_hash]
    if not compatible:
        return local_chain
    return max(compatible, key=lambda c: c.score)


def is_canonical_chain(chain: ChainInfo, all_chains: List[ChainInfo],
                       local_genesis_hash: str) -> bool:
    """Check if a chain is the canonical (best) chain."""
    best = choose_fork(all_chains, local_genesis_hash)
    if best is None:
        return False
    return (chain.chain_id == best.chain_id
            and chain.height == best.height
            and chain.last_block_hash == best.last_block_hash)


def should_sync(local: ChainInfo, remote: ChainInfo,
                local_genesis_hash: str) -> bool:
    """Determine if we should sync from a remote chain.

    Returns True if the remote chain is better than local and compatible.
    """
    if remote.genesis_hash != local_genesis_hash:
        return False
    return remote.score > local.score


def rank_peers(peers: List[ChainInfo],
               local_genesis_hash: str) -> List[ChainInfo]:
    """Rank peers by chain score, best first.

    Filters out incompatible peers (wrong genesis).
    """
    compatible = [p for p in peers if p.genesis_hash == local_genesis_hash]
    return sorted(compatible, key=lambda c: c.score, reverse=True)


# ── Chain weight ─────────────────────────────────────────────────


def get_chain_weight(blocks: List[Block],
                     stake_fn: Any = None) -> int:
    """Compute cumulative chain weight from a list of blocks.

    Weight = sum of proposer stake for each block.  If no stake_fn
    is provided, each block contributes weight=1 (block count).

    Args:
        blocks: List of blocks to weight.
        stake_fn: Optional callable(proposer_id) -> int stake.
                  If None, each block has weight 1.

    Returns:
        Total chain weight as integer.
    """
    if not blocks:
        return 0

    weight = 0
    for block in blocks:
        if stake_fn is not None:
            try:
                w = stake_fn(block.proposer)
                weight += max(1, w)  # at least 1 per block
            except Exception:
                weight += 1
        else:
            weight += 1
    return weight


# ── Fork detection ────────────────────────────────────────────────


@dataclass
class ForkPoint:
    """Describes where two chains diverge."""
    height: int               # block height of the last common block
    common_hash: str = ""     # block hash at the fork point
    local_height: int = 0     # tip of local chain
    remote_height: int = 0    # tip of remote chain
    local_blocks_to_revert: int = 0
    remote_blocks_to_apply: int = 0

    @property
    def has_fork(self) -> bool:
        """True if chains diverge (not just behind)."""
        return self.local_blocks_to_revert > 0


@dataclass
class ReorgResult:
    """Result of a chain reorganization."""
    success: bool
    reverted: int = 0         # blocks rolled back
    applied: int = 0          # new blocks applied
    fork_height: int = 0
    new_height: int = 0
    error: str = ""


def find_common_ancestor(local_blocks: List[Block],
                         remote_blocks: List[Block]) -> int:
    """Find the height of the most recent common ancestor.

    Both lists must be sorted by block_number ascending.
    Returns -1 if no common ancestor exists.
    """
    if not local_blocks or not remote_blocks:
        return -1

    local_by_height = {b.block_number: b.block_hash for b in local_blocks}
    peer_by_height = {b.block_number: b.block_hash for b in remote_blocks}

    max_common = min(
        max(local_by_height) if local_by_height else -1,
        max(peer_by_height) if peer_by_height else -1,
    )

    ancestor = -1
    for h in range(0, max_common + 1):
        lh = local_by_height.get(h)
        ph = peer_by_height.get(h)
        if lh is not None and ph is not None and lh == ph:
            ancestor = h
        elif lh is not None and ph is not None:
            break
        else:
            break

    return ancestor


def detect_fork_info(local_blocks: List[Block],
                     peer_blocks: List[Block],
                     stake_fn: Any = None) -> ForkInfo:
    """Detect fork and compute branch weights.

    Args:
        local_blocks: Local chain blocks, ascending by block_number.
        peer_blocks:  Remote chain blocks, ascending by block_number.
        stake_fn: Optional callable(proposer_id) -> int for weight calc.

    Returns:
        ForkInfo with ancestor height, branch lengths, and weights.
    """
    ancestor = find_common_ancestor(local_blocks, peer_blocks)

    local_branch = [b for b in local_blocks if b.block_number > ancestor]
    remote_branch = [b for b in peer_blocks if b.block_number > ancestor]

    return ForkInfo(
        common_ancestor_height=ancestor,
        local_branch_length=len(local_branch),
        remote_branch_length=len(remote_branch),
        local_weight=get_chain_weight(local_branch, stake_fn),
        remote_weight=get_chain_weight(remote_branch, stake_fn),
    )


def detect_fork(local_blocks: List[Block],
                peer_blocks: List[Block]) -> ForkPoint:
    """Detect the fork point between two block lists.

    Both lists must be sorted by block_number ascending and share the
    same genesis block.  Walks from genesis forward to find the last
    block where the hashes agree.

    Args:
        local_blocks: Local chain blocks, ascending.
        peer_blocks:  Remote chain blocks, ascending.

    Returns:
        ForkPoint describing where the chains diverge.
    """
    if not local_blocks or not peer_blocks:
        return ForkPoint(
            height=-1,
            local_height=local_blocks[-1].block_number if local_blocks else -1,
            remote_height=peer_blocks[-1].block_number if peer_blocks else -1,
            local_blocks_to_revert=len(local_blocks),
            remote_blocks_to_apply=len(peer_blocks),
        )

    local_by_height = {b.block_number: b.block_hash for b in local_blocks}
    peer_by_height = {b.block_number: b.block_hash for b in peer_blocks}

    max_common_height = min(
        max(local_by_height) if local_by_height else -1,
        max(peer_by_height) if peer_by_height else -1,
    )

    fork_height = -1
    common_hash = ""
    for h in range(0, max_common_height + 1):
        lh = local_by_height.get(h)
        ph = peer_by_height.get(h)
        if lh is not None and ph is not None and lh == ph:
            fork_height = h
            common_hash = lh
        elif lh is not None and ph is not None:
            break
        else:
            break

    local_tip = local_blocks[-1].block_number
    remote_tip = peer_blocks[-1].block_number

    return ForkPoint(
        height=fork_height,
        common_hash=common_hash,
        local_height=local_tip,
        remote_height=remote_tip,
        local_blocks_to_revert=local_tip - fork_height,
        remote_blocks_to_apply=remote_tip - fork_height,
    )


# Keep detect_fork_point as alias for detect_fork
detect_fork_point = detect_fork


# ── Chain reorganization ─────────────────────────────────────────


def execute_reorg(engine: Any,
                  common_ancestor: int,
                  new_blocks: List[Block],
                  max_depth: int = MAX_REORG_DEPTH,
                  verify: bool = True) -> ReorgResult:
    """Execute a chain reorganization with depth limit.

    Steps:
      1. Check reorg depth against limit
      2. Revert state to common_ancestor (marks events as reverted)
      3. Delete snapshots > common_ancestor
      4. Apply new_blocks sequentially
      5. Create a new snapshot

    Args:
        engine: ConsensusEngine instance.
        common_ancestor: Block height of the common ancestor.
        new_blocks: Blocks to apply after the ancestor (sorted ascending).
        max_depth: Maximum reorg depth allowed.
        verify: Whether to verify each block before applying.

    Returns:
        ReorgResult with statistics.
    """
    from oasyce_plugin.consensus.network.block_sync import (
        verify_block, apply_synced_block,
    )

    if not new_blocks:
        return ReorgResult(success=True, fork_height=common_ancestor,
                           new_height=common_ancestor)

    # Filter to blocks after ancestor
    blocks_to_apply = [b for b in new_blocks if b.block_number > common_ancestor]
    if not blocks_to_apply:
        return ReorgResult(success=True, fork_height=common_ancestor,
                           new_height=common_ancestor)

    blocks_to_apply.sort(key=lambda b: b.block_number)

    # Compute how many blocks we need to revert
    # We need the engine's current height to know revert depth
    revert_depth = 0
    if hasattr(engine, 'state') and hasattr(engine.state, 'get_meta'):
        current_h = engine.state.get_meta("current_height")
        if current_h is not None:
            revert_depth = int(current_h) - common_ancestor
        else:
            # Estimate from blocks_to_apply: the first block tells us
            revert_depth = 0

    # Check depth limit
    if revert_depth > max_depth:
        return ReorgResult(
            success=False,
            fork_height=common_ancestor,
            error=f"reorg depth {revert_depth} exceeds max {max_depth}",
        )

    # Verify block chain continuity
    if verify:
        prev = None
        for b in blocks_to_apply:
            vr = verify_block(b, prev)
            if not vr:
                return ReorgResult(
                    success=False,
                    fork_height=common_ancestor,
                    error=f"invalid block at height {b.block_number}: {vr.error}",
                )
            prev = b

    # Revert state to common_ancestor
    reverted = 0
    if hasattr(engine, 'state') and hasattr(engine.state, 'revert_to_height'):
        reverted = engine.state.revert_to_height(common_ancestor)
        logger.info("reverted %d events to height %d", reverted, common_ancestor)

    # Delete snapshots above common_ancestor
    if hasattr(engine, 'state') and hasattr(engine.state, 'delete_snapshots_above'):
        engine.state.delete_snapshots_above(common_ancestor)

    # Apply new blocks
    applied = 0
    new_height = common_ancestor
    for block in blocks_to_apply:
        try:
            apply_synced_block(engine, block)
            applied += 1
            new_height = block.block_number
        except Exception as e:
            return ReorgResult(
                success=False,
                reverted=reverted,
                applied=applied,
                fork_height=common_ancestor,
                new_height=new_height,
                error=f"apply failed at height {block.block_number}: {e}",
            )

    # Create new snapshot at the new tip
    try:
        from oasyce_plugin.consensus.storage.snapshots import create_snapshot
        if new_height > 0:
            create_snapshot(engine.state, new_height)
    except Exception:
        pass  # snapshot creation is optional

    logger.info("reorg complete: reverted=%d applied=%d new_height=%d",
                reverted, applied, new_height)

    return ReorgResult(
        success=True,
        reverted=reverted,
        applied=applied,
        fork_height=common_ancestor,
        new_height=new_height,
    )


def reorg_to(engine: Any,
             new_blocks: List[Block],
             fork_point: ForkPoint,
             verify: bool = True,
             max_depth: int = MAX_REORG_DEPTH) -> ReorgResult:
    """Execute a chain reorganization (convenience wrapper).

    Delegates to execute_reorg using fork_point.height as the ancestor.
    """
    # Check depth limit against fork_point info
    if fork_point.local_blocks_to_revert > max_depth:
        return ReorgResult(
            success=False,
            fork_height=fork_point.height,
            error=f"reorg depth {fork_point.local_blocks_to_revert} exceeds max {max_depth}",
        )

    return execute_reorg(
        engine, fork_point.height, new_blocks,
        max_depth=max_depth, verify=verify,
    )
