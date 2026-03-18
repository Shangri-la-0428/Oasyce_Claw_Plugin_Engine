"""
Tests for block synchronization protocol, fork choice, and sync logic.

Covers:
  - Block creation, serialization, hashing
  - Merkle root computation
  - Block verification (chain linkage, merkle, timestamps)
  - Block chain verification (sequence)
  - Sync protocol message types
  - InMemoryPeer transport
  - sync_from_peer (full sync, partial, resume, errors)
  - sync_from_network (best peer selection, genesis filter)
  - Fork choice (choose_fork, should_sync, rank_peers)
  - ConsensusEngine integration (sync_from_peers, get_genesis_hash)
  - Genesis block validation
"""

import json
import time
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

from oasyce_plugin.consensus.core.types import Operation, OperationType, to_units
from oasyce_plugin.consensus.core.signature import serialize_operation
from oasyce_plugin.consensus.network.sync_protocol import (
    Block,
    BlockHeader,
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
    choose_fork,
    is_canonical_chain,
    should_sync,
    rank_peers,
)
from oasyce_plugin.consensus import ConsensusEngine


# ── Helpers ────────────────────────────────────────────────────────

CHAIN_ID = "oasyce-test-sync"
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
    """Create a valid block linked to prev_block."""
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
    """Build a chain of `length` blocks (0=genesis, 1..length-1=regular)."""
    genesis = _genesis() if chain_id == CHAIN_ID else make_genesis_block(chain_id, TS)
    blocks = [genesis]
    for i in range(1, length):
        ops = operations_per_block[i] if i < len(operations_per_block) else ()
        blocks.append(_make_block(i, blocks[-1], ops, chain_id=chain_id))
    return blocks


def _make_peer(addr, blocks, chain_id=CHAIN_ID):
    genesis = blocks[0] if blocks else _genesis()
    return InMemoryPeer(addr, chain_id, genesis.block_hash, blocks)


# ═══════════════════════════════════════════════════════════════════
# 1. Block dataclass
# ═══════════════════════════════════════════════════════════════════

class TestBlock:
    def test_genesis_block(self):
        g = _genesis()
        assert g.block_number == 0
        assert g.prev_hash == GENESIS_PREV_HASH
        assert g.proposer == "genesis"
        assert g.chain_id == CHAIN_ID
        assert len(g.block_hash) == 64

    def test_block_hash_deterministic(self):
        g = _genesis()
        assert g.block_hash == g.block_hash  # same object
        g2 = _genesis()
        assert g.block_hash == g2.block_hash  # same params

    def test_block_hash_changes_with_fields(self):
        g = _genesis()
        g2 = Block(chain_id="other-chain", block_number=0,
                    prev_hash=GENESIS_PREV_HASH, merkle_root="0" * 64,
                    timestamp=TS)
        assert g.block_hash != g2.block_hash

    def test_block_to_dict_roundtrip(self):
        op = _make_op()
        block = _make_block(1, _genesis(), operations=(op,))
        d = block.to_dict()
        restored = Block.from_dict(d)
        assert restored.block_number == block.block_number
        assert restored.chain_id == block.chain_id
        assert restored.prev_hash == block.prev_hash
        assert restored.merkle_root == block.merkle_root
        assert restored.timestamp == block.timestamp
        assert len(restored.operations) == 1
        assert restored.operations[0].validator_id == op.validator_id

    def test_block_json_roundtrip(self):
        block = _make_block(1, _genesis())
        j = block.to_json()
        restored = Block.from_json(j)
        assert restored.block_hash == block.block_hash

    def test_block_frozen(self):
        block = _make_block(1, _genesis())
        with pytest.raises(AttributeError):
            block.block_number = 99


# ═══════════════════════════════════════════════════════════════════
# 2. Merkle root
# ═══════════════════════════════════════════════════════════════════

class TestMerkleRoot:
    def test_empty_operations(self):
        assert compute_merkle_root(()) == "0" * 64

    def test_single_operation(self):
        op = _make_op()
        root = compute_merkle_root((op,))
        assert len(root) == 64
        assert root != "0" * 64

    def test_two_operations(self):
        op1 = _make_op("v1")
        op2 = _make_op("v2")
        root = compute_merkle_root((op1, op2))
        assert len(root) == 64
        # Different from single
        assert root != compute_merkle_root((op1,))

    def test_order_matters(self):
        op1 = _make_op("v1")
        op2 = _make_op("v2")
        assert compute_merkle_root((op1, op2)) != compute_merkle_root((op2, op1))

    def test_deterministic(self):
        op = _make_op()
        assert compute_merkle_root((op,)) == compute_merkle_root((op,))

    def test_odd_number_of_ops(self):
        ops = tuple(_make_op(f"v{i}") for i in range(3))
        root = compute_merkle_root(ops)
        assert len(root) == 64


# ═══════════════════════════════════════════════════════════════════
# 3. Block verification
# ═══════════════════════════════════════════════════════════════════

class TestVerifyBlock:
    def test_valid_genesis(self):
        g = _genesis()
        assert verify_block(g).valid

    def test_valid_block_with_prev(self):
        g = _genesis()
        b1 = _make_block(1, g)
        assert verify_block(b1, g).valid

    def test_valid_block_with_operations(self):
        g = _genesis()
        op = _make_op()
        b1 = _make_block(1, g, operations=(op,))
        assert verify_block(b1, g).valid

    def test_reject_negative_block_number(self):
        b = Block(chain_id=CHAIN_ID, block_number=-1,
                  prev_hash=GENESIS_PREV_HASH, merkle_root="0" * 64,
                  timestamp=TS)
        result = verify_block(b)
        assert not result.valid
        assert "negative block_number" in result.error

    def test_reject_negative_timestamp(self):
        b = Block(chain_id=CHAIN_ID, block_number=0,
                  prev_hash=GENESIS_PREV_HASH, merkle_root="0" * 64,
                  timestamp=-1)
        result = verify_block(b)
        assert not result.valid
        assert "negative timestamp" in result.error

    def test_reject_empty_chain_id(self):
        b = Block(chain_id="", block_number=0,
                  prev_hash=GENESIS_PREV_HASH, merkle_root="0" * 64,
                  timestamp=TS)
        result = verify_block(b)
        assert not result.valid
        assert "empty chain_id" in result.error

    def test_reject_wrong_genesis_prev_hash(self):
        b = Block(chain_id=CHAIN_ID, block_number=0,
                  prev_hash="abc123", merkle_root="0" * 64, timestamp=TS)
        result = verify_block(b)
        assert not result.valid
        assert "genesis prev_hash" in result.error

    def test_reject_block_number_gap(self):
        g = _genesis()
        b = _make_block(5, g)  # gap: expected 1
        result = verify_block(b, g)
        assert not result.valid
        assert "block_number gap" in result.error

    def test_reject_prev_hash_mismatch(self):
        g = _genesis()
        bad = Block(chain_id=CHAIN_ID, block_number=1,
                    prev_hash="deadbeef" * 8, merkle_root="0" * 64,
                    timestamp=TS + 1)
        result = verify_block(bad, g)
        assert not result.valid
        assert "prev_hash mismatch" in result.error

    def test_reject_chain_id_mismatch(self):
        g = _genesis()
        bad = Block(chain_id="other-chain", block_number=1,
                    prev_hash=g.block_hash, merkle_root="0" * 64,
                    timestamp=TS + 1)
        result = verify_block(bad, g)
        assert not result.valid
        assert "chain_id mismatch" in result.error

    def test_reject_timestamp_regression(self):
        g = _genesis()
        bad = Block(chain_id=CHAIN_ID, block_number=1,
                    prev_hash=g.block_hash, merkle_root="0" * 64,
                    timestamp=TS - 1)
        result = verify_block(bad, g)
        assert not result.valid
        assert "timestamp regression" in result.error

    def test_reject_merkle_mismatch(self):
        g = _genesis()
        op = _make_op()
        # Block claims empty merkle but has operations
        bad = Block(chain_id=CHAIN_ID, block_number=1,
                    prev_hash=g.block_hash, merkle_root="0" * 64,
                    timestamp=TS + 1, operations=(op,))
        result = verify_block(bad, g)
        assert not result.valid
        assert "merkle_root mismatch" in result.error

    def test_block_without_prev_skips_linkage(self):
        """verify_block with prev_block=None skips chain linkage."""
        b = _make_block(5, None)
        # This should still check merkle/timestamp/chain_id but not linkage
        result = verify_block(b)
        assert result.valid


# ═══════════════════════════════════════════════════════════════════
# 4. Block chain verification
# ═══════════════════════════════════════════════════════════════════

class TestVerifyBlockChain:
    def test_empty_chain(self):
        assert verify_block_chain([]).valid

    def test_valid_chain(self):
        blocks = _build_chain(5)
        assert verify_block_chain(blocks[1:], anchor=blocks[0]).valid

    def test_full_chain_from_genesis(self):
        blocks = _build_chain(5)
        # Genesis has no anchor
        result = verify_block_chain(blocks)
        assert result.valid

    def test_invalid_block_in_chain(self):
        blocks = _build_chain(5)
        # Corrupt block 3's merkle root
        bad = Block(
            chain_id=CHAIN_ID, block_number=3,
            prev_hash=blocks[2].block_hash,
            merkle_root="bad" * 21 + "b",
            timestamp=TS + 3,
        )
        chain = blocks[:3] + [bad] + blocks[4:]
        result = verify_block_chain(chain)
        assert not result.valid


# ═══════════════════════════════════════════════════════════════════
# 5. Sync protocol messages
# ═══════════════════════════════════════════════════════════════════

class TestSyncProtocol:
    def test_get_blocks_request(self):
        req = GetBlocksRequest(from_height=0, to_height=99, limit=50)
        d = req.to_dict()
        restored = GetBlocksRequest.from_dict(d)
        assert restored.from_height == 0
        assert restored.to_height == 99
        assert restored.limit == 50

    def test_get_blocks_response(self):
        blocks = _build_chain(3)
        resp = GetBlocksResponse(blocks=blocks)
        d = resp.to_dict()
        restored = GetBlocksResponse.from_dict(d)
        assert len(restored.blocks) == 3
        assert restored.blocks[0].block_number == 0

    def test_get_peer_info_request(self):
        req = GetPeerInfoRequest()
        d = req.to_dict()
        restored = GetPeerInfoRequest.from_dict(d)
        assert isinstance(restored, GetPeerInfoRequest)

    def test_get_peer_info_response(self):
        resp = GetPeerInfoResponse(chain_id=CHAIN_ID, height=42,
                                   genesis_hash="abc123")
        d = resp.to_dict()
        restored = GetPeerInfoResponse.from_dict(d)
        assert restored.chain_id == CHAIN_ID
        assert restored.height == 42
        assert restored.genesis_hash == "abc123"

    def test_sync_result_ok(self):
        r = SyncResult(status=SyncStatus.SUCCESS, blocks_synced=10)
        assert r.ok
        d = r.to_dict()
        assert d["ok"] is True
        assert d["status"] == "success"

    def test_sync_result_already_synced(self):
        r = SyncResult(status=SyncStatus.ALREADY_SYNCED)
        assert r.ok

    def test_sync_result_error(self):
        r = SyncResult(status=SyncStatus.ERROR, error="timeout")
        assert not r.ok
        assert r.error == "timeout"

    def test_sync_status_values(self):
        assert SyncStatus.SUCCESS.value == "success"
        assert SyncStatus.GENESIS_MISMATCH.value == "genesis_mismatch"
        assert SyncStatus.INVALID_BLOCK.value == "invalid_block"


# ═══════════════════════════════════════════════════════════════════
# 6. InMemoryPeer
# ═══════════════════════════════════════════════════════════════════

class TestInMemoryPeer:
    def test_peer_info(self):
        blocks = _build_chain(5)
        peer = _make_peer("peer1:8000", blocks)
        info = peer.get_peer_info()
        assert info.chain_id == CHAIN_ID
        assert info.height == 4
        assert info.genesis_hash == blocks[0].block_hash

    def test_peer_info_empty(self):
        peer = InMemoryPeer("peer1:8000", CHAIN_ID, "hash", [])
        info = peer.get_peer_info()
        assert info.height == -1

    def test_get_blocks_range(self):
        blocks = _build_chain(10)
        peer = _make_peer("peer1:8000", blocks)
        resp = peer.get_blocks(GetBlocksRequest(from_height=3, to_height=6))
        assert len(resp.blocks) == 4
        assert resp.blocks[0].block_number == 3
        assert resp.blocks[-1].block_number == 6

    def test_get_blocks_with_limit(self):
        blocks = _build_chain(10)
        peer = _make_peer("peer1:8000", blocks)
        resp = peer.get_blocks(GetBlocksRequest(from_height=0, to_height=9, limit=3))
        assert len(resp.blocks) == 3

    def test_get_blocks_empty_range(self):
        blocks = _build_chain(3)
        peer = _make_peer("peer1:8000", blocks)
        resp = peer.get_blocks(GetBlocksRequest(from_height=10, to_height=20))
        assert len(resp.blocks) == 0

    def test_add_block(self):
        blocks = _build_chain(3)
        peer = _make_peer("peer1:8000", blocks)
        new_block = _make_block(3, blocks[-1])
        peer.add_block(new_block)
        info = peer.get_peer_info()
        assert info.height == 3


# ═══════════════════════════════════════════════════════════════════
# 7. sync_from_peer
# ═══════════════════════════════════════════════════════════════════

class TestSyncFromPeer:
    def test_sync_empty_to_full(self, tmp_path):
        """Sync from an empty local chain to a peer with blocks."""
        blocks = _build_chain(6)
        peer = _make_peer("peer1:8000", blocks)
        engine = _make_engine(tmp_path)
        genesis_hash = blocks[0].block_hash

        result = sync_from_peer(peer, engine, local_height=-1,
                                local_genesis_hash=genesis_hash)
        assert result.ok
        assert result.status == SyncStatus.SUCCESS
        assert result.blocks_synced == 6
        assert result.from_height == 0
        assert result.to_height == 5
        engine.close()

    def test_sync_resume(self, tmp_path):
        """Resume sync from a partially synced chain."""
        blocks = _build_chain(10)
        peer = _make_peer("peer1:8000", blocks)
        engine = _make_engine(tmp_path)
        genesis_hash = blocks[0].block_hash

        # First sync: get blocks 0-4
        result1 = sync_from_peer(peer, engine, local_height=-1,
                                 local_genesis_hash=genesis_hash,
                                 target_height=4)
        assert result1.blocks_synced == 5

        # Resume: get blocks 5-9
        result2 = sync_from_peer(peer, engine, local_height=4,
                                 local_genesis_hash=genesis_hash)
        assert result2.blocks_synced == 5
        assert result2.from_height == 5
        assert result2.to_height == 9
        engine.close()

    def test_sync_already_synced(self, tmp_path):
        """No sync needed when local is at peer's height."""
        blocks = _build_chain(5)
        peer = _make_peer("peer1:8000", blocks)
        engine = _make_engine(tmp_path)
        genesis_hash = blocks[0].block_hash

        result = sync_from_peer(peer, engine, local_height=4,
                                local_genesis_hash=genesis_hash)
        assert result.ok
        assert result.status == SyncStatus.ALREADY_SYNCED
        assert result.blocks_synced == 0
        engine.close()

    def test_sync_genesis_mismatch(self, tmp_path):
        """Reject sync when genesis hashes don't match."""
        blocks = _build_chain(5)
        peer = _make_peer("peer1:8000", blocks)
        engine = _make_engine(tmp_path)

        result = sync_from_peer(peer, engine, local_height=-1,
                                local_genesis_hash="wrong_genesis_hash")
        assert not result.ok
        assert result.status == SyncStatus.GENESIS_MISMATCH
        engine.close()

    def test_sync_invalid_block_rejected(self, tmp_path):
        """Reject sync when a block has invalid merkle root."""
        genesis = _genesis()
        bad_block = Block(
            chain_id=CHAIN_ID, block_number=1,
            prev_hash=genesis.block_hash,
            merkle_root="bad" * 21 + "b",
            timestamp=TS + 1,
        )
        peer = _make_peer("peer1:8000", [genesis, bad_block])
        engine = _make_engine(tmp_path)
        genesis_hash = genesis.block_hash

        result = sync_from_peer(peer, engine, local_height=-1,
                                local_genesis_hash=genesis_hash)
        assert not result.ok
        # Genesis block (0) is valid, but block 1 fails
        # Since genesis syncs first, we get PARTIAL
        assert result.status in (SyncStatus.INVALID_BLOCK, SyncStatus.PARTIAL)
        engine.close()

    def test_sync_with_operations(self, tmp_path):
        """Sync blocks that contain operations."""
        genesis = _genesis()
        op = _make_op("val_sync_001")
        b1 = _make_block(1, genesis, operations=(op,))
        peer = _make_peer("peer1:8000", [genesis, b1])
        engine = _make_engine(tmp_path)

        result = sync_from_peer(peer, engine, local_height=-1,
                                local_genesis_hash=genesis.block_hash)
        assert result.ok
        assert result.blocks_synced == 2
        engine.close()

    def test_sync_batching(self, tmp_path):
        """Sync with small batch size triggers multiple requests."""
        blocks = _build_chain(10)
        peer = _make_peer("peer1:8000", blocks)
        engine = _make_engine(tmp_path)
        genesis_hash = blocks[0].block_hash

        result = sync_from_peer(peer, engine, local_height=-1,
                                local_genesis_hash=genesis_hash,
                                batch_size=3)
        assert result.ok
        assert result.blocks_synced == 10
        engine.close()

    def test_sync_progress_callback(self, tmp_path):
        """Progress callback is invoked during sync."""
        blocks = _build_chain(5)
        peer = _make_peer("peer1:8000", blocks)
        engine = _make_engine(tmp_path)
        genesis_hash = blocks[0].block_hash
        progress = []

        def on_progress(synced, total):
            progress.append((synced, total))

        sync_from_peer(peer, engine, local_height=-1,
                       local_genesis_hash=genesis_hash,
                       on_progress=on_progress)
        assert len(progress) == 5  # one per block
        assert progress[-1][0] == 5  # last call: 5 synced
        engine.close()

    def test_sync_peer_error(self, tmp_path):
        """Handle peer communication errors gracefully."""

        class FailingPeer:
            @property
            def address(self):
                return "failing:8000"

            def get_peer_info(self):
                raise ConnectionError("peer unreachable")

            def get_blocks(self, request):
                raise ConnectionError("peer unreachable")

        engine = _make_engine(tmp_path)
        result = sync_from_peer(FailingPeer(), engine, local_height=-1,
                                local_genesis_hash="hash")
        assert not result.ok
        assert result.status == SyncStatus.ERROR
        assert "peer unreachable" in result.error
        engine.close()

    def test_sync_partial_on_batch_error(self, tmp_path):
        """Partial sync when batch request fails mid-way."""

        class PartialPeer:
            def __init__(self, blocks):
                self._blocks = blocks
                self._call_count = 0

            @property
            def address(self):
                return "partial:8000"

            def get_peer_info(self):
                genesis = self._blocks[0]
                return GetPeerInfoResponse(
                    chain_id=CHAIN_ID,
                    height=len(self._blocks) - 1,
                    genesis_hash=genesis.block_hash,
                )

            def get_blocks(self, request):
                self._call_count += 1
                if self._call_count > 1:
                    raise ConnectionError("connection lost")
                result = []
                for b in self._blocks:
                    if request.from_height <= b.block_number <= request.to_height:
                        result.append(b)
                        if len(result) >= request.limit:
                            break
                return GetBlocksResponse(blocks=sorted(result, key=lambda b: b.block_number))

        blocks = _build_chain(10)
        engine = _make_engine(tmp_path)
        genesis_hash = blocks[0].block_hash

        result = sync_from_peer(PartialPeer(blocks), engine, local_height=-1,
                                local_genesis_hash=genesis_hash, batch_size=3)
        assert result.status == SyncStatus.PARTIAL
        assert result.blocks_synced == 3
        engine.close()


# ═══════════════════════════════════════════════════════════════════
# 8. sync_from_network
# ═══════════════════════════════════════════════════════════════════

class TestSyncFromNetwork:
    def test_no_peers(self, tmp_path):
        engine = _make_engine(tmp_path)
        result = sync_from_network([], engine, -1, "hash")
        assert not result.ok
        assert result.status == SyncStatus.NO_PEERS
        engine.close()

    def test_selects_highest_peer(self, tmp_path):
        """Network sync picks the peer with the highest chain."""
        genesis = _genesis()
        blocks_5 = _build_chain(5)
        blocks_10 = _build_chain(10)
        genesis_hash = genesis.block_hash

        peer_short = _make_peer("short:8000", blocks_5)
        peer_tall = _make_peer("tall:8000", blocks_10)

        engine = _make_engine(tmp_path)
        result = sync_from_network(
            [peer_short, peer_tall], engine, -1, genesis_hash)
        assert result.ok
        assert result.blocks_synced == 10
        assert result.peer == "tall:8000"
        engine.close()

    def test_filters_genesis_mismatch(self, tmp_path):
        """Peers with wrong genesis are filtered out."""
        blocks = _build_chain(5)
        genesis_hash = blocks[0].block_hash

        # Good peer
        peer_good = _make_peer("good:8000", blocks)
        # Bad peer (different genesis)
        other_genesis = make_genesis_block("other-chain", TS)
        other_blocks = _build_chain(20, chain_id="other-chain")
        peer_bad = InMemoryPeer("bad:8000", "other-chain",
                                other_genesis.block_hash, other_blocks)

        engine = _make_engine(tmp_path)
        result = sync_from_network(
            [peer_bad, peer_good], engine, -1, genesis_hash)
        assert result.ok
        assert result.peer == "good:8000"
        engine.close()

    def test_all_peers_wrong_genesis(self, tmp_path):
        other_genesis = make_genesis_block("other-chain", TS)
        other_blocks = _build_chain(5, chain_id="other-chain")
        peer = InMemoryPeer("peer:8000", "other-chain",
                            other_genesis.block_hash, other_blocks)

        engine = _make_engine(tmp_path)
        result = sync_from_network([peer], engine, -1, "my_genesis_hash")
        assert not result.ok
        assert result.status == SyncStatus.GENESIS_MISMATCH
        engine.close()

    def test_already_synced_network(self, tmp_path):
        blocks = _build_chain(5)
        peer = _make_peer("peer:8000", blocks)
        genesis_hash = blocks[0].block_hash

        engine = _make_engine(tmp_path)
        result = sync_from_network([peer], engine, 4, genesis_hash)
        assert result.ok
        assert result.status == SyncStatus.ALREADY_SYNCED
        engine.close()

    def test_all_peers_unreachable(self, tmp_path):
        class BadPeer:
            @property
            def address(self):
                return "bad:8000"
            def get_peer_info(self):
                raise ConnectionError("unreachable")
            def get_blocks(self, req):
                raise ConnectionError("unreachable")

        engine = _make_engine(tmp_path)
        result = sync_from_network([BadPeer()], engine, -1, "hash")
        assert not result.ok
        assert result.status == SyncStatus.NO_PEERS
        engine.close()


# ═══════════════════════════════════════════════════════════════════
# 9. Fork choice
# ═══════════════════════════════════════════════════════════════════

class TestForkChoice:
    GENESIS_HASH = "genesis123"

    def test_choose_fork_empty(self):
        assert choose_fork([], self.GENESIS_HASH) is None

    def test_choose_fork_single(self):
        c = ChainInfo(chain_id="c1", height=10, genesis_hash=self.GENESIS_HASH)
        result = choose_fork([c], self.GENESIS_HASH)
        assert result is not None
        assert result.chain_id == "c1"

    def test_choose_fork_highest_wins(self):
        chains = [
            ChainInfo(chain_id="c1", height=5, genesis_hash=self.GENESIS_HASH),
            ChainInfo(chain_id="c2", height=10, genesis_hash=self.GENESIS_HASH),
            ChainInfo(chain_id="c3", height=7, genesis_hash=self.GENESIS_HASH),
        ]
        result = choose_fork(chains, self.GENESIS_HASH)
        assert result.chain_id == "c2"

    def test_choose_fork_weight_tiebreaker(self):
        chains = [
            ChainInfo(chain_id="c1", height=10, genesis_hash=self.GENESIS_HASH,
                      cumulative_weight=100),
            ChainInfo(chain_id="c2", height=10, genesis_hash=self.GENESIS_HASH,
                      cumulative_weight=200),
        ]
        result = choose_fork(chains, self.GENESIS_HASH)
        assert result.chain_id == "c2"

    def test_choose_fork_filters_genesis(self):
        chains = [
            ChainInfo(chain_id="c1", height=100, genesis_hash="wrong"),
            ChainInfo(chain_id="c2", height=5, genesis_hash=self.GENESIS_HASH),
        ]
        result = choose_fork(chains, self.GENESIS_HASH)
        assert result.chain_id == "c2"

    def test_choose_fork_all_wrong_genesis(self):
        chains = [
            ChainInfo(chain_id="c1", height=10, genesis_hash="wrong1"),
            ChainInfo(chain_id="c2", height=20, genesis_hash="wrong2"),
        ]
        assert choose_fork(chains, self.GENESIS_HASH) is None

    def test_should_sync_true(self):
        local = ChainInfo(chain_id="c1", height=5, genesis_hash=self.GENESIS_HASH)
        remote = ChainInfo(chain_id="c1", height=10, genesis_hash=self.GENESIS_HASH)
        assert should_sync(local, remote, self.GENESIS_HASH)

    def test_should_sync_false_already_ahead(self):
        local = ChainInfo(chain_id="c1", height=10, genesis_hash=self.GENESIS_HASH)
        remote = ChainInfo(chain_id="c1", height=5, genesis_hash=self.GENESIS_HASH)
        assert not should_sync(local, remote, self.GENESIS_HASH)

    def test_should_sync_false_wrong_genesis(self):
        local = ChainInfo(chain_id="c1", height=5, genesis_hash=self.GENESIS_HASH)
        remote = ChainInfo(chain_id="c1", height=100, genesis_hash="wrong")
        assert not should_sync(local, remote, self.GENESIS_HASH)

    def test_rank_peers(self):
        peers = [
            ChainInfo(chain_id="c1", height=5, genesis_hash=self.GENESIS_HASH, peer="p1"),
            ChainInfo(chain_id="c2", height=20, genesis_hash="wrong", peer="p2"),
            ChainInfo(chain_id="c3", height=15, genesis_hash=self.GENESIS_HASH, peer="p3"),
            ChainInfo(chain_id="c4", height=10, genesis_hash=self.GENESIS_HASH, peer="p4"),
        ]
        ranked = rank_peers(peers, self.GENESIS_HASH)
        assert len(ranked) == 3  # p2 filtered
        assert ranked[0].peer == "p3"  # height=15 first
        assert ranked[1].peer == "p4"  # height=10
        assert ranked[2].peer == "p1"  # height=5

    def test_chain_info_score(self):
        c = ChainInfo(chain_id="c1", height=10, genesis_hash="g",
                      cumulative_weight=500)
        assert c.score == (500, 10)

    def test_is_canonical_chain(self):
        chains = [
            ChainInfo(chain_id="c1", height=5, genesis_hash=self.GENESIS_HASH,
                      last_block_hash="h1"),
            ChainInfo(chain_id="c2", height=10, genesis_hash=self.GENESIS_HASH,
                      last_block_hash="h2"),
        ]
        assert is_canonical_chain(chains[1], chains, self.GENESIS_HASH)
        assert not is_canonical_chain(chains[0], chains, self.GENESIS_HASH)


# ═══════════════════════════════════════════════════════════════════
# 10. ConsensusEngine integration
# ═══════════════════════════════════════════════════════════════════

class TestEngineIntegration:
    def test_get_genesis_hash(self, tmp_path):
        engine = _make_engine(tmp_path)
        h = engine.get_genesis_hash()
        assert len(h) == 64
        # Deterministic
        assert h == engine.get_genesis_hash()
        engine.close()

    def test_sync_from_peers_no_peers(self, tmp_path):
        engine = _make_engine(tmp_path)
        result = engine.sync_from_peers([])
        assert result["status"] == "no_peers"
        engine.close()

    def test_sync_from_peers_success(self, tmp_path):
        engine = _make_engine(tmp_path)
        genesis_hash = engine.get_genesis_hash()
        chain_id = engine.chain_id

        # Build blocks for this engine's chain
        genesis = make_genesis_block(chain_id)
        blocks = [genesis]
        for i in range(1, 5):
            blocks.append(_make_block(i, blocks[-1], chain_id=chain_id))

        peer = InMemoryPeer("peer:8000", chain_id, genesis_hash, blocks)
        result = engine.sync_from_peers([peer])
        assert result["ok"] is True
        assert result["blocks_synced"] == 5
        engine.close()


# ═══════════════════════════════════════════════════════════════════
# 11. Genesis block
# ═══════════════════════════════════════════════════════════════════

class TestGenesisBlock:
    def test_make_genesis(self):
        g = make_genesis_block("test-chain", 12345)
        assert g.block_number == 0
        assert g.prev_hash == GENESIS_PREV_HASH
        assert g.chain_id == "test-chain"
        assert g.timestamp == 12345
        assert g.proposer == "genesis"
        assert len(g.operations) == 0

    def test_genesis_hash_depends_on_chain_id(self):
        g1 = make_genesis_block("chain-a")
        g2 = make_genesis_block("chain-b")
        assert g1.block_hash != g2.block_hash

    def test_genesis_hash_deterministic(self):
        g1 = make_genesis_block("chain-a", 100)
        g2 = make_genesis_block("chain-a", 100)
        assert g1.block_hash == g2.block_hash

    def test_genesis_prev_hash_is_zeroed(self):
        assert GENESIS_PREV_HASH == "0" * 64


# ═══════════════════════════════════════════════════════════════════
# 12. ValidationResult
# ═══════════════════════════════════════════════════════════════════

class TestValidationResult:
    def test_valid(self):
        r = ValidationResult(True)
        assert r.valid
        assert bool(r)
        assert "True" in repr(r)

    def test_invalid(self):
        r = ValidationResult(False, "some error")
        assert not r.valid
        assert not bool(r)
        assert "some error" in repr(r)


# ═══════════════════════════════════════════════════════════════════
# 13. BlockHeader
# ═══════════════════════════════════════════════════════════════════

class TestBlockHeader:
    def test_header_from_genesis(self):
        g = _genesis()
        h = g.to_header()
        assert isinstance(h, BlockHeader)
        assert h.block_number == 0
        assert h.chain_id == CHAIN_ID
        assert h.prev_hash == GENESIS_PREV_HASH
        assert h.proposer == "genesis"

    def test_header_hash_matches_block(self):
        g = _genesis()
        b1 = _make_block(1, g)
        h = b1.to_header()
        assert h.block_hash == b1.block_hash

    def test_header_to_dict_roundtrip(self):
        b = _make_block(3, _make_block(2, _make_block(1, _genesis())))
        h = b.to_header()
        d = h.to_dict()
        restored = BlockHeader.from_dict(d)
        assert restored.block_number == h.block_number
        assert restored.chain_id == h.chain_id
        assert restored.prev_hash == h.prev_hash
        assert restored.merkle_root == h.merkle_root
        assert restored.timestamp == h.timestamp
        assert restored.proposer == h.proposer

    def test_header_frozen(self):
        h = _genesis().to_header()
        with pytest.raises(AttributeError):
            h.block_number = 99

    def test_header_different_blocks_different_hashes(self):
        g = _genesis()
        b1 = _make_block(1, g, proposer="A")
        b2 = _make_block(1, g, proposer="A", timestamp=TS + 999)
        assert b1.to_header().block_hash != b2.to_header().block_hash

    def test_header_preserves_signature(self):
        g = _genesis()
        b = Block(
            chain_id=CHAIN_ID, block_number=1,
            prev_hash=g.block_hash, merkle_root="0" * 64,
            timestamp=TS + 1, proposer="val1", signature="sig123",
        )
        h = b.to_header()
        assert h.signature == "sig123"

    def test_header_from_dict_defaults(self):
        h = BlockHeader.from_dict({})
        assert h.chain_id == ""
        assert h.block_number == 0
        assert h.proposer == ""

    def test_header_chain_linkage(self):
        """Headers from a chain have correct prev_hash linkage."""
        blocks = _build_chain(5)
        headers = [b.to_header() for b in blocks]
        for i in range(1, len(headers)):
            assert headers[i].prev_hash == headers[i - 1].block_hash


# ═══════════════════════════════════════════════════════════════════
# 14. Incremental sync scenarios
# ═══════════════════════════════════════════════════════════════════

class TestIncrementalSync:
    def test_sync_incremental_small_batches(self, tmp_path):
        """Multiple incremental syncs with small batches."""
        blocks = _build_chain(20)
        peer = _make_peer("peer:8000", blocks)
        engine = _make_engine(tmp_path)
        genesis_hash = blocks[0].block_hash

        # Sync first 5
        r1 = sync_from_peer(peer, engine, -1, genesis_hash, target_height=4)
        assert r1.blocks_synced == 5

        # Sync next 5
        r2 = sync_from_peer(peer, engine, 4, genesis_hash, target_height=9)
        assert r2.blocks_synced == 5

        # Sync remaining
        r3 = sync_from_peer(peer, engine, 9, genesis_hash)
        assert r3.blocks_synced == 10
        assert r3.to_height == 19
        engine.close()

    def test_sync_local_ahead_of_target(self, tmp_path):
        """Local height exceeds target — already synced."""
        blocks = _build_chain(5)
        peer = _make_peer("peer:8000", blocks)
        engine = _make_engine(tmp_path)
        genesis_hash = blocks[0].block_hash

        result = sync_from_peer(peer, engine, 10, genesis_hash)
        assert result.status == SyncStatus.ALREADY_SYNCED
        engine.close()

    def test_sync_with_different_batch_sizes(self, tmp_path):
        """Sync same chain with various batch sizes gives same result."""
        blocks = _build_chain(25)
        genesis_hash = blocks[0].block_hash

        for bs in [1, 5, 10, 25, 100]:
            engine = _make_engine(tmp_path / f"db_{bs}")
            peer = _make_peer(f"peer_{bs}:8000", blocks)
            result = sync_from_peer(peer, engine, -1, genesis_hash, batch_size=bs)
            assert result.ok
            assert result.blocks_synced == 25
            engine.close()
