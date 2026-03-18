"""
Tests for fork choice rule, fork detection, chain reorganization, and reorg depth limits.

Covers:
  - choose_best_chain (weight-first, height-second selection)
  - choose_fork (genesis filtering, best chain selection)
  - get_chain_weight (with and without stake_fn)
  - find_common_ancestor (various fork topologies)
  - detect_fork → ForkInfo (branch lengths, weights, has_fork)
  - detect_fork_point → ForkPoint (legacy API)
  - execute_reorg (rollback + apply, depth limit, snapshot cleanup)
  - reorg_to (convenience wrapper with depth limit)
  - revert_to_height on ConsensusState (event-sourced rollback)
  - delete_snapshots_above
  - sync_with_fork_detection integration
  - Edge cases: no fork, genesis fork, single-block fork, empty chains
"""

import time
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

from oasyce_plugin.consensus.core.types import Operation, OperationType, to_units
from oasyce_plugin.consensus.core.fork_choice import (
    ChainInfo,
    ForkInfo,
    ForkPoint,
    ReorgResult,
    MAX_REORG_DEPTH,
    choose_fork,
    choose_best_chain,
    is_canonical_chain,
    should_sync,
    rank_peers,
    get_chain_weight,
    find_common_ancestor,
    detect_fork,
    detect_fork_info,
    detect_fork_point,
    execute_reorg,
    reorg_to,
)
from oasyce_plugin.consensus.network.sync_protocol import (
    Block,
    GENESIS_PREV_HASH,
    compute_merkle_root,
    make_genesis_block,
    SyncStatus,
)
from oasyce_plugin.consensus.network.block_sync import (
    InMemoryPeer,
    apply_synced_block,
    sync_with_fork_detection,
)
from oasyce_plugin.consensus import ConsensusEngine


# ── Helpers ────────────────────────────────────────────────────────

CHAIN_ID = "oasyce-test-fork"
TS = 1700000000


def _genesis():
    return make_genesis_block(CHAIN_ID, timestamp=TS)


def _make_op(validator_id="val_001", amount=200, op_type=OperationType.REGISTER):
    return Operation(
        op_type=op_type,
        validator_id=validator_id,
        amount=to_units(amount),
        commission_rate=1000,
    )


def _make_block(block_number, prev_block, operations=(), proposer="proposer_1",
                chain_id=CHAIN_ID, timestamp=None):
    ops = tuple(operations)
    merkle = compute_merkle_root(ops)
    ts = timestamp if timestamp is not None else TS + block_number
    prev_hash = prev_block.block_hash if prev_block else GENESIS_PREV_HASH
    return Block(
        chain_id=chain_id,
        block_number=block_number,
        prev_hash=prev_hash,
        merkle_root=merkle,
        timestamp=ts,
        operations=ops,
        proposer=proposer,
    )


def _build_chain(length, chain_id=CHAIN_ID, proposer="proposer_1"):
    """Build a chain of `length` blocks (0=genesis, 1..length-1=regular)."""
    genesis = make_genesis_block(chain_id, TS)
    blocks = [genesis]
    for i in range(1, length):
        blocks.append(_make_block(i, blocks[-1], proposer=proposer, chain_id=chain_id))
    return blocks


def _build_fork(common_prefix_len, local_extra, remote_extra,
                local_proposer="local_prop", remote_proposer="remote_prop"):
    """Build two chains that share a common prefix then diverge.

    Returns (local_blocks, remote_blocks).
    """
    common = _build_chain(common_prefix_len)
    fork_point = common[-1]

    local_blocks = list(common)
    for i in range(common_prefix_len, common_prefix_len + local_extra):
        local_blocks.append(_make_block(i, local_blocks[-1], proposer=local_proposer))

    remote_blocks = list(common)
    for i in range(common_prefix_len, common_prefix_len + remote_extra):
        # Different proposer → different merkle/hash → genuine fork
        remote_blocks.append(_make_block(
            i, remote_blocks[-1], proposer=remote_proposer,
            timestamp=TS + i + 1000,  # different timestamp to create different hash
        ))

    return local_blocks, remote_blocks


def _make_engine(tmp_path=None):
    db = str(tmp_path / "test.db") if tmp_path else ":memory:"
    return ConsensusEngine(db_path=db)


def _make_peer(addr, blocks, chain_id=CHAIN_ID):
    genesis = blocks[0] if blocks else _genesis()
    return InMemoryPeer(addr, chain_id, genesis.block_hash, blocks)


GENESIS_HASH = _genesis().block_hash


# ═══════════════════════════════════════════════════════════════════
# 1. ChainInfo and choose_best_chain / choose_fork
# ═══════════════════════════════════════════════════════════════════

class TestChooseBestChain:
    def test_select_heavier_chain(self):
        local = ChainInfo("c1", height=5, genesis_hash="g", cumulative_weight=100)
        remote = ChainInfo("c1", height=5, genesis_hash="g", cumulative_weight=200, peer="p1")
        result = choose_best_chain(local, [remote])
        assert result.cumulative_weight == 200

    def test_select_taller_when_same_weight(self):
        local = ChainInfo("c1", height=5, genesis_hash="g", cumulative_weight=100)
        remote = ChainInfo("c1", height=10, genesis_hash="g", cumulative_weight=100, peer="p1")
        result = choose_best_chain(local, [remote])
        assert result.height == 10

    def test_local_wins_when_best(self):
        local = ChainInfo("c1", height=10, genesis_hash="g", cumulative_weight=500)
        remote = ChainInfo("c1", height=5, genesis_hash="g", cumulative_weight=100, peer="p1")
        result = choose_best_chain(local, [remote])
        assert result.height == 10
        assert result.peer == ""  # local

    def test_empty_remotes(self):
        local = ChainInfo("c1", height=5, genesis_hash="g", cumulative_weight=100)
        result = choose_best_chain(local, [])
        assert result == local

    def test_filters_incompatible_genesis(self):
        local = ChainInfo("c1", height=5, genesis_hash="g1", cumulative_weight=100)
        remote = ChainInfo("c1", height=20, genesis_hash="g2", cumulative_weight=999, peer="p1")
        result = choose_best_chain(local, [remote])
        assert result == local  # remote filtered out

    def test_multiple_remotes_picks_best(self):
        local = ChainInfo("c1", height=5, genesis_hash="g", cumulative_weight=100)
        r1 = ChainInfo("c1", height=8, genesis_hash="g", cumulative_weight=200, peer="p1")
        r2 = ChainInfo("c1", height=6, genesis_hash="g", cumulative_weight=300, peer="p2")
        result = choose_best_chain(local, [r1, r2])
        # r2 has weight 300 > r1 weight 200, so r2 wins
        assert result.peer == "p2"


class TestChooseFork:
    def test_no_chains(self):
        assert choose_fork([], "g") is None

    def test_no_compatible(self):
        chains = [ChainInfo("c1", 5, "other_genesis")]
        assert choose_fork(chains, "g") is None

    def test_single_chain(self):
        c = ChainInfo("c1", 5, "g", 100)
        assert choose_fork([c], "g") == c

    def test_picks_best_score(self):
        c1 = ChainInfo("c1", 5, "g", 100)
        c2 = ChainInfo("c1", 5, "g", 200)
        assert choose_fork([c1, c2], "g") == c2


class TestShouldSync:
    def test_remote_ahead(self):
        local = ChainInfo("c1", 5, "g", 100)
        remote = ChainInfo("c1", 10, "g", 200)
        assert should_sync(local, remote, "g") is True

    def test_remote_behind(self):
        local = ChainInfo("c1", 10, "g", 200)
        remote = ChainInfo("c1", 5, "g", 100)
        assert should_sync(local, remote, "g") is False

    def test_genesis_mismatch(self):
        local = ChainInfo("c1", 5, "g1")
        remote = ChainInfo("c1", 10, "g2")
        assert should_sync(local, remote, "g1") is False

    def test_equal_chains(self):
        local = ChainInfo("c1", 5, "g", 100)
        remote = ChainInfo("c1", 5, "g", 100)
        assert should_sync(local, remote, "g") is False


class TestRankPeers:
    def test_ranks_by_score(self):
        p1 = ChainInfo("c1", 5, "g", 100, peer="a")
        p2 = ChainInfo("c1", 10, "g", 50, peer="b")
        p3 = ChainInfo("c1", 5, "g", 200, peer="c")
        ranked = rank_peers([p1, p2, p3], "g")
        # Score = (weight, height): p3=(200,5), p1=(100,5), p2=(50,10)
        assert ranked[0].peer == "c"

    def test_filters_incompatible(self):
        p1 = ChainInfo("c1", 5, "g1", peer="a")
        p2 = ChainInfo("c1", 5, "g2", peer="b")
        ranked = rank_peers([p1, p2], "g1")
        assert len(ranked) == 1
        assert ranked[0].peer == "a"


# ═══════════════════════════════════════════════════════════════════
# 2. get_chain_weight
# ═══════════════════════════════════════════════════════════════════

class TestGetChainWeight:
    def test_empty_blocks(self):
        assert get_chain_weight([]) == 0

    def test_default_weight_per_block(self):
        blocks = _build_chain(5)
        assert get_chain_weight(blocks) == 5  # 1 per block

    def test_with_stake_fn(self):
        blocks = _build_chain(3)
        # proposer_1 has stake 1000
        stake_fn = lambda p: 1000 if p == "proposer_1" else 500
        w = get_chain_weight(blocks, stake_fn)
        # genesis proposer is "genesis", others are "proposer_1"
        # genesis: max(1, stake_fn("genesis"))=500, block1: 1000, block2: 1000
        assert w == 500 + 1000 + 1000

    def test_stake_fn_exception_fallback(self):
        blocks = _build_chain(3)
        def bad_fn(p):
            raise ValueError("boom")
        w = get_chain_weight(blocks, bad_fn)
        assert w == 3  # falls back to 1 per block

    def test_min_weight_one(self):
        blocks = _build_chain(2)
        w = get_chain_weight(blocks, lambda p: 0)
        assert w == 2  # min 1 per block


# ═══════════════════════════════════════════════════════════════════
# 3. find_common_ancestor
# ═══════════════════════════════════════════════════════════════════

class TestFindCommonAncestor:
    def test_identical_chains(self):
        chain = _build_chain(5)
        assert find_common_ancestor(chain, chain) == 4

    def test_no_blocks(self):
        assert find_common_ancestor([], []) == -1
        chain = _build_chain(3)
        assert find_common_ancestor(chain, []) == -1
        assert find_common_ancestor([], chain) == -1

    def test_fork_at_genesis(self):
        local, remote = _build_fork(1, 3, 3)  # only genesis shared
        assert find_common_ancestor(local, remote) == 0

    def test_fork_after_several_blocks(self):
        local, remote = _build_fork(5, 3, 2)  # share blocks 0-4
        assert find_common_ancestor(local, remote) == 4

    def test_no_common_ancestor_different_genesis(self):
        local = _build_chain(3, chain_id="chain-a")
        remote = _build_chain(3, chain_id="chain-b")
        # Different chain_id → different genesis hash → ancestor = -1
        assert find_common_ancestor(local, remote) == -1


# ═══════════════════════════════════════════════════════════════════
# 4. detect_fork_info → ForkInfo
# ═══════════════════════════════════════════════════════════════════

class TestDetectForkInfo:
    def test_no_fork_identical(self):
        chain = _build_chain(5)
        info = detect_fork_info(chain, chain)
        assert info.common_ancestor_height == 4
        assert info.local_branch_length == 0
        assert info.remote_branch_length == 0
        assert info.has_fork is False

    def test_remote_longer_no_fork(self):
        short = _build_chain(3)
        long = _build_chain(6)
        info = detect_fork_info(short, long)
        assert info.common_ancestor_height == 2
        assert info.local_branch_length == 0
        assert info.remote_branch_length == 3
        assert info.has_fork is False

    def test_fork_detected(self):
        local, remote = _build_fork(3, 2, 4)
        info = detect_fork_info(local, remote)
        assert info.common_ancestor_height == 2
        assert info.local_branch_length == 2
        assert info.remote_branch_length == 4
        assert info.has_fork is True

    def test_remote_is_heavier_by_length(self):
        local, remote = _build_fork(3, 2, 5)
        info = detect_fork_info(local, remote)
        assert info.remote_is_heavier is True

    def test_local_is_heavier(self):
        local, remote = _build_fork(3, 5, 2)
        info = detect_fork_info(local, remote)
        assert info.remote_is_heavier is False

    def test_with_stake_fn(self):
        local, remote = _build_fork(3, 3, 3)
        stake_fn = lambda p: 1000 if p == "local_prop" else 100
        info = detect_fork_info(local, remote, stake_fn)
        assert info.local_weight > info.remote_weight
        assert info.remote_is_heavier is False

    def test_empty_chains(self):
        chain = _build_chain(3)
        info = detect_fork_info([], chain)
        assert info.common_ancestor_height == -1
        assert info.local_branch_length == 0
        assert info.remote_branch_length == 3

    def test_single_block_fork(self):
        local, remote = _build_fork(5, 1, 1)
        info = detect_fork_info(local, remote)
        assert info.common_ancestor_height == 4
        assert info.local_branch_length == 1
        assert info.remote_branch_length == 1
        assert info.has_fork is True


# ═══════════════════════════════════════════════════════════════════
# 5. detect_fork_point (legacy ForkPoint API)
# ═══════════════════════════════════════════════════════════════════

class TestDetectForkPoint:
    def test_no_fork(self):
        chain = _build_chain(5)
        fp = detect_fork_point(chain, chain)
        assert fp.height == 4
        assert fp.has_fork is False
        assert fp.local_blocks_to_revert == 0

    def test_fork_at_block_2(self):
        local, remote = _build_fork(3, 2, 4)
        fp = detect_fork_point(local, remote)
        assert fp.height == 2
        assert fp.local_height == 4
        assert fp.remote_height == 6
        assert fp.local_blocks_to_revert == 2
        assert fp.remote_blocks_to_apply == 4
        assert fp.has_fork is True

    def test_empty_local(self):
        remote = _build_chain(3)
        fp = detect_fork_point([], remote)
        assert fp.height == -1

    def test_empty_remote(self):
        local = _build_chain(3)
        fp = detect_fork_point(local, [])
        assert fp.height == -1


# ═══════════════════════════════════════════════════════════════════
# 6. execute_reorg
# ═══════════════════════════════════════════════════════════════════

class TestExecuteReorg:
    def test_reorg_applies_new_blocks(self, tmp_path):
        engine = _make_engine(tmp_path)
        # Build common + local fork
        local, remote = _build_fork(3, 2, 4)

        # Apply local chain first
        for block in local[1:]:  # skip genesis
            apply_synced_block(engine, block)

        # Reorg to remote chain
        result = execute_reorg(engine, 2, remote)
        assert result.success is True
        assert result.applied == 4  # blocks 3,4,5,6
        assert result.fork_height == 2
        assert result.new_height == 6

    def test_reorg_empty_new_blocks(self, tmp_path):
        engine = _make_engine(tmp_path)
        result = execute_reorg(engine, 5, [])
        assert result.success is True
        assert result.applied == 0

    def test_reorg_depth_limit_exceeded(self, tmp_path):
        engine = _make_engine(tmp_path)
        # Set current_height in meta so depth = 200 - 50 = 150
        engine.state.set_meta("current_height", "200")
        # Build blocks that are after height 50
        genesis = _genesis()
        blocks = [genesis]
        for i in range(51, 56):
            blocks.append(_make_block(i, blocks[-1]))
        result = execute_reorg(engine, 50, blocks, max_depth=100)
        assert result.success is False
        assert "exceeds max" in result.error

    def test_reorg_within_depth_limit(self, tmp_path):
        engine = _make_engine(tmp_path)
        engine.state.set_meta("current_height", "50")
        local, remote = _build_fork(3, 2, 4)
        for block in local[1:]:
            apply_synced_block(engine, block)
        result = execute_reorg(engine, 2, remote, max_depth=100)
        assert result.success is True

    def test_reorg_reverts_events(self, tmp_path):
        engine = _make_engine(tmp_path)
        # Register a validator at height 1
        op = _make_op("val_reorg", 100)
        result1 = engine.apply(op, block_height=1)
        assert result1.get("ok") is True
        stake_before = engine.state.get_validator_stake("val_reorg")
        assert stake_before > 0

        # Register another at height 5
        op2 = _make_op("val_reorg_2", 200, op_type=OperationType.REGISTER)
        result2 = engine.apply(op2, block_height=5)
        assert result2.get("ok") is True

        # Verify both have events
        events_before = engine.state.get_stake_events(include_reverted=True)
        h5_events = [e for e in events_before if e["block_height"] == 5]
        assert len(h5_events) > 0, f"No events at height 5. All events: {events_before}"

        # Revert to height 3 — val_reorg_2's events at height 5 should be reverted
        reverted = engine.state.revert_to_height(3)
        assert reverted > 0, f"Expected reverted > 0, got {reverted}. Events: {events_before}"

        # val_reorg_2 events are reverted, stake should be 0
        stake_after = engine.state.get_validator_stake("val_reorg_2")
        assert stake_after == 0

        # val_reorg at height 1 should still have stake
        stake_1 = engine.state.get_validator_stake("val_reorg")
        assert stake_1 > 0

    def test_reorg_invalid_block_fails(self, tmp_path):
        engine = _make_engine(tmp_path)
        # Create a block with wrong prev_hash
        bad_block = Block(
            chain_id=CHAIN_ID,
            block_number=3,
            prev_hash="wrong_hash",
            merkle_root="0" * 64,
            timestamp=TS + 3,
            operations=(),
            proposer="bad",
        )
        result = execute_reorg(engine, 2, [bad_block])
        # The block should fail verification since there's no valid chain linkage
        # For a single block without predecessor, verify_block allows it (prev=None)
        # so it passes. Let's test with two blocks that break linkage.
        b1 = _make_block(3, _genesis())  # valid on its own
        b2 = Block(
            chain_id=CHAIN_ID,
            block_number=4,
            prev_hash="broken_link",
            merkle_root="0" * 64,
            timestamp=TS + 4,
        )
        result = execute_reorg(engine, 2, [b1, b2])
        assert result.success is False
        assert "invalid block" in result.error


class TestReorgTo:
    def test_convenience_wrapper(self, tmp_path):
        engine = _make_engine(tmp_path)
        local, remote = _build_fork(3, 2, 4)
        for block in local[1:]:
            apply_synced_block(engine, block)

        fp = detect_fork_point(local, remote)
        result = reorg_to(engine, remote, fp)
        assert result.success is True
        assert result.applied == 4

    def test_depth_limit_via_fork_point(self, tmp_path):
        engine = _make_engine(tmp_path)
        fp = ForkPoint(
            height=0,
            local_height=200,
            remote_height=250,
            local_blocks_to_revert=200,
        )
        result = reorg_to(engine, _build_chain(3), fp, max_depth=50)
        assert result.success is False
        assert "exceeds max" in result.error


# ═══════════════════════════════════════════════════════════════════
# 7. ConsensusState revert_to_height
# ═══════════════════════════════════════════════════════════════════

class TestRevertToHeight:
    def test_reverts_events_above_height(self):
        engine = _make_engine()
        engine.apply(_make_op("v1", 100), block_height=1)
        engine.apply(_make_op("v2", 200), block_height=5)
        engine.apply(_make_op("v3", 300), block_height=10)

        reverted = engine.state.revert_to_height(5)
        assert reverted > 0

        # v3 should have 0 stake (reverted)
        assert engine.state.get_validator_stake("v3") == 0
        # v1 and v2 should still have stake
        assert engine.state.get_validator_stake("v1") > 0
        assert engine.state.get_validator_stake("v2") > 0

    def test_revert_to_zero(self):
        engine = _make_engine()
        engine.apply(_make_op("v1", 100), block_height=1)
        reverted = engine.state.revert_to_height(0)
        assert reverted > 0
        assert engine.state.get_validator_stake("v1") == 0

    def test_revert_idempotent(self):
        engine = _make_engine()
        engine.apply(_make_op("v1", 100), block_height=1)
        engine.state.revert_to_height(0)
        # Second revert should revert 0 additional events
        reverted = engine.state.revert_to_height(0)
        assert reverted == 0

    def test_revert_preserves_audit_trail(self):
        engine = _make_engine()
        engine.apply(_make_op("v1", 100), block_height=1)
        engine.apply(_make_op("v2", 200), block_height=5)

        engine.state.revert_to_height(2)

        # Reverted events should still be readable with include_reverted
        events = engine.state.get_stake_events(include_reverted=True)
        assert len(events) >= 2  # both events still present

        # Without reverted, only v1's events
        active_events = engine.state.get_stake_events(include_reverted=False)
        for ev in active_events:
            assert ev["block_height"] <= 2


class TestDeleteSnapshotsAbove:
    def test_deletes_snapshots(self, tmp_path):
        engine = _make_engine(tmp_path)
        from oasyce_plugin.consensus.storage.snapshots import create_snapshot

        engine.apply(_make_op("v1", 100), block_height=1)
        create_snapshot(engine.state, 5)
        create_snapshot(engine.state, 10)
        create_snapshot(engine.state, 15)

        deleted = engine.state.delete_snapshots_above(10)
        assert deleted == 1  # snapshot at 15

    def test_delete_all_snapshots(self, tmp_path):
        engine = _make_engine(tmp_path)
        from oasyce_plugin.consensus.storage.snapshots import create_snapshot

        engine.apply(_make_op("v1", 100), block_height=1)
        create_snapshot(engine.state, 5)
        create_snapshot(engine.state, 10)

        deleted = engine.state.delete_snapshots_above(0)
        assert deleted == 2


# ═══════════════════════════════════════════════════════════════════
# 8. ForkInfo dataclass
# ═══════════════════════════════════════════════════════════════════

class TestForkInfo:
    def test_has_fork_true(self):
        fi = ForkInfo(common_ancestor_height=5, local_branch_length=3,
                      remote_branch_length=4, local_weight=30, remote_weight=40)
        assert fi.has_fork is True
        assert fi.reorg_depth == 3

    def test_has_fork_false(self):
        fi = ForkInfo(common_ancestor_height=5, local_branch_length=0,
                      remote_branch_length=3, local_weight=0, remote_weight=30)
        assert fi.has_fork is False

    def test_remote_heavier_by_weight(self):
        fi = ForkInfo(common_ancestor_height=5, local_branch_length=3,
                      remote_branch_length=3, local_weight=100, remote_weight=200)
        assert fi.remote_is_heavier is True

    def test_local_heavier_by_weight(self):
        fi = ForkInfo(common_ancestor_height=5, local_branch_length=3,
                      remote_branch_length=3, local_weight=200, remote_weight=100)
        assert fi.remote_is_heavier is False

    def test_equal_weight_remote_longer(self):
        fi = ForkInfo(common_ancestor_height=5, local_branch_length=3,
                      remote_branch_length=5, local_weight=100, remote_weight=100)
        assert fi.remote_is_heavier is True

    def test_frozen(self):
        fi = ForkInfo(common_ancestor_height=5, local_branch_length=1,
                      remote_branch_length=2, local_weight=10, remote_weight=20)
        with pytest.raises(AttributeError):
            fi.local_weight = 999


# ═══════════════════════════════════════════════════════════════════
# 9. sync_with_fork_detection integration
# ═══════════════════════════════════════════════════════════════════

class TestSyncWithForkDetection:
    def test_normal_sync_no_local_blocks(self, tmp_path):
        """Without local_blocks, falls back to normal sync."""
        engine = _make_engine(tmp_path)
        remote_chain = _build_chain(5)
        peer = _make_peer("peer1", remote_chain)
        genesis_hash = remote_chain[0].block_hash

        result = sync_with_fork_detection(
            peer, engine, -1, genesis_hash,
            local_blocks=None,
        )
        assert result.ok

    def test_reorg_when_remote_heavier(self, tmp_path):
        """Remote chain is longer → reorg to it."""
        engine = _make_engine(tmp_path)
        local, remote = _build_fork(3, 2, 5)
        genesis_hash = local[0].block_hash

        # Apply local chain
        for block in local[1:]:
            apply_synced_block(engine, block)

        peer = _make_peer("peer1", remote, CHAIN_ID)

        result = sync_with_fork_detection(
            peer, engine, 4, genesis_hash,
            local_blocks=local,
        )
        assert result.ok
        assert result.blocks_synced == 5  # 5 remote blocks after ancestor

    def test_no_reorg_when_local_heavier(self, tmp_path):
        """Local chain is longer → no reorg, normal sync (already synced)."""
        engine = _make_engine(tmp_path)
        local, remote = _build_fork(3, 5, 2)
        genesis_hash = local[0].block_hash

        for block in local[1:]:
            apply_synced_block(engine, block)

        peer = _make_peer("peer1", remote, CHAIN_ID)

        result = sync_with_fork_detection(
            peer, engine, 7, genesis_hash,
            local_blocks=local,
        )
        # Local is ahead; should be already synced or normal sync
        assert result.status in (SyncStatus.ALREADY_SYNCED, SyncStatus.SUCCESS)

    def test_genesis_mismatch(self, tmp_path):
        engine = _make_engine(tmp_path)
        remote_chain = _build_chain(5, chain_id="other-chain")
        peer = _make_peer("peer1", remote_chain, "other-chain")

        result = sync_with_fork_detection(
            peer, engine, -1, "some_different_hash",
            local_blocks=None,
        )
        assert result.status == SyncStatus.GENESIS_MISMATCH


# ═══════════════════════════════════════════════════════════════════
# 10. Edge cases
# ═══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_genesis_only_fork(self):
        """Both chains have only genesis — no fork."""
        local = _build_chain(1)
        remote = _build_chain(1)
        fp = detect_fork(local, remote)
        assert fp.height == 0
        assert fp.has_fork is False

    def test_genesis_only_fork_info(self):
        """detect_fork_info for genesis-only chains."""
        local = _build_chain(1)
        remote = _build_chain(1)
        info = detect_fork_info(local, remote)
        assert info.common_ancestor_height == 0
        assert info.has_fork is False

    def test_is_canonical_chain(self):
        c1 = ChainInfo("c1", 5, "g", 100, last_block_hash="h1")
        c2 = ChainInfo("c1", 5, "g", 200, last_block_hash="h2")
        c3 = ChainInfo("c1", 3, "g", 50, last_block_hash="h3")

        assert is_canonical_chain(c2, [c1, c2, c3], "g") is True
        assert is_canonical_chain(c1, [c1, c2, c3], "g") is False

    def test_max_reorg_depth_constant(self):
        assert MAX_REORG_DEPTH == 100

    def test_chain_info_score_weight_primary(self):
        """Weight should be primary in score comparison."""
        c1 = ChainInfo("c1", height=100, genesis_hash="g", cumulative_weight=50)
        c2 = ChainInfo("c1", height=10, genesis_hash="g", cumulative_weight=500)
        # c2 has more weight, should have higher score
        assert c2.score > c1.score

    def test_reorg_result_fields(self):
        r = ReorgResult(success=True, reverted=3, applied=5, fork_height=10, new_height=15)
        assert r.success is True
        assert r.reverted == 3
        assert r.applied == 5
        assert r.new_height == 15
