"""
Oasyce P2P Node — lightweight TCP + JSON protocol.

Single-node first: listens on a port, responds to ping/pong,
get_height, get_block, get_peers.  Ready for future peer connections.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PeerInfo:
    host: str
    port: int
    node_id: str = ""
    last_seen: float = 0.0


class OasyceNode:
    """Async TCP node that speaks JSON-newline protocol."""

    RATE_LIMIT_WINDOW = 10.0  # seconds
    RATE_LIMIT_MAX = 5  # max new_block messages per peer per window

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 9527,
        node_id: Optional[str] = None,
        ledger: Any = None,
    ):
        self.host = host
        self.port = port
        self.node_id = node_id or "node_unknown"
        self.ledger = ledger
        self.peers: Dict[str, PeerInfo] = {}
        self._server: Optional[asyncio.AbstractServer] = None
        self._started = False
        self._block_rate: Dict[str, List[float]] = defaultdict(list)

    # ── lifecycle ────────────────────────────────────────────────────

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_connection, self.host, self.port,
        )
        self._started = True
        logger.info("Oasyce node %s listening on %s:%s", self.node_id, self.host, self.port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._started = False

    @property
    def is_running(self) -> bool:
        return self._started

    # ── connection handler ───────────────────────────────────────────

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
    ) -> None:
        addr = writer.get_extra_info("peername")
        peer_key = f"{addr[0]}:{addr[1]}" if addr else "unknown"
        logger.debug("Connection from %s", addr)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode())
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue

                response = self._dispatch(msg, peer_key)
                if response is not None:
                    writer.write(json.dumps(response).encode() + b"\n")
                    await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    # ── message dispatch ─────────────────────────────────────────────

    def _check_rate_limit(self, peer_key: str) -> bool:
        """Return True if the peer is within rate limits, False if exceeded."""
        now = time.time()
        timestamps = self._block_rate[peer_key]
        # Prune old entries outside the window
        cutoff = now - self.RATE_LIMIT_WINDOW
        self._block_rate[peer_key] = [t for t in timestamps if t > cutoff]
        timestamps = self._block_rate[peer_key]

        if len(timestamps) >= self.RATE_LIMIT_MAX:
            return False
        timestamps.append(now)
        return True

    def _dispatch(self, msg: Dict[str, Any], peer_key: str = "unknown") -> Optional[Dict[str, Any]]:
        msg_type = msg.get("type")
        handler = {
            "ping": self._handle_ping,
            "get_peers": self._handle_get_peers,
            "get_block": self._handle_get_block,
            "get_height": self._handle_get_height,
            "new_block": self._handle_new_block,
            "get_chain": self._handle_get_chain,
        }.get(msg_type)
        if handler is None:
            return {"type": "error", "message": f"unknown type: {msg_type}"}
        # Rate limit new_block messages
        if msg_type == "new_block":
            if not self._check_rate_limit(peer_key):
                logger.warning("Rate limit exceeded for peer %s, dropping new_block", peer_key)
                return {"type": "ack", "status": "rate_limited"}
        return handler(msg)

    def _handle_ping(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        height = self.ledger.get_chain_height() if self.ledger else 0
        return {
            "type": "pong",
            "node_id": self.node_id,
            "height": height,
        }

    def _handle_get_peers(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        peers = [
            {"node_id": p.node_id, "host": p.host, "port": p.port}
            for p in self.peers.values()
        ]
        return {"type": "peers", "peers": peers}

    def _handle_get_block(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        number = msg.get("number")
        if number is None or self.ledger is None:
            return {"type": "block", "block": None}
        block = self.ledger.get_block(int(number), include_tx=True)
        return {"type": "block", "block": block}

    def _handle_get_height(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        height = self.ledger.get_chain_height() if self.ledger else 0
        return {"type": "height", "height": height}

    def _handle_new_block(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        block_data = msg.get("block")
        if not block_data or self.ledger is None:
            logger.info("Received new_block broadcast but no block data or ledger")
            return {"type": "ack", "status": "ignored"}

        bn = block_data.get("block_number")
        bh = block_data.get("block_hash")

        # Check for fork: same height but different hash
        if bn is not None:
            existing = self.ledger.get_block(bn)
            if existing is not None and existing["block_hash"] != bh:
                logger.info("Fork detected at height %d, marking for reorg", bn)
                return {"type": "ack", "status": "fork_detected"}

        ok = self.ledger.insert_remote_block(block_data)
        if ok:
            logger.info("Accepted new_block %s", bn)
            return {"type": "ack", "status": "accepted"}
        else:
            logger.warning("Rejected new_block %s", bn)
            return {"type": "ack", "status": "rejected"}

    def _handle_get_chain(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        start = msg.get("start", 0)
        if self.ledger is None:
            return {"type": "chain", "blocks": []}
        blocks = self.ledger.get_chain_from(int(start))
        return {"type": "chain", "blocks": blocks}

    # ── outbound ─────────────────────────────────────────────────────

    async def connect_to_peer(self, host: str, port: int) -> Dict[str, Any]:
        """Connect to another node, send ping, record peer info."""
        reader, writer = await asyncio.open_connection(host, port)
        try:
            # send ping
            writer.write(json.dumps({"type": "ping"}).encode() + b"\n")
            await writer.drain()

            line = await asyncio.wait_for(reader.readline(), timeout=5.0)
            resp = json.loads(line.decode())

            peer_id = resp.get("node_id", f"{host}:{port}")
            self.peers[peer_id] = PeerInfo(
                host=host, port=port, node_id=peer_id, last_seen=time.time(),
            )
            return resp
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _request(self, host: str, port: int, msg: Dict[str, Any]) -> Dict[str, Any]:
        """Send a single JSON request and return the response."""
        reader, writer = await asyncio.open_connection(host, port)
        try:
            writer.write(json.dumps(msg).encode() + b"\n")
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), timeout=10.0)
            return json.loads(line.decode())
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def sync_from_peer(self, host: str, port: int) -> int:
        """Sync missing blocks from a remote peer.

        Returns the number of blocks fetched and stored.
        """
        # Get remote height
        resp = await self._request(host, port, {"type": "get_height"})
        remote_height = resp.get("height", 0)
        local_height = self.ledger.get_chain_height() if self.ledger else 0

        fetched = 0
        for bn in range(local_height, remote_height):
            resp = await self._request(host, port, {"type": "get_block", "number": bn})
            block = resp.get("block")
            if block and self.ledger:
                ok = self.ledger.insert_remote_block(block)
                if ok:
                    fetched += 1
                else:
                    logger.warning("Failed to insert block %d during sync", bn)
                    break
        return fetched

    async def sync_chain_and_reorg(self, host: str, port: int) -> bool:
        """Fetch the remote peer's full chain and attempt reorg if it's longer."""
        if self.ledger is None:
            return False
        resp = await self._request(host, port, {"type": "get_chain", "start": 0})
        remote_chain = resp.get("blocks", [])
        if not remote_chain:
            return False
        return self.ledger.attempt_reorg(remote_chain)

    async def broadcast_block(self, block_data: Dict[str, Any]) -> None:
        """Push a new block to all connected peers."""
        msg = {"type": "new_block", "block": block_data}
        for peer in list(self.peers.values()):
            try:
                await self._request(peer.host, peer.port, msg)
            except Exception:
                logger.warning("Failed to broadcast block to %s:%s", peer.host, peer.port)

    # ── info ─────────────────────────────────────────────────────────

    def info(self) -> Dict[str, Any]:
        height = self.ledger.get_chain_height() if self.ledger else 0
        return {
            "node_id": self.node_id,
            "host": self.host,
            "port": self.port,
            "height": height,
            "peers": len(self.peers),
            "running": self.is_running,
        }
