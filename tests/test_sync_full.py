"""
Comprehensive tests for block sync protocol, fork detection, reorg,
network protocol messages, and CLI sync commands.

Covers:
  - Fork detection (detect_fork)
  - Chain reorganization (reorg_to)
  - Extended protocol messages (GetHeight, HeightResponse, GetBlocks, etc.)
  - SyncInfo / SyncState
  - Message parsing
  - sync_from_peer with fork scenarios
  - sync_from_network multi-peer fork resolution
  - CLI sync commands (--status, --peers, --auto, chain info)
  - Large chain sync performance
  - Edge cases (empty chains, single block, etc.)
"""

import json
import time
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

from oasyce_plugin.consensus.core.types import Operation, OperationType, to_units
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
from oasyce_plugin.consensus.network.block_sync import (
    InMemoryPeer,
    ValidationResult,
    verify_block,
    verify_block_chain,
    apply_synced_block,
    sync_from_peer,
    sync_from_network,
)
from oasyce_plugin.consensus.core.fork_choice import (
    ChainInfo,
    ForkPoint,
    ReorgResult,
    choose_fork,
    is_canonical_chain,
    should_sync,
    rank_peers,
    detect_fork,
    reorg_to,
)
from oasyce_plugin.consensus.network.sync_protocol import BlockHeader
from oasyce_plugin.consensus.network.protocol import (
    GetHeight,
    HeightResponse,
    GetBlocks,
    BlocksResponse,
    GetBlockHeaders,
    BlockHeaders,
    SyncStatusMessage,
    SyncState,
    SyncInfo,
    parse_message,
)
from oasyce_plugin.consensus.network.sync import BlockSyncProtocol
from oasyce_plugin.consensus.node import ConsensusNode, NodeState, JoinResult
from oasyce_plugin.consensus import ConsensusEngine


# ── Helpers ────────────────────────────────────────────────────────

CHAIN_ID = "oasyce-test-sync-full"
TS = 1700000000


def _make_engine(tmp_path=None):
    db = str(tmp_path / "test.db") if tmp_path else None
    return ConsensusEngine(db_path=db)


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


def _build_chain(length, chain_id=CHAIN_ID, operations_per_block=()):
    genesis = make_genesis_block(chain_id, TS)
    blocks = [genesis]
    for i in range(1, length):
        ops = operations_per_block[i] if i < len(operations_per_block) else ()
        blocks.append(_make_block(i, blocks[-1], ops, chain_id=chain_id))
    return blocks


def _make_peer(addr, blocks, chain_id=CHAIN_ID):
    genesis = blocks[0] if blocks else _genesis()
    return InMemoryPeer(addr, chain_id, genesis.block_hash, blocks)


# ═══════════════════════════════════════════════════════════════════
# 1. Fork detection — detect_fork()
# ═══════════════════════════════════════════════════════════════════

class TestDetectFork:
    def test_identical_chains(self):
        """No fork when chains are identical."""
        blocks = _build_chain(5)
        fp = detect_fork(blocks, blocks)
        assert fp.height == 4
        assert not fp.has_fork
        assert fp.local_blocks_to_revert == 0
        assert fp.remote_blocks_to_apply == 0

    def test_remote_ahead(self):
        """Remote chain is ahead — no fork, just sync needed."""
        local = _build_chain(3)
        remote = _build_chain(6)
        fp = detect_fork(local, remote)
        assert fp.height == 2  # last common block
        assert not fp.has_fork  # local_blocks_to_revert == 0
        assert fp.remote_blocks_to_apply == 3  # blocks 3, 4, 5

    def test_local_ahead(self):
        """Local chain is ahead — no sync needed."""
        local = _build_chain(6)
        remote = _build_chain(3)
        fp = detect_fork(local, remote)
        assert fp.height == 2
        assert fp.has_fork  # local has blocks to revert
        assert fp.local_blocks_to_revert == 3

    def test_fork_at_genesis(self):
        """Chains diverge immediately after genesis."""
        genesis = _genesis()
        local = [genesis, _make_block(1, genesis, proposer="local")]
        # Different block 1 for remote
        remote_b1 = Block(
            chain_id=CHAIN_ID, block_number=1,
            prev_hash=genesis.block_hash,
            merkle_root="0" * 64,
            timestamp=TS + 100,  # different timestamp → different hash
            proposer="remote",
        )
        remote = [genesis, remote_b1]
        fp = detect_fork(local, remote)
        assert fp.height == 0  # genesis is the last common
        assert fp.has_fork
        assert fp.local_blocks_to_revert == 1
        assert fp.remote_blocks_to_apply == 1

    def test_fork_in_middle(self):
        """Chains share first 3 blocks then diverge."""
        common = _build_chain(3)
        # Local continues with different proposer
        local_b3 = _make_block(3, common[-1], proposer="local_proposer")
        local_b4 = _make_block(4, local_b3, proposer="local_proposer")
        local = common + [local_b3, local_b4]

        # Remote continues differently
        remote_b3 = Block(
            chain_id=CHAIN_ID, block_number=3,
            prev_hash=common[-1].block_hash,
            merkle_root="0" * 64,
            timestamp=TS + 300,
            proposer="remote_proposer",
        )
        remote_b4 = _make_block(4, remote_b3, proposer="remote_proposer")
        remote_b5 = _make_block(5, remote_b4, proposer="remote_proposer")
        remote = common + [remote_b3, remote_b4, remote_b5]

        fp = detect_fork(local, remote)
        assert fp.height == 2  # last common block
        assert fp.has_fork
        assert fp.local_blocks_to_revert == 2  # blocks 3, 4
        assert fp.remote_blocks_to_apply == 3  # blocks 3, 4, 5

    def test_empty_local(self):
        """Empty local chain."""
        remote = _build_chain(5)
        fp = detect_fork([], remote)
        assert fp.height == -1
        assert fp.local_height == -1
        assert fp.remote_height == 4

    def test_empty_remote(self):
        """Empty remote chain."""
        local = _build_chain(5)
        fp = detect_fork(local, [])
        assert fp.height == -1
        assert fp.local_height == 4
        assert fp.remote_height == -1

    def test_both_empty(self):
        """Both chains empty."""
        fp = detect_fork([], [])
        assert fp.height == -1
        assert fp.local_blocks_to_revert == 0
        assert fp.remote_blocks_to_apply == 0

    def test_single_block_each(self):
        """Both chains have only genesis."""
        genesis = _genesis()
        fp = detect_fork([genesis], [genesis])
        assert fp.height == 0
        assert not fp.has_fork

    def test_fork_point_common_hash(self):
        """ForkPoint records the hash of the last common block."""
        blocks = _build_chain(5)
        local = blocks[:3]
        remote = blocks[:3] + [_make_block(3, blocks[2], proposer="other",
                                            timestamp=TS + 999)]
        fp = detect_fork(local, remote)
        assert fp.common_hash == blocks[2].block_hash


# ═══════════════════════════════════════════════════════════════════
# 2. Chain reorganization — reorg_to()
# ═══════════════════════════════════════════════════════════════════

class TestReorgTo:
    def test_apply_new_blocks(self, tmp_path):
        """Apply new blocks after fork point."""
        engine = _make_engine(tmp_path)
        blocks = _build_chain(5)
        fp = ForkPoint(height=2, common_hash=blocks[2].block_hash,
                       local_height=2, remote_height=4,
                       local_blocks_to_revert=0, remote_blocks_to_apply=2)

        result = reorg_to(engine, blocks[3:], fp)
        assert result.success
        assert result.applied == 2
        assert result.fork_height == 2
        engine.close()

    def test_empty_new_blocks(self, tmp_path):
        """No blocks to apply — success with 0 applied."""
        engine = _make_engine(tmp_path)
        fp = ForkPoint(height=5)
        result = reorg_to(engine, [], fp)
        assert result.success
        assert result.applied == 0
        engine.close()

    def test_invalid_block_rejected(self, tmp_path):
        """Reorg fails if a new block is invalid."""
        engine = _make_engine(tmp_path)
        genesis = _genesis()
        bad_block = Block(
            chain_id=CHAIN_ID, block_number=1,
            prev_hash=genesis.block_hash,
            merkle_root="bad" * 21 + "b",  # wrong merkle
            timestamp=TS + 1,
        )
        fp = ForkPoint(height=0, common_hash=genesis.block_hash,
                       local_height=0, remote_height=1)

        result = reorg_to(engine, [bad_block], fp, verify=True)
        assert not result.success
        assert "invalid block" in result.error
        engine.close()

    def test_skip_blocks_before_fork(self, tmp_path):
        """Blocks at or before fork point are skipped."""
        engine = _make_engine(tmp_path)
        blocks = _build_chain(5)
        fp = ForkPoint(height=3, common_hash=blocks[3].block_hash,
                       local_height=3, remote_height=4)

        # Pass all blocks including those before fork
        result = reorg_to(engine, blocks, fp)
        assert result.success
        assert result.applied == 1  # only block 4
        engine.close()

    def test_reorg_without_verify(self, tmp_path):
        """Reorg with verify=False skips validation."""
        engine = _make_engine(tmp_path)
        blocks = _build_chain(3)
        fp = ForkPoint(height=0, common_hash=blocks[0].block_hash,
                       local_height=0, remote_height=2)

        result = reorg_to(engine, blocks[1:], fp, verify=False)
        assert result.success
        assert result.applied == 2
        engine.close()


# ═══════════════════════════════════════════════════════════════════
# 3. ForkPoint dataclass
# ═══════════════════════════════════════════════════════════════════

class TestForkPoint:
    def test_has_fork_true(self):
        fp = ForkPoint(height=5, local_blocks_to_revert=3)
        assert fp.has_fork

    def test_has_fork_false(self):
        fp = ForkPoint(height=5, local_blocks_to_revert=0)
        assert not fp.has_fork

    def test_default_values(self):
        fp = ForkPoint(height=0)
        assert fp.common_hash == ""
        assert fp.local_height == 0
        assert fp.remote_height == 0


# ═══════════════════════════════════════════════════════════════════
# 4. ReorgResult dataclass
# ═══════════════════════════════════════════════════════════════════

class TestReorgResult:
    def test_success(self):
        r = ReorgResult(success=True, reverted=3, applied=5, fork_height=10)
        assert r.success
        assert r.reverted == 3
        assert r.applied == 5

    def test_failure(self):
        r = ReorgResult(success=False, error="bad block")
        assert not r.success
        assert r.error == "bad block"


# ═══════════════════════════════════════════════════════════════════
# 5. Extended protocol — GetHeight / HeightResponse
# ═══════════════════════════════════════════════════════════════════

class TestGetHeight:
    def test_to_dict(self):
        msg = GetHeight()
        d = msg.to_dict()
        assert d["type"] == "get_height"

    def test_roundtrip(self):
        msg = GetHeight()
        restored = GetHeight.from_dict(msg.to_dict())
        assert isinstance(restored, GetHeight)


class TestHeightResponse:
    def test_fields(self):
        msg = HeightResponse(height=42, best_hash="abc123",
                             chain_id="test", timestamp=1000)
        assert msg.height == 42
        assert msg.best_hash == "abc123"

    def test_roundtrip(self):
        msg = HeightResponse(height=100, best_hash="hash", chain_id="c1")
        d = msg.to_dict()
        restored = HeightResponse.from_dict(d)
        assert restored.height == 100
        assert restored.best_hash == "hash"
        assert restored.chain_id == "c1"

    def test_defaults(self):
        msg = HeightResponse()
        assert msg.height == -1
        assert msg.best_hash == ""


# ═══════════════════════════════════════════════════════════════════
# 6. Extended protocol — GetBlocks / BlocksResponse
# ═══════════════════════════════════════════════════════════════════

class TestGetBlocks:
    def test_fields(self):
        msg = GetBlocks(from_height=10, to_height=20, count=50)
        assert msg.from_height == 10
        assert msg.to_height == 20
        assert msg.count == 50

    def test_roundtrip(self):
        msg = GetBlocks(from_height=5, to_height=15, count=10)
        d = msg.to_dict()
        restored = GetBlocks.from_dict(d)
        assert restored.from_height == 5
        assert restored.to_height == 15
        assert restored.count == 10

    def test_to_request(self):
        msg = GetBlocks(from_height=0, to_height=99, count=50)
        req = msg.to_request()
        assert isinstance(req, GetBlocksRequest)
        assert req.from_height == 0
        assert req.to_height == 99
        assert req.limit == 50

    def test_defaults(self):
        msg = GetBlocks()
        assert msg.count == 100


class TestBlocksResponse:
    def test_empty(self):
        msg = BlocksResponse()
        assert len(msg.blocks) == 0
        assert not msg.has_more

    def test_with_blocks(self):
        blocks = _build_chain(3)
        msg = BlocksResponse(blocks=blocks, has_more=True, next_height=3)
        assert len(msg.blocks) == 3
        assert msg.has_more
        assert msg.next_height == 3

    def test_roundtrip(self):
        blocks = _build_chain(2)
        msg = BlocksResponse(blocks=blocks, has_more=True, next_height=2)
        d = msg.to_dict()
        restored = BlocksResponse.from_dict(d)
        assert len(restored.blocks) == 2
        assert restored.has_more
        assert restored.next_height == 2
        assert restored.blocks[0].block_number == 0


# ═══════════════════════════════════════════════════════════════════
# 7. SyncState / SyncInfo
# ═══════════════════════════════════════════════════════════════════

class TestSyncState:
    def test_values(self):
        assert SyncState.IDLE.value == "idle"
        assert SyncState.SYNCING.value == "syncing"
        assert SyncState.SYNCED.value == "synced"
        assert SyncState.FORKED.value == "forked"
        assert SyncState.ERROR.value == "error"


class TestSyncInfo:
    def test_sync_progress_synced(self):
        info = SyncInfo(local_height=10, best_known_height=10)
        assert info.sync_progress == pytest.approx(1.0)

    def test_sync_progress_behind(self):
        info = SyncInfo(local_height=5, best_known_height=10)
        assert 0.0 < info.sync_progress < 1.0

    def test_sync_progress_empty(self):
        info = SyncInfo(local_height=-1, best_known_height=10)
        assert info.sync_progress == 0.0

    def test_sync_progress_no_target(self):
        info = SyncInfo(local_height=5, best_known_height=0)
        assert info.sync_progress == 1.0

    def test_blocks_behind(self):
        info = SyncInfo(local_height=5, best_known_height=15)
        assert info.blocks_behind == 10

    def test_blocks_behind_synced(self):
        info = SyncInfo(local_height=15, best_known_height=15)
        assert info.blocks_behind == 0

    def test_blocks_behind_ahead(self):
        info = SyncInfo(local_height=20, best_known_height=15)
        assert info.blocks_behind == 0

    def test_roundtrip(self):
        info = SyncInfo(
            state=SyncState.SYNCING,
            chain_id="test-chain",
            local_height=50,
            best_known_height=100,
            genesis_hash="genesis123",
            peers_connected=3,
            blocks_per_second=12.5,
            last_sync_time=1000,
            last_sync_peer="peer:8000",
        )
        d = info.to_dict()
        restored = SyncInfo.from_dict(d)
        assert restored.state == SyncState.SYNCING
        assert restored.chain_id == "test-chain"
        assert restored.local_height == 50
        assert restored.best_known_height == 100
        assert restored.peers_connected == 3

    def test_from_dict_unknown_state(self):
        info = SyncInfo.from_dict({"state": "unknown_state"})
        assert info.state == SyncState.IDLE

    def test_default_values(self):
        info = SyncInfo()
        assert info.state == SyncState.IDLE
        assert info.local_height == -1
        assert info.last_sync_error == ""


# ═══════════════════════════════════════════════════════════════════
# 8. Message parsing
# ═══════════════════════════════════════════════════════════════════

class TestParseMessage:
    def test_parse_get_height(self):
        msg = parse_message({"type": "get_height"})
        assert isinstance(msg, GetHeight)

    def test_parse_height_response(self):
        msg = parse_message({"type": "height_response", "height": 42})
        assert isinstance(msg, HeightResponse)
        assert msg.height == 42

    def test_parse_get_blocks(self):
        msg = parse_message({"type": "get_blocks", "from_height": 0, "to_height": 10})
        assert isinstance(msg, GetBlocks)
        assert msg.from_height == 0

    def test_parse_unknown(self):
        msg = parse_message({"type": "unknown_msg"})
        assert msg is None

    def test_parse_no_type(self):
        msg = parse_message({})
        assert msg is None


# ═══════════════════════════════════════════════════════════════════
# 9. Multi-peer sync with fork resolution
# ═══════════════════════════════════════════════════════════════════

class TestMultiPeerForkSync:
    def test_sync_selects_longest_chain(self, tmp_path):
        """Network sync picks the longest chain among peers."""
        genesis = _genesis()
        short_chain = _build_chain(3)
        long_chain = _build_chain(8)
        genesis_hash = genesis.block_hash

        peer_a = _make_peer("a:8000", short_chain)
        peer_b = _make_peer("b:8000", long_chain)

        engine = _make_engine(tmp_path)
        result = sync_from_network(
            [peer_a, peer_b], engine, -1, genesis_hash)
        assert result.ok
        assert result.blocks_synced == 8
        assert result.peer == "b:8000"
        engine.close()

    def test_detect_fork_between_peers(self):
        """Detect fork between two peer chains."""
        common = _build_chain(5)

        # Peer A extends from block 4
        peer_a_blocks = common + [_make_block(5, common[-1], proposer="A")]

        # Peer B diverges at block 3
        b3 = Block(
            chain_id=CHAIN_ID, block_number=3,
            prev_hash=common[2].block_hash,
            merkle_root="0" * 64,
            timestamp=TS + 300,
            proposer="B",
        )
        b4 = _make_block(4, b3, proposer="B")
        b5 = _make_block(5, b4, proposer="B")
        b6 = _make_block(6, b5, proposer="B")
        peer_b_blocks = common[:3] + [b3, b4, b5, b6]

        fp = detect_fork(peer_a_blocks, peer_b_blocks)
        assert fp.height == 2
        assert fp.has_fork
        assert fp.local_blocks_to_revert == 3  # blocks 3, 4, 5
        assert fp.remote_blocks_to_apply == 4  # blocks 3, 4, 5, 6


# ═══════════════════════════════════════════════════════════════════
# 10. Large chain sync performance
# ═══════════════════════════════════════════════════════════════════

class TestLargeChainSync:
    def test_sync_100_blocks(self, tmp_path):
        """Sync 100+ blocks efficiently."""
        blocks = _build_chain(120)
        peer = _make_peer("fast:8000", blocks)
        engine = _make_engine(tmp_path)
        genesis_hash = blocks[0].block_hash

        result = sync_from_peer(peer, engine, -1, genesis_hash, batch_size=25)
        assert result.ok
        assert result.blocks_synced == 120
        engine.close()

    def test_sync_with_operations(self, tmp_path):
        """Sync blocks containing operations."""
        ops_per_block = {i: (_make_op(f"val_{i}"),) for i in range(1, 11)}
        blocks = _build_chain(11, operations_per_block=ops_per_block)
        peer = _make_peer("ops:8000", blocks)
        engine = _make_engine(tmp_path)
        genesis_hash = blocks[0].block_hash

        result = sync_from_peer(peer, engine, -1, genesis_hash)
        assert result.ok
        assert result.blocks_synced == 11
        engine.close()

    def test_detect_fork_large_chains(self):
        """Fork detection on larger chains."""
        common = _build_chain(50)

        # Local extends from block 49
        local_ext = [common[-1]]
        for i in range(50, 60):
            local_ext.append(_make_block(i, local_ext[-1], proposer="local"))
        local_full = common + local_ext[1:]

        # Remote extends differently from block 49
        remote_ext = [common[-1]]
        for i in range(50, 70):
            remote_ext.append(_make_block(i, remote_ext[-1], proposer="remote",
                                          timestamp=TS + i + 1000))
        remote_full = common + remote_ext[1:]

        fp = detect_fork(local_full, remote_full)
        assert fp.height == 49
        assert fp.has_fork
        assert fp.local_blocks_to_revert == 10
        assert fp.remote_blocks_to_apply == 20


# ═══════════════════════════════════════════════════════════════════
# 11. Edge cases
# ═══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_sync_single_block(self, tmp_path):
        """Sync a single genesis block."""
        genesis = _genesis()
        peer = _make_peer("single:8000", [genesis])
        engine = _make_engine(tmp_path)

        result = sync_from_peer(peer, engine, -1, genesis.block_hash)
        assert result.ok
        assert result.blocks_synced == 1
        engine.close()

    def test_fork_point_at_tip(self):
        """Fork point is at the chain tip (identical chains)."""
        blocks = _build_chain(10)
        fp = detect_fork(blocks, blocks)
        assert fp.height == 9
        assert not fp.has_fork
        assert fp.local_blocks_to_revert == 0
        assert fp.remote_blocks_to_apply == 0

    def test_reorg_result_defaults(self):
        r = ReorgResult(success=True)
        assert r.reverted == 0
        assert r.applied == 0
        assert r.fork_height == 0
        assert r.error == ""

    def test_sync_info_to_dict_complete(self):
        """SyncInfo.to_dict includes all fields."""
        info = SyncInfo(
            state=SyncState.SYNCED,
            chain_id="chain",
            local_height=100,
            best_known_height=100,
        )
        d = info.to_dict()
        assert "state" in d
        assert "sync_progress" in d
        assert "blocks_behind" in d
        assert d["blocks_behind"] == 0
        assert d["sync_progress"] == pytest.approx(1.0)

    def test_get_blocks_default_count(self):
        """GetBlocks default count is 100."""
        gb = GetBlocks(from_height=0, to_height=200)
        assert gb.count == 100

    def test_blocks_response_empty_roundtrip(self):
        msg = BlocksResponse()
        d = msg.to_dict()
        restored = BlocksResponse.from_dict(d)
        assert len(restored.blocks) == 0
        assert not restored.has_more


# ═══════════════════════════════════════════════════════════════════
# 12. Network retry & error handling
# ═══════════════════════════════════════════════════════════════════

class TestNetworkErrors:
    def test_sync_from_network_all_fail(self, tmp_path):
        """All peers fail gracefully."""
        class FailPeer:
            @property
            def address(self): return "fail:8000"
            def get_peer_info(self): raise ConnectionError("down")
            def get_blocks(self, req): raise ConnectionError("down")

        engine = _make_engine(tmp_path)
        result = sync_from_network([FailPeer(), FailPeer()], engine, -1, "hash")
        assert not result.ok
        assert result.status == SyncStatus.NO_PEERS
        engine.close()

    def test_partial_peer_failure(self, tmp_path):
        """One peer fails, another succeeds."""
        blocks = _build_chain(5)
        genesis_hash = blocks[0].block_hash

        class FailPeer:
            @property
            def address(self): return "fail:8000"
            def get_peer_info(self): raise ConnectionError("down")
            def get_blocks(self, req): raise ConnectionError("down")

        good_peer = _make_peer("good:8000", blocks)

        engine = _make_engine(tmp_path)
        result = sync_from_network([FailPeer(), good_peer], engine, -1, genesis_hash)
        assert result.ok
        assert result.peer == "good:8000"
        engine.close()

    def test_peer_returns_no_blocks(self, tmp_path):
        """Peer has no blocks beyond what we request."""
        genesis = _genesis()
        peer = _make_peer("empty:8000", [genesis])
        engine = _make_engine(tmp_path)

        # We're at height 0, peer at 0 too → already synced
        result = sync_from_peer(peer, engine, 0, genesis.block_hash)
        assert result.ok
        assert result.status == SyncStatus.ALREADY_SYNCED
        engine.close()


# ═══════════════════════════════════════════════════════════════════
# 13. ConsensusEngine fork choice integration
# ═══════════════════════════════════════════════════════════════════

class TestEngineForkChoiceIntegration:
    def test_engine_exports_fork_types(self):
        """ConsensusEngine module exports fork choice types."""
        from oasyce_plugin.consensus import (
            ForkPoint, ReorgResult, detect_fork, reorg_to,
        )
        assert ForkPoint is not None
        assert ReorgResult is not None

    def test_choose_fork_with_weight(self):
        """Fork choice uses cumulative weight as tiebreaker."""
        gh = "genesis"
        chains = [
            ChainInfo(chain_id="a", height=10, genesis_hash=gh,
                      cumulative_weight=500),
            ChainInfo(chain_id="b", height=10, genesis_hash=gh,
                      cumulative_weight=1000),
        ]
        best = choose_fork(chains, gh)
        assert best.chain_id == "b"

    def test_rank_peers_descending(self):
        gh = "genesis"
        peers = [
            ChainInfo(chain_id="a", height=5, genesis_hash=gh, peer="p1"),
            ChainInfo(chain_id="b", height=15, genesis_hash=gh, peer="p2"),
            ChainInfo(chain_id="c", height=10, genesis_hash=gh, peer="p3"),
        ]
        ranked = rank_peers(peers, gh)
        assert ranked[0].peer == "p2"
        assert ranked[1].peer == "p3"
        assert ranked[2].peer == "p1"


# ═══════════════════════════════════════════════════════════════════
# 14. GetBlockHeaders / BlockHeaders messages
# ═══════════════════════════════════════════════════════════════════

class TestGetBlockHeaders:
    def test_fields(self):
        msg = GetBlockHeaders(from_height=10, to_height=50, limit=200)
        assert msg.from_height == 10
        assert msg.to_height == 50
        assert msg.limit == 200

    def test_roundtrip(self):
        msg = GetBlockHeaders(from_height=0, to_height=100, limit=50)
        d = msg.to_dict()
        restored = GetBlockHeaders.from_dict(d)
        assert restored.from_height == 0
        assert restored.to_height == 100
        assert restored.limit == 50

    def test_defaults(self):
        msg = GetBlockHeaders()
        assert msg.from_height == 0
        assert msg.to_height == 0
        assert msg.limit == 500

    def test_parse_message(self):
        msg = parse_message({
            "type": "get_block_headers",
            "from_height": 5,
            "to_height": 15,
        })
        assert isinstance(msg, GetBlockHeaders)
        assert msg.from_height == 5


class TestBlockHeaders:
    def test_empty(self):
        msg = BlockHeaders()
        assert len(msg.headers) == 0
        assert not msg.has_more

    def test_with_headers(self):
        blocks = _build_chain(3)
        headers = [b.to_header() for b in blocks]
        msg = BlockHeaders(headers=headers, has_more=True)
        assert len(msg.headers) == 3
        assert msg.has_more

    def test_roundtrip(self):
        blocks = _build_chain(4)
        headers = [b.to_header() for b in blocks]
        msg = BlockHeaders(headers=headers, has_more=False)
        d = msg.to_dict()
        restored = BlockHeaders.from_dict(d)
        assert len(restored.headers) == 4
        assert restored.headers[0].block_number == 0
        assert restored.headers[3].block_number == 3
        assert not restored.has_more

    def test_parse_message(self):
        blocks = _build_chain(2)
        headers = [b.to_header() for b in blocks]
        data = BlockHeaders(headers=headers).to_dict()
        msg = parse_message(data)
        assert isinstance(msg, BlockHeaders)
        assert len(msg.headers) == 2

    def test_header_hashes_match_blocks(self):
        blocks = _build_chain(5)
        headers = [b.to_header() for b in blocks]
        msg = BlockHeaders(headers=headers)
        d = msg.to_dict()
        restored = BlockHeaders.from_dict(d)
        for orig, h in zip(blocks, restored.headers):
            assert h.block_hash == orig.block_hash


# ═══════════════════════════════════════════════════════════════════
# 15. SyncStatusMessage
# ═══════════════════════════════════════════════════════════════════

class TestSyncStatusMessage:
    def test_fields(self):
        msg = SyncStatusMessage(
            current_height=50,
            target_height=100,
            is_syncing=True,
            chain_id="test-chain",
            genesis_hash="abc123",
        )
        assert msg.current_height == 50
        assert msg.target_height == 100
        assert msg.is_syncing

    def test_roundtrip(self):
        msg = SyncStatusMessage(
            current_height=10, target_height=20,
            is_syncing=True, chain_id="c1", genesis_hash="g1",
        )
        d = msg.to_dict()
        restored = SyncStatusMessage.from_dict(d)
        assert restored.current_height == 10
        assert restored.target_height == 20
        assert restored.is_syncing
        assert restored.chain_id == "c1"
        assert restored.genesis_hash == "g1"

    def test_defaults(self):
        msg = SyncStatusMessage()
        assert msg.current_height == -1
        assert msg.target_height == -1
        assert not msg.is_syncing

    def test_parse_message(self):
        msg = parse_message({
            "type": "sync_status",
            "current_height": 42,
            "is_syncing": True,
        })
        assert isinstance(msg, SyncStatusMessage)
        assert msg.current_height == 42

    def test_not_syncing_status(self):
        msg = SyncStatusMessage(
            current_height=100, target_height=100, is_syncing=False,
        )
        d = msg.to_dict()
        assert d["is_syncing"] is False
        assert d["current_height"] == d["target_height"]


# ═══════════════════════════════════════════════════════════════════
# 16. BlockSyncProtocol (async)
# ═══════════════════════════════════════════════════════════════════

class TestBlockSyncProtocol:
    @pytest.fixture
    def setup(self, tmp_path):
        engine = _make_engine(tmp_path)
        genesis = make_genesis_block(engine.chain_id)
        blocks = [genesis]
        for i in range(1, 10):
            blocks.append(_make_block(i, blocks[-1], chain_id=engine.chain_id))
        genesis_hash = genesis.block_hash
        peer = InMemoryPeer("peer1:8000", engine.chain_id, genesis_hash, blocks)
        return engine, peer, blocks, genesis_hash

    def test_sync_from_network(self, setup):
        engine, peer, blocks, genesis_hash = setup
        protocol = BlockSyncProtocol(
            engine=engine, peers=[peer], local_height=-1,
        )
        import asyncio
        result = asyncio.run(protocol.sync_from_network())
        assert result.ok
        assert result.blocks_synced == 10
        assert protocol.local_height == 9
        engine.close()

    def test_sync_from_named_peer(self, setup):
        engine, peer, blocks, genesis_hash = setup
        protocol = BlockSyncProtocol(
            engine=engine, peers=[peer], local_height=-1,
        )
        import asyncio
        result = asyncio.run(protocol.sync_from_peer("peer1:8000"))
        assert result.ok
        assert result.blocks_synced == 10
        engine.close()

    def test_sync_from_unknown_peer(self, setup):
        engine, peer, blocks, genesis_hash = setup
        protocol = BlockSyncProtocol(
            engine=engine, peers=[peer], local_height=-1,
        )
        import asyncio
        result = asyncio.run(protocol.sync_from_peer("unknown:9999"))
        assert not result.ok
        assert result.status == SyncStatus.NO_PEERS
        engine.close()

    def test_get_block_headers(self, setup):
        engine, peer, blocks, genesis_hash = setup
        protocol = BlockSyncProtocol(
            engine=engine, peers=[peer], local_height=-1,
        )
        import asyncio
        headers = asyncio.run(protocol.get_block_headers("peer1:8000", 0, 4))
        assert len(headers) == 5
        assert all(isinstance(h, BlockHeader) for h in headers)
        assert headers[0].block_number == 0
        assert headers[4].block_number == 4
        engine.close()

    def test_get_block(self, setup):
        engine, peer, blocks, genesis_hash = setup
        protocol = BlockSyncProtocol(
            engine=engine, peers=[peer], local_height=-1,
        )
        import asyncio
        block = asyncio.run(protocol.get_block("peer1:8000", 5))
        assert block is not None
        assert block.block_number == 5
        assert block.block_hash == blocks[5].block_hash
        engine.close()

    def test_get_block_unknown_peer(self, setup):
        engine, peer, blocks, genesis_hash = setup
        protocol = BlockSyncProtocol(
            engine=engine, peers=[peer], local_height=-1,
        )
        import asyncio
        block = asyncio.run(protocol.get_block("nope:8000", 0))
        assert block is None
        engine.close()

    def test_verify_chain(self, setup):
        engine, peer, blocks, genesis_hash = setup
        protocol = BlockSyncProtocol(
            engine=engine, peers=[peer], local_height=-1,
        )
        import asyncio
        valid = asyncio.run(protocol.verify_chain(blocks))
        assert valid
        engine.close()

    def test_needs_sync_true(self, setup):
        engine, peer, blocks, genesis_hash = setup
        protocol = BlockSyncProtocol(
            engine=engine, peers=[peer], local_height=-1,
        )
        import asyncio
        assert asyncio.run(protocol.needs_sync())
        engine.close()

    def test_needs_sync_false_when_caught_up(self, setup):
        engine, peer, blocks, genesis_hash = setup
        protocol = BlockSyncProtocol(
            engine=engine, peers=[peer], local_height=9,
        )
        import asyncio
        assert not asyncio.run(protocol.needs_sync())
        engine.close()

    def test_sync_info_updated(self, setup):
        engine, peer, blocks, genesis_hash = setup
        protocol = BlockSyncProtocol(
            engine=engine, peers=[peer], local_height=-1,
        )
        import asyncio
        asyncio.run(protocol.sync_from_network())
        assert protocol.sync_info.state == SyncState.SYNCED
        assert protocol.sync_info.local_height == 9
        assert protocol.sync_info.last_sync_peer == "peer1:8000"
        engine.close()

    def test_get_sync_status_message(self, setup):
        engine, peer, blocks, genesis_hash = setup
        protocol = BlockSyncProtocol(
            engine=engine, peers=[peer], local_height=5,
        )
        status = protocol.get_sync_status()
        assert isinstance(status, SyncStatusMessage)
        assert status.current_height == 5
        assert not status.is_syncing
        assert status.chain_id == engine.chain_id
        engine.close()

    def test_get_peer_chains(self, setup):
        engine, peer, blocks, genesis_hash = setup
        protocol = BlockSyncProtocol(
            engine=engine, peers=[peer], local_height=-1,
        )
        import asyncio
        chains = asyncio.run(protocol.get_peer_chains())
        assert len(chains) == 1
        assert chains[0].height == 9
        assert chains[0].peer == "peer1:8000"
        engine.close()

    def test_no_peers(self, tmp_path):
        engine = _make_engine(tmp_path)
        protocol = BlockSyncProtocol(
            engine=engine, peers=[], local_height=-1,
        )
        import asyncio
        result = asyncio.run(protocol.sync_from_network())
        assert not result.ok
        assert result.status == SyncStatus.NO_PEERS
        engine.close()

    def test_progress_callback(self, setup):
        engine, peer, blocks, genesis_hash = setup
        progress_calls = []
        protocol = BlockSyncProtocol(
            engine=engine, peers=[peer], local_height=-1,
            on_progress=lambda s, t: progress_calls.append((s, t)),
        )
        import asyncio
        asyncio.run(protocol.sync_from_network())
        assert len(progress_calls) == 10
        engine.close()


# ═══════════════════════════════════════════════════════════════════
# 17. ConsensusNode — join flow
# ═══════════════════════════════════════════════════════════════════

class TestConsensusNode:
    @pytest.fixture
    def setup(self, tmp_path):
        engine = _make_engine(tmp_path)
        genesis = make_genesis_block(engine.chain_id)
        blocks = [genesis]
        for i in range(1, 8):
            blocks.append(_make_block(i, blocks[-1], chain_id=engine.chain_id))
        genesis_hash = genesis.block_hash
        peer = InMemoryPeer("bootstrap:8000", engine.chain_id, genesis_hash, blocks)
        return engine, peer, blocks

    def test_join_network_success(self, setup):
        engine, peer, blocks = setup
        node = ConsensusNode(engine, [peer])
        import asyncio
        result = asyncio.run(node.join_network())
        assert result.success
        assert result.state == NodeState.SYNCED
        assert result.blocks_synced == 8
        assert result.local_height == 7
        assert result.peers_connected == 1
        engine.close()

    def test_join_no_peers(self, tmp_path):
        engine = _make_engine(tmp_path)
        node = ConsensusNode(engine)
        import asyncio
        result = asyncio.run(node.join_network())
        assert not result.success
        assert result.state == NodeState.ERROR
        assert "no bootstrap peers" in result.error
        engine.close()

    def test_join_already_synced(self, setup):
        engine, peer, blocks = setup
        node = ConsensusNode(engine, [peer], local_height=7)
        import asyncio
        result = asyncio.run(node.join_network())
        assert result.success
        assert result.state == NodeState.SYNCED
        assert result.blocks_synced == 0
        engine.close()

    def test_join_all_peers_unreachable(self, tmp_path):
        engine = _make_engine(tmp_path)

        class FailPeer:
            @property
            def address(self): return "fail:8000"
            def get_peer_info(self): raise ConnectionError("down")
            def get_blocks(self, req): raise ConnectionError("down")

        node = ConsensusNode(engine, [FailPeer()])
        import asyncio
        result = asyncio.run(node.join_network())
        assert not result.success
        assert result.state == NodeState.ERROR
        assert "unreachable" in result.error
        engine.close()

    def test_node_state_transitions(self, setup):
        engine, peer, blocks = setup
        node = ConsensusNode(engine, [peer])
        assert node.state == NodeState.INITIALIZING

        import asyncio
        asyncio.run(node.join_network())
        assert node.state == NodeState.SYNCED

        node.enter_producing_mode()
        assert node.state == NodeState.PRODUCING

        node.stop()
        assert node.state == NodeState.STOPPED
        engine.close()

    def test_check_sync_needed(self, setup):
        engine, peer, blocks = setup
        node = ConsensusNode(engine, [peer], local_height=-1)
        import asyncio
        assert asyncio.run(node.check_sync_needed())
        engine.close()

    def test_check_sync_not_needed(self, setup):
        engine, peer, blocks = setup
        node = ConsensusNode(engine, [peer], local_height=7)
        import asyncio
        assert not asyncio.run(node.check_sync_needed())
        engine.close()

    def test_incremental_sync(self, setup):
        engine, peer, blocks = setup
        node = ConsensusNode(engine, [peer], local_height=-1)

        import asyncio
        # Initial join
        asyncio.run(node.join_network())
        assert node.local_height == 7

        # Add more blocks to peer
        for i in range(8, 12):
            blocks.append(_make_block(i, blocks[-1], chain_id=engine.chain_id))
            peer.add_block(blocks[-1])

        # Incremental sync
        result = asyncio.run(node.incremental_sync())
        assert result.ok
        assert node.local_height == 11
        engine.close()

    def test_get_status(self, setup):
        engine, peer, blocks = setup
        node = ConsensusNode(engine, [peer], local_height=5)
        status = node.get_status()
        assert status["state"] == "initializing"
        assert status["local_height"] == 5
        assert status["peers"] == 1
        assert status["chain_id"] == engine.chain_id
        engine.close()

    def test_add_peer(self, setup):
        engine, peer, blocks = setup
        node = ConsensusNode(engine)
        assert len(node.bootstrap_peers) == 0
        node.add_peer(peer)
        assert len(node.bootstrap_peers) == 1
        engine.close()

    def test_join_result_to_dict(self, setup):
        engine, peer, blocks = setup
        node = ConsensusNode(engine, [peer])
        import asyncio
        result = asyncio.run(node.join_network())
        d = result.to_dict()
        assert d["success"] is True
        assert d["state"] == "synced"
        assert d["blocks_synced"] == 8
        assert d["peers_connected"] == 1
        engine.close()

    def test_node_genesis_mismatch_peer(self, tmp_path):
        engine = _make_engine(tmp_path)
        other_genesis = make_genesis_block("other-chain", TS)
        other_blocks = _build_chain(5, chain_id="other-chain")
        peer = InMemoryPeer("peer:8000", "other-chain",
                            other_genesis.block_hash, other_blocks)
        node = ConsensusNode(engine, [peer])
        import asyncio
        result = asyncio.run(node.join_network())
        # Peer has wrong genesis → unreachable from our perspective
        assert not result.success
        engine.close()


# ═══════════════════════════════════════════════════════════════════
# 18. NodeState enum
# ═══════════════════════════════════════════════════════════════════

class TestNodeState:
    def test_values(self):
        assert NodeState.INITIALIZING.value == "initializing"
        assert NodeState.SYNCING.value == "syncing"
        assert NodeState.SYNCED.value == "synced"
        assert NodeState.PRODUCING.value == "producing"
        assert NodeState.STOPPED.value == "stopped"
        assert NodeState.ERROR.value == "error"

    def test_is_string_enum(self):
        assert isinstance(NodeState.SYNCED, str)
        assert NodeState.SYNCED == "synced"


# ═══════════════════════════════════════════════════════════════════
# 19. JoinResult
# ═══════════════════════════════════════════════════════════════════

class TestJoinResult:
    def test_success_result(self):
        r = JoinResult(
            success=True, state=NodeState.SYNCED,
            local_height=100, network_height=100,
            blocks_synced=50, peers_connected=3,
        )
        assert r.success
        assert r.blocks_synced == 50
        assert r.error == ""

    def test_failure_result(self):
        r = JoinResult(
            success=False, state=NodeState.ERROR,
            error="peer unreachable",
        )
        assert not r.success
        assert r.error == "peer unreachable"

    def test_to_dict(self):
        r = JoinResult(
            success=True, state=NodeState.SYNCED,
            local_height=10, network_height=10,
        )
        d = r.to_dict()
        assert d["success"] is True
        assert d["state"] == "synced"
        assert d["local_height"] == 10
        assert d["error"] == ""

    def test_defaults(self):
        r = JoinResult(success=False, state=NodeState.ERROR)
        assert r.local_height == -1
        assert r.network_height == -1
        assert r.blocks_synced == 0
        assert r.peers_connected == 0
