"""Main Node class that ties the P2P networking layer together.

Usage::

    node = Node(config)
    await node.start()           # start listening + join network
    await node.submit_asset(...)  # broadcast an asset for validation
    await node.stop()            # graceful shutdown
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Awaitable, Dict, List, Optional

from oasyce.network.broadcast import GossipBroadcast
from oasyce.network.config import NetworkConfig
from oasyce.network.consensus import ConsensusManager, RoundStatus
from oasyce.network.discovery import PeerDiscovery
from oasyce.network.identity import NodeIdentity
from oasyce.network.message import (
    NetworkMessage,
    make_asset_submit,
    make_heartbeat,
    make_peer_exchange,
    make_vote,
)
from oasyce.network.monitor import NodeMonitor
from oasyce.network.scoring import PeerScoring
from oasyce.network.transport import HttpTransport

logger = logging.getLogger(__name__)

# Callback fired when an asset reaches consensus.
AssetAcceptedCallback = Callable[[str, Dict[str, Any]], Awaitable[None]]


class Node:
    """A single Oasyce P2P node."""

    def __init__(
        self,
        config: Optional[NetworkConfig] = None,
        identity: Optional[NodeIdentity] = None,
        on_asset_accepted: Optional[AssetAcceptedCallback] = None,
        monitor: Optional[NodeMonitor] = None,
    ) -> None:
        self.config = config or NetworkConfig()
        self.identity = identity or NodeIdentity.generate()
        self._on_asset_accepted = on_asset_accepted
        self.monitor = monitor or NodeMonitor()

        own_address = f"{self.config.host}:{self.config.port}"
        # Use 127.0.0.1 for self-identification when binding 0.0.0.0
        if self.config.host == "0.0.0.0":
            own_address = f"127.0.0.1:{self.config.port}"

        self.discovery = PeerDiscovery(self.config, own_address)
        self.consensus = ConsensusManager(self.config)
        self.transport = HttpTransport(
            host=self.config.host,
            port=self.config.port,
            on_message=self._on_message,
            monitor=self.monitor,
            discovery=self.discovery,
        )
        self.broadcast = GossipBroadcast(
            discovery=self.discovery,
            send_func=self._send_with_scoring,
        )

        self._scoring = PeerScoring(data_dir=os.path.expanduser("~/.oasyce"))
        self._scoring.load()

        self._running = False
        self._background_tasks: List[asyncio.Task] = []
        self._external_address: Optional[str] = None
        self._worker_client = None  # Cloudflare Worker client for bootstrap

    # ------------------------------------------------------------------
    # Transport wrapper for scoring
    # ------------------------------------------------------------------

    async def _send_with_scoring(self, address: str, msg: NetworkMessage) -> bool:
        """Send a message and record failure in scoring if it fails."""
        success = await self.transport.send_message(address, msg)
        if not success:
            self._scoring.record_failure(address)
        return success

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the node: transport, bootstrap peers, background loops."""
        # Auto-harden on first start
        from oasyce.network.bootstrap import auto_harden

        harden_status = auto_harden(self.config.key_dir)
        logger.info("Auto-harden: %s", harden_status)

        # Initialize Worker client if configured
        if self.config.worker_url:
            try:
                from oasyce.network.worker_client import WorkerClient

                # Load node config to get public IP
                node_config_path = Path(self.config.key_dir) / "node.json"
                node_config = {}
                if node_config_path.exists():
                    node_config = json.loads(node_config_path.read_text())

                public_ip = node_config.get("public_ip")
                auto_seed = node_config.get("auto_seed", False)

                self._worker_client = WorkerClient(
                    worker_url=self.config.worker_url,
                    node_ip=public_ip,
                    node_port=self.config.port,
                    node_id=self.identity.node_id,
                )
                logger.info("Worker client initialized: %s", self.config.worker_url)

                # Load cached peers first
                cached_peers = self._worker_client.load_cached_peers()
                if cached_peers:
                    for peer in cached_peers:
                        await self.discovery.add_peer(peer)
                    logger.info("Loaded %d cached peers", len(cached_peers))

                # Fetch seeds from Worker
                seeds = self._worker_client.fetch_seeds()
                for seed in seeds:
                    # Worker returns dict with node_id, we need to construct address
                    # For now, seeds are fetched but connection happens in discovery.bootstrap()
                    pass
                if seeds:
                    logger.info("Fetched %d seeds from Worker", len(seeds))

                # Register as seed if auto_seed=True
                if auto_seed and public_ip:
                    registered = self._worker_client.register_seed()
                    if registered:
                        logger.info("Registered as seed node: %s:%d", public_ip, self.config.port)
            except Exception as e:
                logger.warning("Failed to initialize Worker client: %s", e)
                self._worker_client = None

        # NAT traversal probe (skip for localhost — only useful on public interfaces)
        if self.config.host not in ("127.0.0.1", "localhost", "::1"):
            from oasyce.network.nat import NATTraversal

            nat = NATTraversal(self.config.port)
            nat_status = nat.probe()
            logger.info("NAT status: %s", nat_status)

            if nat_status.get("external"):
                self._external_address = nat_status["external"]
            else:
                self._external_address = None
        else:
            self._external_address = None

        await self.transport.start()
        await self.discovery.bootstrap()
        self._running = True
        self._background_tasks.append(asyncio.create_task(self._heartbeat_loop()))
        self._background_tasks.append(asyncio.create_task(self._peer_exchange_loop()))
        self._background_tasks.append(asyncio.create_task(self._scoring_save_loop()))
        # Add Worker heartbeat loop if client is initialized
        if self._worker_client:
            self._background_tasks.append(asyncio.create_task(self._worker_heartbeat_loop()))
        logger.info(
            "Node %s started on port %d",
            self.identity.node_id[:12],
            self.config.port,
        )

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        for task in self._background_tasks:
            task.cancel()
        await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()
        await self.transport.stop()
        self.monitor.close()
        self._scoring.save()
        logger.info("Node %s stopped", self.identity.node_id[:12])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def submit_asset(
        self,
        media_hash: str,
        creator: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> str:
        """Broadcast an asset submission. Returns the msg_id used for the voting round."""
        msg = make_asset_submit(
            self.identity,
            media_hash=media_hash,
            creator=creator,
            metadata=metadata,
            ttl=self.config.default_ttl,
        )
        await self.consensus.open_round(msg.msg_id)
        await self.broadcast.mark_seen(msg.msg_hash)
        await self.broadcast.broadcast(msg)

        # The submitter also casts its own vote (if staking allows it).
        protocol = getattr(self, "_protocol", None)
        should_vote = True
        if protocol is not None and not protocol.is_staked_validator(self.identity.node_id):
            should_vote = False
        if should_vote:
            await self.consensus.cast_vote(msg.msg_id, self.identity.node_id, accept=True)

        self.monitor.record(
            "msgs_sent",
            detail="asset submitted",
            msg_id=msg.msg_id,
            msg_type="ASSET_SUBMIT",
        )
        logger.info("Submitted asset %s for validation", msg.msg_id)
        return msg.msg_id

    async def wait_for_consensus(self, asset_msg_id: str) -> RoundStatus:
        """Block until the voting round for *asset_msg_id* is finalised."""
        return await self.consensus.wait_for_result(asset_msg_id)

    def get_peer_scores(self) -> list:
        """Return top peers ranked by score."""
        return self._scoring.get_best_peers(50)

    # ------------------------------------------------------------------
    # Message handler (called by transport)
    # ------------------------------------------------------------------

    async def _on_message(self, msg: NetworkMessage) -> None:
        """Dispatch an incoming network message."""
        is_new = await self.broadcast.receive_and_rebroadcast(msg)
        if not is_new:
            # If signature verification failed (not just dedup), record drop
            if not msg.verify_signature():
                self.monitor.record(
                    "msgs_dropped",
                    detail="bad signature",
                    msg_id=msg.msg_id,
                    msg_type=msg.msg_type,
                    peer=msg.sender_id[:12],
                )
            return

        self.monitor.record(
            "msgs_received",
            msg_type=msg.msg_type,
            msg_id=msg.msg_id,
            peer=msg.sender_id[:12],
        )

        # Record heartbeat for scoring on every valid message
        sender_addr = msg.payload.get("sender_addr", "")
        if sender_addr:
            self._scoring.record_heartbeat(sender_addr, msg.sender_id)

        handler = {
            "ASSET_SUBMIT": self._handle_asset_submit,
            "VOTE": self._handle_vote,
            "PEER_EXCHANGE": self._handle_peer_exchange,
            "HEARTBEAT": self._handle_heartbeat,
        }.get(msg.msg_type)

        if handler:
            await handler(msg)
        else:
            logger.warning("Unknown message type: %s", msg.msg_type)

        # Broadcast to WebSocket clients for real-time monitoring
        if msg.msg_type in ("ASSET_SUBMIT", "VOTE", "HEARTBEAT"):
            await self.transport.broadcast_event(
                {
                    "type": msg.msg_type.lower(),
                    "msg_id": msg.msg_id,
                    "sender": msg.sender_id[:12],
                    "timestamp": msg.timestamp,
                    "payload": msg.payload,
                }
            )

    # ------------------------------------------------------------------
    # Per-type handlers
    # ------------------------------------------------------------------

    async def _handle_asset_submit(self, msg: NetworkMessage) -> None:
        """When we receive an asset submission, open a round and cast our vote.

        If a protocol is attached and this node is a staked validator,
        run local verification before voting.  Non-staked nodes skip voting.
        """
        await self.consensus.open_round(msg.msg_id)

        # Determine if we should vote (staking gate)
        protocol = getattr(self, "_protocol", None)
        if protocol is not None:
            if not protocol.is_staked_validator(self.identity.node_id):
                logger.debug(
                    "Skipping vote on %s — not a staked validator",
                    msg.msg_id,
                )
                return
            # Run local verification via protocol
            media_hash = msg.payload.get("media_hash", "")
            accept = protocol.verify_asset(media_hash)
        else:
            # Legacy behaviour: auto-accept
            accept = True

        vote_msg = make_vote(
            self.identity,
            asset_msg_id=msg.msg_id,
            accept=accept,
            ttl=self.config.default_ttl,
        )
        await self.consensus.cast_vote(msg.msg_id, self.identity.node_id, accept=accept)
        await self.broadcast.mark_seen(vote_msg.msg_hash)
        await self.broadcast.broadcast(vote_msg)

        # Try to finalise.
        status = await self.consensus.finalise(msg.msg_id)
        if status == RoundStatus.ACCEPTED:
            self.monitor.record(
                "consensus_reached",
                detail="asset accepted",
                msg_id=msg.msg_id,
            )
            await self.transport.broadcast_event(
                {
                    "type": "consensus_reached",
                    "msg_id": msg.msg_id,
                    "status": "accepted",
                    "payload": msg.payload,
                }
            )
            if self._on_asset_accepted:
                await self._on_asset_accepted(msg.msg_id, msg.payload)

    async def _handle_vote(self, msg: NetworkMessage) -> None:
        """Record an incoming vote and try to finalise the round.

        If a protocol is attached, only votes from staked validators are counted.
        """
        payload = msg.payload
        asset_msg_id = payload.get("asset_msg_id", "")
        accept = payload.get("accept", False)
        reason = payload.get("reason", "")

        # Staking gate: ignore votes from non-staked nodes
        protocol = getattr(self, "_protocol", None)
        if protocol is not None and not protocol.is_staked_validator(msg.sender_id):
            logger.debug("Ignoring vote from non-staked node %s", msg.sender_id[:12])
            return

        await self.consensus.cast_vote(asset_msg_id, msg.sender_id, accept=accept, reason=reason)
        status = await self.consensus.finalise(asset_msg_id)
        if status == RoundStatus.ACCEPTED and self._on_asset_accepted:
            vr = await self.consensus.get_round(asset_msg_id)
            # payload not stored on vote round; use empty dict as fallback
            await self._on_asset_accepted(asset_msg_id, {})

    async def _handle_peer_exchange(self, msg: NetworkMessage) -> None:
        """Merge received peer list into our own discovery."""
        peers = msg.payload.get("peers", [])
        sender_address = msg.payload.get("sender_address", "")

        # Track which peers are new before merging
        existing = set(self._scoring.peers.keys())
        existing.update(addr for addr in (await self.discovery.get_peer_addresses()))

        added = await self.discovery.merge_peers(peers)
        if added:
            self.monitor.record(
                "peers_discovered",
                detail=f"added {added} new peers",
                peer=msg.sender_id[:12],
                count=added,
            )
            logger.debug("Peer exchange: added %d new peers", added)

            # Verify newly added peers if we know the sender address
            if sender_address:
                new_peers = [
                    p for p in peers if p not in existing and p != self.discovery._own_address
                ]
                # Cap concurrent verifications
                verify_peers = new_peers[:5]
                for new_peer_addr in verify_peers:
                    asyncio.create_task(self._verify_pex_referral(sender_address, new_peer_addr))

    async def _verify_pex_referral(self, sender_addr: str, new_peer_addr: str) -> None:
        """Verify a PEX-referred peer by sending a heartbeat with timeout."""
        try:
            hb = make_heartbeat(self.identity, ttl=1)
            success = await asyncio.wait_for(
                self.transport.send_message(new_peer_addr, hb),
                timeout=5.0,
            )
            self._scoring.record_referral(sender_addr, new_peer_addr, reachable=success)
        except (asyncio.TimeoutError, Exception):
            self._scoring.record_referral(sender_addr, new_peer_addr, reachable=False)

    async def _handle_heartbeat(self, msg: NetworkMessage) -> None:
        """Update last-seen timestamp for the sender."""
        # We don't know the sender's address from the message alone,
        # but we mark them by node_id for liveness tracking.
        pass

    # ------------------------------------------------------------------
    # Background loops
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                msg = make_heartbeat(self.identity, ttl=1)
                await self.broadcast.mark_seen(msg.msg_hash)
                await self.broadcast.broadcast(msg)
            except Exception as exc:
                self.monitor.record("error", detail=f"heartbeat: {exc}")
                logger.debug("Heartbeat error: %s", exc)
            await asyncio.sleep(self.config.heartbeat_interval_seconds)

    async def _peer_exchange_loop(self) -> None:
        while self._running:
            try:
                addrs = await self.discovery.get_peer_addresses()
                # Prefer high-scoring peers for PEX broadcast
                best = self._scoring.get_best_peers(20)
                if best:
                    best_addrs = [p.address for p in best]
                    # Merge: best peers first, then remaining discovery peers
                    merged = list(dict.fromkeys(best_addrs + list(addrs)))
                    addrs = merged
                else:
                    addrs = list(addrs)
                # Always include our own listen address so peers learn about us
                own_addr = f"{self.config.host}:{self.config.port}"
                if own_addr not in addrs:
                    addrs.append(own_addr)
                # Include our external address if available
                if self._external_address and self._external_address not in addrs:
                    addrs.append(self._external_address)
                if addrs:
                    msg = make_peer_exchange(self.identity, addrs, ttl=2, sender_address=own_addr)
                    await self.broadcast.mark_seen(msg.msg_hash)
                    await self.broadcast.broadcast(msg)
                await self.discovery.evict_stale()
                await self.discovery.evict_low_score(self._scoring)
            except Exception as exc:
                self.monitor.record("error", detail=f"peer exchange: {exc}")
                logger.debug("Peer exchange error: %s", exc)
            await asyncio.sleep(self.config.peer_exchange_interval_seconds)

    async def _worker_heartbeat_loop(self) -> None:
        """Send periodic heartbeats to Cloudflare Worker to keep seed registration alive."""
        while self._running and self._worker_client:
            try:
                if self._worker_client.should_send_heartbeat():
                    success = self._worker_client.send_heartbeat()
                    if success:
                        logger.debug("Worker heartbeat sent")
                    else:
                        logger.warning("Worker heartbeat failed")
                await asyncio.sleep(60)  # Check every minute
            except Exception as exc:
                logger.debug("Worker heartbeat loop error: %s", exc)
                await asyncio.sleep(60)

    async def _scoring_save_loop(self) -> None:
        while self._running:
            await asyncio.sleep(300)  # every 5 minutes
            try:
                self._scoring.save()
            except Exception as exc:
                logger.debug("Scoring save error: %s", exc)
