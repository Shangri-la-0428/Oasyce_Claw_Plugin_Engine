"""
Tests for block producer — Mempool and BlockProducer.

Covers:
  - Mempool: submit, drain, peek, clear, size, overflow
  - BlockProducer: genesis init, single block, chained blocks, empty mempool
  - BlockProducer: background loop start/stop, on_block callback
  - BlockProducer: SyncServer integration, status reporting
  - Thread safety: concurrent submits
"""

import threading
import time

import pytest

from oasyce_plugin.consensus import ConsensusEngine
from oasyce_plugin.consensus.core.types import Operation, OperationType, to_units
from oasyce_plugin.consensus.execution.producer import Mempool, BlockProducer
from oasyce_plugin.consensus.network.sync_protocol import (
    Block, make_genesis_block, GENESIS_PREV_HASH,
)
from oasyce_plugin.consensus.network.http_transport import SyncServer


# ── Helpers ───────────────────────────────────────────────────────


def _make_engine(**kw):
    return ConsensusEngine(db_path=":memory:", **kw)


def _make_op(op_type=OperationType.DELEGATE, validator_id="v1",
             amount=None, **kw):
    if amount is None:
        amount = to_units(100)
    return Operation(op_type=op_type, validator_id=validator_id,
                     amount=amount, **kw)


# ── Mempool tests ────────────────────────────────────────────────


class TestMempool:
    def test_submit_and_drain(self):
        mp = Mempool()
        op1 = _make_op(validator_id="v1")
        op2 = _make_op(validator_id="v2")
        assert mp.submit(op1)["ok"] is True
        assert mp.submit(op2)["ok"] is True
        assert mp.size == 2

        drained = mp.drain(10)
        assert len(drained) == 2
        assert drained[0].validator_id == "v1"
        assert drained[1].validator_id == "v2"
        assert mp.size == 0

    def test_drain_respects_max(self):
        mp = Mempool()
        for i in range(5):
            mp.submit(_make_op(validator_id=f"v{i}"))
        drained = mp.drain(3)
        assert len(drained) == 3
        assert mp.size == 2

    def test_drain_empty(self):
        mp = Mempool()
        assert mp.drain() == []

    def test_peek_does_not_remove(self):
        mp = Mempool()
        mp.submit(_make_op(validator_id="v1"))
        mp.submit(_make_op(validator_id="v2"))
        peeked = mp.peek(10)
        assert len(peeked) == 2
        assert mp.size == 2  # still there

    def test_peek_respects_max(self):
        mp = Mempool()
        for i in range(5):
            mp.submit(_make_op(validator_id=f"v{i}"))
        peeked = mp.peek(2)
        assert len(peeked) == 2

    def test_clear(self):
        mp = Mempool()
        for i in range(3):
            mp.submit(_make_op(validator_id=f"v{i}"))
        removed = mp.clear()
        assert removed == 3
        assert mp.size == 0

    def test_max_size_overflow(self):
        mp = Mempool(max_size=3)
        for i in range(3):
            assert mp.submit(_make_op(validator_id=f"v{i}"))["ok"] is True
        result = mp.submit(_make_op(validator_id="v_overflow"))
        assert result["ok"] is False
        assert "full" in result["error"]
        assert mp.size == 3

    def test_submit_returns_position(self):
        mp = Mempool()
        r1 = mp.submit(_make_op())
        assert r1["position"] == 1
        r2 = mp.submit(_make_op())
        assert r2["position"] == 2

    def test_fifo_order(self):
        mp = Mempool()
        ids = ["a", "b", "c", "d"]
        for vid in ids:
            mp.submit(_make_op(validator_id=vid))
        drained = mp.drain(10)
        assert [op.validator_id for op in drained] == ids

    def test_concurrent_submits(self):
        mp = Mempool(max_size=1000)
        errors = []

        def submit_batch(start):
            for i in range(100):
                r = mp.submit(_make_op(validator_id=f"v{start}_{i}"))
                if not r["ok"]:
                    errors.append(r)

        threads = [threading.Thread(target=submit_batch, args=(t,))
                   for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert mp.size == 500


# ── BlockProducer tests ──────────────────────────────────────────


class TestBlockProducer:
    def test_genesis_init(self):
        engine = _make_engine()
        mp = Mempool()
        producer = BlockProducer(engine, mp, proposer_id="node-1")

        assert producer.height == 0
        assert producer.prev_hash != GENESIS_PREV_HASH
        assert producer.blocks_produced == 0

    def test_produce_single_block(self):
        engine = _make_engine()
        mp = Mempool()
        producer = BlockProducer(engine, mp, proposer_id="node-1")

        # Submit an operation (use REGISTER with enough stake)
        op = Operation(
            op_type=OperationType.REGISTER,
            validator_id="val-1",
            amount=to_units(200),
            commission_rate=1000,
        )
        mp.submit(op)

        block = producer.produce_block()
        assert block is not None
        assert block.block_number == 1
        assert block.proposer == "node-1"
        assert len(block.operations) == 1
        assert producer.height == 1
        assert producer.blocks_produced == 1

    def test_produce_empty_block(self):
        engine = _make_engine()
        mp = Mempool()
        producer = BlockProducer(engine, mp)

        block = producer.produce_block()
        assert block is not None
        assert block.block_number == 1
        assert len(block.operations) == 0

    def test_chained_blocks(self):
        engine = _make_engine()
        mp = Mempool()
        producer = BlockProducer(engine, mp, proposer_id="node-1")

        b1 = producer.produce_block()
        b2 = producer.produce_block()
        b3 = producer.produce_block()

        assert b1.block_number == 1
        assert b2.block_number == 2
        assert b3.block_number == 3

        # Chain linkage
        assert b2.prev_hash == b1.block_hash
        assert b3.prev_hash == b2.block_hash

        assert producer.height == 3
        assert producer.blocks_produced == 3

    def test_on_block_callback(self):
        engine = _make_engine()
        mp = Mempool()
        received = []

        producer = BlockProducer(engine, mp, on_block=received.append)
        producer.produce_block()
        producer.produce_block()

        assert len(received) == 2
        assert received[0].block_number == 1
        assert received[1].block_number == 2

    def test_max_ops_per_block(self):
        engine = _make_engine()
        mp = Mempool()
        producer = BlockProducer(engine, mp, max_ops_per_block=3)

        for i in range(7):
            mp.submit(Operation(
                op_type=OperationType.REGISTER,
                validator_id=f"val-{i}",
                amount=to_units(200),
                commission_rate=1000,
            ))

        b1 = producer.produce_block()
        assert len(b1.operations) == 3
        assert mp.size == 4  # 4 remaining

        b2 = producer.produce_block()
        assert len(b2.operations) == 3
        assert mp.size == 1

        b3 = producer.produce_block()
        assert len(b3.operations) == 1
        assert mp.size == 0

    def test_status(self):
        engine = _make_engine()
        mp = Mempool()
        mp.submit(_make_op())
        producer = BlockProducer(engine, mp, proposer_id="node-x")

        status = producer.status()
        assert status["height"] == 0
        assert status["blocks_produced"] == 0
        assert status["mempool_size"] == 1
        assert status["proposer"] == "node-x"
        assert status["running"] is False

    def test_start_stop(self):
        engine = _make_engine()
        mp = Mempool()
        producer = BlockProducer(engine, mp, proposer_id="node-1")

        producer.start(interval=0.1, empty_blocks=True)
        assert producer.status()["running"] is True

        time.sleep(0.5)  # let it produce a few blocks
        producer.stop()

        assert producer.status()["running"] is False
        assert producer.blocks_produced >= 2  # should have produced several

    def test_start_no_empty_blocks(self):
        engine = _make_engine()
        mp = Mempool()
        producer = BlockProducer(engine, mp, proposer_id="node-1")

        producer.start(interval=0.1, empty_blocks=False)
        time.sleep(0.3)

        # No ops submitted, so no blocks produced
        produced_before = producer.blocks_produced

        # Now submit an op
        mp.submit(Operation(
            op_type=OperationType.REGISTER,
            validator_id="val-1",
            amount=to_units(200),
            commission_rate=1000,
        ))
        time.sleep(0.3)
        producer.stop()

        # Should have produced at least 1 block after submission
        assert producer.blocks_produced > produced_before

    def test_start_idempotent(self):
        engine = _make_engine()
        mp = Mempool()
        producer = BlockProducer(engine, mp)

        producer.start(interval=0.1)
        producer.start(interval=0.1)  # should not create second thread
        time.sleep(0.2)
        producer.stop()

    def test_sync_server_integration(self):
        """BlockProducer pushes blocks to SyncServer."""
        engine = _make_engine()
        mp = Mempool()
        server = SyncServer(engine, port=0, db_path=":memory:")  # port=0 won't start

        producer = BlockProducer(engine, mp, sync_server=server,
                                 proposer_id="node-1")

        # Genesis should already be in server
        assert len(server.blocks) == 1

        mp.submit(Operation(
            op_type=OperationType.REGISTER,
            validator_id="val-1",
            amount=to_units(200),
            commission_rate=1000,
        ))
        producer.produce_block()

        assert len(server.blocks) == 2
        assert server.blocks[1].block_number == 1

    def test_sync_server_genesis_not_duplicated(self):
        """If SyncServer already has genesis, don't add again."""
        engine = _make_engine()
        mp = Mempool()
        server = SyncServer(engine, port=0, db_path=":memory:")

        # Pre-add genesis
        genesis = make_genesis_block(engine.chain_id,
                                     timestamp=engine.genesis_time)
        server.add_block(genesis)
        assert len(server.blocks) == 1

        # Producer init should not duplicate
        producer = BlockProducer(engine, mp, sync_server=server)
        assert len(server.blocks) == 1

    def test_block_has_correct_chain_id(self):
        engine = _make_engine(consensus_params={"chain_id": "test-chain-42"})
        mp = Mempool()
        producer = BlockProducer(engine, mp)

        block = producer.produce_block()
        assert block.chain_id == "test-chain-42"

    def test_block_merkle_root(self):
        """Blocks with different operations produce different merkle roots."""
        engine = _make_engine()
        mp = Mempool()
        producer = BlockProducer(engine, mp)

        # Empty block
        b1 = producer.produce_block()

        # Block with op
        mp.submit(Operation(
            op_type=OperationType.REGISTER,
            validator_id="val-1",
            amount=to_units(200),
            commission_rate=1000,
        ))
        b2 = producer.produce_block()

        assert b1.merkle_root != b2.merkle_root
