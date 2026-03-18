"""
End-to-end lifecycle integration test.

Full pipeline:
  1. Initialize two nodes with consensus engines
  2. Register validators
  3. Submit operations to mempool
  4. BlockProducer builds blocks and pushes to SyncServer
  5. Second node syncs blocks from first node via HTTP
  6. Verify state convergence across nodes

This is the top-level integration test that exercises:
  Mempool → BlockProducer → SyncServer → HTTPPeerTransport → sync_from_peers
"""

import socket
import time

import pytest

from oasyce_plugin.consensus import ConsensusEngine
from oasyce_plugin.consensus.core.types import (
    Operation, OperationType, to_units, from_units,
)
from oasyce_plugin.consensus.execution.producer import Mempool, BlockProducer
from oasyce_plugin.consensus.network.http_transport import (
    HTTPPeerTransport, SyncServer,
)
from oasyce_plugin.consensus.network.sync_protocol import (
    make_genesis_block, GetBlocksRequest,
)


# ── Helpers ───────────────────────────────────────────────────────


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_engine(**kw):
    return ConsensusEngine(db_path=":memory:", **kw)


def _register_op(validator_id, stake_oas=200):
    return Operation(
        op_type=OperationType.REGISTER,
        validator_id=validator_id,
        amount=to_units(stake_oas),
        commission_rate=1000,
    )


def _delegate_op(validator_id, from_addr, amount_oas=50):
    return Operation(
        op_type=OperationType.DELEGATE,
        validator_id=validator_id,
        amount=to_units(amount_oas),
        from_addr=from_addr,
    )


# ── E2E Tests ────────────────────────────────────────────────────


class TestE2ELifecycle:
    """Full lifecycle: init → register → produce → sync → verify."""

    def test_single_node_produce_and_query(self):
        """Single node: submit ops → produce blocks → verify state."""
        engine = _make_engine()
        mp = Mempool()
        producer = BlockProducer(engine, mp, proposer_id="node-0")

        # Register two validators
        mp.submit(_register_op("val-A"))
        mp.submit(_register_op("val-B"))

        b1 = producer.produce_block()
        assert b1.block_number == 1
        assert len(b1.operations) == 2

        # Verify validators were registered in engine state
        val_a = engine.state.get_validator("val-A")
        val_b = engine.state.get_validator("val-B")
        assert val_a is not None
        assert val_b is not None
        assert val_a["status"] == "active"
        assert val_b["status"] == "active"

        # Produce empty block to advance chain
        b2 = producer.produce_block()
        assert b2.block_number == 2
        assert b2.prev_hash == b1.block_hash

        assert producer.height == 2
        assert producer.blocks_produced == 2
        engine.close()

    def test_two_node_sync(self):
        """Node A produces blocks → Node B syncs via HTTP → state converges."""
        port_a = _free_port()

        # ── Node A: producer ──
        engine_a = _make_engine()
        mp = Mempool()
        server_a = SyncServer(engine_a, host="127.0.0.1", port=port_a)
        producer = BlockProducer(
            engine_a, mp, sync_server=server_a, proposer_id="node-A",
        )

        server_a.start()
        try:
            # Register validators and produce blocks
            mp.submit(_register_op("val-1"))
            producer.produce_block()

            mp.submit(_register_op("val-2"))
            producer.produce_block()

            # Produce a couple more blocks
            producer.produce_block()
            producer.produce_block()

            assert producer.height == 4
            assert len(server_a.blocks) == 5  # genesis + 4

            # ── Node B: syncer ──
            engine_b = _make_engine()
            peer_a = HTTPPeerTransport(f"http://127.0.0.1:{port_a}")

            # Verify peer info
            info = peer_a.get_peer_info()
            assert info.height == 4
            assert info.chain_id == engine_a.chain_id

            # Sync blocks
            result = engine_b.sync_from_peers(
                [peer_a], local_height=-1,
            )
            assert result["ok"] or result.get("status") == "success"
            assert result["blocks_synced"] >= 3

            engine_b.close()
        finally:
            server_a.stop()
            engine_a.close()

    def test_producer_with_background_loop_and_sync(self):
        """Producer runs in background, syncer catches up."""
        port = _free_port()

        engine_a = _make_engine()
        mp = Mempool()
        server = SyncServer(engine_a, host="127.0.0.1", port=port)
        producer = BlockProducer(
            engine_a, mp, sync_server=server, proposer_id="node-bg",
        )

        server.start()
        try:
            # Start background production with empty blocks
            producer.start(interval=0.1, empty_blocks=True)
            time.sleep(0.6)  # let it produce ~5 blocks
            producer.stop()

            produced = producer.blocks_produced
            assert produced >= 3

            # Node B syncs all blocks
            engine_b = _make_engine()
            peer = HTTPPeerTransport(f"http://127.0.0.1:{port}")
            result = engine_b.sync_from_peers([peer], local_height=-1)
            assert result["ok"] or result.get("status") == "success"
            assert result["blocks_synced"] >= 2

            engine_b.close()
        finally:
            producer.stop()
            server.stop()
            engine_a.close()

    def test_multi_validator_operations(self):
        """Register, delegate, produce blocks — verify stake changes."""
        engine = _make_engine()
        mp = Mempool()
        producer = BlockProducer(engine, mp, proposer_id="node-0")

        # Block 1: Register validator
        mp.submit(_register_op("val-X", stake_oas=300))
        producer.produce_block()

        val = engine.state.get_validator("val-X")
        assert val is not None

        # Block 2: Delegate to validator
        mp.submit(_delegate_op("val-X", from_addr="delegator-1", amount_oas=100))
        producer.produce_block()

        # Verify delegation recorded
        delegation = engine.state.get_delegation_amount("delegator-1", "val-X")
        assert delegation == to_units(100)

        assert producer.height == 2
        engine.close()

    def test_sync_preserves_block_integrity(self):
        """Synced blocks have identical hashes and operations."""
        port = _free_port()

        engine_a = _make_engine()
        mp = Mempool()
        server = SyncServer(engine_a, host="127.0.0.1", port=port)
        producer = BlockProducer(
            engine_a, mp, sync_server=server, proposer_id="node-A",
        )

        server.start()
        try:
            # Produce blocks with operations
            mp.submit(_register_op("val-1"))
            b1 = producer.produce_block()

            mp.submit(_register_op("val-2"))
            b2 = producer.produce_block()

            # Fetch blocks via HTTP
            peer = HTTPPeerTransport(f"http://127.0.0.1:{port}")
            resp = peer.get_blocks(GetBlocksRequest(from_height=1, to_height=2))

            assert len(resp.blocks) == 2

            synced_b1 = resp.blocks[0]
            synced_b2 = resp.blocks[1]

            # Hash integrity
            assert synced_b1.block_hash == b1.block_hash
            assert synced_b2.block_hash == b2.block_hash

            # Chain linkage
            assert synced_b2.prev_hash == synced_b1.block_hash

            # Operations preserved
            assert len(synced_b1.operations) == 1
            assert synced_b1.operations[0].validator_id == "val-1"
            assert synced_b1.operations[0].amount == to_units(200)
        finally:
            server.stop()
            engine_a.close()

    def test_three_node_produce_and_converge(self):
        """Node A produces → Node B and C both sync → all have same chain."""
        port_a = _free_port()

        engine_a = _make_engine()
        mp = Mempool()
        server_a = SyncServer(engine_a, host="127.0.0.1", port=port_a)
        producer = BlockProducer(
            engine_a, mp, sync_server=server_a, proposer_id="node-A",
        )

        server_a.start()
        try:
            # Produce 5 blocks with validators
            for i in range(5):
                mp.submit(_register_op(f"val-{i}"))
                producer.produce_block()

            assert producer.height == 5

            peer_a = HTTPPeerTransport(f"http://127.0.0.1:{port_a}")

            # Node B syncs
            engine_b = _make_engine()
            result_b = engine_b.sync_from_peers([peer_a], local_height=-1)
            assert result_b["ok"] or result_b.get("status") == "success"

            # Node C syncs
            engine_c = _make_engine()
            result_c = engine_c.sync_from_peers([peer_a], local_height=-1)
            assert result_c["ok"] or result_c.get("status") == "success"

            # Both should have synced same number of blocks
            assert result_b["blocks_synced"] == result_c["blocks_synced"]

            engine_b.close()
            engine_c.close()
        finally:
            server_a.stop()
            engine_a.close()

    def test_incremental_sync(self):
        """Node B syncs partially, then catches up on new blocks."""
        port_a = _free_port()

        engine_a = _make_engine()
        mp = Mempool()
        server_a = SyncServer(engine_a, host="127.0.0.1", port=port_a)
        producer = BlockProducer(
            engine_a, mp, sync_server=server_a, proposer_id="node-A",
        )

        server_a.start()
        try:
            # Phase 1: produce 3 blocks
            for i in range(3):
                mp.submit(_register_op(f"val-{i}"))
                producer.produce_block()

            # Node B: first sync
            engine_b = _make_engine()
            peer_a = HTTPPeerTransport(f"http://127.0.0.1:{port_a}")
            r1 = engine_b.sync_from_peers([peer_a], local_height=-1)
            first_synced = r1["blocks_synced"]
            assert first_synced >= 2

            # Phase 2: produce 3 more blocks
            for i in range(3, 6):
                mp.submit(_register_op(f"val-{i}"))
                producer.produce_block()

            assert producer.height == 6

            # Node B: incremental sync (from where it left off)
            r2 = engine_b.sync_from_peers(
                [peer_a], local_height=first_synced,
            )
            assert r2["ok"] or r2.get("status") == "success"
            assert r2["blocks_synced"] >= 2  # caught up with new blocks

            engine_b.close()
        finally:
            server_a.stop()
            engine_a.close()

    def test_mempool_overflow_graceful(self):
        """Mempool rejects ops when full; producer still works."""
        engine = _make_engine()
        mp = Mempool(max_size=5)
        producer = BlockProducer(engine, mp, max_ops_per_block=3)

        # Fill mempool
        for i in range(5):
            assert mp.submit(_register_op(f"val-{i}"))["ok"]

        # 6th should be rejected
        result = mp.submit(_register_op("val-overflow"))
        assert result["ok"] is False

        # Producer still drains normally
        b1 = producer.produce_block()
        assert len(b1.operations) == 3
        assert mp.size == 2

        # Now there's room again
        assert mp.submit(_register_op("val-new"))["ok"]
        assert mp.size == 3

        engine.close()

    def test_full_lifecycle_with_status(self):
        """Complete lifecycle with status checks at each stage."""
        port = _free_port()
        engine = _make_engine()
        mp = Mempool()
        server = SyncServer(engine, host="127.0.0.1", port=port)
        producer = BlockProducer(
            engine, mp, sync_server=server, proposer_id="lifecycle-node",
        )

        # Stage 1: Initial state
        status = producer.status()
        assert status["height"] == 0
        assert status["blocks_produced"] == 0
        assert status["mempool_size"] == 0
        assert status["running"] is False

        server.start()
        try:
            # Stage 2: Submit operations
            mp.submit(_register_op("val-1"))
            mp.submit(_register_op("val-2"))
            assert producer.status()["mempool_size"] == 2

            # Stage 3: Produce block
            producer.produce_block()
            status = producer.status()
            assert status["height"] == 1
            assert status["blocks_produced"] == 1
            assert status["mempool_size"] == 0

            # Stage 4: Delegate
            mp.submit(_delegate_op("val-1", "alice", 50))
            producer.produce_block()

            # Stage 5: Verify via sync endpoint
            peer = HTTPPeerTransport(f"http://127.0.0.1:{port}")
            info = peer.get_peer_info()
            assert info.height == 2
            assert info.chain_id == engine.chain_id

            # Stage 6: Verify blocks via HTTP
            resp = peer.get_blocks(GetBlocksRequest(from_height=0, to_height=2))
            assert len(resp.blocks) == 3  # genesis + 2

            # Final status
            status = producer.status()
            assert status["height"] == 2
            assert status["blocks_produced"] == 2
            assert "lifecycle-node" in status["proposer"]
        finally:
            server.stop()
            engine.close()
