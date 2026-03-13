"""
Tests for the P2P network node layer.
"""

import asyncio
import json
import pytest

from oasyce_plugin.network.node import OasyceNode, PeerInfo
from oasyce_plugin.storage.ledger import Ledger


@pytest.fixture
def ledger(tmp_path):
    db = tmp_path / "test_chain.db"
    return Ledger(str(db))


@pytest.fixture
def node(ledger):
    return OasyceNode(host="127.0.0.1", port=0, node_id="test_node_01", ledger=ledger)


# ── Helpers ──────────────────────────────────────────────────────────

async def _send_msg(host, port, msg):
    """Connect, send a JSON message, read one JSON response."""
    reader, writer = await asyncio.open_connection(host, port)
    writer.write(json.dumps(msg).encode() + b"\n")
    await writer.drain()
    line = await asyncio.wait_for(reader.readline(), timeout=5.0)
    writer.close()
    await writer.wait_closed()
    return json.loads(line.decode())


def _get_bound_port(node: OasyceNode) -> int:
    """Return the actual port the server bound to (useful when port=0)."""
    for sock in node._server.sockets:
        return sock.getsockname()[1]
    raise RuntimeError("No sockets found")


# ── Tests ────────────────────────────────────────────────────────────

class TestNodeLifecycle:
    def test_start_and_stop(self, node):
        async def _run():
            await node.start()
            assert node.is_running
            await node.stop()
            assert not node.is_running

        asyncio.run(_run())

    def test_info_before_start(self, node):
        info = node.info()
        assert info["node_id"] == "test_node_01"
        assert info["running"] is False
        assert info["height"] == 0

    def test_info_after_start(self, node):
        async def _run():
            await node.start()
            info = node.info()
            assert info["running"] is True
            assert info["node_id"] == "test_node_01"
            await node.stop()

        asyncio.run(_run())


class TestPingPong:
    def test_ping_returns_pong(self, node):
        async def _run():
            await node.start()
            port = _get_bound_port(node)
            resp = await _send_msg("127.0.0.1", port, {"type": "ping"})
            assert resp["type"] == "pong"
            assert resp["node_id"] == "test_node_01"
            assert resp["height"] == 0
            await node.stop()

        asyncio.run(_run())

    def test_ping_with_blocks(self, node, ledger):
        async def _run():
            # Create a transaction and mine a block
            ledger.record_tx("register", asset_id="A1", from_addr="sys", to_addr="owner")
            ledger.create_block()

            await node.start()
            port = _get_bound_port(node)
            resp = await _send_msg("127.0.0.1", port, {"type": "ping"})
            assert resp["height"] == 1
            await node.stop()

        asyncio.run(_run())


class TestGetHeight:
    def test_get_height_empty(self, node):
        async def _run():
            await node.start()
            port = _get_bound_port(node)
            resp = await _send_msg("127.0.0.1", port, {"type": "get_height"})
            assert resp["type"] == "height"
            assert resp["height"] == 0
            await node.stop()

        asyncio.run(_run())

    def test_get_height_after_blocks(self, node, ledger):
        async def _run():
            ledger.record_tx("register", asset_id="A1", from_addr="sys", to_addr="o1")
            ledger.create_block()
            ledger.record_tx("buy", asset_id="A1", from_addr="buyer", to_addr="o1", amount=10)
            ledger.create_block()

            await node.start()
            port = _get_bound_port(node)
            resp = await _send_msg("127.0.0.1", port, {"type": "get_height"})
            assert resp["height"] == 2
            await node.stop()

        asyncio.run(_run())


class TestGetBlock:
    def test_get_block_existing(self, node, ledger):
        async def _run():
            ledger.record_tx("register", asset_id="A1", from_addr="sys", to_addr="o1")
            block = ledger.create_block()

            await node.start()
            port = _get_bound_port(node)
            resp = await _send_msg("127.0.0.1", port, {"type": "get_block", "number": 0})
            assert resp["type"] == "block"
            assert resp["block"] is not None
            assert resp["block"]["block_number"] == 0
            assert resp["block"]["block_hash"] == block["block_hash"]
            await node.stop()

        asyncio.run(_run())

    def test_get_block_nonexistent(self, node):
        async def _run():
            await node.start()
            port = _get_bound_port(node)
            resp = await _send_msg("127.0.0.1", port, {"type": "get_block", "number": 999})
            assert resp["type"] == "block"
            assert resp["block"] is None
            await node.stop()

        asyncio.run(_run())


class TestGetPeers:
    def test_get_peers_empty(self, node):
        async def _run():
            await node.start()
            port = _get_bound_port(node)
            resp = await _send_msg("127.0.0.1", port, {"type": "get_peers"})
            assert resp["type"] == "peers"
            assert resp["peers"] == []
            await node.stop()

        asyncio.run(_run())

    def test_get_peers_with_known_peer(self, node):
        async def _run():
            node.peers["peer1"] = PeerInfo(host="10.0.0.1", port=9527, node_id="peer1")
            await node.start()
            port = _get_bound_port(node)
            resp = await _send_msg("127.0.0.1", port, {"type": "get_peers"})
            assert len(resp["peers"]) == 1
            assert resp["peers"][0]["node_id"] == "peer1"
            await node.stop()

        asyncio.run(_run())


class TestNewBlock:
    def test_new_block_ack(self, node):
        async def _run():
            await node.start()
            port = _get_bound_port(node)
            resp = await _send_msg(
                "127.0.0.1", port,
                {"type": "new_block", "block": {"block_number": 42}},
            )
            assert resp["type"] == "ack"
            assert resp["status"] == "rejected"  # invalid block data → rejected
            await node.stop()

        asyncio.run(_run())


class TestUnknownMessage:
    def test_unknown_type(self, node):
        async def _run():
            await node.start()
            port = _get_bound_port(node)
            resp = await _send_msg("127.0.0.1", port, {"type": "foobar"})
            assert resp["type"] == "error"
            await node.stop()

        asyncio.run(_run())


class TestPeerConnection:
    def test_two_nodes_ping(self, ledger, tmp_path):
        """Two local nodes: node A pings node B."""
        async def _run():
            db2 = tmp_path / "chain2.db"
            ledger2 = Ledger(str(db2))

            node_a = OasyceNode(host="127.0.0.1", port=0, node_id="node_A", ledger=ledger)
            node_b = OasyceNode(host="127.0.0.1", port=0, node_id="node_B", ledger=ledger2)

            await node_b.start()
            port_b = _get_bound_port(node_b)

            # node_a connects to node_b
            resp = await node_a.connect_to_peer("127.0.0.1", port_b)
            assert resp["type"] == "pong"
            assert resp["node_id"] == "node_B"

            # node_a should have recorded node_b as a peer
            assert "node_B" in node_a.peers
            assert node_a.peers["node_B"].port == port_b

            await node_b.stop()

        asyncio.run(_run())
