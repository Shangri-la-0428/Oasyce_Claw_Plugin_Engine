"""
Tests for Phase 6: Simple Consensus — timestamp validation, longest chain rule,
chain reorg, rate limiting, and fork convergence.
"""

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from oasyce_plugin.network.node import OasyceNode, PeerInfo
from oasyce_plugin.storage.ledger import Ledger


@pytest.fixture
def ledger_a(tmp_path):
    return Ledger(str(tmp_path / "a.db"))


@pytest.fixture
def ledger_b(tmp_path):
    return Ledger(str(tmp_path / "b.db"))


@pytest.fixture
def ledger_c(tmp_path):
    return Ledger(str(tmp_path / "c.db"))


def _make_blocks(ledger, n=3, prefix="asset"):
    """Create n blocks with one tx each."""
    for i in range(n):
        ledger.record_tx("register", asset_id=f"{prefix}_{i}", from_addr="sys", to_addr="owner")
        ledger.create_block()


def _get_bound_port(node: OasyceNode) -> int:
    for sock in node._server.sockets:
        return sock.getsockname()[1]
    raise RuntimeError("No sockets")


# ── 6a: Timestamp validation ─────────────────────────────────────────


class TestTimestampValidation:
    def test_reject_future_timestamp(self, ledger_a, ledger_b):
        """Block with timestamp > now + 120s is rejected."""
        ledger_a.record_tx("register", asset_id="A1", from_addr="sys", to_addr="o1")
        ledger_a.create_block()
        block = ledger_a.get_block(0, include_tx=True)

        # Set timestamp 5 minutes in the future
        future_ts = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        # Recompute hash with new timestamp
        new_hash = ledger_a._block_hash(block["prev_hash"], block["merkle_root"], future_ts, block["nonce"])
        block["timestamp"] = future_ts
        block["block_hash"] = new_hash

        assert ledger_b.insert_remote_block(block) is False
        assert ledger_b.get_chain_height() == 0

    def test_reject_timestamp_before_previous(self, ledger_a, ledger_b):
        """Block with timestamp earlier than its predecessor is rejected."""
        _make_blocks(ledger_a, 2)

        # Copy block 0 to B
        block0 = ledger_a.get_block(0, include_tx=True)
        ledger_b.insert_remote_block(block0)

        # Get block 1 and set its timestamp before block 0
        block1 = ledger_a.get_block(1, include_tx=True)
        # Parse block 0 timestamp and go 1 hour before
        b0_ts = datetime.fromisoformat(block0["timestamp"])
        if b0_ts.tzinfo is None:
            b0_ts = b0_ts.replace(tzinfo=timezone.utc)
        old_ts = (b0_ts - timedelta(hours=1)).isoformat()
        new_hash = ledger_a._block_hash(block1["prev_hash"], block1["merkle_root"], old_ts, block1["nonce"])
        block1["timestamp"] = old_ts
        block1["block_hash"] = new_hash

        assert ledger_b.insert_remote_block(block1) is False
        assert ledger_b.get_chain_height() == 1

    def test_accept_normal_timestamp(self, ledger_a, ledger_b):
        """Block with a valid timestamp within tolerance is accepted."""
        ledger_a.record_tx("register", asset_id="A1", from_addr="sys", to_addr="o1")
        ledger_a.create_block()
        block = ledger_a.get_block(0, include_tx=True)

        assert ledger_b.insert_remote_block(block) is True
        assert ledger_b.get_chain_height() == 1
        assert ledger_b.verify_chain() is True


# ── 6b: Longest chain + reorg ────────────────────────────────────────


class TestLongestChainReorg:
    def test_longer_chain_wins(self, ledger_a, ledger_b):
        """A has 3 blocks, B has 5 blocks. A reorgs to B's chain."""
        _make_blocks(ledger_a, 3, prefix="a")
        _make_blocks(ledger_b, 5, prefix="b")

        assert ledger_a.get_chain_height() == 3
        assert ledger_b.get_chain_height() == 5

        # Get B's full chain
        b_chain = ledger_b.get_chain_from(0)
        assert len(b_chain) == 5

        # A attempts reorg with B's chain
        result = ledger_a.attempt_reorg(b_chain)
        assert result is True
        assert ledger_a.get_chain_height() == 5
        assert ledger_a.verify_chain() is True

        # Verify A now has B's blocks
        for i in range(5):
            a_block = ledger_a.get_block(i)
            b_block = ledger_b.get_block(i)
            assert a_block["block_hash"] == b_block["block_hash"]

    def test_shorter_chain_rejected(self, ledger_a, ledger_b):
        """Reorg with a shorter or equal chain is rejected."""
        _make_blocks(ledger_a, 5, prefix="a")
        _make_blocks(ledger_b, 3, prefix="b")

        b_chain = ledger_b.get_chain_from(0)
        result = ledger_a.attempt_reorg(b_chain)
        assert result is False
        assert ledger_a.get_chain_height() == 5

    def test_invalid_chain_rejected(self, ledger_a, ledger_b):
        """Reorg with a chain containing invalid blocks is rejected."""
        _make_blocks(ledger_a, 3, prefix="a")
        _make_blocks(ledger_b, 5, prefix="b")

        b_chain = ledger_b.get_chain_from(0)
        # Tamper with one block's hash
        b_chain[2]["block_hash"] = "deadbeef" * 8

        result = ledger_a.attempt_reorg(b_chain)
        assert result is False
        assert ledger_a.get_chain_height() == 3  # unchanged

    def test_reorg_depth_limit(self, ledger_a, ledger_b):
        """Reorg deeper than MAX_REORG_DEPTH (10) is rejected."""
        _make_blocks(ledger_a, 12, prefix="a")
        _make_blocks(ledger_b, 15, prefix="b")

        assert ledger_a.get_chain_height() == 12
        assert ledger_b.get_chain_height() == 15

        b_chain = ledger_b.get_chain_from(0)
        result = ledger_a.attempt_reorg(b_chain)
        assert result is False  # would roll back 12 blocks > 10
        assert ledger_a.get_chain_height() == 12

    def test_network_reorg_longer_chain(self, ledger_a, ledger_b):
        """Over network: A has 3 blocks, B has 5. A syncs and reorgs to B's chain."""
        _make_blocks(ledger_a, 3, prefix="a")
        _make_blocks(ledger_b, 5, prefix="b")

        async def _run():
            node_b = OasyceNode(host="127.0.0.1", port=0, node_id="B", ledger=ledger_b)
            await node_b.start()
            port_b = _get_bound_port(node_b)

            node_a = OasyceNode(host="127.0.0.1", port=0, node_id="A", ledger=ledger_a)
            result = await node_a.sync_chain_and_reorg("127.0.0.1", port_b)
            assert result is True
            assert ledger_a.get_chain_height() == 5
            assert ledger_a.verify_chain() is True

            await node_b.stop()

        asyncio.run(_run())

    def test_get_chain_protocol(self, ledger_a):
        """get_chain message returns blocks from specified height."""
        _make_blocks(ledger_a, 4)

        async def _run():
            node_a = OasyceNode(host="127.0.0.1", port=0, node_id="A", ledger=ledger_a)
            await node_a.start()
            port_a = _get_bound_port(node_a)

            node_b = OasyceNode(host="127.0.0.1", port=0, node_id="B")
            resp = await node_b._request("127.0.0.1", port_a, {"type": "get_chain", "start": 2})
            assert resp["type"] == "chain"
            assert len(resp["blocks"]) == 2
            assert resp["blocks"][0]["block_number"] == 2

            await node_a.stop()

        asyncio.run(_run())


# ── 6c: Rate limiting ────────────────────────────────────────────────


class TestRateLimiting:
    def test_rate_limit_excess_blocks_dropped(self, ledger_a, ledger_b):
        """Peer sending > 5 new_block messages in 10s gets rate-limited."""
        # Create blocks on A
        _make_blocks(ledger_a, 7, prefix="rl")

        async def _run():
            node_b = OasyceNode(host="127.0.0.1", port=0, node_id="B", ledger=ledger_b)
            await node_b.start()
            port_b = _get_bound_port(node_b)

            # Send 7 new_block messages over a SINGLE connection (same peer_key)
            reader, writer = await asyncio.open_connection("127.0.0.1", port_b)
            results = []
            for i in range(7):
                block = ledger_a.get_block(i, include_tx=True)
                msg = {"type": "new_block", "block": block}
                writer.write(json.dumps(msg).encode() + b"\n")
                await writer.drain()
                line = await asyncio.wait_for(reader.readline(), timeout=5.0)
                resp = json.loads(line.decode())
                results.append(resp.get("status"))

            writer.close()
            await writer.wait_closed()

            # First 5 should be accepted, 6th and 7th rate-limited
            rate_limited_count = results.count("rate_limited")
            assert rate_limited_count >= 2, f"Expected at least 2 rate_limited, got {results}"

            await node_b.stop()

        asyncio.run(_run())

    def test_rate_limit_resets_after_window(self, ledger_a, ledger_b):
        """After the rate limit window passes, new blocks are accepted again."""
        node = OasyceNode(host="127.0.0.1", port=0, node_id="B", ledger=ledger_b)

        # Simulate 5 messages at t=0
        peer_key = "test_peer"
        now = time.time()
        node._block_rate[peer_key] = [now - 15.0] * 5  # all expired

        # Should be within limits since all entries are outside window
        assert node._check_rate_limit(peer_key) is True


# ── Fork convergence ─────────────────────────────────────────────────


class TestForkConvergence:
    def test_fork_detection_same_height_different_hash(self, ledger_a, ledger_b):
        """Two nodes produce different blocks at same height; fork is detected."""
        _make_blocks(ledger_a, 2, prefix="a")
        _make_blocks(ledger_b, 2, prefix="b")

        async def _run():
            node_b = OasyceNode(host="127.0.0.1", port=0, node_id="B", ledger=ledger_b)
            await node_b.start()
            port_b = _get_bound_port(node_b)

            # A sends its block 0 to B — B already has a different block 0
            block0_a = ledger_a.get_block(0, include_tx=True)
            node_a = OasyceNode(host="127.0.0.1", port=0, node_id="A", ledger=ledger_a)
            resp = await node_a._request("127.0.0.1", port_b, {
                "type": "new_block",
                "block": block0_a,
            })
            assert resp["status"] == "fork_detected"

            await node_b.stop()

        asyncio.run(_run())

    def test_two_nodes_converge_to_longer_chain(self, ledger_a, ledger_b):
        """Two nodes with different chains converge: shorter adopts the longer."""
        _make_blocks(ledger_a, 3, prefix="a")
        _make_blocks(ledger_b, 5, prefix="b")

        async def _run():
            # B serves its chain
            node_b = OasyceNode(host="127.0.0.1", port=0, node_id="B", ledger=ledger_b)
            await node_b.start()
            port_b = _get_bound_port(node_b)

            # A detects fork, then syncs and reorgs
            node_a = OasyceNode(host="127.0.0.1", port=0, node_id="A", ledger=ledger_a)
            reorged = await node_a.sync_chain_and_reorg("127.0.0.1", port_b)
            assert reorged is True

            # Both chains now identical
            assert ledger_a.get_chain_height() == ledger_b.get_chain_height()
            for i in range(5):
                assert ledger_a.get_block(i)["block_hash"] == ledger_b.get_block(i)["block_hash"]

            await node_b.stop()

        asyncio.run(_run())


# ── evaluate_chain ────────────────────────────────────────────────────


class TestEvaluateChain:
    def test_valid_chain(self, ledger_a):
        """evaluate_chain returns True for a valid chain."""
        _make_blocks(ledger_a, 3)
        chain = ledger_a.get_chain_from(0)
        assert ledger_a.evaluate_chain(chain) is True

    def test_empty_chain(self, ledger_a):
        """evaluate_chain returns True for an empty chain."""
        assert ledger_a.evaluate_chain([]) is True

    def test_tampered_block(self, ledger_a):
        """evaluate_chain returns False when a block hash is tampered."""
        _make_blocks(ledger_a, 3)
        chain = ledger_a.get_chain_from(0)
        chain[1]["block_hash"] = "bad" * 21 + "b"
        assert ledger_a.evaluate_chain(chain) is False
