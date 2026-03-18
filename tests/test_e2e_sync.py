"""
End-to-end tests for block synchronization protocol.

Simulates multi-node scenarios:
  - 3-node network: Node 1 produces blocks, Node 2 joins and syncs
  - Fork scenario: Node 3 joins with a divergent chain
  - State consistency verification after sync
  - Incremental sync (node joins late)
  - Operations applied during sync

All tests use in-memory engines and InMemoryPeer transports
(no real networking), proving correctness of the sync logic itself.
"""

import tempfile
from pathlib import Path

import pytest

from oasyce_plugin.consensus import ConsensusEngine
from oasyce_plugin.consensus.core.types import Operation, OperationType, to_units
from oasyce_plugin.consensus.network.sync_protocol import (
    Block,
    GENESIS_PREV_HASH,
    compute_merkle_root,
    make_genesis_block,
)
from oasyce_plugin.consensus.network.block_sync import (
    InMemoryPeer,
    sync_from_peer,
    sync_from_network,
    verify_block_chain,
    SyncStatus,
)
from oasyce_plugin.consensus.core.fork_choice import (
    ChainInfo,
    detect_fork,
    reorg_to,
    ForkPoint,
    choose_fork,
)


# ── Helpers ────────────────────────────────────────────────────────

CHAIN_ID = "oasyce-e2e-test"
TS = 1700000000


def _make_engine(tmp_path, name="node"):
    db = str(tmp_path / f"{name}.db")
    return ConsensusEngine(
        db_path=db,
        consensus_params={"chain_id": CHAIN_ID, "blocks_per_epoch": 10},
    )


def _make_op(validator_id, amount=100, op_type=OperationType.REGISTER):
    return Operation(
        op_type=op_type,
        validator_id=validator_id,
        amount=to_units(amount),
        commission_rate=1000,
    )


def _make_block(block_number, prev_block, operations=(), proposer="proposer",
                timestamp=None):
    ops = tuple(operations)
    merkle = compute_merkle_root(ops)
    ts = timestamp if timestamp is not None else TS + block_number
    prev_hash = prev_block.block_hash if prev_block else GENESIS_PREV_HASH
    return Block(
        chain_id=CHAIN_ID,
        block_number=block_number,
        prev_hash=prev_hash,
        merkle_root=merkle,
        timestamp=ts,
        operations=ops,
        proposer=proposer,
    )


def _build_chain(length, operations_per_block=None):
    """Build a chain of length blocks (0=genesis, 1..n-1=regular)."""
    genesis = make_genesis_block(CHAIN_ID, TS)
    blocks = [genesis]
    for i in range(1, length):
        ops = ()
        if operations_per_block and i in operations_per_block:
            ops = operations_per_block[i]
        blocks.append(_make_block(i, blocks[-1], ops))
    return blocks


def _peer_from_blocks(name, blocks):
    genesis_hash = blocks[0].block_hash
    return InMemoryPeer(f"{name}:8000", CHAIN_ID, genesis_hash, blocks)


# ═══════════════════════════════════════════════════════════════════
# E2E-1: Three-node network — Node 1 produces, Node 2 syncs
# ═══════════════════════════════════════════════════════════════════

class TestThreeNodeSync:
    def test_node2_syncs_from_node1(self, tmp_path):
        """Node 1 has 50 blocks, Node 2 joins and syncs all of them."""
        blocks = _build_chain(51)  # genesis + 50 blocks
        genesis_hash = blocks[0].block_hash

        engine2 = _make_engine(tmp_path, "node2")
        peer1 = _peer_from_blocks("node1", blocks)

        result = sync_from_peer(peer1, engine2, -1, genesis_hash)
        assert result.ok
        assert result.status == SyncStatus.SUCCESS
        assert result.blocks_synced == 51
        assert result.from_height == 0
        assert result.to_height == 50
        engine2.close()

    def test_node2_state_matches_node1(self, tmp_path):
        """After sync, Node 2's state should match Node 1's state."""
        # Node 1: produce blocks with register operations
        ops = {
            1: (_make_op("val_001"),),
            5: (_make_op("val_002"),),
            10: (_make_op("val_003"),),
        }
        blocks = _build_chain(20, operations_per_block=ops)
        genesis_hash = blocks[0].block_hash

        # Engine for Node 1
        engine1 = _make_engine(tmp_path, "node1")
        for block in blocks:
            engine1.apply_block({
                "height": block.block_number,
                "operations": list(block.operations),
            })

        # Engine for Node 2 — sync from Node 1
        engine2 = _make_engine(tmp_path, "node2")
        peer1 = _peer_from_blocks("node1", blocks)
        result = sync_from_peer(peer1, engine2, -1, genesis_hash)
        assert result.ok

        # Both engines should have the same validators
        vals1 = engine1.get_validators(include_inactive=True)
        vals2 = engine2.get_validators(include_inactive=True)
        assert len(vals1) == len(vals2)
        ids1 = sorted(v["validator_id"] for v in vals1)
        ids2 = sorted(v["validator_id"] for v in vals2)
        assert ids1 == ids2

        engine1.close()
        engine2.close()

    def test_node3_syncs_from_best_peer(self, tmp_path):
        """Node 3 syncs from the best of two peers."""
        blocks_short = _build_chain(10)
        blocks_long = _build_chain(30)
        genesis_hash = blocks_short[0].block_hash

        peer1 = _peer_from_blocks("node1", blocks_short)
        peer2 = _peer_from_blocks("node2", blocks_long)

        engine3 = _make_engine(tmp_path, "node3")
        result = sync_from_network(
            [peer1, peer2], engine3, -1, genesis_hash)
        assert result.ok
        assert result.blocks_synced == 30
        assert result.peer == "node2:8000"
        engine3.close()


# ═══════════════════════════════════════════════════════════════════
# E2E-2: Incremental sync
# ═══════════════════════════════════════════════════════════════════

class TestIncrementalSync:
    def test_node2_catches_up(self, tmp_path):
        """Node 2 syncs first 20 blocks, then later syncs 20 more."""
        blocks = _build_chain(41)  # 0..40
        genesis_hash = blocks[0].block_hash

        engine2 = _make_engine(tmp_path, "node2")

        # First sync: blocks 0–20
        peer1_partial = _peer_from_blocks("node1", blocks[:21])
        result1 = sync_from_peer(peer1_partial, engine2, -1, genesis_hash)
        assert result1.ok
        assert result1.blocks_synced == 21

        # Later: Node 1 has more blocks
        peer1_full = _peer_from_blocks("node1", blocks)
        result2 = sync_from_peer(peer1_full, engine2, 20, genesis_hash)
        assert result2.ok
        assert result2.blocks_synced == 20  # blocks 21-40
        assert result2.from_height == 21
        assert result2.to_height == 40
        engine2.close()

    def test_already_synced(self, tmp_path):
        """No blocks to sync when Node 2 is up to date."""
        blocks = _build_chain(10)
        genesis_hash = blocks[0].block_hash

        engine2 = _make_engine(tmp_path, "node2")
        peer1 = _peer_from_blocks("node1", blocks)

        # Full sync
        sync_from_peer(peer1, engine2, -1, genesis_hash)

        # Try again — should be ALREADY_SYNCED
        result = sync_from_peer(peer1, engine2, 9, genesis_hash)
        assert result.ok
        assert result.status == SyncStatus.ALREADY_SYNCED
        assert result.blocks_synced == 0
        engine2.close()


# ═══════════════════════════════════════════════════════════════════
# E2E-3: Fork scenario
# ═══════════════════════════════════════════════════════════════════

class TestForkScenario:
    def test_detect_fork_between_nodes(self, tmp_path):
        """Node 2 and Node 3 have divergent chains — detect fork."""
        common = _build_chain(10)

        # Node 2 extends from block 9
        n2_blocks = list(common)
        for i in range(10, 15):
            n2_blocks.append(_make_block(i, n2_blocks[-1], proposer="node2"))

        # Node 3 diverges at block 7
        n3_base = common[:8]  # blocks 0..7
        n3_b8 = Block(
            chain_id=CHAIN_ID, block_number=8,
            prev_hash=common[7].block_hash,
            merkle_root="0" * 64,
            timestamp=TS + 800,
            proposer="node3",
        )
        n3_blocks = list(n3_base) + [n3_b8]
        for i in range(9, 20):
            n3_blocks.append(_make_block(i, n3_blocks[-1], proposer="node3",
                                          timestamp=TS + i + 1000))

        fp = detect_fork(n2_blocks, n3_blocks)
        assert fp.height == 7  # last common block
        assert fp.has_fork
        assert fp.local_blocks_to_revert == 7   # blocks 8-14
        assert fp.remote_blocks_to_apply == 12  # blocks 8-19

    def test_choose_longer_fork(self):
        """Fork choice selects the longer chain."""
        gh = "genesis_hash_123"
        chain_a = ChainInfo(chain_id=CHAIN_ID, height=14,
                            genesis_hash=gh, peer="node2")
        chain_b = ChainInfo(chain_id=CHAIN_ID, height=19,
                            genesis_hash=gh, peer="node3")

        best = choose_fork([chain_a, chain_b], gh)
        assert best.peer == "node3"

    def test_reorg_applies_new_chain(self, tmp_path):
        """Reorg applies new chain after fork point."""
        common = _build_chain(5)

        # New chain extends from block 4
        new_blocks = []
        prev = common[-1]
        for i in range(5, 10):
            b = _make_block(i, prev, proposer="new_chain")
            new_blocks.append(b)
            prev = b

        engine = _make_engine(tmp_path, "reorg_node")
        fp = ForkPoint(
            height=4,
            common_hash=common[-1].block_hash,
            local_height=4,
            remote_height=9,
            local_blocks_to_revert=0,
            remote_blocks_to_apply=5,
        )

        result = reorg_to(engine, new_blocks, fp)
        assert result.success
        assert result.applied == 5
        engine.close()

    def test_reorg_rejects_invalid_blocks(self, tmp_path):
        """Reorg rejects chain with invalid block."""
        common = _build_chain(3)

        bad_block = Block(
            chain_id=CHAIN_ID, block_number=3,
            prev_hash=common[-1].block_hash,
            merkle_root="invalid" * 8,  # bad merkle
            timestamp=TS + 3,
        )

        engine = _make_engine(tmp_path, "reorg_bad")
        fp = ForkPoint(height=2, common_hash=common[-1].block_hash,
                       local_height=2, remote_height=3)

        result = reorg_to(engine, [bad_block], fp, verify=True)
        assert not result.success
        assert "invalid block" in result.error
        engine.close()


# ═══════════════════════════════════════════════════════════════════
# E2E-4: Block verification through sync
# ═══════════════════════════════════════════════════════════════════

class TestBlockVerificationE2E:
    def test_valid_chain_passes_verification(self):
        """A properly built chain passes block chain verification."""
        blocks = _build_chain(20)
        result = verify_block_chain(blocks)
        assert result.valid

    def test_tampered_block_fails_sync(self, tmp_path):
        """Peer with a tampered block fails sync."""
        blocks = _build_chain(10)
        genesis_hash = blocks[0].block_hash

        # Tamper block 5
        tampered = Block(
            chain_id=CHAIN_ID,
            block_number=5,
            prev_hash=blocks[4].block_hash,
            merkle_root="tampered" * 8,
            timestamp=TS + 5,
        )
        bad_blocks = blocks[:5] + [tampered] + blocks[6:]

        peer = _peer_from_blocks("bad_node", bad_blocks)
        engine = _make_engine(tmp_path, "victim")

        result = sync_from_peer(peer, engine, -1, genesis_hash)
        # Should sync up to block 4, then fail on block 5
        assert result.status in (SyncStatus.PARTIAL, SyncStatus.INVALID_BLOCK)
        engine.close()

    def test_operations_in_synced_blocks(self, tmp_path):
        """Operations in synced blocks are applied to engine state."""
        op1 = _make_op("sync_val_001", 200)
        op2 = _make_op("sync_val_002", 300)

        ops = {1: (op1,), 3: (op2,)}
        blocks = _build_chain(5, operations_per_block=ops)
        genesis_hash = blocks[0].block_hash

        engine = _make_engine(tmp_path, "sync_ops")
        peer = _peer_from_blocks("producer", blocks)

        result = sync_from_peer(peer, engine, -1, genesis_hash)
        assert result.ok

        # Verify validators were registered
        vals = engine.get_validators(include_inactive=True)
        val_ids = [v["validator_id"] for v in vals]
        assert "sync_val_001" in val_ids
        assert "sync_val_002" in val_ids
        engine.close()


# ═══════════════════════════════════════════════════════════════════
# E2E-5: Genesis mismatch
# ═══════════════════════════════════════════════════════════════════

class TestGenesisMismatch:
    def test_different_chain_id_rejected(self, tmp_path):
        """Peers with different chain_id are rejected during sync."""
        blocks = _build_chain(10)
        genesis_hash = blocks[0].block_hash

        # Create peer with different chain_id
        other_genesis = make_genesis_block("other-chain-id", TS)
        other_blocks = [other_genesis]
        prev = other_genesis
        for i in range(1, 10):
            b = Block(
                chain_id="other-chain-id",
                block_number=i,
                prev_hash=prev.block_hash,
                merkle_root="0" * 64,
                timestamp=TS + i,
            )
            other_blocks.append(b)
            prev = b

        other_peer = InMemoryPeer(
            "other:8000", "other-chain-id",
            other_genesis.block_hash, other_blocks)

        engine = _make_engine(tmp_path, "local")
        result = sync_from_peer(other_peer, engine, -1, genesis_hash)
        assert not result.ok
        assert result.status == SyncStatus.GENESIS_MISMATCH
        engine.close()


# ═══════════════════════════════════════════════════════════════════
# E2E-6: Batch sync with progress tracking
# ═══════════════════════════════════════════════════════════════════

class TestBatchSyncProgress:
    def test_progress_callback_fires(self, tmp_path):
        """Progress callback fires for each synced block."""
        blocks = _build_chain(15)
        genesis_hash = blocks[0].block_hash
        peer = _peer_from_blocks("node1", blocks)
        engine = _make_engine(tmp_path, "tracker")
        progress_log = []

        def on_progress(synced, total):
            progress_log.append((synced, total))

        result = sync_from_peer(peer, engine, -1, genesis_hash,
                                on_progress=on_progress)
        assert result.ok
        assert len(progress_log) == 15  # one per block
        assert progress_log[0][0] == 1
        assert progress_log[-1][0] == 15
        engine.close()

    def test_batch_size_affects_requests(self, tmp_path):
        """Small batch size triggers multiple request rounds."""
        blocks = _build_chain(25)
        genesis_hash = blocks[0].block_hash

        request_log = []

        class LoggingPeer(InMemoryPeer):
            def get_blocks(self, request):
                request_log.append(request)
                return super().get_blocks(request)

        peer = LoggingPeer("logger:8000", CHAIN_ID, genesis_hash, blocks)
        engine = _make_engine(tmp_path, "batched")

        result = sync_from_peer(peer, engine, -1, genesis_hash, batch_size=5)
        assert result.ok
        assert result.blocks_synced == 25
        assert len(request_log) == 5  # 25 blocks / 5 per batch
        engine.close()


# ═══════════════════════════════════════════════════════════════════
# E2E-7: Full pipeline — produce → sync → verify → fork → reorg
# ═══════════════════════════════════════════════════════════════════

class TestFullPipeline:
    def test_produce_sync_fork_reorg(self, tmp_path):
        """Complete pipeline: produce blocks, sync, detect fork, resolve."""
        # Phase 1: Node 1 produces 20 blocks
        blocks_n1 = _build_chain(21)
        genesis_hash = blocks_n1[0].block_hash

        # Phase 2: Node 2 syncs from Node 1
        engine2 = _make_engine(tmp_path, "node2_pipeline")
        peer1 = _peer_from_blocks("node1", blocks_n1)
        result = sync_from_peer(peer1, engine2, -1, genesis_hash)
        assert result.ok
        assert result.blocks_synced == 21

        # Phase 3: Node 3 has a longer divergent chain (fork at block 15)
        common = blocks_n1[:16]  # blocks 0..15

        n3_chain = list(common)
        prev = common[-1]
        for i in range(16, 30):
            b = Block(
                chain_id=CHAIN_ID,
                block_number=i,
                prev_hash=prev.block_hash,
                merkle_root="0" * 64,
                timestamp=TS + i + 2000,
                proposer="node3_proposer",
            )
            n3_chain.append(b)
            prev = b

        # Phase 4: Detect fork
        fp = detect_fork(blocks_n1, n3_chain)
        assert fp.height == 15
        assert fp.has_fork
        assert fp.local_blocks_to_revert == 5   # blocks 16-20
        assert fp.remote_blocks_to_apply == 14  # blocks 16-29

        # Phase 5: Node 3 chain is longer → should sync
        local_info = ChainInfo(
            chain_id=CHAIN_ID, height=20,
            genesis_hash=genesis_hash, peer="node1")
        remote_info = ChainInfo(
            chain_id=CHAIN_ID, height=29,
            genesis_hash=genesis_hash, peer="node3")
        best = choose_fork([local_info, remote_info], genesis_hash)
        assert best.peer == "node3"

        # Phase 6: Reorg to Node 3's chain
        engine_reorg = _make_engine(tmp_path, "reorg_pipeline")
        new_blocks = n3_chain[16:]  # blocks after fork point
        reorg_result = reorg_to(engine_reorg, new_blocks, fp)
        assert reorg_result.success
        assert reorg_result.applied == 14

        engine2.close()
        engine_reorg.close()
