"""
Tests for network persistence: node identity, peer list, and bootstrap.
"""

import asyncio
import json
import pytest

from oasyce_plugin.config import (
    BOOTSTRAP_NODES,
    NetworkConfig,
    load_or_create_node_identity,
    reset_node_identity,
)
from oasyce_plugin.network.node import OasyceNode, PeerInfo
from oasyce_plugin.storage.ledger import Ledger


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
    for sock in node._server.sockets:
        return sock.getsockname()[1]
    raise RuntimeError("No sockets found")


# ── Node Identity Persistence ───────────────────────────────────────

class TestNodeIdentityPersistence:
    def test_create_new_identity(self, tmp_path):
        """First call creates a new identity."""
        priv, pub = load_or_create_node_identity(str(tmp_path))
        assert len(priv) == 64  # 32 bytes hex
        assert len(pub) == 64
        assert (tmp_path / "node_id.json").exists()

    def test_identity_persists_across_loads(self, tmp_path):
        """Second call returns the same identity."""
        priv1, pub1 = load_or_create_node_identity(str(tmp_path))
        priv2, pub2 = load_or_create_node_identity(str(tmp_path))
        assert priv1 == priv2
        assert pub1 == pub2

    def test_identity_file_contents(self, tmp_path):
        """node_id.json contains correct fields."""
        priv, pub = load_or_create_node_identity(str(tmp_path))
        data = json.loads((tmp_path / "node_id.json").read_text())
        assert data["node_id"] == pub
        assert data["private_key"] == priv
        assert "created_at" in data

    def test_reset_identity_changes_keys(self, tmp_path):
        """reset_node_identity generates a new keypair."""
        _priv1, pub1 = load_or_create_node_identity(str(tmp_path))
        _priv2, pub2 = reset_node_identity(str(tmp_path))
        assert pub1 != pub2  # new identity

    def test_reset_identity_persists(self, tmp_path):
        """After reset, loading returns the new identity."""
        load_or_create_node_identity(str(tmp_path))
        _priv_new, pub_new = reset_node_identity(str(tmp_path))
        _priv_loaded, pub_loaded = load_or_create_node_identity(str(tmp_path))
        assert pub_loaded == pub_new

    def test_creates_parent_dirs(self, tmp_path):
        """Identity creation works even if nested dirs don't exist."""
        deep = tmp_path / "a" / "b" / "c"
        priv, pub = load_or_create_node_identity(str(deep))
        assert len(pub) == 64
        assert (deep / "node_id.json").exists()


# ── Peer List Persistence ───────────────────────────────────────────

class TestPeerListPersistence:
    def test_add_peer_creates_file(self, tmp_path):
        """add_peer() persists to peers.json."""
        ledger = Ledger(str(tmp_path / "chain.db"))
        node = OasyceNode(
            host="127.0.0.1", port=0, node_id="test_01",
            ledger=ledger, data_dir=str(tmp_path),
        )
        node.add_peer("peer_A", "10.0.0.1", 9527)

        peers_path = tmp_path / "peers.json"
        assert peers_path.exists()
        data = json.loads(peers_path.read_text())
        assert len(data) == 1
        assert data[0]["node_id"] == "peer_A"
        assert data[0]["host"] == "10.0.0.1"
        assert data[0]["port"] == 9527

    def test_peers_survive_restart(self, tmp_path):
        """Peers saved by node A are loaded by node B using same data_dir."""
        ledger = Ledger(str(tmp_path / "chain.db"))

        # Node A adds peers
        node_a = OasyceNode(
            host="127.0.0.1", port=0, node_id="test_01",
            ledger=ledger, data_dir=str(tmp_path),
        )
        node_a.add_peer("peer_X", "192.168.1.1", 9527)
        node_a.add_peer("peer_Y", "192.168.1.2", 9528)
        assert len(node_a.peers) == 2

        # Node B loads same data_dir (simulates restart)
        node_b = OasyceNode(
            host="127.0.0.1", port=0, node_id="test_01",
            ledger=ledger, data_dir=str(tmp_path),
        )
        assert len(node_b.peers) == 2
        assert "peer_X" in node_b.peers
        assert "peer_Y" in node_b.peers
        assert node_b.peers["peer_X"].host == "192.168.1.1"

    def test_remove_peer_updates_file(self, tmp_path):
        """remove_peer() updates peers.json."""
        ledger = Ledger(str(tmp_path / "chain.db"))
        node = OasyceNode(
            host="127.0.0.1", port=0, node_id="test_01",
            ledger=ledger, data_dir=str(tmp_path),
        )
        node.add_peer("peer_A", "10.0.0.1", 9527)
        node.add_peer("peer_B", "10.0.0.2", 9528)
        assert len(node.peers) == 2

        removed = node.remove_peer("peer_A")
        assert removed is True
        assert "peer_A" not in node.peers

        # Verify file was updated
        data = json.loads((tmp_path / "peers.json").read_text())
        assert len(data) == 1
        assert data[0]["node_id"] == "peer_B"

    def test_remove_nonexistent_peer(self, tmp_path):
        """remove_peer() returns False for unknown peer."""
        ledger = Ledger(str(tmp_path / "chain.db"))
        node = OasyceNode(
            host="127.0.0.1", port=0, node_id="test_01",
            ledger=ledger, data_dir=str(tmp_path),
        )
        assert node.remove_peer("ghost") is False

    def test_no_data_dir_skips_persistence(self, tmp_path):
        """Without data_dir, peers are memory-only (no file created)."""
        ledger = Ledger(str(tmp_path / "chain.db"))
        node = OasyceNode(
            host="127.0.0.1", port=0, node_id="test_01",
            ledger=ledger,  # no data_dir
        )
        node.add_peer("peer_A", "10.0.0.1", 9527)
        assert "peer_A" in node.peers
        assert not (tmp_path / "peers.json").exists()

    def test_connect_to_peer_persists(self, tmp_path):
        """connect_to_peer() should save the peer to disk."""
        async def _run():
            db1 = tmp_path / "chain1.db"
            db2 = tmp_path / "chain2.db"
            ledger1 = Ledger(str(db1))
            ledger2 = Ledger(str(db2))

            data_dir = str(tmp_path / "node_data")

            node_a = OasyceNode(
                host="127.0.0.1", port=0, node_id="node_A",
                ledger=ledger1, data_dir=data_dir,
            )
            node_b = OasyceNode(
                host="127.0.0.1", port=0, node_id="node_B",
                ledger=ledger2,
            )

            await node_b.start()
            port_b = _get_bound_port(node_b)

            resp = await node_a.connect_to_peer("127.0.0.1", port_b)
            assert resp["node_id"] == "node_B"
            assert "node_B" in node_a.peers

            # Verify persisted
            from pathlib import Path
            peers_path = Path(data_dir) / "peers.json"
            assert peers_path.exists()
            data = json.loads(peers_path.read_text())
            assert any(p["node_id"] == "node_B" for p in data)

            await node_b.stop()

        asyncio.run(_run())

    def test_corrupt_peers_file_handled(self, tmp_path):
        """Corrupt peers.json doesn't crash; starts with empty peers."""
        (tmp_path / "peers.json").write_text("not valid json!!")
        ledger = Ledger(str(tmp_path / "chain.db"))
        node = OasyceNode(
            host="127.0.0.1", port=0, node_id="test_01",
            ledger=ledger, data_dir=str(tmp_path),
        )
        assert len(node.peers) == 0


# ── Bootstrap Configuration ─────────────────────────────────────────

class TestBootstrapConfig:
    def test_bootstrap_list_exists(self):
        """BOOTSTRAP_NODES is a non-empty list."""
        assert isinstance(BOOTSTRAP_NODES, list)
        assert len(BOOTSTRAP_NODES) > 0

    def test_bootstrap_entry_format(self):
        """Each entry has host, port, node_id."""
        for entry in BOOTSTRAP_NODES:
            assert "host" in entry
            assert "port" in entry
            assert "node_id" in entry


# ── NetworkConfig ────────────────────────────────────────────────────

class TestNetworkConfig:
    def test_defaults(self):
        """NetworkConfig has sensible defaults."""
        cfg = NetworkConfig()
        assert cfg.listen_host == "0.0.0.0"
        assert cfg.listen_port == 9527
        assert cfg.public_host is None
        assert cfg.public_port is None
        assert cfg.use_stun is False

    def test_custom_values(self):
        """NetworkConfig accepts custom values."""
        cfg = NetworkConfig(
            listen_host="127.0.0.1",
            listen_port=8080,
            public_host="my.node.com",
            public_port=9527,
            use_stun=True,
        )
        assert cfg.listen_host == "127.0.0.1"
        assert cfg.listen_port == 8080
        assert cfg.public_host == "my.node.com"
        assert cfg.use_stun is True


# ── Bootstrap Connection (integration) ──────────────────────────────

class TestBootstrapConnection:
    def test_bootstrap_graceful_failure(self, tmp_path):
        """start(bootstrap=True) doesn't crash when bootstrap unreachable."""
        async def _run():
            ledger = Ledger(str(tmp_path / "chain.db"))
            node = OasyceNode(
                host="127.0.0.1", port=0, node_id="test_boot",
                ledger=ledger, data_dir=str(tmp_path),
            )
            # This should not raise even though bootstrap is unreachable
            await node.start(bootstrap=True)
            assert node.is_running
            await node.stop()

        asyncio.run(_run())

    def test_bootstrap_discovers_peers(self, tmp_path):
        """Bootstrap node returns peer list that gets connected."""
        async def _run():
            db1 = tmp_path / "chain1.db"
            db2 = tmp_path / "chain2.db"
            db3 = tmp_path / "chain3.db"
            ledger1 = Ledger(str(db1))
            ledger2 = Ledger(str(db2))
            ledger3 = Ledger(str(db3))

            # Node B and C are running
            node_b = OasyceNode(
                host="127.0.0.1", port=0, node_id="node_B", ledger=ledger2,
            )
            node_c = OasyceNode(
                host="127.0.0.1", port=0, node_id="node_C", ledger=ledger3,
            )
            await node_b.start()
            await node_c.start()
            port_b = _get_bound_port(node_b)
            port_c = _get_bound_port(node_c)

            # Node B knows about node C
            node_b.add_peer("node_C", "127.0.0.1", port_c)

            # Node A connects to node B as "bootstrap" manually
            node_a = OasyceNode(
                host="127.0.0.1", port=0, node_id="node_A", ledger=ledger1,
            )
            await node_a.start()

            # Simulate bootstrap: connect to B, then discover C via get_peers
            await node_a.connect_to_peer("127.0.0.1", port_b)
            assert "node_B" in node_a.peers

            # Ask B for peers
            resp = await node_a._request("127.0.0.1", port_b, {"type": "get_peers"})
            for p in resp.get("peers", []):
                if p.get("node_id") != node_a.node_id:
                    await node_a.connect_to_peer(p["host"], p["port"])

            assert "node_C" in node_a.peers

            await node_a.stop()
            await node_b.stop()
            await node_c.stop()

        asyncio.run(_run())


# ── Reconnection After Restart ──────────────────────────────────────

class TestReconnection:
    def test_reconnect_saved_peers_after_restart(self, tmp_path):
        """Node A connects to B, restarts, auto-reconnects to B."""
        async def _run():
            db1 = tmp_path / "chain1.db"
            db2 = tmp_path / "chain2.db"
            ledger1 = Ledger(str(db1))
            ledger2 = Ledger(str(db2))
            data_dir_a = str(tmp_path / "node_a_data")

            # Node B stays running the whole time
            node_b = OasyceNode(
                host="127.0.0.1", port=0, node_id="node_B", ledger=ledger2,
            )
            await node_b.start()
            port_b = _get_bound_port(node_b)

            # Node A connects to B (first run)
            node_a1 = OasyceNode(
                host="127.0.0.1", port=0, node_id="node_A",
                ledger=ledger1, data_dir=data_dir_a,
            )
            await node_a1.start()
            await node_a1.connect_to_peer("127.0.0.1", port_b)
            assert "node_B" in node_a1.peers
            await node_a1.stop()

            # Node A restarts (second run) — peers should be loaded from disk
            node_a2 = OasyceNode(
                host="127.0.0.1", port=0, node_id="node_A",
                ledger=ledger1, data_dir=data_dir_a,
            )
            # Peers loaded from disk in __init__
            assert "node_B" in node_a2.peers

            # Start with reconnection
            await node_a2.start(bootstrap=True)
            # After reconnection, node_B should still be in peers with updated last_seen
            assert "node_B" in node_a2.peers

            await node_a2.stop()
            await node_b.stop()

        asyncio.run(_run())
