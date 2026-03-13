"""
Tests for Phase 5: Block Sync — insert_remote_block, sync_from_peer, broadcast_block.
"""

import asyncio
import json
import pytest

from oasyce_plugin.network.node import OasyceNode, PeerInfo
from oasyce_plugin.storage.ledger import Ledger


@pytest.fixture
def ledger_a(tmp_path):
    return Ledger(str(tmp_path / "a.db"))


@pytest.fixture
def ledger_b(tmp_path):
    return Ledger(str(tmp_path / "b.db"))


def _make_blocks(ledger, n=3):
    """Create n blocks with one tx each."""
    for i in range(n):
        ledger.record_tx("register", asset_id=f"asset_{i}", from_addr="sys", to_addr="owner")
        ledger.create_block()


def _get_bound_port(node: OasyceNode) -> int:
    for sock in node._server.sockets:
        return sock.getsockname()[1]
    raise RuntimeError("No sockets")


# ── insert_remote_block ──────────────────────────────────────────────


class TestInsertRemoteBlock:
    def test_insert_valid_block(self, ledger_a, ledger_b):
        """Block created on A can be inserted into B."""
        ledger_a.record_tx("register", asset_id="A1", from_addr="sys", to_addr="o1")
        ledger_a.create_block()
        block = ledger_a.get_block(0, include_tx=True)

        assert ledger_b.insert_remote_block(block) is True
        assert ledger_b.get_chain_height() == 1
        assert ledger_b.verify_chain() is True

    def test_reject_bad_hash(self, ledger_a, ledger_b):
        """Block with tampered block_hash is rejected."""
        ledger_a.record_tx("register", asset_id="A1", from_addr="sys", to_addr="o1")
        ledger_a.create_block()
        block = ledger_a.get_block(0, include_tx=True)
        block["block_hash"] = "deadbeef" * 8

        assert ledger_b.insert_remote_block(block) is False
        assert ledger_b.get_chain_height() == 0

    def test_reject_broken_chain(self, ledger_a, ledger_b):
        """Block with wrong prev_hash is rejected."""
        _make_blocks(ledger_a, 2)
        # Try inserting block 1 without block 0
        block1 = ledger_a.get_block(1, include_tx=True)
        assert ledger_b.insert_remote_block(block1) is False

    def test_reject_bad_merkle(self, ledger_a, ledger_b):
        """Block with tampered merkle_root is rejected."""
        ledger_a.record_tx("register", asset_id="A1", from_addr="sys", to_addr="o1")
        ledger_a.create_block()
        block = ledger_a.get_block(0, include_tx=True)
        block["merkle_root"] = "0" * 64

        assert ledger_b.insert_remote_block(block) is False

    def test_idempotent(self, ledger_a, ledger_b):
        """Inserting the same block twice is fine."""
        ledger_a.record_tx("register", asset_id="A1", from_addr="sys", to_addr="o1")
        ledger_a.create_block()
        block = ledger_a.get_block(0, include_tx=True)

        assert ledger_b.insert_remote_block(block) is True
        assert ledger_b.insert_remote_block(block) is True
        assert ledger_b.get_chain_height() == 1

    def test_reject_incomplete_data(self, ledger_b):
        """Block missing required fields is rejected."""
        assert ledger_b.insert_remote_block({"block_number": 0}) is False


# ── Two-node sync ────────────────────────────────────────────────────


class TestSyncFromPeer:
    def test_sync_three_blocks(self, ledger_a, ledger_b):
        """B syncs 3 blocks from A over the network."""
        _make_blocks(ledger_a, 3)
        assert ledger_a.get_chain_height() == 3

        async def _run():
            node_a = OasyceNode(host="127.0.0.1", port=0, node_id="A", ledger=ledger_a)
            node_b = OasyceNode(host="127.0.0.1", port=0, node_id="B", ledger=ledger_b)

            await node_a.start()
            port_a = _get_bound_port(node_a)

            fetched = await node_b.sync_from_peer("127.0.0.1", port_a)
            assert fetched == 3
            assert ledger_b.get_chain_height() == 3
            assert ledger_b.verify_chain() is True

            await node_a.stop()

        asyncio.run(_run())

    def test_sync_incremental(self, ledger_a, ledger_b):
        """B already has 1 block, syncs 2 more from A."""
        _make_blocks(ledger_a, 3)
        # Give B block 0
        block0 = ledger_a.get_block(0, include_tx=True)
        ledger_b.insert_remote_block(block0)
        assert ledger_b.get_chain_height() == 1

        async def _run():
            node_a = OasyceNode(host="127.0.0.1", port=0, node_id="A", ledger=ledger_a)
            await node_a.start()
            port_a = _get_bound_port(node_a)

            node_b = OasyceNode(host="127.0.0.1", port=0, node_id="B", ledger=ledger_b)
            fetched = await node_b.sync_from_peer("127.0.0.1", port_a)
            assert fetched == 2
            assert ledger_b.get_chain_height() == 3

            await node_a.stop()

        asyncio.run(_run())

    def test_sync_already_up_to_date(self, ledger_a, ledger_b):
        """No blocks fetched when B is already at the same height."""
        _make_blocks(ledger_a, 2)
        # Copy all blocks to B
        for i in range(2):
            ledger_b.insert_remote_block(ledger_a.get_block(i, include_tx=True))

        async def _run():
            node_a = OasyceNode(host="127.0.0.1", port=0, node_id="A", ledger=ledger_a)
            await node_a.start()
            port_a = _get_bound_port(node_a)

            node_b = OasyceNode(host="127.0.0.1", port=0, node_id="B", ledger=ledger_b)
            fetched = await node_b.sync_from_peer("127.0.0.1", port_a)
            assert fetched == 0

            await node_a.stop()

        asyncio.run(_run())


# ── Broadcast ────────────────────────────────────────────────────────


class TestBroadcastBlock:
    def test_broadcast_accepted(self, ledger_a, ledger_b):
        """A broadcasts a new block, B receives and stores it."""
        async def _run():
            node_a = OasyceNode(host="127.0.0.1", port=0, node_id="A", ledger=ledger_a)
            node_b = OasyceNode(host="127.0.0.1", port=0, node_id="B", ledger=ledger_b)

            await node_b.start()
            port_b = _get_bound_port(node_b)

            # Register B as a peer of A
            node_a.peers["B"] = PeerInfo(host="127.0.0.1", port=port_b, node_id="B")

            # Create a block on A
            ledger_a.record_tx("register", asset_id="X1", from_addr="sys", to_addr="o1")
            ledger_a.create_block()
            block = ledger_a.get_block(0, include_tx=True)

            # Broadcast
            await node_a.broadcast_block(block)

            # Give B a moment to process
            await asyncio.sleep(0.1)

            assert ledger_b.get_chain_height() == 1
            assert ledger_b.verify_chain() is True

            await node_b.stop()

        asyncio.run(_run())

    def test_broadcast_rejects_fake(self, ledger_a, ledger_b):
        """B rejects a broadcast with tampered data."""
        async def _run():
            node_b = OasyceNode(host="127.0.0.1", port=0, node_id="B", ledger=ledger_b)
            await node_b.start()
            port_b = _get_bound_port(node_b)

            # Create valid block on A then tamper
            ledger_a.record_tx("register", asset_id="X1", from_addr="sys", to_addr="o1")
            ledger_a.create_block()
            block = ledger_a.get_block(0, include_tx=True)
            block["block_hash"] = "bad" * 21 + "b"  # 64 chars

            node_a = OasyceNode(host="127.0.0.1", port=0, node_id="A", ledger=ledger_a)
            node_a.peers["B"] = PeerInfo(host="127.0.0.1", port=port_b, node_id="B")
            await node_a.broadcast_block(block)

            await asyncio.sleep(0.1)
            assert ledger_b.get_chain_height() == 0  # rejected

            await node_b.stop()

        asyncio.run(_run())
