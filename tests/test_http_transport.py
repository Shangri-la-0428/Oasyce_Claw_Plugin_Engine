"""
Tests for HTTP JSON sync transport.

Covers:
  - SyncServer serves peer info and blocks
  - HTTPPeerTransport fetches peer info and blocks
  - Full sync cycle: server ↔ client ↔ engine
  - Multi-node testnet simulation
  - Error handling (bad requests, unreachable peers)
  - Block production + sync integration
"""

import json
import time
import threading
from unittest.mock import patch
from urllib.error import URLError

import pytest

from oasyce_plugin.consensus import ConsensusEngine
from oasyce_plugin.consensus.core.types import Operation, OperationType, to_units
from oasyce_plugin.consensus.network.sync_protocol import (
    Block, GetBlocksRequest, GetBlocksResponse, GetPeerInfoResponse,
    make_genesis_block, compute_merkle_root, GENESIS_PREV_HASH,
)
from oasyce_plugin.consensus.network.block_sync import (
    InMemoryPeer, sync_from_peer, sync_from_network, verify_block,
)
from oasyce_plugin.consensus.network.http_transport import (
    HTTPPeerTransport, SyncServer,
)


# ── Helpers ───────────────────────────────────────────────────────


def _make_engine(**kw):
    return ConsensusEngine(db_path=":memory:", **kw)


def _make_block(chain_id: str, number: int, prev_hash: str,
                timestamp: int = 0, operations=()) -> Block:
    ops_tuple = tuple(operations)
    merkle = compute_merkle_root(ops_tuple)
    return Block(
        chain_id=chain_id,
        block_number=number,
        prev_hash=prev_hash,
        merkle_root=merkle,
        timestamp=timestamp or (1000 + number),
        operations=ops_tuple,
    )


def _make_chain(chain_id: str, length: int) -> list:
    """Build a valid chain of `length` blocks (including genesis)."""
    genesis = make_genesis_block(chain_id)
    blocks = [genesis]
    for i in range(1, length):
        b = _make_block(chain_id, i, blocks[-1].block_hash, timestamp=1000 + i)
        blocks.append(b)
    return blocks


def _free_port():
    """Find a free TCP port."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── SyncServer Tests ─────────────────────────────────────────────


class TestSyncServer:
    def test_server_starts_and_stops(self):
        engine = _make_engine()
        port = _free_port()
        server = SyncServer(engine, host="127.0.0.1", port=port)
        server.start()
        try:
            # Health check
            transport = HTTPPeerTransport(f"http://127.0.0.1:{port}")
            info = transport.get_peer_info()
            assert info.chain_id == "oasyce-testnet-1"
        finally:
            server.stop()
            engine.close()

    def test_info_endpoint_returns_chain_info(self):
        engine = _make_engine()
        port = _free_port()
        chain_id = engine.chain_id
        genesis = make_genesis_block(chain_id)

        server = SyncServer(engine, host="127.0.0.1", port=port,
                            block_store=[genesis])
        server.start()
        try:
            transport = HTTPPeerTransport(f"http://127.0.0.1:{port}")
            info = transport.get_peer_info()
            assert info.chain_id == chain_id
            assert info.height == 0  # genesis is block 0
            assert info.genesis_hash == genesis.block_hash
        finally:
            server.stop()
            engine.close()

    def test_info_endpoint_empty_store(self):
        engine = _make_engine()
        port = _free_port()
        server = SyncServer(engine, host="127.0.0.1", port=port)
        server.start()
        try:
            transport = HTTPPeerTransport(f"http://127.0.0.1:{port}")
            info = transport.get_peer_info()
            assert info.height == -1  # no blocks
        finally:
            server.stop()
            engine.close()

    def test_blocks_endpoint_returns_requested_range(self):
        engine = _make_engine()
        port = _free_port()
        chain_id = engine.chain_id
        blocks = _make_chain(chain_id, 5)

        server = SyncServer(engine, host="127.0.0.1", port=port,
                            block_store=blocks)
        server.start()
        try:
            transport = HTTPPeerTransport(f"http://127.0.0.1:{port}")
            req = GetBlocksRequest(from_height=1, to_height=3)
            resp = transport.get_blocks(req)
            assert len(resp.blocks) == 3
            assert resp.blocks[0].block_number == 1
            assert resp.blocks[-1].block_number == 3
        finally:
            server.stop()
            engine.close()

    def test_blocks_endpoint_respects_limit(self):
        engine = _make_engine()
        port = _free_port()
        blocks = _make_chain(engine.chain_id, 10)

        server = SyncServer(engine, host="127.0.0.1", port=port,
                            block_store=blocks)
        server.start()
        try:
            transport = HTTPPeerTransport(f"http://127.0.0.1:{port}")
            req = GetBlocksRequest(from_height=0, to_height=9, limit=3)
            resp = transport.get_blocks(req)
            assert len(resp.blocks) == 3
        finally:
            server.stop()
            engine.close()

    def test_blocks_endpoint_empty_range(self):
        engine = _make_engine()
        port = _free_port()
        blocks = _make_chain(engine.chain_id, 3)

        server = SyncServer(engine, host="127.0.0.1", port=port,
                            block_store=blocks)
        server.start()
        try:
            transport = HTTPPeerTransport(f"http://127.0.0.1:{port}")
            req = GetBlocksRequest(from_height=100, to_height=200)
            resp = transport.get_blocks(req)
            assert len(resp.blocks) == 0
        finally:
            server.stop()
            engine.close()

    def test_add_block_updates_height(self):
        engine = _make_engine()
        port = _free_port()
        chain_id = engine.chain_id
        genesis = make_genesis_block(chain_id)

        server = SyncServer(engine, host="127.0.0.1", port=port,
                            block_store=[genesis])
        server.start()
        try:
            transport = HTTPPeerTransport(f"http://127.0.0.1:{port}")

            info1 = transport.get_peer_info()
            assert info1.height == 0

            block1 = _make_block(chain_id, 1, genesis.block_hash)
            server.add_block(block1)

            info2 = transport.get_peer_info()
            assert info2.height == 1
        finally:
            server.stop()
            engine.close()


# ── HTTPPeerTransport Tests ──────────────────────────────────────


class TestHTTPPeerTransport:
    def test_transport_satisfies_peer_protocol(self):
        """HTTPPeerTransport has address, get_peer_info, get_blocks."""
        transport = HTTPPeerTransport("http://127.0.0.1:9999")
        assert transport.address == "http://127.0.0.1:9999"
        assert hasattr(transport, "get_peer_info")
        assert hasattr(transport, "get_blocks")

    def test_transport_strips_trailing_slash(self):
        transport = HTTPPeerTransport("http://example.com:8080/")
        assert transport.address == "http://example.com:8080"

    def test_transport_repr(self):
        transport = HTTPPeerTransport("http://localhost:9528")
        assert "localhost:9528" in repr(transport)

    def test_unreachable_peer_raises(self):
        transport = HTTPPeerTransport("http://127.0.0.1:1", timeout=1.0)
        with pytest.raises((URLError, OSError, ConnectionError)):
            transport.get_peer_info()


# ── Full Sync Integration ────────────────────────────────────────


class TestHTTPSync:
    def test_sync_from_http_peer(self):
        """Sync blocks from an HTTP server using sync_from_peer."""
        engine = _make_engine()
        port = _free_port()
        chain_id = engine.chain_id
        genesis_hash = engine.get_genesis_hash()
        blocks = _make_chain(chain_id, 5)

        server = SyncServer(engine, host="127.0.0.1", port=port,
                            block_store=blocks)
        server.start()
        try:
            transport = HTTPPeerTransport(f"http://127.0.0.1:{port}")
            result = sync_from_peer(
                transport, engine, local_height=-1,
                local_genesis_hash=genesis_hash,
            )
            assert result.ok
            assert result.blocks_synced >= 4  # blocks 1-4 (genesis doesn't count)
        finally:
            server.stop()
            engine.close()

    def test_sync_from_network_picks_best_peer(self):
        """sync_from_network picks the peer with the most blocks."""
        engine = _make_engine()
        chain_id = engine.chain_id
        genesis_hash = engine.get_genesis_hash()

        port1 = _free_port()
        port2 = _free_port()
        blocks_short = _make_chain(chain_id, 3)
        blocks_long = _make_chain(chain_id, 8)

        server1 = SyncServer(engine, host="127.0.0.1", port=port1,
                             block_store=blocks_short)
        # Use a separate engine for server2 to avoid DB conflicts
        engine2 = _make_engine()
        server2 = SyncServer(engine2, host="127.0.0.1", port=port2,
                             block_store=blocks_long)
        server1.start()
        server2.start()
        try:
            peers = [
                HTTPPeerTransport(f"http://127.0.0.1:{port1}"),
                HTTPPeerTransport(f"http://127.0.0.1:{port2}"),
            ]
            # Fresh engine for syncing
            sync_engine = _make_engine()
            result = sync_from_network(
                peers, sync_engine, local_height=-1,
                local_genesis_hash=genesis_hash,
            )
            assert result.ok
            assert result.blocks_synced >= 7  # from the longer chain
            sync_engine.close()
        finally:
            server1.stop()
            server2.stop()
            engine.close()
            engine2.close()

    def test_genesis_mismatch_rejects_peer(self):
        """Peer with different genesis hash is rejected."""
        engine = _make_engine()
        port = _free_port()
        chain_id = engine.chain_id
        blocks = _make_chain(chain_id, 3)

        server = SyncServer(engine, host="127.0.0.1", port=port,
                            block_store=blocks)
        server.start()
        try:
            transport = HTTPPeerTransport(f"http://127.0.0.1:{port}")
            result = sync_from_peer(
                transport, engine, local_height=-1,
                local_genesis_hash="wrong_hash_" + "0" * 54,
            )
            assert not result.ok
            assert "genesis" in result.status.value.lower() or "mismatch" in result.error.lower()
        finally:
            server.stop()
            engine.close()

    def test_already_synced(self):
        """No-op when local height >= peer height."""
        engine = _make_engine()
        port = _free_port()
        chain_id = engine.chain_id
        genesis_hash = engine.get_genesis_hash()
        blocks = _make_chain(chain_id, 3)

        server = SyncServer(engine, host="127.0.0.1", port=port,
                            block_store=blocks)
        server.start()
        try:
            transport = HTTPPeerTransport(f"http://127.0.0.1:{port}")
            result = sync_from_peer(
                transport, engine, local_height=10,
                local_genesis_hash=genesis_hash,
            )
            assert result.ok
            assert result.blocks_synced == 0
        finally:
            server.stop()
            engine.close()


# ── Multi-Node Simulation ────────────────────────────────────────


class TestMultiNode:
    def test_two_node_sync(self):
        """Node A produces blocks, Node B syncs via HTTP."""
        chain_id = "oasyce-testnet-1"

        # Node A: produces blocks
        engine_a = _make_engine()
        port_a = _free_port()
        blocks = _make_chain(chain_id, 6)
        server_a = SyncServer(engine_a, host="127.0.0.1", port=port_a,
                              block_store=blocks)
        server_a.start()

        # Node B: syncs from A
        engine_b = _make_engine()
        try:
            peer_a = HTTPPeerTransport(f"http://127.0.0.1:{port_a}")
            result = engine_b.sync_from_peers(
                [peer_a], local_height=-1,
            )
            assert result["ok"] or result["status"] == "success"
            assert result["blocks_synced"] >= 5
        finally:
            server_a.stop()
            engine_a.close()
            engine_b.close()

    def test_three_node_convergence(self):
        """Three nodes with different heights converge to longest chain."""
        chain_id = "oasyce-testnet-1"

        blocks_3 = _make_chain(chain_id, 3)
        blocks_5 = _make_chain(chain_id, 5)
        blocks_10 = _make_chain(chain_id, 10)

        engines = [_make_engine() for _ in range(3)]
        ports = [_free_port() for _ in range(3)]
        servers = [
            SyncServer(engines[0], host="127.0.0.1", port=ports[0],
                       block_store=blocks_3),
            SyncServer(engines[1], host="127.0.0.1", port=ports[1],
                       block_store=blocks_5),
            SyncServer(engines[2], host="127.0.0.1", port=ports[2],
                       block_store=blocks_10),
        ]
        for s in servers:
            s.start()

        try:
            peers = [HTTPPeerTransport(f"http://127.0.0.1:{p}") for p in ports]

            # Fresh node syncs from all three → should get 10-block chain
            fresh = _make_engine()
            result = sync_from_network(
                peers, fresh, local_height=-1,
                local_genesis_hash=fresh.get_genesis_hash(),
            )
            assert result.ok
            assert result.blocks_synced >= 9
            fresh.close()
        finally:
            for s in servers:
                s.stop()
            for e in engines:
                e.close()

    def test_block_with_operations_syncs_correctly(self):
        """Blocks containing operations serialize/deserialize through HTTP."""
        chain_id = "oasyce-testnet-1"
        engine = _make_engine()
        port = _free_port()

        genesis = make_genesis_block(chain_id)
        op = Operation(
            op_type=OperationType.REGISTER,
            validator_id="val_001",
            amount=to_units(100),
            commission_rate=1000,
        )
        merkle = compute_merkle_root((op,))
        block1 = Block(
            chain_id=chain_id,
            block_number=1,
            prev_hash=genesis.block_hash,
            merkle_root=merkle,
            timestamp=2000,
            operations=(op,),
        )

        server = SyncServer(engine, host="127.0.0.1", port=port,
                            block_store=[genesis, block1])
        server.start()
        try:
            transport = HTTPPeerTransport(f"http://127.0.0.1:{port}")
            resp = transport.get_blocks(GetBlocksRequest(
                from_height=1, to_height=1,
            ))
            assert len(resp.blocks) == 1
            synced = resp.blocks[0]
            assert synced.block_number == 1
            assert len(synced.operations) == 1
            assert synced.operations[0].op_type == OperationType.REGISTER
            assert synced.operations[0].amount == to_units(100)
            # Verify hash integrity survives serialization round-trip
            assert synced.block_hash == block1.block_hash
        finally:
            server.stop()
            engine.close()


# ── Server Edge Cases ────────────────────────────────────────────


class TestServerEdgeCases:
    def test_404_on_unknown_path(self):
        engine = _make_engine()
        port = _free_port()
        server = SyncServer(engine, host="127.0.0.1", port=port)
        server.start()
        try:
            from urllib.request import urlopen
            from urllib.error import HTTPError
            with pytest.raises(HTTPError) as exc_info:
                urlopen(f"http://127.0.0.1:{port}/unknown", timeout=3)
            assert exc_info.value.code == 404
        finally:
            server.stop()
            engine.close()

    def test_health_endpoint(self):
        engine = _make_engine()
        port = _free_port()
        server = SyncServer(engine, host="127.0.0.1", port=port)
        server.start()
        try:
            from urllib.request import urlopen
            resp = urlopen(f"http://127.0.0.1:{port}/sync/health", timeout=3)
            data = json.loads(resp.read())
            assert data["ok"] is True
        finally:
            server.stop()
            engine.close()

    def test_concurrent_requests(self):
        """Server handles multiple concurrent requests."""
        engine = _make_engine()
        port = _free_port()
        blocks = _make_chain(engine.chain_id, 20)
        server = SyncServer(engine, host="127.0.0.1", port=port,
                            block_store=blocks)
        server.start()

        results = []
        errors = []

        def fetch(from_h, to_h):
            try:
                t = HTTPPeerTransport(f"http://127.0.0.1:{port}")
                resp = t.get_blocks(GetBlocksRequest(
                    from_height=from_h, to_height=to_h,
                ))
                results.append(len(resp.blocks))
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=fetch, args=(0, 4)),
            threading.Thread(target=fetch, args=(5, 9)),
            threading.Thread(target=fetch, args=(10, 14)),
            threading.Thread(target=fetch, args=(15, 19)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        try:
            assert len(errors) == 0, f"Errors: {errors}"
            assert len(results) == 4
            assert sum(results) == 20  # all blocks fetched
        finally:
            server.stop()
            engine.close()

    def test_server_url_property(self):
        engine = _make_engine()
        server = SyncServer(engine, host="0.0.0.0", port=9999)
        assert server.url == "http://0.0.0.0:9999"
        engine.close()

    def test_blocks_property(self):
        engine = _make_engine()
        blocks = _make_chain(engine.chain_id, 3)
        server = SyncServer(engine, host="127.0.0.1", port=_free_port(),
                            block_store=blocks)
        assert len(server.blocks) == 3
        engine.close()
