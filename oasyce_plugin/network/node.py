"""
Oasyce P2P Node — lightweight TCP + JSON protocol.

Listens on a port, responds to ping/pong, get_height, get_block, get_peers.
Supports persistent peer lists and bootstrap node connections.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
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

    MAX_MESSAGE_SIZE = 1_048_576  # 1 MB
    RATE_LIMIT_WINDOW = 10.0  # seconds
    RATE_LIMIT_MAX = 5  # max new_block messages per peer per window

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 9527,
        node_id: Optional[str] = None,
        ledger: Any = None,
        data_dir: Optional[str] = None,
        consensus_engine: Any = None,
        validator_key: Optional[str] = None,
    ):
        self.host = host
        self.port = port
        self.node_id = node_id or "node_unknown"
        self.ledger = ledger
        self.data_dir = data_dir
        self.consensus_engine = consensus_engine
        self.validator_key = validator_key  # Ed25519 private key for block signing
        self.peers: Dict[str, PeerInfo] = {}
        self._server: Optional[asyncio.AbstractServer] = None
        self._started = False
        self._consensus_task: Optional[asyncio.Task] = None
        self._last_processed_epoch: Optional[int] = None
        self._block_rate: Dict[str, List[float]] = defaultdict(list)

        # Load persisted peers
        if self.data_dir:
            self._load_peers()

    # ── peer persistence ─────────────────────────────────────────────

    @property
    def _peers_path(self) -> Optional[Path]:
        if not self.data_dir:
            return None
        return Path(self.data_dir) / "peers.json"

    def _load_peers(self) -> None:
        """Load persisted peer list from disk."""
        path = self._peers_path
        if path is None or not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            for entry in data:
                pid = entry.get("node_id", f"{entry['host']}:{entry['port']}")
                self.peers[pid] = PeerInfo(
                    host=entry["host"],
                    port=entry["port"],
                    node_id=pid,
                    last_seen=entry.get("last_seen", 0.0),
                )
        except (json.JSONDecodeError, KeyError, OSError):
            logger.warning("Failed to load peers.json, starting with empty peer list")

    def _save_peers(self) -> None:
        """Persist current peer list to disk."""
        path = self._peers_path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        entries = [
            {"host": p.host, "port": p.port, "node_id": p.node_id, "last_seen": p.last_seen}
            for p in self.peers.values()
        ]
        path.write_text(json.dumps(entries, indent=2))

    def add_peer(self, node_id: str, host: str, port: int) -> None:
        """Add a peer and persist to disk."""
        self.peers[node_id] = PeerInfo(
            host=host, port=port, node_id=node_id, last_seen=time.time(),
        )
        self._save_peers()

    def remove_peer(self, node_id: str) -> bool:
        """Remove a peer and persist to disk. Returns True if removed."""
        if node_id in self.peers:
            del self.peers[node_id]
            self._save_peers()
            return True
        return False

    # ── lifecycle ────────────────────────────────────────────────────

    async def start(self, bootstrap: bool = False) -> None:
        self._server = await asyncio.start_server(
            self._handle_connection, self.host, self.port,
        )
        self._started = True
        logger.info("Oasyce node %s listening on %s:%s", self.node_id, self.host, self.port)

        if self.consensus_engine is not None:
            self._consensus_task = asyncio.create_task(self._consensus_tick())
            logger.info("Consensus tick started for node %s", self.node_id)

        if bootstrap:
            await self._connect_bootstrap()
            await self._reconnect_saved_peers()

    async def stop(self) -> None:
        if self._consensus_task is not None:
            self._consensus_task.cancel()
            try:
                await self._consensus_task
            except asyncio.CancelledError:
                pass
            self._consensus_task = None
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._started = False

    @property
    def is_running(self) -> bool:
        return self._started

    async def _connect_bootstrap(self) -> None:
        """Try connecting to bootstrap nodes to discover peers."""
        from oasyce_plugin.config import BOOTSTRAP_NODES

        connected = False
        for entry in BOOTSTRAP_NODES:
            host = str(entry["host"])
            port = int(entry["port"])  # type: ignore[arg-type]
            try:
                resp = await asyncio.wait_for(
                    self.connect_to_peer(host, port), timeout=5.0,
                )
                logger.info("Connected to bootstrap %s:%s → %s", host, port, resp.get("node_id"))
                connected = True
                # Ask bootstrap for more peers
                try:
                    peers_resp = await asyncio.wait_for(
                        self._request(host, port, {"type": "get_peers"}), timeout=5.0,
                    )
                    for p in peers_resp.get("peers", []):
                        if p.get("node_id") != self.node_id:
                            try:
                                await asyncio.wait_for(
                                    self.connect_to_peer(p["host"], p["port"]), timeout=3.0,
                                )
                            except Exception:
                                pass
                except Exception:
                    pass
            except Exception:
                logger.debug("Bootstrap %s:%s unreachable", host, port)

        if not connected:
            logger.warning(
                "Could not connect to any bootstrap node. "
                "Running as isolated local node. "
                "Use 'oasyce node ping <host:port>' to connect to a known peer."
            )

    async def _reconnect_saved_peers(self) -> None:
        """Try reconnecting to previously saved peers."""
        saved = list(self.peers.values())
        for peer in saved:
            try:
                await asyncio.wait_for(
                    self.connect_to_peer(peer.host, peer.port), timeout=3.0,
                )
            except Exception:
                logger.debug("Saved peer %s:%s unreachable", peer.host, peer.port)

    # ── consensus tick ─────────────────────────────────────────────

    async def _consensus_tick(self) -> None:
        """Background loop: propose blocks when we are the slot leader."""
        ce = self.consensus_engine
        slot_duration = ce.epoch_manager.slot_duration
        try:
            while True:
                try:
                    now = int(time.time())
                    current_epoch = ce.epoch_manager.current_epoch(now)
                    current_slot = ce.epoch_manager.current_slot(now)

                    # Epoch boundary check
                    if self._last_processed_epoch is None or current_epoch > self._last_processed_epoch:
                        prev_block_hash = ""
                        current_height = 0
                        if self.ledger is not None:
                            current_height = self.ledger.get_chain_height()
                            if current_height > 0:
                                tip = self.ledger.get_block(current_height - 1)
                                if tip:
                                    prev_block_hash = tip.get("block_hash", "")
                        validator_metrics = {}
                        active = ce.state.get_active_validators(min_stake=0)
                        for v in active:
                            vid = v if isinstance(v, str) else v.get("validator_id", v)
                            proposed = ce.state.count_proposed_slots(current_epoch - 1, vid)
                            assigned = ce.state.count_assigned_slots(current_epoch - 1, vid)
                            validator_metrics[vid] = {
                                "validator_id": vid,
                                "blocks_proposed": proposed,
                                "work_value": 0,
                            }
                        ce.on_epoch_boundary(
                            current_epoch,
                            prev_block_hash,
                            current_height,
                            list(validator_metrics.values()),
                        )
                        self._last_processed_epoch = current_epoch
                        logger.info("Epoch boundary processed: epoch %d", current_epoch)

                    # Check if we are the proposer for the current slot
                    if ce.verify_proposer(current_epoch, current_slot, self.node_id):
                        if self.ledger is not None:
                            block = self.ledger.create_block(
                                validator_key=self.validator_key,
                                validator_pubkey=self.node_id,
                            )
                            if block:
                                await self.broadcast_block(block)
                                logger.info(
                                    "Proposed block at epoch=%d slot=%d", current_epoch, current_slot,
                                )
                        ce.state.mark_slot_proposed(current_epoch, current_slot)

                except Exception:
                    logger.exception("Error in consensus tick")

                await asyncio.sleep(slot_duration)
        except asyncio.CancelledError:
            logger.info("Consensus tick cancelled for node %s", self.node_id)
            raise

    # ── connection handler ───────────────────────────────────────────

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
    ) -> None:
        addr = writer.get_extra_info("peername")
        peer_key = f"{addr[0]}:{addr[1]}" if addr else "unknown"
        logger.debug("Connection from %s", addr)
        try:
            while True:
                try:
                    line = await reader.readuntil(b'\n')
                    if len(line) > self.MAX_MESSAGE_SIZE:
                        logger.warning("Oversized message from %s (%d bytes), dropping", peer_key, len(line))
                        continue
                except asyncio.LimitOverrunError:
                    logger.warning("Message from %s exceeded buffer limit, closing", peer_key)
                    break
                except asyncio.IncompleteReadError:
                    break
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
            "get_epoch_info": self._handle_get_epoch_info,
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

        # Validate required fields
        required_fields = ("block_number", "block_hash", "prev_hash", "merkle_root", "timestamp")
        for f in required_fields:
            if f not in block_data:
                logger.warning("new_block missing required field: %s", f)
                return {"type": "ack", "status": "rejected"}

        bn = block_data["block_number"]
        bh = block_data["block_hash"]

        # Check for fork FIRST: same height but different hash
        existing = self.ledger.get_block(bn)
        if existing is not None and existing["block_hash"] != bh:
            logger.info("Fork detected at height %d, marking for reorg", bn)
            return {"type": "ack", "status": "fork_detected"}

        # Verify proposer via consensus engine — use block timestamp, not current time
        if self.consensus_engine is not None:
            ce = self.consensus_engine
            if "validator_pubkey" not in block_data:
                logger.warning("Block missing validator_pubkey, rejected")
                return {"type": "ack", "status": "rejected"}
            # Parse block timestamp to derive epoch/slot the block claims
            try:
                from datetime import datetime, timezone
                block_ts = block_data["timestamp"]
                if isinstance(block_ts, str):
                    dt = datetime.fromisoformat(block_ts.replace("Z", "+00:00"))
                    block_unix = int(dt.timestamp())
                else:
                    block_unix = int(block_ts)
            except (ValueError, TypeError):
                logger.warning("Block has unparseable timestamp: %s", block_data["timestamp"])
                return {"type": "ack", "status": "rejected"}
            # Reject future blocks (>1 slot tolerance)
            now_unix = int(time.time())
            if block_unix > now_unix + ce.epoch_manager.slot_duration:
                logger.warning("Block timestamp %d is in the future (now=%d)", block_unix, now_unix)
                return {"type": "ack", "status": "rejected"}
            epoch = ce.epoch_manager.current_epoch(block_unix)
            slot = ce.epoch_manager.current_slot(block_unix)
            if not ce.verify_proposer(epoch, slot, block_data["validator_pubkey"]):
                logger.warning(
                    "Block proposer %s is not the expected leader for epoch=%d slot=%d",
                    block_data["validator_pubkey"], epoch, slot,
                )
                return {"type": "ack", "status": "rejected"}

        # Mandatory signature verification when consensus is enabled
        if self.consensus_engine is not None:
            if "validator_signature" not in block_data:
                logger.warning("Block missing signature, rejected (consensus requires signed blocks)")
                return {"type": "ack", "status": "rejected"}

        # Verify validator signature if present
        if "validator_signature" in block_data and "validator_pubkey" in block_data:
            from oasyce_plugin.crypto.keys import verify
            # Recompute expected hash for signature verification (includes chain_id)
            chain_id = ""
            if self.consensus_engine is not None:
                chain_id = getattr(self.consensus_engine, "chain_id", "")
            if chain_id:
                from oasyce_plugin.consensus.execution.engine import compute_block_hash
                expected_hash = compute_block_hash(
                    chain_id, bn, block_data['prev_hash'],
                    block_data['merkle_root'], int(block_data['timestamp']) if isinstance(block_data['timestamp'], (int, float)) else 0,
                )
            else:
                hash_input = f"{bn}{block_data['prev_hash']}{block_data['merkle_root']}{block_data['timestamp']}"
                expected_hash = hashlib.sha256(hash_input.encode()).hexdigest()
            if bh != expected_hash:
                logger.warning("Signed block hash mismatch: expected %s, got %s", expected_hash, bh)
                return {"type": "ack", "status": "rejected"}
            if not verify(
                expected_hash.encode(),
                block_data["validator_signature"],
                block_data["validator_pubkey"],
            ):
                logger.warning("new_block has invalid validator signature")
                return {"type": "ack", "status": "rejected"}

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

    def _handle_get_epoch_info(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        if self.consensus_engine is None:
            return {"type": "epoch_info", "error": "consensus not enabled"}
        now = int(time.time())
        return {"type": "epoch_info", **self.consensus_engine.status(now)}

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
            self.add_peer(peer_id, host, port)
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

        # Validate chain linkage: each block's prev_hash must match the previous block's block_hash
        for i in range(1, len(remote_chain)):
            prev_block = remote_chain[i - 1]
            curr_block = remote_chain[i]
            if curr_block.get("prev_hash") != prev_block.get("block_hash"):
                logger.warning(
                    "Remote chain broken at index %d: prev_hash %s != previous block_hash %s",
                    i, curr_block.get("prev_hash"), prev_block.get("block_hash"),
                )
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
